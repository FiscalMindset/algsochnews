"""
narration.py — Template-based narration generation + optional Gemini refinement.
"""

import os
import re
from typing import List, Optional
from backend.utils import get_logger, config, sanitize_text

log = get_logger("narration")

# ------------------------------------------------------------------ #
# Template bank — intro / body / outro variations
# ------------------------------------------------------------------ #
INTRO_TEMPLATES = [
    "Breaking update: {headline}. {lead}",
    "Tonight: {headline}. {lead}",
    "Here is the latest: {headline}. {lead}",
]

OUTRO_TEMPLATES = [
    "Authorities are still assessing the situation, and we will bring you more updates as they come in.",
    "That is the latest for now. We will continue tracking developments and return with new information.",
    "Officials say the situation remains active, and more confirmed details are expected soon.",
    "For now, that is the latest verified update on this story.",
]

INSTRUCTIONAL_RE = re.compile(
    r"^(state|shift|let|deliver|read|speak|emphasize|convey|stress|frame|open|focus|"
    r"mention|use|keep|avoid|make\s+sure|ensure|pace|highlight|replace|cover|bridge)\b",
    re.IGNORECASE,
)
PROMO_RE = re.compile(
    r"(listen\s+to|watch\s+the\s+full|full\s+discussion|podcast|apple\s+podcasts?|spotify|youtube|"
    r"click\s+here|join\s+.*\s+channel|whatsapp\s+channel|support\s+us|write\s+to\s+us|"
    r"send\s+your\s+thoughts|quick\s+feedback\s+form)",
    re.IGNORECASE,
)


def _truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,.;:") + "..."


def _extract_fact_sentences(text: str) -> List[str]:
    cleaned = sanitize_text(text)
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    factual: List[str] = []
    for raw_sentence in parts:
        sentence = re.sub(r"^(?:\d+\s+){1,4}", "", raw_sentence).strip()
        if len(sentence.split()) < 5:
            continue
        if INSTRUCTIONAL_RE.search(sentence):
            continue
        if PROMO_RE.search(sentence) and len(sentence.split()) <= 30:
            continue
        if len(re.findall(r"\d", sentence)) > max(3, len(sentence) // 20):
            continue
        factual.append(sentence)
    return factual


def _is_instructional_or_meta(text: str) -> bool:
    lowered = sanitize_text(text).strip().lower()
    if not lowered:
        return True
    if INSTRUCTIONAL_RE.search(lowered):
        return True
    if re.search(r"\b(read\s+the\s+question|stress\s+the\s+words?|with\s+a\s+\w+\s+tone)\b", lowered):
        return True
    if any(
        token in lowered
        for token in (
            "camera",
            "pace",
            "tone",
            "segment",
            "control room",
            "anchor should",
            "narration should",
            "voice-over",
            "voice over",
            "replace with",
            "cover this segment",
            "click here",
            "join",
            "whatsapp channel",
            "support us",
        )
    ):
        return True
    return False


def _template_narration(
    segment_type: str,
    text: str,
    headline: str = "",
) -> str:
    """Generate narration from template."""
    facts = _extract_fact_sentences(text)
    lead = sanitize_text((facts[0] if facts else text).rstrip("."))
    secondary = sanitize_text((facts[1] if len(facts) > 1 else lead).rstrip("."))

    if not lead:
        lead = "Authorities confirmed new details as the story continues to develop"

    if segment_type == "intro":
        clean_headline = sanitize_text(headline).strip()
        if clean_headline and clean_headline.lower() not in lead.lower():
            line = INTRO_TEMPLATES[0].format(headline=clean_headline, lead=lead)
        else:
            line = f"Breaking update: {lead}"
        return _truncate_words(sanitize_text(line), 34)

    if segment_type == "outro":
        closing = OUTRO_TEMPLATES[1]
        if facts:
            closing = f"Latest verified line: {_truncate_words(facts[-1], 18)}. {OUTRO_TEMPLATES[1]}"
        return _truncate_words(sanitize_text(closing), 40)

    return _truncate_words(secondary, 34)


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

        prompt = f"""You are a senior TV newsroom script editor.
    Rewrite the provided narration for a {segment_type} segment.

    Hard rules:
    - Keep under 60 words
    - Maintain factual grounding to source context
    - Never write presenter instructions, directives, or production notes
    - Avoid promotional CTA language unless it is explicitly factual source content
    - Use broadcast rhythm and concise wording
    - Avoid robotic filler and legalistic phrasing
    - Return plain text only

    Original narration:
    {raw_narration}

    Source context:
    {context[:900]}
    """
        response = model.generate_content(prompt)
        refined = response.text.strip()
        if refined and len(refined) > 20 and not _is_instructional_or_meta(refined):
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
    model_name_override: Optional[str] = None,
) -> List[str]:
    """
    Generate narration for each segment.
    Returns list of narration strings aligned to segments.
    """
    log.info(f"Generating narrations for {len(segments)} segments (gemini={use_gemini})")

    use_gemini = use_gemini and config.USE_GEMINI and bool(config.GEMINI_API_KEY)
    model_name = model_name_override or config.GEMINI_MODEL

    narrations: List[str] = []

    for i, (seg, headline) in enumerate(zip(segments, headlines)):
        # 1. Template baseline
        raw = _template_narration(
            segment_type=seg["segment_type"],
            text=seg["text"],
            headline=headline,
        )
        raw = sanitize_text(raw)
        if _is_instructional_or_meta(raw):
            raw = _truncate_words(sanitize_text(seg["text"]), 30)

        # 2. Gemini refinement (use on any segment when enabled to improve tone)
        if use_gemini:
            refined = _gemini_refine(
                raw_narration=raw,
                context=seg["text"],
                segment_type=seg["segment_type"],
                model_name=model_name,
                api_key=config.GEMINI_API_KEY,
            )
            final_line = sanitize_text(refined)
            if _is_instructional_or_meta(final_line):
                final_line = raw
            narrations.append(_truncate_words(final_line, 42))
        else:
            narrations.append(_truncate_words(raw, 42))

        log.debug(f"Seg {i} ({seg['segment_type']}): {narrations[-1][:60]}…")

    return narrations
