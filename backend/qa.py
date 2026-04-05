"""
qa.py — Broadcast screenplay review, scoring, and targeted retry decisions.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from backend.models import QAReview, ReviewCriterion, SegmentQADiagnostic
from backend.utils import get_logger, word_count

log = get_logger("qa")


def _norm_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{3,}", text.lower())}


def _headline_score(segments: Sequence[dict]) -> tuple[int, str, List[str], str]:
    main_headlines = [seg.get("main_headline", "").strip() for seg in segments]
    subheadlines = [seg.get("subheadline", "").strip() for seg in segments]
    unique_ratio = len(set(main_headlines)) / max(len(main_headlines), 1)
    short_main = all(word_count(text) <= 6 for text in main_headlines if text)
    short_sub = all(word_count(text) <= 11 for text in subheadlines if text)
    evidence = [
        f"Unique headline ratio: {unique_ratio:.2f}",
        f"Longest main headline: {max((word_count(text) for text in main_headlines), default=0)} words",
        f"Longest subheadline: {max((word_count(text) for text in subheadlines), default=0)} words",
    ]
    if unique_ratio == 1 and short_main and short_sub:
        return 5, "Headlines and subheadlines are short, varied, and segment-specific.", evidence, "Keep this format and maintain segment-specific verbs."
    if unique_ratio >= 0.8 and short_main:
        return 4, "Headline system is mostly distinct and broadcast-friendly.", evidence, "Sharpen one or two generic lines to improve distinctiveness."
    if unique_ratio >= 0.6:
        return 3, "Headline system is usable but still repeats or runs long.", evidence, "Reduce repeated phrasing and tighten long subheadlines."
    if unique_ratio >= 0.4:
        return 2, "Too many segments share similar headline treatment.", evidence, "Rebuild headline stack with stronger beat differentiation."
    return 1, "Headline system is repetitive and weak.", evidence, "Regenerate headline package from segment-specific facts."


def _structure_score(segments: Sequence[dict]) -> tuple[int, str, List[str], str]:
    if not segments:
        return 1, "No segments were generated.", ["Segment count: 0"], "Generate at least intro, body, and outro segments."

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
    runtime = segments[-1].get("end_time", 0)
    evidence = [
        f"Segment types: {' > '.join(types)}",
        f"Runtime: {runtime:.1f} seconds",
        f"Monotonic timing: {'yes' if smooth_lengths else 'no'}",
    ]
    recommendation = "Ensure intro, at least two body beats, and a decisive outro handoff."
    return max(1, min(score, 5)), ", ".join(reasons) or "Structure feels incomplete.", evidence, recommendation


def _hook_score(segments: Sequence[dict]) -> tuple[int, str, List[str], str]:
    if not segments:
        return 1, "No opening beat available.", ["No intro segment found"], "Add an opening beat with urgency and context."

    intro = segments[0].get("anchor_narration", "")
    intro_lower = intro.lower()
    strong_open = any(
        phrase in intro_lower
        for phrase in ("breaking", "good evening", "we begin", "tonight", "developing")
    )
    concise = 8 <= word_count(intro) <= 32
    generic = "this article is about" in intro_lower or "according to the article" in intro_lower
    evidence = [
        f"Opening line words: {word_count(intro)}",
        f"Contains broadcast cue: {'yes' if strong_open else 'no'}",
        f"Contains generic phrasing: {'yes' if generic else 'no'}",
    ]
    recommendation = "Start with a concrete event plus consequence in the first sentence."

    if strong_open and concise and not generic:
        return 5, "Opening feels like a real broadcast hook.", evidence, recommendation
    if strong_open and not generic:
        return 4, "Opening is solid but could hit harder.", evidence, recommendation
    if concise and not generic:
        return 3, "Opening is serviceable but not especially strong.", evidence, recommendation
    if not generic:
        return 2, "Opening exists but feels flat.", evidence, recommendation
    return 1, "Opening sounds generic instead of broadcast-ready.", evidence, recommendation


def _narration_score(segments: Sequence[dict], article_text: str) -> tuple[int, str, List[str], str]:
    if not segments:
        return 1, "No narration available.", ["No narration provided"], "Generate grounded narration before packaging."

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
    evidence = [
        f"Average lexical grounding overlap: {avg_overlap:.2f}",
        f"Repeated opener count: {repeated_openers}",
        f"Robotic phrase hits: {robotic_hits}",
    ]
    recommendation = "Keep factual overlap high and vary sentence openers across segments."
    if avg_overlap >= 0.45 and repeated_openers == 0 and robotic_hits == 0:
        return 5, "Narration is grounded, concise, and varied.", evidence, recommendation
    if avg_overlap >= 0.35 and robotic_hits <= 1:
        return 4, "Narration quality is good with only minor repetition.", evidence, recommendation
    if avg_overlap >= 0.25:
        return 3, "Narration is acceptable but could sound sharper.", evidence, recommendation
    if avg_overlap >= 0.18:
        return 2, "Narration drifts from the source or sounds repetitive.", evidence, recommendation
    return 1, "Narration quality is weak and not well grounded.", evidence, recommendation


def _visual_score(segments: Sequence[dict]) -> tuple[int, str, List[str], str]:
    if not segments:
        return 1, "No visual plan available.", ["No visual segments found"], "Provide visual layout and source/AI support assets per segment."

    covered = 0
    source_or_ai = 0
    transitions = set()
    source_count = 0
    ai_count = 0
    html_frame_count = 0

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
        if seg.get("html_frame_url"):
            html_frame_count += 1

    coverage_ratio = covered / max(len(segments), 1)
    variety = len(transitions)
    evidence = [
        f"Coverage ratio: {coverage_ratio:.2f}",
        f"Source visuals: {source_count}, AI support visuals: {ai_count}",
        f"Transition variety: {variety}",
        f"HTML frame previews: {html_frame_count}/{len(segments)}",
    ]
    recommendation = "Keep every segment visually grounded and vary transitions while preserving continuity."
    if coverage_ratio == 1 and source_or_ai == len(segments) and source_count and ai_count and variety >= 3:
        return 5, "Visual plan covers every beat with good source/support balance.", evidence, recommendation
    if coverage_ratio >= 0.9 and source_or_ai >= len(segments) - 1:
        return 4, "Visual plan is strong with only minor coverage gaps.", evidence, recommendation
    if coverage_ratio >= 0.75:
        return 3, "Visual plan is workable but still thin.", evidence, recommendation
    if coverage_ratio >= 0.5:
        return 2, "Visual plan is inconsistent across segments.", evidence, recommendation
    return 1, "Visual plan is too weak for a broadcast package.", evidence, recommendation


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


def _build_segment_diagnostics(segments: Sequence[dict], article_text: str) -> tuple[List[SegmentQADiagnostic], List[int]]:
    article_tokens = _norm_words(article_text)
    diagnostics: List[SegmentQADiagnostic] = []
    weak_indices: List[int] = []

    for index, seg in enumerate(segments):
        score = 5
        strengths: List[str] = []
        issues: List[str] = []

        main_words = word_count(seg.get("main_headline", ""))
        sub_words = word_count(seg.get("subheadline", ""))
        narration_words = word_count(seg.get("anchor_narration", ""))
        overlap = len(_norm_words(seg.get("anchor_narration", "")) & article_tokens) / max(
            len(_norm_words(seg.get("anchor_narration", ""))), 1
        )

        if main_words <= 6:
            strengths.append("Main headline length is broadcast-safe.")
        else:
            issues.append("Main headline is too long for fast read-on-air.")
            score -= 1

        if sub_words <= 11:
            strengths.append("Subheadline length is concise.")
        else:
            issues.append("Subheadline should be tightened for legibility.")
            score -= 1

        if seg.get("layout") and (seg.get("source_image_url") or seg.get("ai_support_visual_prompt")):
            strengths.append("Visual slot and right-panel asset are available.")
        else:
            issues.append("Visual layout or right-panel asset is incomplete.")
            score -= 1

        if 8 <= narration_words <= 60:
            strengths.append("Narration pacing length is acceptable.")
        else:
            issues.append("Narration length is outside preferred range (8-60 words).")
            score -= 1

        if overlap >= 0.3:
            strengths.append("Narration shows factual lexical overlap with source text.")
        else:
            issues.append("Narration appears weakly grounded in source wording.")
            score -= 1

        score = max(1, min(score, 5))
        status = "strong" if score >= 4 else "warning"
        recommendation = (
            "Preserve this segment structure and only polish stylistic tone."
            if score >= 4
            else "Address top issue first: " + (issues[0] if issues else "tighten narrative and packaging")
        )

        diagnostics.append(
            SegmentQADiagnostic(
                segment_id=int(seg.get("segment_id", index + 1)),
                headline=seg.get("main_headline", ""),
                score=score,
                status=status,
                strengths=strengths,
                issues=issues,
                recommendation=recommendation,
            )
        )
        if score < 4:
            weak_indices.append(index)

    return diagnostics, weak_indices


def _build_score_explanation(criteria: Sequence[ReviewCriterion], average: float) -> str:
    ordered = sorted(criteria, key=lambda item: item.score)
    weakest = ordered[0]
    strongest = ordered[-1]
    return (
        f"Overall {average:.2f}/5. Strongest area: {strongest.label} ({strongest.score}/5). "
        f"Biggest drag: {weakest.label} ({weakest.score}/5)."
    )


def _build_next_actions(criteria: Sequence[ReviewCriterion], diagnostics: Sequence[SegmentQADiagnostic]) -> List[str]:
    actions: List[str] = []
    for criterion in criteria:
        if criterion.score < 5 and criterion.recommendation:
            actions.append(f"{criterion.label}: {criterion.recommendation}")

    weak_segments = [item for item in diagnostics if item.score < 4]
    for item in weak_segments[:3]:
        actions.append(f"Segment {item.segment_id} ({item.headline or 'untitled'}): {item.recommendation}")

    deduped: List[str] = []
    seen = set()
    for action in actions:
        if action in seen:
            continue
        seen.add(action)
        deduped.append(action)
    return deduped[:8]


def identify_weak_segments(segments: Sequence[dict]) -> List[int]:
    diagnostics, weak = _build_segment_diagnostics(segments, " ".join(seg.get("source_text", "") for seg in segments))
    if diagnostics:
        return weak
    return []


def review_broadcast_package(
    segments: Sequence[dict],
    article_text: str,
    retry_rounds: int = 0,
) -> Tuple[float, QAReview]:
    structure_score, structure_reason, structure_evidence, structure_reco = _structure_score(segments)
    hook_score, hook_reason, hook_evidence, hook_reco = _hook_score(segments)
    narration_score, narration_reason, narration_evidence, narration_reco = _narration_score(segments, article_text)
    visual_score, visual_reason, visual_evidence, visual_reco = _visual_score(segments)
    headline_score, headline_reason, headline_evidence, headline_reco = _headline_score(segments)

    criteria = [
        ReviewCriterion(
            key="structure_flow",
            label="Story Structure & Flow",
            score=structure_score,
            reason=structure_reason,
            evidence=structure_evidence,
            recommendation=structure_reco,
        ),
        ReviewCriterion(
            key="hook_engagement",
            label="Hook & Engagement",
            score=hook_score,
            reason=hook_reason,
            evidence=hook_evidence,
            recommendation=hook_reco,
        ),
        ReviewCriterion(
            key="narration_quality",
            label="Narration Quality",
            score=narration_score,
            reason=narration_reason,
            evidence=narration_evidence,
            recommendation=narration_reco,
        ),
        ReviewCriterion(
            key="visual_planning",
            label="Visual Planning & Placement",
            score=visual_score,
            reason=visual_reason,
            evidence=visual_evidence,
            recommendation=visual_reco,
        ),
        ReviewCriterion(
            key="headline_quality",
            label="Headline / Subheadline Quality",
            score=headline_score,
            reason=headline_reason,
            evidence=headline_evidence,
            recommendation=headline_reco,
        ),
    ]

    average = round(sum(item.score for item in criteria) / max(len(criteria), 1), 2)
    segment_diagnostics, weak_segments = _build_segment_diagnostics(segments, article_text)
    notes = _extra_notes(segments, article_text)
    score_breakdown = {item.key: round(item.score / item.max_score, 3) for item in criteria}
    score_explanation = _build_score_explanation(criteria, average)
    next_actions = _build_next_actions(criteria, segment_diagnostics)

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
        score_breakdown=score_breakdown,
        score_explanation=score_explanation,
        segment_diagnostics=segment_diagnostics,
        next_actions=next_actions,
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
