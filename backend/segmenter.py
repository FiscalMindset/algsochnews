"""
segmenter.py — Rule-based text segmentation with timestamp assignment.
No LLM involved.
"""

import re
from typing import List
from backend.utils import get_logger, chunk_text, estimate_duration, word_count, config

log = get_logger("segmenter")


def _split_into_sentences(text: str) -> List[str]:
    """Split text on sentence boundaries, preserving punctuation."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 15]


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
    max_segments: int = 8,
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
    if not sentences:
        raise ValueError("Article too short or malformed — cannot segment.")

    # Target ~55 words per segment, then trim to max_segments
    target_wc = max(30, word_count(text) // max_segments)
    raw_groups = _group_sentences(sentences, target_words=target_wc)

    # Limit total count (keep first N-1 groups + synthesise outro)
    if len(raw_groups) > max_segments - 1:
        raw_groups = raw_groups[: max_segments - 1]

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
