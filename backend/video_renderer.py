"""
video_renderer.py — FFmpeg-based video pipeline.
Combines images + audio segments, adds transitions, outputs final MP4.
"""

import json
import subprocess
from pathlib import Path
from typing import List
from backend.html_frame_renderer import rasterize_html_frames
from backend.utils import get_logger, config

log = get_logger("video_renderer")


def _get_audio_duration(audio_path: Path) -> float:
    """Probe audio file duration via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if "duration" in stream:
                return float(stream["duration"])
    except Exception as e:
        log.warning(f"ffprobe failed: {e}")
    return 5.0  # safe default


def _get_media_duration(path: Path) -> float:
    """Probe container duration via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception as e:
        log.warning(f"ffprobe duration failed: {e}")
    return 5.0


def _motion_filter(style: str, duration: float) -> str:
    frames = max(1, int(duration * config.VIDEO_FPS))
    base = f"d={frames}:s={config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}:fps={config.VIDEO_FPS}"
    style = (style or "").lower()

    if style == "drift_left":
        return (
            "zoompan="
            "z='min(zoom+0.00055,1.08)':"
            "x='max(0,iw/2-(iw/zoom/2)-on*0.35)':"
            "y='ih/2-(ih/zoom/2)':"
            f"{base}"
        )
    if style == "drift_right":
        return (
            "zoompan="
            "z='min(zoom+0.00055,1.08)':"
            "x='min(iw-iw/zoom,iw/2-(iw/zoom/2)+on*0.35)':"
            "y='ih/2-(ih/zoom/2)':"
            f"{base}"
        )
    if style == "rise":
        return (
            "zoompan="
            "z='min(zoom+0.0006,1.09)':"
            "x='iw/2-(iw/zoom/2)':"
            "y='max(0,ih/2-(ih/zoom/2)-on*0.28)':"
            f"{base}"
        )
    if style == "pull_back":
        return (
            "zoompan="
            "z='if(eq(on,1),1.08,max(1.0,zoom-0.00045))':"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"{base}"
        )
    if style == "steady":
        return (
            "zoompan="
            "z='1.02':"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"{base}"
        )
    return (
        "zoompan="
        "z='min(zoom+0.00075,1.12)':"
        "x='iw/2-(iw/zoom/2)':"
        "y='ih/2-(ih/zoom/2)':"
        f"{base}"
    )


def _render_segment(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    headline: str,
    narration: str,
    segment_type: str,
    index: int,
    overall_headline: str,
    motion_style: str,
) -> Path:
    """
    Render a single segment: composed scene image + audio → MP4 clip.
    """
    duration = _get_audio_duration(audio_path)

    W = config.VIDEO_WIDTH
    H = config.VIDEO_HEIGHT

    vf_filters = [
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
        _motion_filter(motion_style, duration),
        f"fade=t=in:st=0:d=0.5",
        f"fade=t=out:st={max(0, duration - 0.5):.2f}:d=0.5",
        "eq=contrast=1.04:saturation=1.1:brightness=0.02",
        "unsharp=5:5:0.7:5:5:0.0",
    ]

    vf = ",".join(vf_filters)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(config.VIDEO_FPS),
        "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error(f"FFmpeg segment error:\n{result.stderr[-1000:]}")
            raise RuntimeError(f"FFmpeg failed for segment {index}")
        log.debug(f"Rendered segment {index} → {output_path.name}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg timeout on segment {index}")

    return output_path


def _basic_concat_segments(segment_paths: List[Path], output_path: Path) -> Path:
    """Concatenate rendered MP4 clips using FFmpeg concat demuxer."""
    # Write concat list file
    concat_file = output_path.parent / "concat_list.txt"
    with open(concat_file, "w") as f:
        for p in segment_paths:
            f.write(f"file '{p.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        log.error(f"FFmpeg concat error:\n{result.stderr[-2000:]}")
        raise RuntimeError("FFmpeg concat failed")

    concat_file.unlink(missing_ok=True)
    log.info(f"Final video: {output_path}")
    return output_path


def _transition_name(name: str) -> str:
    mapping = {
        "cut": "fade",
        "crossfade": "fade",
        "slide": "slideleft",
        "wipe": "wipeleft",
        "push": "smoothleft",
        "zoom": "circleopen",
        "fade_out": "fadeblack",
    }
    return mapping.get((name or "").lower(), "fade")


def _concat_segments(segment_paths: List[Path], transitions: List[str], output_path: Path) -> Path:
    """
    Concatenate clips using xfade/acrossfade when available, otherwise fall back
    to the concat demuxer.
    """
    if len(segment_paths) <= 1:
        return _basic_concat_segments(segment_paths, output_path)

    durations = [_get_media_duration(path) for path in segment_paths]
    cmd = ["ffmpeg", "-y"]
    for path in segment_paths:
        cmd.extend(["-i", str(path)])

    filter_parts = []
    video_label = "[0:v]"
    audio_label = "[0:a]"
    offset = durations[0]

    for index in range(1, len(segment_paths)):
        transition = _transition_name(transitions[index - 1] if index - 1 < len(transitions) else "crossfade")
        duration = 0.15 if transition == "fade" and (transitions[index - 1] if index - 1 < len(transitions) else "") == "cut" else 0.55
        if transition == "fadeblack":
            duration = 0.65
        offset = max(0.0, offset - duration)
        next_video = f"[v{index}]"
        next_audio = f"[a{index}]"
        filter_parts.append(
            f"{video_label}[{index}:v]xfade=transition={transition}:duration={duration}:offset={offset}{next_video}"
        )
        filter_parts.append(
            f"{audio_label}[{index}:a]acrossfade=d={duration}:c1=tri:c2=tri{next_audio}"
        )
        video_label = next_video
        audio_label = next_audio
        offset += durations[index]

    cmd.extend(
        [
            "-filter_complex", ";".join(filter_parts),
            "-map", video_label,
            "-map", audio_label,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode == 0:
        log.info(f"Final video with transitions: {output_path}")
        return output_path

    log.warning(f"Transition concat failed, falling back to basic concat.\n{result.stderr[-1200:]}")
    return _basic_concat_segments(segment_paths, output_path)


def render_video(
    segments: List[dict],
    visuals: List[dict],
    narrations: List[str],
    audio_paths: List[Path],
    headlines: List[str],
    overall_headline: str,
    job_id: str,
) -> Path:
    """
    Full rendering pipeline:
      1. Render each segment clip
      2. Concatenate all clips
      3. Return final video path
    """
    clips_dir = config.MEDIA_DIR / job_id / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    output_dir = config.OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: List[Path] = []

    render_visuals = visuals
    if config.RENDER_HTML_FRAMES:
        render_visuals = rasterize_html_frames(visuals, job_id)

    for i, (seg, vis, narr, audio, headline) in enumerate(
        zip(segments, render_visuals, narrations, audio_paths, headlines)
    ):
        clip_out = clips_dir / f"clip_{i:02d}.mp4"
        log.info(f"Rendering clip {i+1}/{len(segments)}: {headline[:40]}")
        _render_segment(
            image_path=Path(vis["image_path"]),
            audio_path=audio,
            output_path=clip_out,
            headline=headline,
            narration=narr,
            segment_type=seg["segment_type"],
            index=i,
            overall_headline=overall_headline,
            motion_style=vis.get("camera_motion", "push_in"),
        )
        clip_paths.append(clip_out)

    final_path = output_dir / "final_video.mp4"
    log.info(f"Concatenating {len(clip_paths)} clips…")
    transitions = [visual.get("transition", "crossfade") for visual in render_visuals]
    _concat_segments(clip_paths, transitions, final_path)

    return final_path
