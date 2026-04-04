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
    "Good evening. Breaking tonight: {headline}. {lead}",
    "We begin with breaking news: {headline}. {lead}",
    "Tonight's top story: {headline}. {lead}",
    "This is a developing story: {headline}. {lead}",
]

BODY_TEMPLATES = [
    "{lead}",
    "Officials say {lead}",
    "According to the latest reporting, {lead}",
    "The latest information indicates {lead}",
]

OUTRO_TEMPLATES = [
    "Authorities are still assessing the situation, and we will bring you more updates as they come in.",
    "That is the latest for now. We will continue tracking developments and return with new information.",
    "Officials say the situation remains active, and more confirmed details are expected soon.",
    "For now, that is the latest verified update on this story.",
]


def _template_narration(
    segment_type: str,
    text: str,
    headline: str = "",
) -> str:
    """Generate narration from template."""
    sentences = [s.strip() for s in text.split(".") if len(s.strip().split()) >= 4]
    lead = sentences[0] if sentences else text
    lead = sanitize_text(lead.rstrip("."))
    if segment_type == "intro":
        tpl = random.choice(INTRO_TEMPLATES)
        return tpl.format(headline=headline, text=text, lead=lead)
    elif segment_type == "outro":
        return random.choice(OUTRO_TEMPLATES)
    else:
        tpl = random.choice(BODY_TEMPLATES)
        return tpl.format(text=text, headline=headline, lead=lead)


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

        # 2. Gemini refinement (use on any segment when enabled to improve tone)
        if use_gemini:
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
