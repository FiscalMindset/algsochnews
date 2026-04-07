"""
qa.py — Broadcast screenplay review, scoring, and targeted retry decisions.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from backend.models import QAReview, ReviewCriterion, SegmentQADiagnostic
from backend.utils import get_logger, word_count

log = get_logger("qa")

_INSTRUCTIONAL_NARRATION_RE = re.compile(
    r"^(state|shift|emphasize|convey|stress|frame|open|focus|mention|use|keep)\b",
    re.IGNORECASE,
)


def _looks_instructional_narration(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if _INSTRUCTIONAL_NARRATION_RE.search(lowered):
        return True
    return any(
        phrase in lowered
        for phrase in (
            "set the stage",
            "shift tone",
            "stress the phrase",
            "emphasize the words",
        )
    )


def _norm_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{3,}", text.lower())}


_COMMON_TOKENS = {
    "this",
    "that",
    "with",
    "from",
    "into",
    "after",
    "before",
    "about",
    "under",
    "over",
    "more",
    "less",
    "still",
    "just",
    "very",
    "have",
    "has",
    "had",
    "were",
    "been",
    "their",
    "there",
    "where",
    "which",
    "while",
    "would",
    "could",
    "should",
    "today",
    "tonight",
    "latest",
    "update",
    "story",
}

_STORY_BEAT_ORDER = ["hook", "context", "key_development", "impact_response", "closing"]

_STORY_BEAT_ALIASES = {
    "hook": ("hook", "breaking", "opening", "intro"),
    "context": ("context", "background"),
    "key_development": ("key development", "development", "new development", "escalation"),
    "impact_response": ("impact", "response", "reaction", "fallout", "consequence"),
    "closing": ("closing", "close", "outro", "what next", "next steps"),
}


def _story_beat_tags(segment: dict) -> set[str]:
    raw = str(segment.get("story_beat") or segment.get("segment_type") or "").strip().lower()
    tags: set[str] = set()
    for tag, aliases in _STORY_BEAT_ALIASES.items():
        if any(alias in raw for alias in aliases):
            tags.add(tag)

    if not tags:
        segment_type = str(segment.get("segment_type") or "body").lower()
        if segment_type == "intro":
            tags.add("hook")
        elif segment_type == "outro":
            tags.add("closing")
        else:
            tags.add("key_development")

    return tags


def _story_beat_flow_metrics(segments: Sequence[dict]) -> Dict[str, object]:
    first_positions: Dict[str, int] = {}
    beat_sequence: List[str] = []

    for index, segment in enumerate(segments):
        tags = _story_beat_tags(segment)
        ordered_tags = [tag for tag in _STORY_BEAT_ORDER if tag in tags]
        beat_sequence.append(" + ".join(ordered_tags) if ordered_tags else "key_development")
        for tag in ordered_tags:
            if tag not in first_positions:
                first_positions[tag] = index

    covered = [tag for tag in _STORY_BEAT_ORDER if tag in first_positions]
    coverage_ratio = len(covered) / float(len(_STORY_BEAT_ORDER))
    ordered_positions = [first_positions[tag] for tag in covered]
    ordered = ordered_positions == sorted(ordered_positions)

    return {
        "coverage_ratio": round(coverage_ratio, 3),
        "ordered": ordered,
        "covered": covered,
        "missing": [tag for tag in _STORY_BEAT_ORDER if tag not in first_positions],
        "sequence": " > ".join(beat_sequence),
    }


def _unsupported_token_ratio(text: str, article_tokens: set[str]) -> float:
    tokens = [token.lower() for token in re.findall(r"[a-zA-Z]{4,}", text)]
    if not tokens:
        return 1.0
    content_tokens = [token for token in tokens if token not in _COMMON_TOKENS]
    if not content_tokens:
        return 0.0
    unsupported = [token for token in content_tokens if token not in article_tokens]
    return len(unsupported) / max(len(content_tokens), 1)


def _major_fact_coverage_ratio(segments: Sequence[dict], article_text: str) -> float:
    article_tokens = _norm_words(article_text)
    if not segments:
        return 0.0

    covered = 0
    for segment in segments:
        facts = segment.get("factual_points") or []
        source_excerpt = str(segment.get("source_excerpt") or "")
        fact_tokens = _norm_words(" ".join(map(str, facts)) + " " + source_excerpt)
        if not fact_tokens:
            fact_tokens = _norm_words(str(segment.get("source_text") or ""))

        narration_tokens = _norm_words(str(segment.get("anchor_narration") or ""))
        if not narration_tokens:
            continue

        fact_overlap = len(narration_tokens & fact_tokens) / max(len(narration_tokens), 1)
        article_overlap = len(narration_tokens & article_tokens) / max(len(narration_tokens), 1)
        if fact_overlap >= 0.22 and article_overlap >= 0.22:
            covered += 1

    return round(covered / max(len(segments), 1), 3)


def _hallucination_metrics(segments: Sequence[dict], article_text: str) -> Dict[str, float | int]:
    article_tokens = _norm_words(article_text)
    if not segments:
        return {"avg_unsupported_ratio": 1.0, "high_risk_segments": 0}

    ratios: List[float] = []
    high_risk = 0
    for segment in segments:
        ratio = _unsupported_token_ratio(str(segment.get("anchor_narration") or ""), article_tokens)
        ratios.append(ratio)
        if ratio > 0.62:
            high_risk += 1

    average = sum(ratios) / max(len(ratios), 1)
    return {
        "avg_unsupported_ratio": round(average, 3),
        "high_risk_segments": int(high_risk),
    }


def _repetition_metrics(segments: Sequence[dict]) -> Dict[str, float | int | bool]:
    main_headlines = [str(seg.get("main_headline") or "").strip().lower() for seg in segments if seg.get("main_headline")]
    subheadlines = [str(seg.get("subheadline") or "").strip().lower() for seg in segments if seg.get("subheadline")]
    narrations = [str(seg.get("anchor_narration") or "").strip().lower() for seg in segments if seg.get("anchor_narration")]

    opener_phrases = [" ".join(item.split()[:4]) for item in narrations if item]

    repeated_headlines = max(0, len(main_headlines) - len(set(main_headlines)))
    repeated_subheadlines = max(0, len(subheadlines) - len(set(subheadlines)))
    repeated_narration_lines = max(0, len(narrations) - len(set(narrations)))
    repeated_openers = max(0, len(opener_phrases) - len(set(opener_phrases)))

    headline_unique_ratio = len(set(main_headlines)) / max(len(main_headlines), 1)
    subheadline_unique_ratio = len(set(subheadlines)) / max(len(subheadlines), 1)

    no_repetition_ok = (
        repeated_headlines == 0
        and repeated_subheadlines <= 1
        and repeated_narration_lines == 0
        and repeated_openers <= 1
    )

    return {
        "headline_unique_ratio": round(headline_unique_ratio, 3),
        "subheadline_unique_ratio": round(subheadline_unique_ratio, 3),
        "repeated_headlines": repeated_headlines,
        "repeated_subheadlines": repeated_subheadlines,
        "repeated_narration_lines": repeated_narration_lines,
        "repeated_openers": repeated_openers,
        "no_repetition_ok": no_repetition_ok,
    }


def _narration_visual_alignment_ratio(segments: Sequence[dict]) -> float:
    if not segments:
        return 0.0

    aligned = 0
    for segment in segments:
        narration_tokens = _norm_words(str(segment.get("anchor_narration") or ""))
        visual_text = " ".join(
            [
                str(segment.get("main_headline") or ""),
                str(segment.get("subheadline") or ""),
                str(segment.get("source_excerpt") or ""),
                str(segment.get("right_panel") or ""),
                str(segment.get("visual_rationale") or ""),
            ]
        )
        visual_tokens = _norm_words(visual_text)
        has_visual = bool(segment.get("layout") and (segment.get("source_image_url") or segment.get("ai_support_visual_prompt") or segment.get("scene_image_url")))
        if not has_visual:
            continue

        overlap = len(narration_tokens & visual_tokens) / max(len(narration_tokens), 1)
        if overlap >= 0.16:
            aligned += 1

    return round(aligned / max(len(segments), 1), 3)


def _headline_score(segments: Sequence[dict]) -> tuple[int, str, List[str], str]:
    main_headlines = [str(seg.get("main_headline") or "").strip() for seg in segments]
    subheadlines = [str(seg.get("subheadline") or "").strip() for seg in segments]
    repetition = _repetition_metrics(segments)
    beat_metrics = _story_beat_flow_metrics(segments)

    unique_ratio = float(repetition["headline_unique_ratio"])
    sub_unique_ratio = float(repetition["subheadline_unique_ratio"])
    short_main = all(word_count(text) <= 6 for text in main_headlines if text)
    short_sub = all(word_count(text) <= 11 for text in subheadlines if text)

    aligned = 0
    for segment in segments:
        headline_tokens = _norm_words(f"{segment.get('main_headline', '')} {segment.get('subheadline', '')}")
        source_tokens = _norm_words(str(segment.get("source_text") or ""))
        overlap = len(headline_tokens & source_tokens) / max(len(headline_tokens), 1)
        if overlap >= 0.2:
            aligned += 1
    alignment_ratio = aligned / max(len(segments), 1)

    evidence = [
        f"Unique headline ratio: {unique_ratio:.2f}",
        f"Unique subheadline ratio: {sub_unique_ratio:.2f}",
        f"Headline-source alignment ratio: {alignment_ratio:.2f}",
        f"Story-beat coverage ratio: {float(beat_metrics['coverage_ratio']):.2f}",
        f"Longest main headline: {max((word_count(text) for text in main_headlines), default=0)} words",
        f"Longest subheadline: {max((word_count(text) for text in subheadlines), default=0)} words",
    ]

    if unique_ratio == 1 and sub_unique_ratio >= 0.9 and short_main and short_sub and alignment_ratio >= 0.75:
        return 5, "Headlines are unique, beat-aligned, and broadcast-ready.", evidence, "Maintain this sharp, segment-specific headline progression."
    if unique_ratio >= 0.85 and sub_unique_ratio >= 0.8 and short_main and alignment_ratio >= 0.65:
        return 4, "Headline stack is strong with minor opportunities to sharpen progression.", evidence, "Tighten one or two weaker subheadlines for clearer beat progression."
    if unique_ratio >= 0.7 and sub_unique_ratio >= 0.65:
        return 3, "Headline stack is workable but still has repetition or weak beat linkage.", evidence, "Rebuild weak headlines around each segment's specific story beat."
    if unique_ratio >= 0.5:
        return 2, "Headline quality is inconsistent and repeats across beats.", evidence, "Regenerate headline/subheadline pairs with strict uniqueness and beat mapping."
    return 1, "Headline system is repetitive and not broadcast-grade.", evidence, "Regenerate all segment headlines from beat-specific factual points."


def _structure_score(segments: Sequence[dict]) -> tuple[int, str, List[str], str]:
    if not segments:
        return 1, "No segments were generated.", ["Segment count: 0"], "Generate at least intro, body, and outro segments."

    types = [seg.get("segment_type", "body") for seg in segments]
    beat_metrics = _story_beat_flow_metrics(segments)
    has_intro = types[0] == "intro"
    has_outro = types[-1] == "outro"
    smooth_lengths = all(seg.get("end_time", 0) > seg.get("start_time", 0) for seg in segments)
    closes_well = any(
        phrase in segments[-1].get("anchor_narration", "").lower()
        for phrase in ("latest", "updates", "for now", "continue", "developments")
    )
    body_count = sum(1 for t in types if t == "body")

    score = 1
    if has_intro:
        score += 1
    if has_outro:
        score += 1
    if smooth_lengths and body_count >= 2:
        score += 1
    if float(beat_metrics["coverage_ratio"]) >= 0.8 and bool(beat_metrics["ordered"]):
        score += 1
    if closes_well:
        score += 1

    reasons = []
    if has_intro:
        reasons.append("clear opening")
    if body_count >= 2:
        reasons.append("middle flow")
    if float(beat_metrics["coverage_ratio"]) >= 0.8:
        reasons.append("story-beat coverage")
    if bool(beat_metrics["ordered"]):
        reasons.append("beat order respected")
    if has_outro and closes_well:
        reasons.append("proper close")
    runtime = segments[-1].get("end_time", 0)
    evidence = [
        f"Segment types: {' > '.join(types)}",
        f"Story beats: {beat_metrics['sequence']}",
        f"Beat coverage ratio: {float(beat_metrics['coverage_ratio']):.2f}",
        f"Beat ordering valid: {'yes' if bool(beat_metrics['ordered']) else 'no'}",
        f"Runtime: {runtime:.1f} seconds",
        f"Monotonic timing: {'yes' if smooth_lengths else 'no'}",
    ]
    recommendation = "Enforce Hook -> Context -> Key Development -> Impact/Response -> Closing progression with clear handoff language."
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
    instructional_hits = 0
    quote_heavy_hits = 0
    direct_lift_hits = 0
    unsupported_ratios: List[float] = []

    for seg in segments:
        narration = str(seg.get("anchor_narration") or "")
        words = narration.split()
        opener = " ".join(words[:3]).lower()
        if opener in openers:
            repeated_openers += 1
        openers.add(opener)

        if any(phrase in narration.lower() for phrase in ("as per the report", "according to sources")):
            robotic_hits += 1

        if _looks_instructional_narration(narration):
            instructional_hits += 1

        narration_tokens = _norm_words(narration)
        overlap = len(narration_tokens & article_tokens) / max(len(narration_tokens), 1)
        overlap_scores.append(overlap)

        quote_marks = narration.count('"') + narration.count("“") + narration.count("”")
        if quote_marks >= 2:
            quote_heavy_hits += 1

        source_tokens = _norm_words(str(seg.get("source_text") or ""))
        source_overlap = len(narration_tokens & source_tokens) / max(len(narration_tokens), 1)
        if len(words) >= 12 and source_overlap >= 0.78:
            direct_lift_hits += 1

        unsupported_ratios.append(_unsupported_token_ratio(narration, article_tokens))

    avg_overlap = sum(overlap_scores) / max(len(overlap_scores), 1)
    avg_unsupported = sum(unsupported_ratios) / max(len(unsupported_ratios), 1)
    evidence = [
        f"Average lexical grounding overlap: {avg_overlap:.2f}",
        f"Average unsupported-token ratio: {avg_unsupported:.2f}",
        f"Repeated opener count: {repeated_openers}",
        f"Robotic phrase hits: {robotic_hits}",
        f"Instruction-style narration hits: {instructional_hits}",
        f"Quote-heavy lines: {quote_heavy_hits}",
        f"Direct article-lift risk lines: {direct_lift_hits}",
    ]
    recommendation = "Keep anchor wording concise, paraphrased, and source-grounded while avoiding repeated openers and heavy quoting."

    if instructional_hits >= max(1, len(segments) // 3):
        return 1, "Narration includes editorial instructions instead of on-air lines.", evidence, "Replace directive notes with factual broadcast narration."
    if direct_lift_hits >= max(1, len(segments) // 3):
        return 1, "Narration is lifting article phrasing too directly.", evidence, "Rewrite lines into paraphrased anchor language instead of source-text copying."
    if avg_unsupported > 0.58:
        return 1, "Narration introduces too many unsupported tokens.", evidence, "Ground each segment in source facts before polishing tone."
    if instructional_hits > 0:
        return 2, "Narration includes some directive-style lines.", evidence, "Rewrite directive lines into declarative, factual narration."
    if avg_overlap >= 0.45 and avg_unsupported <= 0.42 and repeated_openers == 0 and robotic_hits == 0 and quote_heavy_hits == 0 and direct_lift_hits == 0:
        return 5, "Narration is grounded, concise, and varied.", evidence, recommendation
    if avg_overlap >= 0.35 and avg_unsupported <= 0.5 and robotic_hits <= 1 and direct_lift_hits == 0:
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
    aligned_visuals = 0

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

        narration_tokens = _norm_words(str(seg.get("anchor_narration") or ""))
        visual_tokens = _norm_words(
            " ".join(
                [
                    str(seg.get("main_headline") or ""),
                    str(seg.get("subheadline") or ""),
                    str(seg.get("right_panel") or ""),
                    str(seg.get("visual_rationale") or ""),
                ]
            )
        )
        overlap = len(narration_tokens & visual_tokens) / max(len(narration_tokens), 1)
        if overlap >= 0.16:
            aligned_visuals += 1

    coverage_ratio = covered / max(len(segments), 1)
    variety = len(transitions)
    source_priority_ratio = source_count / max(source_or_ai, 1)
    alignment_ratio = aligned_visuals / max(len(segments), 1)
    evidence = [
        f"Coverage ratio: {coverage_ratio:.2f}",
        f"Source visuals: {source_count}, AI support visuals: {ai_count}",
        f"Source-priority ratio: {source_priority_ratio:.2f}",
        f"Narration-visual alignment ratio: {alignment_ratio:.2f}",
        f"Transition variety: {variety}",
        f"HTML frame previews: {html_frame_count}/{len(segments)}",
    ]
    recommendation = "Prefer source imagery whenever available, and keep every visual beat tightly aligned with the narration copy."

    if coverage_ratio == 1 and source_or_ai == len(segments) and source_priority_ratio >= 0.85 and alignment_ratio >= 0.75 and variety >= 3:
        return 5, "Visual plan is complete, source-prioritized, and well-aligned to narration.", evidence, recommendation
    if coverage_ratio >= 0.9 and source_or_ai >= len(segments) - 1 and source_priority_ratio >= 0.65 and alignment_ratio >= 0.65:
        return 4, "Visual plan is strong with minor source-priority or alignment gaps.", evidence, recommendation
    if coverage_ratio >= 0.75:
        return 3, "Visual plan is workable but needs stronger source usage or alignment.", evidence, recommendation
    if coverage_ratio >= 0.5:
        return 2, "Visual plan is inconsistent across segments.", evidence, recommendation
    return 1, "Visual plan is too weak for a broadcast package.", evidence, recommendation


def _factual_grounding_average(segments: Sequence[dict], article_text: str) -> float:
    article_tokens = _norm_words(article_text)
    if not article_tokens:
        return 0.0
    overlaps: List[float] = []
    for seg in segments:
        narration_tokens = _norm_words(seg.get("anchor_narration", ""))
        if not narration_tokens:
            overlaps.append(0.0)
            continue
        overlaps.append(len(narration_tokens & article_tokens) / max(len(narration_tokens), 1))
    if not overlaps:
        return 0.0
    return round(sum(overlaps) / len(overlaps), 3)


def _visual_coverage_ratio(segments: Sequence[dict]) -> float:
    if not segments:
        return 0.0
    covered = 0
    for seg in segments:
        has_layout = bool(seg.get("layout"))
        has_visual = bool(seg.get("source_image_url") or seg.get("ai_support_visual_prompt") or seg.get("scene_image_url"))
        if has_layout and has_visual:
            covered += 1
    return round(covered / max(len(segments), 1), 3)


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
        narration_text = seg.get("anchor_narration", "")
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

        if _looks_instructional_narration(narration_text):
            issues.append("Narration reads like editorial instruction instead of broadcast copy.")
            score -= 2

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
            label="Visual Planning",
            score=visual_score,
            reason=visual_reason,
            evidence=visual_evidence,
            recommendation=visual_reco,
        ),
        ReviewCriterion(
            key="headline_quality",
            label="Headline/Subheadline Quality",
            score=headline_score,
            reason=headline_reason,
            evidence=headline_evidence,
            recommendation=headline_reco,
        ),
    ]

    average = round(sum(item.score for item in criteria) / max(len(criteria), 1), 2)
    segment_diagnostics, weak_segments = _build_segment_diagnostics(segments, article_text)
    notes = _extra_notes(segments, article_text)

    runtime_sec = float(segments[-1].get("end_time", 0.0)) if segments else 0.0
    duration_ok = 60 <= runtime_sec <= 120
    grounding_avg = _factual_grounding_average(segments, article_text)
    grounding_ok = grounding_avg >= 0.3
    visual_coverage = _visual_coverage_ratio(segments)
    visual_coverage_ok = visual_coverage >= 0.9

    major_fact_coverage = _major_fact_coverage_ratio(segments, article_text)
    major_fact_coverage_ok = major_fact_coverage >= 0.8

    hallucination_metrics = _hallucination_metrics(segments, article_text)
    no_hallucination_ok = (
        float(hallucination_metrics["avg_unsupported_ratio"]) <= 0.55
        and int(hallucination_metrics["high_risk_segments"]) == 0
    )

    repetition_metrics = _repetition_metrics(segments)
    no_repetition_ok = bool(repetition_metrics["no_repetition_ok"])

    narration_visual_alignment = _narration_visual_alignment_ratio(segments)
    narration_visual_alignment_ok = narration_visual_alignment >= 0.7

    beat_flow_metrics = _story_beat_flow_metrics(segments)
    story_beat_flow_ok = float(beat_flow_metrics["coverage_ratio"]) >= 1.0 and bool(beat_flow_metrics["ordered"])

    hard_failures: List[str] = []
    if not duration_ok:
        hard_failures.append("duration_fit")
        notes.append("Duration gate failed: runtime must stay within 60-120 seconds.")
    if not grounding_ok:
        hard_failures.append("factual_grounding")
        notes.append("Grounding gate failed: narration overlap with source facts is too low.")
    if not visual_coverage_ok:
        hard_failures.append("visual_coverage")
        notes.append("Visual gate failed: every segment should carry a clear layout + visual asset.")
    if not major_fact_coverage_ok:
        hard_failures.append("major_fact_coverage")
        notes.append("Major-fact gate failed: key source facts are not covered consistently across segments.")
    if not no_hallucination_ok:
        hard_failures.append("hallucination_guard")
        notes.append("Hallucination gate failed: unsupported narration tokens are above the safety limit.")
    if not no_repetition_ok:
        hard_failures.append("repetition_guard")
        notes.append("Repetition gate failed: headline or narration duplication exceeded limits.")
    if not narration_visual_alignment_ok:
        hard_failures.append("narration_visual_alignment")
        notes.append("Alignment gate failed: narration and visual plan are not consistently aligned.")
    if not story_beat_flow_ok:
        hard_failures.append("story_beat_flow")
        notes.append("Story-beat gate failed: Hook -> Context -> Key Development -> Impact/Response -> Closing flow is incomplete.")

    # Deduplicate notes while preserving order.
    seen_notes = set()
    notes = [note for note in notes if not (note in seen_notes or seen_notes.add(note))]

    score_breakdown = {item.key: round(item.score / item.max_score, 3) for item in criteria}
    score_explanation = _build_score_explanation(criteria, average)
    next_actions = _build_next_actions(criteria, segment_diagnostics)

    editor_reasons: List[str] = []
    packaging_reasons: List[str] = []

    if narration_score < 4:
        editor_reasons.append(f"Narration Quality scored {narration_score}/5: {narration_reason}")
    if hook_score < 4:
        editor_reasons.append(f"Hook & Engagement scored {hook_score}/5: {hook_reason}")
    if structure_score < 4:
        editor_reasons.append(f"Story Structure & Flow scored {structure_score}/5: {structure_reason}")

    if not duration_ok:
        editor_reasons.append("Duration is outside the required 60-120 second window.")
    if not grounding_ok:
        editor_reasons.append("Narration grounding overlap is below the required threshold.")
    if not major_fact_coverage_ok:
        editor_reasons.append("Major facts are not adequately represented across narration beats.")
    if not no_hallucination_ok:
        editor_reasons.append("Unsupported narration tokens indicate possible hallucination risk.")
    if not no_repetition_ok:
        editor_reasons.append("Narration/headline repetition exceeded allowed tolerance.")
    if not story_beat_flow_ok:
        editor_reasons.append("Required story-beat progression is incomplete or out of order.")

    if visual_score < 4:
        packaging_reasons.append(f"Visual Planning scored {visual_score}/5: {visual_reason}")
    if headline_score < 4:
        packaging_reasons.append(f"Headline/Subheadline Quality scored {headline_score}/5: {headline_reason}")
    if not visual_coverage_ok:
        packaging_reasons.append("Visual coverage is below the minimum threshold for production.")
    if not narration_visual_alignment_ok:
        packaging_reasons.append("Narration and visuals are not aligned tightly enough per segment.")

    retry_decision = "finalize"
    decision_reason = "All rubric criteria and hard validation gates passed."

    # Targeted retry policy:
    # 1) Narration/editorial failures route only to editor.
    # 2) Visual/headline packaging failures route only to packaging.
    # 3) If all checks pass, finalize.
    if narration_score < 4 or not duration_ok or not grounding_ok or not no_hallucination_ok:
        retry_decision = "retry_editor"
        decision_reason = editor_reasons[0] if editor_reasons else "Narration/editorial quality fell below threshold."
    elif visual_score < 4 or not visual_coverage_ok or not narration_visual_alignment_ok or headline_score < 4:
        retry_decision = "retry_packaging"
        decision_reason = packaging_reasons[0] if packaging_reasons else "Visual/headline packaging quality fell below threshold."
    elif editor_reasons:
        retry_decision = "retry_editor"
        decision_reason = editor_reasons[0]
    elif packaging_reasons:
        retry_decision = "retry_packaging"
        decision_reason = packaging_reasons[0]

    notes.append(f"Reviewer routing decision: {retry_decision}. Reason: {decision_reason}")
    seen_notes = set()
    notes = [note for note in notes if not (note in seen_notes or seen_notes.add(note))]

    passed = (
        retry_decision == "finalize"
        and average >= 4
        and not hard_failures
        and all(item.score >= 4 for item in criteria)
    )

    gating = {
        "duration_ok": duration_ok,
        "runtime_sec": round(runtime_sec, 2),
        "grounding_ok": grounding_ok,
        "grounding_average": grounding_avg,
        "visual_coverage_ok": visual_coverage_ok,
        "visual_coverage_ratio": visual_coverage,
        "major_fact_coverage_ok": major_fact_coverage_ok,
        "major_fact_coverage_ratio": major_fact_coverage,
        "no_hallucination_ok": no_hallucination_ok,
        "avg_unsupported_token_ratio": float(hallucination_metrics["avg_unsupported_ratio"]),
        "hallucination_high_risk_segments": int(hallucination_metrics["high_risk_segments"]),
        "no_repetition_ok": no_repetition_ok,
        "headline_unique_ratio": float(repetition_metrics["headline_unique_ratio"]),
        "subheadline_unique_ratio": float(repetition_metrics["subheadline_unique_ratio"]),
        "repeated_openers": int(repetition_metrics["repeated_openers"]),
        "narration_visual_alignment_ok": narration_visual_alignment_ok,
        "narration_visual_alignment_ratio": narration_visual_alignment,
        "story_beat_flow_ok": story_beat_flow_ok,
        "story_beat_coverage_ratio": float(beat_flow_metrics["coverage_ratio"]),
        "story_beat_ordered": bool(beat_flow_metrics["ordered"]),
        "story_beat_sequence": str(beat_flow_metrics["sequence"]),
    }

    structured_evaluation = {
        "scores": {
            "structure": structure_score,
            "hook": hook_score,
            "narration": narration_score,
            "visuals": visual_score,
            "headlines": headline_score,
        },
        "final_decision": retry_decision,
        "decision_reason": decision_reason,
        "retry_target": (
            "editor_agent"
            if retry_decision == "retry_editor"
            else "visual_packaging_agent"
            if retry_decision == "retry_packaging"
            else "finalize"
        ),
        "hard_failures": hard_failures,
        "gates": gating,
    }

    review = QAReview(
        passed=passed,
        overall_average=average,
        retry_rounds=retry_rounds,
        retry_decision=retry_decision,
        final_decision=retry_decision,
        decision_reason=decision_reason,
        weak_segments=weak_segments,
        hard_failures=hard_failures,
        gating=gating,
        notes=notes,
        criteria=criteria,
        score_breakdown=score_breakdown,
        score_explanation=score_explanation,
        structured_evaluation=structured_evaluation,
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
