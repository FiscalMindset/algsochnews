"""
html_frame_renderer.py - Rasterize HTML broadcast frames to images via Playwright.

This module is optional at runtime. If Playwright or Chromium is unavailable,
callers can fall back to pre-rendered scene JPGs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from backend.utils import config, get_logger

log = get_logger("html_frame_renderer")


def _render_one(page, html_path: Path, out_path: Path) -> bool:
    try:
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        if config.PLAYWRIGHT_RENDER_WAIT_MS > 0:
            page.wait_for_timeout(config.PLAYWRIGHT_RENDER_WAIT_MS)
        page.screenshot(path=str(out_path), type="jpeg", quality=92)
        return True
    except Exception as exc:
        log.warning(f"Failed to rasterize HTML frame {html_path.name}: {exc}")
        return False


def rasterize_html_frames(visuals: List[dict], job_id: str) -> List[dict]:
    """
    Convert visual html_frame_path files to JPEG images and set image_path to the
    rasterized output for downstream FFmpeg clip rendering.

    Returns updated visual dicts.
    """
    if not visuals:
        return visuals

    updated: List[dict] = [dict(item) for item in visuals]
    candidates = [
        (idx, Path(item["html_frame_path"]))
        for idx, item in enumerate(updated)
        if item.get("html_frame_path") and Path(item["html_frame_path"]).exists()
    ]
    if not candidates:
        return updated

    rasterized_dir = config.MEDIA_DIR / job_id / "rasterized"
    rasterized_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception as exc:
        log.warning(f"Playwright python package not available. Falling back to scene images: {exc}")
        return updated

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": config.VIDEO_WIDTH, "height": config.VIDEO_HEIGHT})

            rendered = 0
            for idx, html_path in candidates:
                out_name = f"frame_{idx:02d}.jpg"
                out_path = rasterized_dir / out_name
                if _render_one(page, html_path, out_path):
                    updated[idx]["rasterized_frame_path"] = str(out_path)
                    updated[idx]["rasterized_frame_url"] = f"/media/{job_id}/rasterized/{out_name}"
                    updated[idx]["image_path"] = str(out_path)
                    updated[idx]["render_source"] = "playwright_html_frame"
                    rendered += 1

            page.close()
            browser.close()
            log.info(f"Playwright rasterized {rendered}/{len(candidates)} HTML frames.")
            return updated
    except Exception as exc:
        log.warning(
            "Playwright Chromium could not launch or render frames. "
            f"Falling back to scene images: {exc}"
        )
        return updated
