"""
video_renderer.py — FFmpeg-based video pipeline.
Combines images + audio segments, adds transitions, outputs final MP4.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import List

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from backend.html_frame_renderer import rasterize_html_frames
from backend.utils import get_logger, config

log = get_logger("video_renderer")


def _stinger_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        ("/System/Library/Fonts/Helvetica.ttc", size),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf", size),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size),
    ]
    for path, point in candidates:
        try:
            return ImageFont.truetype(path, point)
        except Exception:
            continue
    return ImageFont.load_default()


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


def _create_stinger_card(path: Path, label: str) -> Path:
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    canvas = Image.new("RGB", (width, height), (5, 10, 22))
    draw = ImageDraw.Draw(canvas)

    for y in range(height):
        t = y / max(1, height - 1)
        color = (
            int(6 + 16 * t),
            int(12 + 26 * t),
            int(28 + 44 * t),
        )
        draw.line((0, y, width, y), fill=color)

    for x in range(0, width, 86):
        draw.line((x, 0, x + 140, height), fill=(24, 42, 72), width=1)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((width - 380, -180, width + 180, 380), fill=(224, 38, 58, 110))
    gdraw.ellipse((-180, height - 340, 360, height + 180), fill=(28, 123, 248, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(36))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((78, 74, width - 78, 196), radius=26, fill=(7, 12, 24), outline=(235, 52, 70), width=3)
    draw.rounded_rectangle((116, 102, 358, 168), radius=18, fill=(222, 40, 58))
    draw.text((152, 121), "LIVE", font=_stinger_font(34, bold=True), fill="white")
    draw.text((392, 96), "ALGSOCH NEWSROOM", font=_stinger_font(24, bold=True), fill=(230, 238, 252))
    draw.text((392, 132), "TRANSITION STINGER", font=_stinger_font(20), fill=(170, 190, 226))

    clean = re.sub(r"\s+", " ", (label or "")).strip().upper()
    if not clean:
        clean = "BREAKING UPDATE"
    words = clean.split()
    if len(words) > 7:
        clean = " ".join(words[:7]) + "..."

    draw.rounded_rectangle((118, 264, width - 118, 442), radius=28, fill=(8, 14, 30), outline=(106, 148, 220), width=2)
    draw.text((152, 310), clean, font=_stinger_font(52, bold=True), fill=(245, 250, 255))

    draw.rounded_rectangle((120, height - 126, width - 120, height - 72), radius=16, fill=(11, 18, 34))
    draw.text((150, height - 110), "HARD STINGER CUT", font=_stinger_font(24, bold=True), fill=(255, 228, 232))
    draw.text((460, height - 108), "Major beat transition", font=_stinger_font(22), fill=(170, 190, 226))

    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "JPEG", quality=95)
    return path


def _render_stinger_clip(image_path: Path, output_path: Path, duration: float = 0.32) -> Path:
    duration = max(0.18, float(duration))
    fade_out_start = max(0.0, duration - 0.08)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(config.VIDEO_FPS),
        "-t", f"{duration:.2f}",
        "-i", str(image_path),
        "-f", "lavfi",
        "-t", f"{duration:.2f}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", (
            f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
            "eq=contrast=1.06:saturation=1.12:brightness=0.02,"
            "fade=t=in:st=0:d=0.06,"
            f"fade=t=out:st={fade_out_start:.2f}:d=0.07"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "21",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"stinger render failed: {result.stderr[-700:]}")
    return output_path


def _inject_stinger_clips(
    segment_paths: List[Path],
    transitions: List[str],
    visuals: List[dict],
    job_id: str,
) -> tuple[List[Path], List[str]]:
    if not segment_paths or len(segment_paths) <= 1:
        return segment_paths, transitions

    stinger_dir = config.MEDIA_DIR / job_id / "stingers"
    stinger_dir.mkdir(parents=True, exist_ok=True)

    expanded_paths: List[Path] = [segment_paths[0]]
    expanded_transitions: List[str] = []
    inserted = 0

    for index in range(len(segment_paths) - 1):
        transition = transitions[index] if index < len(transitions) else "dissolve"
        next_clip = segment_paths[index + 1]

        if transition != "stinger":
            expanded_transitions.append(transition)
            expanded_paths.append(next_clip)
            continue

        label_source = "BREAKING UPDATE"
        if index + 1 < len(visuals):
            visual = visuals[index + 1]
            label_source = visual.get("top_tag") or visual.get("main_headline") or label_source

        slug = re.sub(r"[^a-z0-9]+", "-", str(label_source).lower()).strip("-")[:24] or f"{index:02d}"
        card_path = stinger_dir / f"stinger_{index:02d}_{slug}.jpg"
        clip_path = stinger_dir / f"stinger_{index:02d}_{slug}.mp4"

        try:
            _create_stinger_card(card_path, str(label_source))
            _render_stinger_clip(card_path, clip_path, duration=0.32)
            expanded_transitions.append("hard_cut")
            expanded_paths.append(clip_path)
            expanded_transitions.append("hard_cut")
            expanded_paths.append(next_clip)
            inserted += 1
        except Exception as exc:
            log.warning(f"Stinger generation failed at boundary {index}: {exc}. Falling back to hard cut.")
            expanded_transitions.append("hard_cut")
            expanded_paths.append(next_clip)

    if inserted:
        log.info(f"Inserted {inserted} branded stinger clip(s) between major beats.")

    return expanded_paths, expanded_transitions


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


def _transition_profile(name: str, conservative: bool = False) -> tuple[str, float, str]:
    key = (name or "").strip().lower()

    profiles = {
        # Backward compatibility with previous transition labels.
        "cut": ("fade", 0.15, "tri"),
        "crossfade": ("fade", 0.5, "tri"),
        "slide": ("slideleft", 0.45, "tri"),
        "wipe": ("wipeleft", 0.46, "tri"),
        "push": ("smoothleft", 0.5, "tri"),
        "zoom": ("circleopen", 0.56, "tri"),
        "fade_out": ("fadeblack", 0.68, "tri"),
        # Expanded transition vocabulary used by the packaging layer.
        "hard_cut": ("fade", 0.12, "tri"),
        "dissolve": ("fade", 0.54, "tri"),
        "slide_left": ("slideleft", 0.44, "tri"),
        "slide_right": ("slideright", 0.44, "tri"),
        "wipe_left": ("wipeleft", 0.46, "tri"),
        "wipe_right": ("wiperight", 0.46, "tri"),
        "wipe_reveal": ("wiperight", 0.5, "tri"),
        "push_left": ("smoothleft", 0.52, "tri"),
        "push_right": ("smoothright", 0.52, "tri"),
        "zoom_in": ("zoomin", 0.58, "tri"),
        "pixel_flow": ("pixelize", 0.6, "tri"),
        "stinger": ("fade", 0.12, "tri"),
        "dip_to_black": ("fadeblack", 0.72, "tri"),
    }

    xfade_name, duration, audio_curve = profiles.get(key, ("fade", 0.5, "tri"))

    if conservative:
        if xfade_name == "fadeblack":
            return "fadeblack", 0.62, "tri"
        # Keep compatibility fallback simple and broadly supported.
        return "fade", 0.36, "tri"

    return xfade_name, duration, audio_curve


def _run_concat_with_transitions(
    segment_paths: List[Path],
    durations: List[float],
    transitions: List[str],
    output_path: Path,
    conservative: bool,
) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-y"]
    for path in segment_paths:
        cmd.extend(["-i", str(path)])

    filter_parts = []
    video_label = "[0:v]"
    audio_label = "[0:a]"
    offset = durations[0]

    for index in range(1, len(segment_paths)):
        raw_transition = transitions[index - 1] if index - 1 < len(transitions) else "dissolve"
        transition, duration, audio_curve = _transition_profile(raw_transition, conservative=conservative)

        offset = max(0.0, offset - duration)
        next_video = f"[v{index}]"
        next_audio = f"[a{index}]"
        filter_parts.append(
            f"{video_label}[{index}:v]xfade=transition={transition}:duration={duration}:offset={offset}{next_video}"
        )
        filter_parts.append(
            f"{audio_label}[{index}:a]acrossfade=d={duration}:c1={audio_curve}:c2={audio_curve}{next_audio}"
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

    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _concat_segments(segment_paths: List[Path], transitions: List[str], output_path: Path) -> Path:
    """
    Concatenate clips using xfade/acrossfade when available, otherwise fall back
    to the concat demuxer.
    """
    if len(segment_paths) <= 1:
        return _basic_concat_segments(segment_paths, output_path)

    durations = [_get_media_duration(path) for path in segment_paths]

    result = _run_concat_with_transitions(
        segment_paths,
        durations,
        transitions,
        output_path,
        conservative=False,
    )
    if result.returncode == 0:
        log.info(f"Final video with transitions: {output_path}")
        return output_path

    log.warning(f"Transition concat failed; retrying conservative transition profile.\n{result.stderr[-1200:]}")

    fallback_result = _run_concat_with_transitions(
        segment_paths,
        durations,
        transitions,
        output_path,
        conservative=True,
    )
    if fallback_result.returncode == 0:
        log.info(f"Final video with conservative transitions: {output_path}")
        return output_path

    log.warning(f"Conservative transition concat failed, falling back to basic concat.\n{fallback_result.stderr[-1200:]}")
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
    transitions = [visual.get("transition", "dissolve") for visual in render_visuals]
    transitions = transitions[: max(0, len(clip_paths) - 1)]
    concat_paths, concat_transitions = _inject_stinger_clips(clip_paths, transitions, render_visuals, job_id)
    _concat_segments(concat_paths, concat_transitions, final_path)

    return final_path
