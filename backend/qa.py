"""
qa.py — Broadcast screenplay review, scoring, and targeted retry decisions.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from backend.models import QAReview, ReviewCriterion
from backend.utils import get_logger, word_count

log = get_logger("qa")


def _norm_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{3,}", text.lower())}


def _headline_score(segments: Sequence[dict]) -> tuple[int, str]:
    main_headlines = [seg.get("main_headline", "").strip() for seg in segments]
    subheadlines = [seg.get("subheadline", "").strip() for seg in segments]
    unique_ratio = len(set(main_headlines)) / max(len(main_headlines), 1)
    short_main = all(word_count(text) <= 6 for text in main_headlines if text)
    short_sub = all(word_count(text) <= 11 for text in subheadlines if text)
    if unique_ratio == 1 and short_main and short_sub:
        return 5, "Headlines and subheadlines are short, varied, and segment-specific."
    if unique_ratio >= 0.8 and short_main:
        return 4, "Headline system is mostly distinct and broadcast-friendly."
    if unique_ratio >= 0.6:
        return 3, "Headline system is usable but still repeats or runs long."
    if unique_ratio >= 0.4:
        return 2, "Too many segments share similar headline treatment."
    return 1, "Headline system is repetitive and weak."


def _structure_score(segments: Sequence[dict]) -> tuple[int, str]:
    if not segments:
        return 1, "No segments were generated."

    types = [seg.get("segment_type", "body") for seg in segments]
    has_intro = types[0] == "intro"
    has_outro = types[-1] == "outro"
    smooth_lengths = all(seg.get("end_time", 0) > seg.get("start_time", 0) for seg in segments)
    closes_well = any(
        phrase in segments[-1].get("anchor_narration", "").lower()
        for phrase in ("latest", "updates", "for now", "continue", "developments")
    )
    body_count = sum(1 for t in types if t == "body")

    score = 2
    if has_intro:
        score += 1
    if has_outro:
        score += 1
    if smooth_lengths and body_count >= 2 and closes_well:
        score += 1

    reasons = []
    if has_intro:
        reasons.append("clear opening")
    if body_count >= 2:
        reasons.append("middle flow")
    if has_outro and closes_well:
        reasons.append("proper close")
    return max(1, min(score, 5)), ", ".join(reasons) or "Structure feels incomplete."


def _hook_score(segments: Sequence[dict]) -> tuple[int, str]:
    if not segments:
        return 1, "No opening beat available."

    intro = segments[0].get("anchor_narration", "")
    intro_lower = intro.lower()
    strong_open = any(
        phrase in intro_lower
        for phrase in ("breaking", "good evening", "we begin", "tonight", "developing")
    )
    concise = 8 <= word_count(intro) <= 32
    generic = "this article is about" in intro_lower or "according to the article" in intro_lower

    if strong_open and concise and not generic:
        return 5, "Opening feels like a real broadcast hook."
    if strong_open and not generic:
        return 4, "Opening is solid but could hit harder."
    if concise and not generic:
        return 3, "Opening is serviceable but not especially strong."
    if not generic:
        return 2, "Opening exists but feels flat."
    return 1, "Opening sounds generic instead of broadcast-ready."


def _narration_score(segments: Sequence[dict], article_text: str) -> tuple[int, str]:
    if not segments:
        return 1, "No narration available."

    article_tokens = _norm_words(article_text)
    overlap_scores = []
    repeated_openers = 0
    openers = set()
    robotic_hits = 0

    for seg in segments:
        narration = seg.get("anchor_narration", "")
        words = narration.split()
        opener = " ".join(words[:3]).lower()
        if opener in openers:
            repeated_openers += 1
        openers.add(opener)

        if any(phrase in narration.lower() for phrase in ("as per the report", "according to sources")):
            robotic_hits += 1

        overlap = len(_norm_words(narration) & article_tokens) / max(len(_norm_words(narration)), 1)
        overlap_scores.append(overlap)

    avg_overlap = sum(overlap_scores) / max(len(overlap_scores), 1)
    if avg_overlap >= 0.45 and repeated_openers == 0 and robotic_hits == 0:
        return 5, "Narration is grounded, concise, and varied."
    if avg_overlap >= 0.35 and robotic_hits <= 1:
        return 4, "Narration quality is good with only minor repetition."
    if avg_overlap >= 0.25:
        return 3, "Narration is acceptable but could sound sharper."
    if avg_overlap >= 0.18:
        return 2, "Narration drifts from the source or sounds repetitive."
    return 1, "Narration quality is weak and not well grounded."


def _visual_score(segments: Sequence[dict]) -> tuple[int, str]:
    if not segments:
        return 1, "No visual plan available."

    covered = 0
    source_or_ai = 0
    transitions = set()
    source_count = 0
    ai_count = 0

    for seg in segments:
        if seg.get("layout") and seg.get("right_panel"):
            covered += 1
        if seg.get("source_image_url") or seg.get("ai_support_visual_prompt"):
            source_or_ai += 1
        if seg.get("source_image_url"):
            source_count += 1
        if seg.get("ai_support_visual_prompt"):
            ai_count += 1
        if seg.get("transition"):
            transitions.add(seg["transition"])

    coverage_ratio = covered / max(len(segments), 1)
    variety = len(transitions)
    if coverage_ratio == 1 and source_or_ai == len(segments) and source_count and ai_count and variety >= 3:
        return 5, "Visual plan covers every beat with good source/support balance."
    if coverage_ratio >= 0.9 and source_or_ai >= len(segments) - 1:
        return 4, "Visual plan is strong with only minor coverage gaps."
    if coverage_ratio >= 0.75:
        return 3, "Visual plan is workable but still thin."
    if coverage_ratio >= 0.5:
        return 2, "Visual plan is inconsistent across segments."
    return 1, "Visual plan is too weak for a broadcast package."


def _extra_notes(segments: Sequence[dict], article_text: str) -> List[str]:
    notes = []
    total_duration = segments[-1].get("end_time", 0) if segments else 0
    if not (60 <= total_duration <= 120):
        notes.append("Duration is outside the ideal 60-120 second target.")

    article_tokens = _norm_words(article_text)
    coverage = 0
    for seg in segments:
        overlap = len(_norm_words(seg.get("anchor_narration", "")) & article_tokens)
        if overlap >= 5:
            coverage += 1
    if coverage < max(2, len(segments) - 1):
        notes.append("Some narration beats are not strongly grounded in the article.")

    if len({seg.get("main_headline", "") for seg in segments}) < len(segments) - 1:
        notes.append("Headline repetition is still visible in the package.")
    return notes


def identify_weak_segments(segments: Sequence[dict]) -> List[int]:
    weak = []
    for index, seg in enumerate(segments):
        main_words = word_count(seg.get("main_headline", ""))
        sub_words = word_count(seg.get("subheadline", ""))
        if main_words > 6 or sub_words > 11 or not seg.get("layout"):
            weak.append(index)
            continue
        if not (seg.get("source_image_url") or seg.get("ai_support_visual_prompt")):
            weak.append(index)
    return weak


def review_broadcast_package(
    segments: Sequence[dict],
    article_text: str,
    retry_rounds: int = 0,
) -> Tuple[float, QAReview]:
    structure_score, structure_reason = _structure_score(segments)
    hook_score, hook_reason = _hook_score(segments)
    narration_score, narration_reason = _narration_score(segments, article_text)
    visual_score, visual_reason = _visual_score(segments)
    headline_score, headline_reason = _headline_score(segments)

    criteria = [
        ReviewCriterion(
            key="structure_flow",
            label="Story Structure & Flow",
            score=structure_score,
            reason=structure_reason,
        ),
        ReviewCriterion(
            key="hook_engagement",
            label="Hook & Engagement",
            score=hook_score,
            reason=hook_reason,
        ),
        ReviewCriterion(
            key="narration_quality",
            label="Narration Quality",
            score=narration_score,
            reason=narration_reason,
        ),
        ReviewCriterion(
            key="visual_planning",
            label="Visual Planning & Placement",
            score=visual_score,
            reason=visual_reason,
        ),
        ReviewCriterion(
            key="headline_quality",
            label="Headline / Subheadline Quality",
            score=headline_score,
            reason=headline_reason,
        ),
    ]

    average = round(sum(item.score for item in criteria) / max(len(criteria), 1), 2)
    weak_segments = identify_weak_segments(segments)
    notes = _extra_notes(segments, article_text)

    main_failures = [item.key for item in criteria if item.score < 3]
    quality_pressure = [item.key for item in criteria if item.score < 4]

    retry_decision = "finalize"
    if any(key in quality_pressure for key in ("hook_engagement", "narration_quality", "structure_flow")):
        retry_decision = "retry_editor"
    if any(key in quality_pressure for key in ("visual_planning", "headline_quality")):
        retry_decision = "retry_packaging" if retry_decision == "finalize" else "retry_editor_and_packaging"
    if average >= 4 and not main_failures and not notes:
        retry_decision = "finalize"

    passed = average >= 4 and not main_failures

    review = QAReview(
        passed=passed,
        overall_average=average,
        retry_rounds=retry_rounds,
        retry_decision=retry_decision,
        weak_segments=weak_segments,
        notes=notes,
        criteria=criteria,
    )

    log.info(
        f"QA average: {average:.2f}/5 "
        f"{'PASS' if passed else 'FAIL'} "
        f"(decision={retry_decision})"
    )
    return round(average / 5.0, 4), review


def compute_qa_score(
    segments: Sequence[dict],
    article_text: str,
    retry_rounds: int = 0,
) -> Tuple[float, dict]:
    score, review = review_broadcast_package(segments, article_text, retry_rounds=retry_rounds)
    return score, review.model_dump()
