"""
video_renderer.py — FFmpeg-based video pipeline.
Combines images + audio segments, adds transitions, outputs final MP4.
"""

import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List
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


@lru_cache(maxsize=1)
def _supports_drawtext() -> bool:
    """Return True when the local ffmpeg build exposes the drawtext filter."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-h", "filter=drawtext"],
            capture_output=True,
            text=True,
        )
        return "Unknown filter" not in result.stdout + result.stderr
    except Exception:
        return False


def _render_segment(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    headline: str,
    narration: str,
    segment_type: str,
    index: int,
    overall_headline: str,
) -> Path:
    """
    Render a single segment: image + audio + overlay text → MP4 clip.
    """
    duration = _get_audio_duration(audio_path)

    W = config.VIDEO_WIDTH
    H = config.VIDEO_HEIGHT

    # Build drawtext filters
    # Escape special chars for FFmpeg
    def esc(t: str) -> str:
        return (
            t.replace("\\", "\\\\")
             .replace("'", "\\'")
             .replace(":", "\\:")
             .replace(",", "\\,")
             .replace("[", "\\[")
             .replace("]", "\\]")
        )

    safe_headline = esc(headline[:60])
    safe_overall = esc(overall_headline[:50])

    # Ticker bar: overall headline scrolling
    ticker_speed = 80  # pixels per second
    ticker_start_x = W
    ticker_text_width_est = len(overall_headline) * 14
    ticker_end_x = -(ticker_text_width_est + 50)

    # Subtitle bar narration (first 80 chars)
    short_narration = esc(narration[:90] + ("…" if len(narration) > 90 else ""))

    # Segment label
    label = {"intro": "LIVE", "outro": "RECAP"}.get(segment_type, f"SEG {index+1}")

    vf_filters = [
        # Ken Burns zoom
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
        f"zoompan=z='min(zoom+0.0008,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={int(duration * config.VIDEO_FPS)}:s={W}x{H}:fps={config.VIDEO_FPS}",
        # Fade in / fade out
        f"fade=t=in:st=0:d=0.5",
        f"fade=t=out:st={max(0, duration - 0.5):.2f}:d=0.5",
    ]

    if _supports_drawtext():
        vf_filters.extend([
            # Bottom ticker band background
            f"drawbox=x=0:y={H-80}:w={W}:h=80:color=0x0A0A1E@0.92:t=fill",
            # Red BREAKING label box
            f"drawbox=x=0:y={H-80}:w=200:h=80:color=0xC81E1E@1.0:t=fill",
            # BREAKING text
            f"drawtext=text='{label}':fontsize=22:fontcolor=white:"
            f"x=12:y={H-80+26}:shadowcolor=black:shadowx=1:shadowy=1",
            # Scrolling headline ticker
            f"drawtext=text='{safe_overall}':fontsize=24:fontcolor=0xFFDC32:"
            f"x='({W}-t*{ticker_speed})':y={H-80+22}:shadowcolor=black:shadowx=1:shadowy=1:"
            f"enable='gte(t,0)'",
            # Top headline bar
            f"drawbox=x=0:y=0:w={W}:h=72:color=0x0B0F1A@0.85:t=fill",
            f"drawtext=text='{safe_headline}':fontsize=30:fontcolor=white:"
            f"x=20:y=20:shadowcolor=black:shadowx=2:shadowy=2",
            # Subtitle narration at bottom above ticker
            f"drawbox=x=0:y={H-140}:w={W}:h=56:color=0x000000@0.55:t=fill",
            f"drawtext=text='{short_narration}':fontsize=18:fontcolor=0xE0E0E0:"
            f"x=14:y={H-130}:shadowcolor=black:shadowx=1:shadowy=1",
        ])
    else:
        log.warning("FFmpeg drawtext filter is unavailable; rendering video without text overlays.")
        vf_filters.extend([
            f"drawbox=x=0:y=0:w={W}:h=72:color=0x0B0F1A@0.45:t=fill",
            f"drawbox=x=0:y={H-80}:w={W}:h=80:color=0x0A0A1E@0.55:t=fill",
        ])

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


def _concat_segments(segment_paths: List[Path], output_path: Path) -> Path:
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

    for i, (seg, vis, narr, audio, headline) in enumerate(
        zip(segments, visuals, narrations, audio_paths, headlines)
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
        )
        clip_paths.append(clip_out)

    final_path = output_dir / "final_video.mp4"
    log.info(f"Concatenating {len(clip_paths)} clips…")
    _concat_segments(clip_paths, final_path)

    return final_path
