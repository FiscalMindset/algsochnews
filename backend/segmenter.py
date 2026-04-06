"""
segmenter.py — Rule-based text segmentation with timestamp assignment.
No LLM involved.
"""

import re
from typing import List
from backend.utils import get_logger, chunk_text, estimate_duration, word_count, config

log = get_logger("segmenter")

PROMOTIONAL_SENTENCE_RE = re.compile(
    r"(listen\s+to|watch\s+the\s+full|full\s+discussion|podcast|episode\s+\d+|"
    r"apple\s+podcasts?|spotify|youtube|follow\s+us|subscribe|download\s+our\s+app|"
    r"click\s+here|join\s+.*\s+channel|whatsapp\s+channel|support\s+us|"
    r"write\s+to\s+us|send\s+your\s+thoughts|quick\s+feedback\s+form)",
    re.IGNORECASE,
)
BOILERPLATE_SENTENCE_RE = re.compile(
    r"^(this\s+article\s+is\s+about|for\s+the\s+.*\s+see|image\s+credit|photo\s+of)",
    re.IGNORECASE,
)
INSTRUCTIONAL_SENTENCE_RE = re.compile(
    r"^(?:please\s+)?(?:use\s+(?!of\b)|keep\b|shift\b|deliver\b|read\b|speak\b|"
    r"stress\b|emphasize\b|highlight\b|focus\b|mention\b|frame\b|convey\b|"
    r"ensure\b|avoid\b|make\s+sure\b|let\b)|"
    r"\b(read\s+the\s+question|stress\s+the\s+words?|with\s+a\s+\w+\s+tone|"
    r"voice[-\s]?over\b|anchor\s+should\b|control\s+room\b)\b",
    re.IGNORECASE,
)


def _split_into_sentences(text: str) -> List[str]:
    """Split text on sentence boundaries, preserving punctuation."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 15]


def _is_low_signal_sentence(sentence: str) -> bool:
    lowered = sentence.strip().lower()
    if not lowered:
        return True

    if INSTRUCTIONAL_SENTENCE_RE.search(lowered):
        return True

    if BOILERPLATE_SENTENCE_RE.search(lowered):
        return True

    if PROMOTIONAL_SENTENCE_RE.search(lowered) and len(lowered.split()) <= 48:
        return True

    return False


def _filter_sentences(sentences: List[str]) -> List[str]:
    filtered: List[str] = []
    seen = set()
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        if _is_low_signal_sentence(normalized):
            continue
        filtered.append(normalized)
        seen.add(key)
    return filtered


def _group_sentences(sentences: List[str], target_words: int = 50) -> List[str]:
    """
    Group sentences into paragraph-sized chunks targeting ~target_words each.
    Respects natural paragraph breaks.
    """
    groups, current, count = [], [], 0
    for sent in sentences:
        wc = word_count(sent)
        if count + wc > target_words * 1.5 and current:
            groups.append(" ".join(current))
            current, count = [sent], wc
        else:
            current.append(sent)
            count += wc
    if current:
        groups.append(" ".join(current))
    return groups


def segment_article(
    text: str,
    max_segments: int = 6,
    intro_text: str = "",
) -> List[dict]:
    """
    Segment article text into timed blocks.

    Returns list of dicts:
      {
        index, text, start_time, end_time, duration, word_count,
        segment_type: "intro" | "body" | "outro"
      }
    """
    log.info(f"Segmenting article ({word_count(text)} words, max={max_segments} segs)")

    sentences = _split_into_sentences(text)
    sentences = _filter_sentences(sentences)
    if not sentences:
        raise ValueError("Article too short or malformed — cannot segment.")

    total_segments = max(4, min(max_segments, 8))
    body_segments = max(2, total_segments - 2)

    # Target balanced body chunks while reserving space for intro + close.
    target_wc = max(28, word_count(text) // body_segments)
    raw_groups = _group_sentences(sentences, target_words=target_wc)

    if len(raw_groups) < body_segments:
        body_segments = len(raw_groups)
    if len(raw_groups) > body_segments:
        raw_groups = raw_groups[:body_segments]

    segments: List[dict] = []
    cursor = 0.0

    # ---- INTRO segment (shortened first sentence or supplied intro_text) ----
    intro = intro_text or (sentences[0] if sentences else "")
    intro_dur = estimate_duration(intro)
    segments.append(
        {
            "index": 0,
            "text": intro,
            "start_time": cursor,
            "end_time": cursor + intro_dur,
            "duration": intro_dur,
            "word_count": word_count(intro),
            "segment_type": "intro",
        }
    )
    cursor += intro_dur

    # ---- BODY segments ----
    for i, group in enumerate(raw_groups, start=1):
        dur = estimate_duration(group)
        # Pad slightly for visual breathing room
        padded_dur = dur + 0.8
        segments.append(
            {
                "index": i,
                "text": group,
                "start_time": round(cursor, 2),
                "end_time": round(cursor + padded_dur, 2),
                "duration": round(padded_dur, 2),
                "word_count": word_count(group),
                "segment_type": "body",
            }
        )
        cursor += padded_dur

    # ---- OUTRO segment ----
    outro = "Stay tuned for more updates on this developing story."
    outro_dur = estimate_duration(outro)
    segments.append(
        {
            "index": len(segments),
            "text": outro,
            "start_time": round(cursor, 2),
            "end_time": round(cursor + outro_dur, 2),
            "duration": round(outro_dur, 2),
            "word_count": word_count(outro),
            "segment_type": "outro",
        }
    )

    total_duration = segments[-1]["end_time"]
    log.info(
        f"Produced {len(segments)} segments, total duration {total_duration:.1f}s"
    )
    return segments
