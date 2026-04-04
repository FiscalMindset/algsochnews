"""
narration.py — Template-based narration generation + optional Gemini refinement.
"""

import os
import random
from typing import List, Optional
from backend.utils import get_logger, config, sanitize_text

log = get_logger("narration")

# ------------------------------------------------------------------ #
# Template bank — intro / body / outro variations
# ------------------------------------------------------------------ #
INTRO_TEMPLATES = [
    "Breaking news: {headline}. Here's what we know so far.",
    "In today's top story, {headline}. Let's dive into the details.",
    "This just in — {headline}. We bring you full coverage.",
    "Developing story: {headline}. Our team has the latest.",
]

BODY_TEMPLATES = [
    "{text}",
    "Reports confirm: {text}",
    "According to sources, {text}",
    "Our correspondents reveal: {text}",
]

OUTRO_TEMPLATES = [
    "That's all for this report. Stay with us for further developments.",
    "We will continue monitoring the situation and bring you updates as they happen.",
    "For the latest news, stay tuned to our channel. This has been a live update.",
    "Thank you for watching. We'll keep you informed as this story develops.",
]


def _template_narration(
    segment_type: str,
    text: str,
    headline: str = "",
) -> str:
    """Generate narration from template."""
    if segment_type == "intro":
        tpl = random.choice(INTRO_TEMPLATES)
        return tpl.format(headline=headline, text=text)
    elif segment_type == "outro":
        return random.choice(OUTRO_TEMPLATES)
    else:
        tpl = random.choice(BODY_TEMPLATES)
        return tpl.format(text=text, headline=headline)


# ------------------------------------------------------------------ #
# Gemini refinement
# ------------------------------------------------------------------ #

def _gemini_refine(
    raw_narration: str,
    context: str,
    segment_type: str,
    model_name: str,
    api_key: str,
) -> str:
    """
    Use Gemini to improve narration quality.
    Falls back to raw_narration on any error.
    """
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)

        prompt = f"""You are a professional news anchor script writer.
Improve the following {segment_type} narration for a TV news segment.
Rules:
- Keep it concise (under 60 words)
- Use formal but engaging news broadcast language
- Do NOT add commentary, opinions, or analysis not present in the source
- Return ONLY the revised narration text, nothing else

Original narration:
{raw_narration}

Context from article:
{context[:300]}
"""
        response = model.generate_content(prompt)
        refined = response.text.strip()
        if refined and len(refined) > 20:
            return refined
        return raw_narration
    except Exception as e:
        log.warning(f"Gemini refinement failed: {e}")
        return raw_narration


# ------------------------------------------------------------------ #
# Public
# ------------------------------------------------------------------ #

def generate_narrations(
    segments: List[dict],
    headlines: List[str],
    article_text: str,
    use_gemini: bool = True,
) -> List[str]:
    """
    Generate narration for each segment.
    Returns list of narration strings aligned to segments.
    """
    log.info(f"Generating narrations for {len(segments)} segments (gemini={use_gemini})")

    use_gemini = use_gemini and config.USE_GEMINI and bool(config.GEMINI_API_KEY)

    narrations: List[str] = []

    for i, (seg, headline) in enumerate(zip(segments, headlines)):
        # 1. Template baseline
        raw = _template_narration(
            segment_type=seg["segment_type"],
            text=seg["text"],
            headline=headline,
        )
        raw = sanitize_text(raw)

        # 2. Gemini refinement (body segments only, to control API cost)
        if use_gemini and seg["segment_type"] == "body":
            refined = _gemini_refine(
                raw_narration=raw,
                context=seg["text"],
                segment_type=seg["segment_type"],
                model_name=config.GEMINI_MODEL,
                api_key=config.GEMINI_API_KEY,
            )
            narrations.append(refined)
        else:
            narrations.append(raw)

        log.debug(f"Seg {i} ({seg['segment_type']}): {narrations[-1][:60]}…")

    return narrations
