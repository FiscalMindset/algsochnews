"""
qa.py — Quality scoring and selective retry orchestration.
"""

import re
from typing import List, Optional, Tuple
from backend.utils import get_logger, word_count, config

log = get_logger("qa")


# ------------------------------------------------------------------ #
# Scoring
# ------------------------------------------------------------------ #

def _score_narration(narration: str, segment_text: str) -> float:
    """
    Score narration quality 0–1.
    Checks: length appropriateness, relevance overlap, no template leaking.
    """
    if not narration or len(narration) < 10:
        return 0.0

    n_words = word_count(narration)
    s_words = word_count(segment_text)

    # Length ratio (narration should be 0.5–2x segment)
    ratio = n_words / max(s_words, 1)
    length_score = 1.0 if 0.3 <= ratio <= 2.5 else max(0.0, 1.0 - abs(ratio - 1.0))

    # Vocabulary overlap
    n_tokens = set(narration.lower().split())
    s_tokens = set(segment_text.lower().split())
    overlap = len(n_tokens & s_tokens) / max(len(s_tokens), 1)
    relevance_score = min(overlap * 3, 1.0)

    # Template leak penalty (check for unfilled placeholders)
    template_penalty = 0.1 if re.search(r"\{[a-z_]+\}", narration) else 0.0

    score = 0.4 * length_score + 0.5 * relevance_score - template_penalty
    return round(max(0.0, min(1.0, score)), 4)


def _score_structure(segments: List[dict]) -> float:
    """
    Score overall article structure.
    Checks: presence of intro + outro, adequate body count, segment balance.
    """
    types = [s.get("segment_type", "body") for s in segments]
    has_intro = types[0] == "intro" if types else False
    has_outro = types[-1] == "outro" if types else False
    body_count = sum(1 for t in types if t == "body")

    structure_base = 0.5
    if has_intro:
        structure_base += 0.2
    if has_outro:
        structure_base += 0.15
    if body_count >= 2:
        structure_base += 0.15 * min(body_count / 4, 1.0)

    # Duration balance check
    durations = [s.get("duration", 5.0) for s in segments]
    avg_dur = sum(durations) / max(len(durations), 1)
    variance_penalty = sum(abs(d - avg_dur) for d in durations) / (avg_dur * len(durations) + 1e-9)
    balance_score = max(0.0, 1.0 - variance_penalty * 0.3)

    return round(min((structure_base + balance_score * 0.1), 1.0), 4)


def _score_visual_alignment(segments: List[dict], visuals: List[dict]) -> float:
    """Check that every segment has an image assigned."""
    if not visuals:
        return 0.0
    covered = sum(1 for v in visuals if v.get("image_path"))
    return round(covered / max(len(segments), 1), 4)


def compute_qa_score(
    segments: List[dict],
    narrations: List[str],
    visuals: List[dict],
) -> Tuple[float, dict]:
    """
    Compute composite QA score.
    Returns (overall_score, detail_dict)
    """
    narration_scores = []
    for seg, narr in zip(segments, narrations):
        s = _score_narration(narr, seg.get("text", ""))
        narration_scores.append(s)

    avg_narration = sum(narration_scores) / max(len(narration_scores), 1)
    structure = _score_structure(segments)
    visual_align = _score_visual_alignment(segments, visuals)

    overall = (
        0.45 * avg_narration
        + 0.30 * structure
        + 0.25 * visual_align
    )
    overall = round(max(0.0, min(1.0, overall)), 4)

    detail = {
        "overall": overall,
        "narration": round(avg_narration, 4),
        "structure": structure,
        "visual_alignment": visual_align,
        "per_segment_narration": narration_scores,
        "passed": overall >= config.QA_THRESHOLD,
    }
    log.info(
        f"QA score: {overall:.3f} (narr={avg_narration:.3f}, "
        f"struct={structure:.3f}, visual={visual_align:.3f}) "
        f"{'✓ PASS' if detail['passed'] else '✗ FAIL'}"
    )
    return overall, detail


def identify_weak_segments(
    narrations: List[str],
    segments: List[dict],
    threshold: float = 0.4,
) -> List[int]:
    """Return indices of segments with narration score below threshold."""
    weak = []
    for i, (narr, seg) in enumerate(zip(narrations, segments)):
        score = _score_narration(narr, seg.get("text", ""))
        if score < threshold:
            weak.append(i)
            log.debug(f"Weak narration at segment {i} (score={score:.3f})")
    return weak
