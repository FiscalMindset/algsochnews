"""
visual_planner.py — Broadcast scene planner and scene-image composer.
"""

from __future__ import annotations

import hashlib
import html
import textwrap
from pathlib import Path
from typing import List, Optional, Sequence

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from backend.utils import config, get_logger, sanitize_text

log = get_logger("visual_planner")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsVideoBot/2.0)"
}
LOW_VALUE_IMAGE_HINTS = ("flag", "icon", "logo", "sprite", "avatar", "badge")
MIN_IMAGE_WIDTH = 560
MIN_IMAGE_HEIGHT = 320
MIN_IMAGE_AREA = 560 * 320


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


def _is_low_value_image(url: str, width: int, height: int) -> bool:
    lower_url = url.lower()
    if any(token in lower_url for token in LOW_VALUE_IMAGE_HINTS):
        return True
    if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
        return True
    if width * height < MIN_IMAGE_AREA:
        return True
    aspect = width / max(height, 1)
    # Narrow strips and almost-square tiny assets are poor as right-panel visuals.
    if aspect > 3.2 or aspect < 0.45:
        return True
    return False


def _image_quality_score(url: str, width: int, height: int) -> float:
    area_score = min((width * height) / float(1920 * 1080), 1.0)
    aspect = width / max(height, 1)
    aspect_score = 1.0 - min(abs(aspect - 16 / 9) / 1.2, 1.0)
    penalty = 0.25 if any(token in url.lower() for token in LOW_VALUE_IMAGE_HINTS) else 0.0
    return round(max(0.0, 0.65 * area_score + 0.35 * aspect_score - penalty), 3)


def prepare_source_images(article_images: List[str], job_id: str) -> List[dict]:
    media_dir = config.MEDIA_DIR / job_id / "source"
    media_dir.mkdir(parents=True, exist_ok=True)
    downloaded: List[dict] = []
    for image_url in article_images[:10]:
        if any(token in image_url.lower() for token in LOW_VALUE_IMAGE_HINTS):
            continue
        path = _download_image(image_url, media_dir)
        if path:
            try:
                with Image.open(path) as img:
                    width, height = img.size
            except Exception:
                path.unlink(missing_ok=True)
                continue

            if _is_low_value_image(image_url, width, height):
                path.unlink(missing_ok=True)
                continue

            downloaded.append(
                {
                    "url": image_url,
                    "path": path,
                    "width": width,
                    "height": height,
                    "quality_score": _image_quality_score(image_url, width, height),
                }
            )
    downloaded.sort(key=lambda item: item.get("quality_score", 0.0), reverse=True)
    return downloaded


def plan_visual_blueprint(
    segments: Sequence[dict],
    source_inventory: Optional[Sequence[dict]] = None,
) -> List[dict]:
    """
    Create a lightweight visual-routing blueprint independent from headline copy.
    This can run in parallel with copy/headline generation and later be merged
    with the richer packaging metadata.
    """
    total = len(segments)
    source_budget = len(source_inventory or [])
    blueprint: List[dict] = []

    for index, seg in enumerate(segments):
        segment_type = str(seg.get("segment_type", "body"))
        prefer_source = segment_type in {"intro", "outro"} or index % 2 == 0
        if segment_type == "body" and index == max(0, total - 2):
            prefer_source = True

        preferred_kind = "source" if prefer_source and source_budget > 0 else "ai_support"
        if preferred_kind == "source":
            source_budget -= 1

        blueprint.append(
            {
                "index": index,
                "segment_type": segment_type,
                "preferred_visual_kind": preferred_kind,
                "preferred_layout": (
                    "anchor_left + source_visual_right"
                    if preferred_kind == "source"
                    else "anchor_left + ai_support_visual_right"
                ),
                "reason": (
                    "Prioritize source grounding for opening/closing or high-salience beats."
                    if preferred_kind == "source"
                    else "Fallback to AI support visual where source assets are unavailable."
                ),
            }
        )

    return blueprint


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


def _create_support_visual(size: tuple[int, int], headline: str, support_copy: str, top_tag: str) -> Image.Image:
    base = _gradient_background(size, (24, 29, 52), (63, 31, 42))
    draw = ImageDraw.Draw(base)
    width, height = size

    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=22, outline=(255, 255, 255), width=2)
    draw.rounded_rectangle((32, 30, 218, 74), radius=12, fill=(22, 25, 39))
    support_tag_font = _font(18, bold=True)
    tag_text = _truncate_to_width(draw, top_tag.upper(), support_tag_font, 170)
    draw.text((46, 44), tag_text, font=support_tag_font, fill=(255, 216, 84))

    for x in range(60, width, 120):
        draw.line((x, 110, x - 80, height - 40), fill=(214, 224, 248), width=2)
    for y in range(120, height, 72):
        draw.line((40, y, width - 40, y), fill=(90, 118, 170), width=1)

    title_font = _font(36, bold=True)
    detail_font = _font(20)
    title_lines = _wrap(draw, headline, title_font, width - 104, 2)
    detail_lines = _wrap(draw, support_copy, detail_font, width - 104, 3)

    y = 104
    for line in title_lines:
        draw.text((52, y), line, font=title_font, fill=(255, 255, 255))
        y += 42

    y += 6
    draw.line((52, y, width - 52, y), fill=(121, 158, 221), width=2)
    y += 12
    for line in detail_lines:
        draw.text((52, y), line, font=detail_font, fill=(208, 220, 244))
        y += 28

    chip_box = (44, height - 78, width - 44, height - 34)
    draw.rounded_rectangle(chip_box, radius=14, fill=(10, 14, 24))
    draw.text((62, height - 64), "SUPPORT VISUAL", font=_font(18, bold=True), fill=(255, 255, 255))
    draw.text((250, height - 62), "Story context generated from available source text", font=_font(14), fill=(167, 189, 226))
    return base


def _brief_copy(text: str, max_words: int = 22) -> str:
    cleaned = sanitize_text(text or "")
    if not cleaned:
        return "Context visual generated from verified story details."

    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    return " ".join(words[:max_words]) + "..."


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _split_token(draw: ImageDraw.ImageDraw, token: str, font: ImageFont.ImageFont, width: int) -> List[str]:
    if _text_width(draw, token, font) <= width:
        return [token]

    chunks: List[str] = []
    current = ""
    for char in token:
        candidate = f"{current}{char}"
        if current and _text_width(draw, candidate, font) > width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _truncate_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    width: int,
    suffix: str = "...",
) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if _text_width(draw, cleaned, font) <= width:
        return cleaned

    low, high = 0, len(cleaned)
    best = suffix
    while low <= high:
        mid = (low + high) // 2
        candidate = f"{cleaned[:mid].rstrip()}{suffix}"
        if _text_width(draw, candidate, font) <= width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int, max_lines: int) -> List[str]:
    words = " ".join((text or "").split()).split()
    if not words or max_lines <= 0:
        return []

    tokens: List[str] = []
    for word in words:
        tokens.extend(_split_token(draw, word, font, width))

    lines: List[str] = []
    current: List[str] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if len(lines) == max_lines - 1:
            tail = " ".join(current + tokens[i:])
            lines.append(_truncate_to_width(draw, tail, font, width))
            return lines

        candidate = " ".join(current + [token]) if current else token
        if _text_width(draw, candidate, font) <= width:
            current.append(token)
            i += 1
            continue

        if current:
            lines.append(" ".join(current))
            current = []
        else:
            lines.append(_truncate_to_width(draw, token, font, width))
            i += 1

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


def _write_html_frame(
        dest: Path,
        package: dict,
        source_domain: str,
        visual_url: str,
        visual_kind: str,
) -> Path:
        top_tag = html.escape(package.get("top_tag", "UPDATE"))
        main_headline = html.escape(package.get("main_headline", ""))
        subheadline = html.escape(package.get("subheadline", ""))
        lower_third = html.escape(package.get("lower_third", ""))
        ticker_text = html.escape(package.get("ticker_text", ""))
        start_tc = html.escape(package.get("start_timecode", "00:00"))
        end_tc = html.escape(package.get("end_timecode", "00:00"))
        visual_src = html.escape(visual_url or "")
        source_domain = html.escape((source_domain or "news desk").upper())
        visual_label = "SOURCE" if visual_kind == "source" else "AI SUPPORT"
        transition_label = html.escape(str(package.get("transition", "cut")).replace("_", " "))

        html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{main_headline}</title>
    <style>
        :root {{
            --bg1: #040c1b;
            --bg2: #0b1e3d;
            --ink: #f7fbff;
            --sub: #c3d5f1;
            --accent: #e11d2f;
        }}
        * {{ box-sizing: border-box; }}
        html, body {{
            margin: 0;
            width: 100vw;
            height: 100vh;
            overflow: hidden !important;
            background: #030811;
        }}
        body {{
            display: grid;
            place-items: center;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            color: var(--ink);
        }}
        .frame {{
            width: min(100vw, calc(100vh * 16 / 9));
            height: min(100vh, calc(100vw * 9 / 16));
            border-radius: 18px;
            border: 1px solid rgba(146, 188, 255, 0.22);
            box-shadow: 0 28px 60px rgba(3, 8, 20, 0.66);
            background: radial-gradient(circle at 82% 8%, rgba(59,130,246,.40), transparent 42%),
                linear-gradient(135deg, var(--bg1), var(--bg2));
            display: grid;
            grid-template-rows: minmax(0, 22%) 1fr minmax(0, 24%);
            gap: clamp(4px, 0.8vw, 12px);
            padding: clamp(6px, 1.1vw, 18px);
            overflow: hidden;
        }}
        .top {{
            border: 1px solid rgba(255,255,255,.18);
            border-radius: 16px;
            background: rgba(5, 12, 24, .80);
            display: grid;
            grid-template-columns: minmax(74px, 16%) minmax(0, 1fr);
            align-items: center;
            gap: clamp(6px, 0.9vw, 16px);
            padding: clamp(5px, 0.8vw, 12px) clamp(6px, 1vw, 16px);
            min-height: 0;
        }}
        .tag {{
            justify-self: start;
            background: var(--accent);
            border-radius: 999px;
            padding: clamp(3px, 0.7vw, 10px) clamp(6px, 0.9vw, 14px);
            font-size: clamp(9px, 1.05vw, 20px);
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .heads {{ min-width: 0; }}
        .heads h1 {{
            margin: 0;
            font-size: clamp(12px, 2.3vw, 40px);
            line-height: 1.04;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
            word-break: break-word;
            overflow-wrap: anywhere;
        }}
        .heads p {{
            margin: clamp(4px, .7vw, 8px) 0 0 0;
            color: var(--sub);
            font-size: clamp(10px, 1.3vw, 22px);
            line-height: 1.2;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
            word-break: break-word;
            overflow-wrap: anywhere;
        }}
        .main {{
            display: grid;
            grid-template-columns: minmax(90px, 31%) minmax(0, 1fr);
            gap: clamp(4px, 0.8vw, 14px);
            min-height: 0;
        }}
        .left, .right {{
            border: 1px solid rgba(255,255,255,.15);
            border-radius: 16px;
            overflow: hidden;
            background: rgba(7,13,24,.74);
            min-height: 0;
        }}
        .left {{
            display: grid;
            align-content: end;
            gap: 6px;
            padding: clamp(5px, 0.8vw, 14px);
            background: linear-gradient(160deg, rgba(20,34,66,.94), rgba(6,12,24,.94));
        }}
        .left .label {{
            font-size: clamp(10px, 1.1vw, 20px);
            color: #b7d1fb;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
        }}
        .left .cue {{
            margin: 0;
            font-size: clamp(9px, 0.95vw, 15px);
            color: #dce9ff;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }}
        .right-wrap {{ position: relative; height: 100%; }}
        .right img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
        .visual-kind {{
            position: absolute;
            top: clamp(4px, 0.8vw, 12px);
            left: clamp(4px, 0.8vw, 12px);
            background: rgba(3,9,18,.82);
            border: 1px solid rgba(255,255,255,.24);
            color: #dbeafe;
            font-weight: 700;
            font-size: clamp(8px, 0.85vw, 14px);
            padding: clamp(3px, 0.5vw, 6px) clamp(6px, 0.8vw, 10px);
            border-radius: 999px;
            letter-spacing: .06em;
            max-width: 45%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .bottom {{
            border: 1px solid rgba(255,255,255,.16);
            border-radius: 16px;
            background: rgba(4,10,20,.80);
            display: grid;
            grid-template-rows: auto auto;
            padding: clamp(5px, 0.8vw, 12px) clamp(6px, 1vw, 16px);
            gap: clamp(4px, .6vw, 10px);
            min-height: 0;
        }}
        .lower {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 12px;
            min-height: 0;
        }}
        .lower strong {{
            font-size: clamp(10px, 1.45vw, 28px);
            line-height: 1.17;
            max-width: 68%;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
            overflow-wrap: anywhere;
        }}
        .time {{
            font-family: 'JetBrains Mono', monospace;
            color: #9fc6ff;
            font-size: clamp(8px, 0.95vw, 16px);
            max-width: 32%;
            text-align: right;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .ticker {{
            background: rgba(225, 29, 47, .24);
            border: 1px solid rgba(225, 29, 47, .52);
            border-radius: 12px;
            padding: clamp(4px, .6vw, 10px) clamp(6px, 0.8vw, 12px);
            font-size: clamp(9px, 1.05vw, 19px);
            color: #ffe5e7;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
    </style>
</head>
<body>
    <article class=\"frame\">
        <section class=\"top\">
            <div class=\"tag\">{top_tag}</div>
            <div class=\"heads\">
                <h1>{main_headline}</h1>
                <p>{subheadline}</p>
            </div>
        </section>
        <section class=\"main\">
            <div class=\"left\">
                <div class=\"label\">Anchor Feed</div>
                <p class=\"cue\">Camera: {html.escape(package.get('camera_motion', 'steady')).replace('_', ' ')}</p>
                <p class=\"cue\">Transition: {transition_label}</p>
            </div>
            <div class=\"right\">
                <div class=\"right-wrap\">
                    <span class=\"visual-kind\">{visual_label}</span>
                    <img src=\"{visual_src}\" alt=\"Frame visual\" />
                </div>
            </div>
        </section>
        <section class=\"bottom\">
            <div class=\"lower\">
                <strong>{lower_third}</strong>
                <span class=\"time\">{start_tc} - {end_tc} | {source_domain}</span>
            </div>
            <div class=\"ticker\">{ticker_text}</div>
        </section>
    </article>
</body>
</html>
"""
        dest.write_text(html_doc, encoding="utf-8")
        return dest


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

    left_box = (42, 172, 440, 548)
    right_box = (486, 172, 1238, 548)
    top_bar = (34, 24, width - 34, 152)
    lower_bar = (34, 556, width - 34, height - 24)
    ticker_bar = (46, height - 72, width - 46, height - 34)

    draw.rounded_rectangle(top_bar, radius=24, fill=(9, 13, 22), outline=(39, 56, 90), width=2)
    draw.rounded_rectangle(lower_bar, radius=24, fill=(10, 14, 25), outline=(39, 56, 90), width=2)
    draw.rounded_rectangle(left_box, radius=24, fill=(8, 14, 24), outline=(48, 74, 120), width=2)
    draw.rounded_rectangle(right_box, radius=24, fill=(8, 14, 24), outline=(48, 74, 120), width=2)

    tag_box = (54, 36, 236, 94)
    draw.rounded_rectangle(tag_box, radius=16, fill=(195, 34, 46))
    scene_tag_font = _font(20, bold=True)
    tag_text = _truncate_to_width(draw, package.get("top_tag", "UPDATE"), scene_tag_font, 170)
    draw.text((72, 54), tag_text, font=scene_tag_font, fill="white")

    headline_font = _font(30, bold=True)
    sub_font = _font(18)
    headline_lines = _wrap(draw, package["main_headline"], headline_font, 850, 2)
    subheadline_lines = _wrap(draw, package["subheadline"], sub_font, 850, 2)
    y = 34
    for line in headline_lines:
        draw.text((270, y), line, font=headline_font, fill=(255, 255, 255))
        y += 33
    y += 4
    for line in subheadline_lines:
        draw.text((270, y), line, font=sub_font, fill=(188, 204, 229))
        y += 22

    anchor_panel = _create_anchor_panel((left_box[2] - left_box[0], left_box[3] - left_box[1]), package["top_tag"])
    canvas.paste(anchor_panel, (left_box[0], left_box[1]))

    panel_visual = _fit_cover(panel_visual, (right_box[2] - right_box[0], right_box[3] - right_box[1]))
    canvas.paste(panel_visual, (right_box[0], right_box[1]))

    lower_font = _font(22, bold=True)
    mono_font = _font(16)
    lower_lines = _wrap(draw, package.get("lower_third", package["main_headline"]), lower_font, 760, 2)
    lower_y = 572
    for line in lower_lines:
        draw.text((56, lower_y), line, font=lower_font, fill=(255, 255, 255))
        lower_y += 23

    time_line = _truncate_to_width(
        draw,
        f"{package['start_timecode']} - {package['end_timecode']}  {source_domain.upper() or 'NEWS DESK'}",
        mono_font,
        360,
    )
    time_width = _text_width(draw, time_line, mono_font)
    draw.text(
        (width - 56 - time_width, 574),
        time_line,
        font=mono_font,
        fill=(116, 145, 194),
    )

    draw.rounded_rectangle(ticker_bar, radius=14, fill=(141, 23, 36))
    ticker_font = _font(18, bold=True)
    ticker_text = package.get("ticker_text", package["main_headline"])
    ticker_line = _truncate_to_width(draw, ticker_text, ticker_font, ticker_bar[2] - ticker_bar[0] - 24)
    draw.text((58, height - 62), ticker_line, font=ticker_font, fill=(255, 248, 248))

    canvas.save(dest, "JPEG", quality=94)
    return dest


def plan_visuals(
    segments: Sequence[dict],
    packages: Sequence[dict],
    article_images: List[str],
    source_domain: str,
    job_id: str,
    source_inventory: Optional[List[dict]] = None,
    visual_blueprint: Optional[Sequence[dict]] = None,
) -> List[dict]:
    media_dir = config.MEDIA_DIR / job_id
    support_dir = media_dir / "support"
    scene_dir = media_dir / "scenes"
    frame_dir = media_dir / "frames"
    for directory in (support_dir, scene_dir, frame_dir):
        directory.mkdir(parents=True, exist_ok=True)

    downloaded = source_inventory if source_inventory is not None else prepare_source_images(article_images, job_id)

    log.info(f"Downloaded {len(downloaded)}/{len(article_images[:10])} source images")

    visuals: List[dict] = []
    has_any_source = len(downloaded) > 0
    blueprint_by_index = {
        int(item.get("index", -1)): item
        for item in (visual_blueprint or [])
        if isinstance(item, dict)
    }

    for index, (seg, package) in enumerate(zip(segments, packages)):
        blueprint_item = blueprint_by_index.get(index, {})
        source_item = None
        source_reused = False
        if has_any_source:
            source_index = index % len(downloaded)
            source_item = downloaded[source_index]
            source_reused = index >= len(downloaded)

        support_copy = _brief_copy(package.get("source_excerpt", ""), max_words=20)
        support_prompt = (
            f"Broadcast support visual for '{package['main_headline']}'. "
            f"Context: {support_copy}"
        )
        support_prompt = str(blueprint_item.get("support_prompt") or support_prompt)

        if source_item:
            layout = "anchor_left + source_visual_right"
            right_panel = f"Source visual supporting: {package['main_headline']}"
            panel_visual = Image.open(source_item["path"]).convert("RGB")
            source_image_url = source_item["url"]
            ai_support_visual_prompt = None
            support_path = None
            support_image_url = None
            rationale = (
                "A source image is available for this beat, so the package keeps factual visual grounding on screen."
                if not source_reused
                else "Reusing a verified source image to preserve source-grounded visuals across all beats."
            )
            visual_source_kind = "source"
            visual_confidence = 0.92
        else:
            layout = "anchor_left + ai_support_visual_right"
            right_panel = f"Support visual aligned to: {package['main_headline']}"
            panel_visual = _create_support_visual((752, 376), package["main_headline"], support_copy, package["top_tag"])
            support_path = support_dir / f"seg_{index:02d}_support.jpg"
            panel_visual.save(support_path, "JPEG", quality=92)
            source_image_url = None
            ai_support_visual_prompt = support_prompt
            support_image_url = f"/media/{job_id}/support/{support_path.name}"
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

        html_frame_path = frame_dir / f"seg_{index:02d}_frame.html"
        visual_url = source_image_url or support_image_url or f"/media/{job_id}/scenes/{scene_path.name}"
        _write_html_frame(
            html_frame_path,
            package_with_visual,
            source_domain,
            visual_url=visual_url,
            visual_kind=visual_source_kind,
        )

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
                "html_frame_path": str(html_frame_path),
                "html_frame_url": f"/media/{job_id}/frames/{html_frame_path.name}",
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
