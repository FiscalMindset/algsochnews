"""
visual_planner.py — Broadcast scene planner and scene-image composer.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from typing import List, Optional, Sequence

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from backend.utils import config, get_logger

log = get_logger("visual_planner")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsVideoBot/2.0)"
}


def _safe_filename(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16] + ".jpg"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        ("/System/Library/Fonts/Helvetica.ttc", size),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", size),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size),
    ]
    for path, size in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _download_image(url: str, dest_dir: Path) -> Optional[Path]:
    if not url or not url.startswith("http"):
        return None
    dest = dest_dir / _safe_filename(url)
    if dest.exists():
        return dest
    try:
        response = requests.get(url, headers=HEADERS, timeout=10, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type and "octet-stream" not in content_type:
            return None
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(8192):
                handle.write(chunk)
        img = Image.open(dest).convert("RGB")
        img.save(dest, "JPEG", quality=92)
        return dest
    except Exception as exc:
        log.warning(f"Image download failed ({url[:60]}): {exc}")
        dest.unlink(missing_ok=True)
        return None


def prepare_source_images(article_images: List[str], job_id: str) -> List[dict]:
    media_dir = config.MEDIA_DIR / job_id / "source"
    media_dir.mkdir(parents=True, exist_ok=True)
    downloaded: List[dict] = []
    for image_url in article_images[:10]:
        path = _download_image(image_url, media_dir)
        if path:
            downloaded.append({"url": image_url, "path": path})
    return downloaded


def _fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    img = img.convert("RGB")
    scale = max(target_w / img.width, target_h / img.height)
    resized = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _gradient_background(size: tuple[int, int], top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    return image


def _create_anchor_panel(size: tuple[int, int], top_tag: str) -> Image.Image:
    width, height = size
    panel = _gradient_background(size, (12, 20, 44), (3, 9, 22))
    draw = ImageDraw.Draw(panel)

    for radius, alpha in ((160, 40), (110, 80), (65, 150)):
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.ellipse(
            (
                width - 220 - radius,
                90 - radius,
                width - 220 + radius,
                90 + radius,
            ),
            fill=(35, 95, 255, alpha),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(24))
        panel = Image.alpha_composite(panel.convert("RGBA"), glow).convert("RGB")
        draw = ImageDraw.Draw(panel)

    draw.rounded_rectangle((28, 28, width - 28, height - 28), radius=22, outline=(58, 96, 170), width=2)
    draw.rounded_rectangle((40, 40, width - 40, 100), radius=16, fill=(194, 35, 47))
    draw.text((58, 56), top_tag, fill="white", font=_font(26, bold=True))

    # Studio wall lines
    for row in range(3):
        y = 150 + row * 90
        draw.rounded_rectangle((44, y, width - 44, y + 44), radius=12, outline=(31, 54, 92), width=1)
    for x in range(70, width - 60, 32):
        draw.line((x, 132, x, height - 70), fill=(19, 43, 80), width=1)

    # Simple anchor silhouette
    head_center = (width // 2, height // 2 - 36)
    draw.ellipse((head_center[0] - 54, head_center[1] - 68, head_center[0] + 54, head_center[1] + 40), fill=(238, 205, 184))
    draw.rounded_rectangle((head_center[0] - 88, head_center[1] + 40, head_center[0] + 88, height - 120), radius=28, fill=(20, 28, 52))
    draw.polygon(
        [
            (head_center[0] - 46, head_center[1] + 48),
            (head_center[0], head_center[1] + 118),
            (head_center[0] + 46, head_center[1] + 48),
        ],
        fill=(255, 255, 255),
    )
    draw.polygon(
        [
            (head_center[0] - 90, head_center[1] + 44),
            (head_center[0] - 10, head_center[1] + 122),
            (head_center[0] - 10, height - 120),
            (head_center[0] - 120, height - 120),
        ],
        fill=(36, 54, 103),
    )
    draw.polygon(
        [
            (head_center[0] + 90, head_center[1] + 44),
            (head_center[0] + 10, head_center[1] + 122),
            (head_center[0] + 10, height - 120),
            (head_center[0] + 120, height - 120),
        ],
        fill=(36, 54, 103),
    )

    label_font = _font(22, bold=True)
    small_font = _font(16)
    draw.text((56, height - 104), "AI ANCHOR", fill=(255, 255, 255), font=label_font)
    draw.text((56, height - 74), "Studio-side narration panel", fill=(150, 176, 220), font=small_font)
    return panel


def _create_support_visual(size: tuple[int, int], headline: str, prompt: str, top_tag: str) -> Image.Image:
    base = _gradient_background(size, (24, 29, 52), (63, 31, 42))
    draw = ImageDraw.Draw(base)
    width, height = size

    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=22, outline=(255, 255, 255), width=2)
    draw.rounded_rectangle((32, 30, 210, 74), radius=12, fill=(22, 25, 39))
    draw.text((48, 42), top_tag, font=_font(20, bold=True), fill=(255, 216, 84))

    for x in range(60, width, 120):
        draw.line((x, 110, x - 80, height - 40), fill=(214, 224, 248), width=2)
    for y in range(120, height, 72):
        draw.line((40, y, width - 40, y), fill=(90, 118, 170), width=1)

    title_lines = textwrap.wrap(headline, width=20)[:3]
    prompt_lines = textwrap.wrap(prompt, width=28)[:5]
    y = 120
    for line in title_lines:
        draw.text((52, y), line, font=_font(34, bold=True), fill=(255, 255, 255))
        y += 40
    y += 12
    for line in prompt_lines:
        draw.text((52, y), line, font=_font(18), fill=(205, 216, 240))
        y += 28

    draw.rounded_rectangle((44, height - 138, width - 44, height - 54), radius=18, fill=(10, 14, 24))
    draw.text((64, height - 118), "AI SUPPORT VISUAL", font=_font(20, bold=True), fill=(255, 255, 255))
    draw.text((64, height - 88), "Generated planning placeholder for the right-side panel", font=_font(16), fill=(165, 182, 214))
    return base


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int, max_lines: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] > width and current:
            lines.append(" ".join(current))
            current = [word]
            if len(lines) == max_lines:
                break
        else:
            current.append(word)
    if current and len(lines) < max_lines:
        lines.append(" ".join(current))
    return lines


def _camera_motion(segment_type: str, index: int, has_source: bool) -> str:
    if segment_type == "intro":
        return "push_in"
    if segment_type == "outro":
        return "pull_back"
    if not has_source:
        return ["drift_right", "rise", "steady", "push_in"][index % 4]
    return ["drift_left", "drift_right", "rise", "steady"][index % 4]


def _director_note(layout: str, transition: str, camera_motion: str, has_source: bool) -> str:
    visual_kind = "source-grounded visual" if has_source else "AI-support visual"
    return (
        f"Maintain {layout}, use {camera_motion} motion, then exit on {transition}. "
        f"Keep the beat anchored to the {visual_kind}."
    )


def _compose_scene(
    dest: Path,
    source_domain: str,
    package: dict,
    panel_visual: Image.Image,
) -> Path:
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    canvas = _gradient_background((width, height), (7, 10, 18), (13, 19, 33))
    draw = ImageDraw.Draw(canvas)

    # Background texture
    for x in range(0, width, 80):
        draw.line((x, 0, x + 180, height), fill=(18, 31, 54), width=1)

    left_box = (42, 122, 440, 610)
    right_box = (486, 122, 1238, 610)
    top_bar = (34, 28, width - 34, 108)
    lower_bar = (34, 626, width - 34, height - 34)
    ticker_bar = (46, height - 76, width - 46, height - 42)

    draw.rounded_rectangle(top_bar, radius=24, fill=(9, 13, 22), outline=(39, 56, 90), width=2)
    draw.rounded_rectangle(lower_bar, radius=24, fill=(10, 14, 25), outline=(39, 56, 90), width=2)
    draw.rounded_rectangle(left_box, radius=24, fill=(8, 14, 24), outline=(48, 74, 120), width=2)
    draw.rounded_rectangle(right_box, radius=24, fill=(8, 14, 24), outline=(48, 74, 120), width=2)

    tag_box = (54, 42, 240, 94)
    draw.rounded_rectangle(tag_box, radius=16, fill=(195, 34, 46))
    draw.text((74, 58), package["top_tag"], font=_font(24, bold=True), fill="white")

    headline_font = _font(34, bold=True)
    sub_font = _font(20)
    headline_lines = _wrap(draw, package["main_headline"], headline_font, 860, 2)
    subheadline_lines = _wrap(draw, package["subheadline"], sub_font, 860, 2)
    y = 40
    for line in headline_lines:
        draw.text((270, y), line, font=headline_font, fill=(255, 255, 255))
        y += 38
    for line in subheadline_lines:
        draw.text((270, y), line, font=sub_font, fill=(188, 204, 229))
        y += 24

    anchor_panel = _create_anchor_panel((left_box[2] - left_box[0], left_box[3] - left_box[1]), package["top_tag"])
    canvas.paste(anchor_panel, (left_box[0], left_box[1]))

    panel_visual = _fit_cover(panel_visual, (right_box[2] - right_box[0], right_box[3] - right_box[1]))
    canvas.paste(panel_visual, (right_box[0], right_box[1]))

    draw.text((56, 584), package["left_panel"], font=_font(16, bold=True), fill=(171, 188, 220))
    right_panel_lines = _wrap(draw, package["right_panel"], _font(16), 700, 2)
    y = 584
    for line in right_panel_lines:
        draw.text((504, y), line, font=_font(16), fill=(171, 188, 220))
        y += 20

    lower_font = _font(22, bold=True)
    mono_font = _font(16)
    draw.text((56, 642), package.get("lower_third", package["main_headline"]), font=lower_font, fill=(255, 255, 255))
    draw.text(
        (56, 668),
        f"{package['start_timecode']} - {package['end_timecode']}  {source_domain.upper() or 'NEWS DESK'}",
        font=mono_font,
        fill=(116, 145, 194),
    )

    draw.rounded_rectangle(ticker_bar, radius=14, fill=(141, 23, 36))
    ticker_font = _font(18, bold=True)
    ticker_text = package.get("ticker_text", package["main_headline"])
    ticker_loop = f"{ticker_text}   •   {ticker_text}   •   {ticker_text}"
    draw.text((66, height - 68), ticker_loop, font=ticker_font, fill=(255, 248, 248))

    control_box = (width - 312, 646, width - 58, 698)
    draw.rounded_rectangle(control_box, radius=16, fill=(8, 12, 21), outline=(195, 34, 46), width=2)
    draw.text((width - 290, 662), "LIVE EDIT CONTROL", font=_font(17, bold=True), fill=(255, 214, 214))

    canvas.save(dest, "JPEG", quality=94)
    return dest


def plan_visuals(
    segments: Sequence[dict],
    packages: Sequence[dict],
    article_images: List[str],
    source_domain: str,
    job_id: str,
    source_inventory: Optional[List[dict]] = None,
) -> List[dict]:
    media_dir = config.MEDIA_DIR / job_id
    support_dir = media_dir / "support"
    scene_dir = media_dir / "scenes"
    for directory in (support_dir, scene_dir):
        directory.mkdir(parents=True, exist_ok=True)

    downloaded = source_inventory if source_inventory is not None else prepare_source_images(article_images, job_id)

    log.info(f"Downloaded {len(downloaded)}/{len(article_images[:10])} source images")

    visuals: List[dict] = []
    source_cursor = 0

    for index, (seg, package) in enumerate(zip(segments, packages)):
        prefer_source = seg["segment_type"] in {"intro", "outro"} or index % 2 == 0
        source_item = None
        if prefer_source and source_cursor < len(downloaded):
            source_item = downloaded[source_cursor]
            source_cursor += 1
        elif source_cursor < len(downloaded) and seg["segment_type"] == "body" and index == len(segments) - 2:
            source_item = downloaded[source_cursor]
            source_cursor += 1

        support_prompt = (
            f"realistic news broadcast support visual, {package['main_headline'].lower()}, "
            f"{package['source_excerpt'].lower()}, cinematic lighting, newsroom quality"
        )

        if source_item:
            layout = "anchor_left + source_visual_right"
            right_panel = f"Source article image {source_cursor} supporting the {package['main_headline']} beat"
            panel_visual = Image.open(source_item["path"]).convert("RGB")
            source_image_url = source_item["url"]
            ai_support_visual_prompt = None
            support_path = None
            rationale = "A source image is available for this beat, so the package keeps factual visual grounding on screen."
            visual_source_kind = "source"
            visual_confidence = 0.92
        else:
            layout = "anchor_left + ai_support_visual_right"
            right_panel = f"AI-generated support visual for {package['main_headline'].lower()}"
            panel_visual = _create_support_visual((752, 488), package["main_headline"], support_prompt, package["top_tag"])
            support_path = support_dir / f"seg_{index:02d}_support.jpg"
            panel_visual.save(support_path, "JPEG", quality=92)
            source_image_url = None
            ai_support_visual_prompt = support_prompt
            rationale = "No reliable source image was available for this beat, so the package uses an AI-support visual plan."
            visual_source_kind = "ai_support"
            visual_confidence = 0.74

        camera_motion = _camera_motion(seg["segment_type"], index, bool(source_item))
        control_room_cue = (
            f"Hold anchor on the left, keep {visual_source_kind.replace('_', ' ')} on the right, "
            f"and pace this beat with a {camera_motion.replace('_', ' ')} move."
        )
        director_note = _director_note(layout, package["transition"], camera_motion, bool(source_item))
        package_with_visual = {
            **package,
            "layout": layout,
            "left_panel": "AI anchor in studio",
            "right_panel": right_panel,
            "anchor_narration": package["anchor_narration"],
            "start_timecode": package["start_timecode"],
            "end_timecode": package["end_timecode"],
            "camera_motion": camera_motion,
        }

        scene_path = scene_dir / f"seg_{index:02d}_scene.jpg"
        _compose_scene(scene_path, source_domain, package_with_visual, panel_visual)

        visuals.append(
            {
                "index": index,
                "layout": layout,
                "left_panel": "AI anchor in studio",
                "right_panel": right_panel,
                "source_image_url": source_image_url,
                "source_image_path": str(source_item["path"]) if source_item else None,
                "ai_support_visual_prompt": ai_support_visual_prompt,
                "support_image_path": str(support_path) if support_path else None,
                "image_path": str(scene_path),
                "scene_image_path": str(scene_path),
                "scene_image_url": f"/media/{job_id}/scenes/{scene_path.name}",
                "visual_prompt": ai_support_visual_prompt or "",
                "visual_rationale": rationale,
                "transition": package["transition"],
                "camera_motion": camera_motion,
                "visual_source_kind": visual_source_kind,
                "visual_confidence": visual_confidence,
                "control_room_cue": control_room_cue,
                "director_note": director_note,
            }
        )

    return visuals
