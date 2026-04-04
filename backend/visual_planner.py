"""
visual_planner.py — Assigns images or generates colored scene backgrounds for each segment.
Downloads article images; falls back to gradient placeholder images if unavailable.
"""

import hashlib
import os
import re
import requests
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
from backend.utils import get_logger, config

log = get_logger("visual_planner")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsVideoBot/1.0)"
}

# Gradient palettes for each segment type
PALETTES = {
    "intro":  [("#0B0F1A", "#1A1F3A"), ("#0D1B2A", "#1B2A4A")],
    "body":   [("#0A0F1E", "#1A2744"), ("#0F1628", "#203060"),
               ("#0B1422", "#182038"), ("#0D1530", "#1C2850")],
    "outro":  [("#0A0A1A", "#1A1A3A")],
}


def _safe_filename(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16] + ".jpg"


def _download_image(url: str, dest_dir: Path) -> Optional[Path]:
    """Download an image URL, saving to dest_dir. Returns local path or None."""
    if not url or not url.startswith("http"):
        return None
    dest = dest_dir / _safe_filename(url)
    if dest.exists():
        return dest
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and "octet-stream" not in content_type:
            return None
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        # Validate & resize
        img = Image.open(dest).convert("RGB")
        img = img.resize((config.VIDEO_WIDTH, config.VIDEO_HEIGHT), Image.LANCZOS)
        img.save(dest, "JPEG", quality=90)
        log.debug(f"Downloaded image → {dest.name}")
        return dest
    except Exception as e:
        log.warning(f"Image download failed ({url[:60]}): {e}")
        if dest.exists():
            dest.unlink(missing_ok=True)
        return None


def _create_placeholder(
    dest: Path,
    headline: str,
    segment_type: str,
    index: int,
    source_domain: str = "",
) -> Path:
    """
    Generate a news-style gradient placeholder image with headline text.
    """
    palette_list = PALETTES.get(segment_type, PALETTES["body"])
    bg1_hex, bg2_hex = palette_list[index % len(palette_list)]

    def hex_to_rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    W, H = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # Vertical gradient
    c1, c2 = hex_to_rgb(bg1_hex), hex_to_rgb(bg2_hex)
    for y in range(H):
        t = y / H
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Decorative accent strip at bottom
    accent_h = int(H * 0.08)
    for x in range(W):
        t = x / W
        r = int(0x0A + (0x7C - 0x0A) * t)
        g = int(0x7C - 0x3C * t)
        bb = int(0xFF - 0x4D * t)
        draw.line([(x, H - accent_h), (x, H)], fill=(r, g, bb, 200))

    # Breaking news ticker band
    ticker_y = H - accent_h - 80
    draw.rectangle([(0, ticker_y), (W, ticker_y + 66)], fill=(10, 10, 30, 210))
    draw.rectangle([(0, ticker_y), (220, ticker_y + 66)], fill=(200, 30, 30))

    # Try to load a suitable font; fall back to default
    font_large = font_small = font_ticker = None
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 44)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
        font_ticker = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    except Exception:
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
            font_ticker = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
        except Exception:
            font_large = font_small = font_ticker = ImageFont.load_default()

    # BREAKING NEWS label
    draw.text((10, ticker_y + 16), "BREAKING", font=font_ticker, fill=(255, 255, 255))

    # Headline text (word-wrapped)
    words = headline.split()
    lines, line = [], []
    for w in words:
        test = " ".join(line + [w])
        bbox = draw.textbbox((0, 0), test, font=font_ticker)
        if bbox[2] - bbox[0] > W - 250 and line:
            lines.append(" ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append(" ".join(line))

    text_x = 235
    text_y = ticker_y + 10
    for ln in lines[:2]:
        draw.text((text_x, text_y), ln, font=font_ticker, fill=(255, 220, 50))
        text_y += 32

    # Channel watermark
    if source_domain:
        draw.text((W - 280, 20), source_domain.upper(), font=font_small, fill=(255, 255, 255, 160))

    # Segment type label (top-left)
    label_map = {"intro": "LIVE", "outro": "RECAP", "body": f"SEGMENT {index+1}"}
    label = label_map.get(segment_type, "NEWS")
    draw.rectangle([(20, 20), (160, 58)], fill=(200, 30, 30))
    draw.text((28, 26), f"● {label}", font=font_small, fill=(255, 255, 255))

    img.save(dest, "JPEG", quality=92)
    log.debug(f"Created placeholder: {dest.name}")
    return dest


def plan_visuals(
    segments: List[dict],
    headlines: List[str],
    article_images: List[str],
    source_domain: str,
    job_id: str,
) -> List[dict]:
    """
    For each segment assign a local image path and visual prompt.
    Returns updated list of segment visual info.
    """
    media_dir = config.MEDIA_DIR / job_id
    media_dir.mkdir(parents=True, exist_ok=True)

    # Pre-download article images (up to 10)
    downloaded: List[Optional[Path]] = []
    for img_url in article_images[:10]:
        p = _download_image(img_url, media_dir)
        downloaded.append(p)
    downloaded = [p for p in downloaded if p]  # filter None

    log.info(
        f"Downloaded {len(downloaded)}/{len(article_images[:10])} article images"
    )

    visuals: List[dict] = []
    for i, (seg, headline) in enumerate(zip(segments, headlines)):
        seg_type = seg["segment_type"]

        # Try to use a downloaded article image
        image_path: Optional[Path] = None
        image_url: Optional[str] = None
        if seg_type != "outro" and i < len(downloaded):
            image_path = downloaded[i]
            image_url = article_images[i] if i < len(article_images) else None

        # Generate visual prompt (used in metadata / future image gen)
        visual_prompt = (
            f"realistic news broadcast scene, {headline.lower()}, "
            f"cinematic lighting, 4K, professional television studio"
        )

        # Fallback: placeholder image
        if not image_path:
            placeholder = media_dir / f"seg_{i:02d}_placeholder.jpg"
            image_path = _create_placeholder(
                dest=placeholder,
                headline=headline,
                segment_type=seg_type,
                index=i,
                source_domain=source_domain,
            )

        visuals.append(
            {
                "index": i,
                "image_path": str(image_path),
                "image_url": image_url,
                "visual_prompt": visual_prompt,
            }
        )

    return visuals
