# pyright: reportGeneralTypeIssues=false
"""
langgraph_pipeline.py - Real LangGraph orchestration for Algsoch News.
"""

from __future__ import annotations

import asyncio
import copy
import re
from functools import partial
from typing import Any, Dict, List, Sequence, TypedDict, cast

from langgraph.graph import END, StateGraph

from backend.broadcast import (
    build_rundown,
    build_screenplay_text,
    build_transcript_cues,
    generate_segment_copy,
    seconds_to_timecode,
)
from backend.langchain_agents import (
    apply_editorial_directives,
    apply_packaging_overrides,
    generate_editorial_plan,
    generate_packaging_overrides,
    generate_qa_critique,
)
from backend.models import QAReview
from backend.narration import generate_narrations
from backend.qa import review_broadcast_package
from backend.scraper import scrape_article
from backend.segmenter import segment_article
from backend.utils import config, estimate_duration, sanitize_text
from backend.visual_planner import plan_visuals, prepare_source_images
from backend.workflow import (
    append_agent_output,
    record_agent_decision,
    record_trace_event,
    set_agent_input,
    set_agent_model,
    set_agent_state,
    set_agent_tools,
)


class GraphState(TypedDict):
    article_url: str
    max_segments: int
    use_gemini: bool
    selected_model: str
    gemini_api_key: str
    retry_round: int
    route_history: List[str]
    article_raw: Dict[str, Any]
    segments_raw: List[dict]
    narrations: List[str]
    copy_plan: List[dict]
    overall_headline: str
    hydrated_packages: List[dict]
    source_inventory: List[dict]
    visuals: List[dict]
    packaged_segments: List[dict]
    review: QAReview | None
    qa_score: float
    weak_segments: List[int]
    editorial_directives: Dict[str, Any]
    qa_critique: Dict[str, Any]
    transcript_cues: List[dict]
    rundown: List[dict]
    screenplay_text: str


def _truncate_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(" ,.;:") + "..."



def _retime_segments(segments: Sequence[dict], narrations: Sequence[str]) -> List[dict]:
    retimed: List[dict] = []
    for segment, narration in zip(segments, narrations):
        seg = dict(segment)
        floor = 6.5 if seg["segment_type"] in {"intro", "outro"} else 8.0
        padding = 0.5 if seg["segment_type"] in {"intro", "outro"} else 0.9
        duration = round(max(floor, estimate_duration(narration) + padding), 2)
        seg["duration"] = duration
        retimed.append(seg)

    total = sum(seg["duration"] for seg in retimed)
    if retimed and total < 60:
        bump = round((60 - total) / len(retimed), 2)
        for seg in retimed:
            seg["duration"] = round(seg["duration"] + bump, 2)
    elif retimed and total > 120:
        scale = 120 / total
        for seg in retimed:
            floor = 6.0 if seg["segment_type"] in {"intro", "outro"} else 7.0
            seg["duration"] = round(max(floor, seg["duration"] * scale), 2)

    cursor = 0.0
    for seg in retimed:
        seg["start_time"] = round(cursor, 2)
        seg["end_time"] = round(cursor + seg["duration"], 2)
        cursor += seg["duration"]
    return retimed



def _hydrate_copy_plan(segments: Sequence[dict], narrations: Sequence[str], copy_plan: Sequence[dict]) -> List[dict]:
    hydrated = []
    for segment, narration, package in zip(segments, narrations, copy_plan):
        hydrated.append(
            {
                **package,
                "segment_type": segment["segment_type"],
                "anchor_narration": narration,
                "source_text": segment["text"],
                "start_time": segment["start_time"],
                "end_time": segment["end_time"],
                "duration": segment["duration"],
                "start_timecode": seconds_to_timecode(segment["start_time"]),
                "end_timecode": seconds_to_timecode(segment["end_time"]),
            }
        )
    return hydrated



def _build_segment_records(
    segments: Sequence[dict],
    narrations: Sequence[str],
    packages: Sequence[dict],
    visuals: Sequence[dict],
) -> List[dict]:
    records: List[dict] = []
    for index, (segment, narration, package, visual) in enumerate(zip(segments, narrations, packages, visuals)):
        records.append(
            {
                "segment_id": package["segment_id"],
                "index": index,
                "segment_type": segment["segment_type"],
                "start_time": segment["start_time"],
                "end_time": segment["end_time"],
                "start_timecode": package["start_timecode"],
                "end_timecode": package["end_timecode"],
                "duration": segment["duration"],
                "layout": visual["layout"],
                "anchor_narration": narration,
                "main_headline": package["main_headline"],
                "subheadline": package["subheadline"],
                "top_tag": package["top_tag"],
                "left_panel": visual["left_panel"],
                "right_panel": visual["right_panel"],
                "source_text": segment["text"],
                "source_excerpt": package["source_excerpt"],
                "source_image_url": visual.get("source_image_url"),
                "ai_support_visual_prompt": visual.get("ai_support_visual_prompt"),
                "transition": visual.get("transition", package["transition"]),
                "story_beat": package.get("story_beat", segment["segment_type"]),
                "editorial_focus": package.get("editorial_focus", ""),
                "lower_third": package.get("lower_third", ""),
                "ticker_text": package.get("ticker_text", ""),
                "camera_motion": visual.get("camera_motion", ""),
                "visual_source_kind": visual.get("visual_source_kind", ""),
                "visual_confidence": visual.get("visual_confidence", 0.0),
                "control_room_cue": visual.get("control_room_cue", ""),
                "director_note": visual.get("director_note", ""),
                "source_visual_used": bool(visual.get("source_image_url")),
                "scene_image_url": visual.get("scene_image_url"),
                "scene_image_path": visual.get("scene_image_path"),
                "html_frame_url": visual.get("html_frame_url"),
                "html_frame_path": visual.get("html_frame_path"),
                "support_image_path": visual.get("support_image_path"),
                "image_url": visual.get("source_image_url"),
                "image_path": visual.get("image_path"),
                "visual_prompt": visual.get("visual_prompt", ""),
                "visual_rationale": visual.get("visual_rationale", ""),
                "headline_reason": package.get("headline_reason", ""),
                "factual_points": package.get("factual_points", []),
                "headline": package["main_headline"],
                "narration": narration,
                "transcript_cues": [],
            }
        )
    return records



def _tighten_narration(segment: dict) -> str:
    narration = sanitize_text(segment["anchor_narration"])
    if segment["segment_type"] == "intro" and "breaking" not in narration.lower():
        return f"Breaking tonight: {segment['main_headline']}. {segment['source_excerpt']}"
    if segment["segment_type"] == "outro":
        return "That is the latest for now. We will continue tracking developments and bring you more verified updates."
    return _truncate_words(narration, 28)



def _tighten_packaging(segment: dict) -> dict:
    updated = dict(segment)
    updated["main_headline"] = updated["main_headline"].rstrip(".")
    updated["main_headline"] = " ".join(updated["main_headline"].split()[:6])
    updated["subheadline"] = " ".join(updated["subheadline"].split()[:10])
    updated["lower_third"] = " ".join(updated.get("lower_third", updated["main_headline"]).split()[:12])
    updated["ticker_text"] = " ".join(updated.get("ticker_text", updated["subheadline"]).split()[:12])
    if not updated.get("top_tag"):
        updated["top_tag"] = "UPDATE"
    return updated


_INSTRUCTION_PATTERNS = [
    r"^state\b",
    r"^shift\b",
    r"^emphasize\b",
    r"^convey\b",
    r"^stress\b",
    r"^frame\b",
    r"^open\b",
    r"^close\b",
    r"^highlight\b",
    r"^focus\b",
    r"^mention\b",
    r"^use\b",
    r"^keep\b",
    r"\bphrase\b",
    r"\btone\b",
]


def _looks_like_editor_instruction(text: str) -> bool:
    compact = sanitize_text(text).strip().lower()
    if not compact:
        return False
    return any(re.search(pattern, compact) for pattern in _INSTRUCTION_PATTERNS)


def _fallback_narration_from_segment(segment: dict) -> str:
    segment_type = segment.get("segment_type", "body")
    source = _truncate_words(sanitize_text(segment.get("text", "")), 30)
    if not source:
        source = _truncate_words(sanitize_text(segment.get("headline", "")), 18)

    if segment_type == "intro":
        return f"Tonight: {source}" if source else "Tonight, we bring you the latest verified update."
    if segment_type == "outro":
        return "That is the latest for now. We will continue tracking developments and bring you more verified updates."
    return source or "Here is the latest verified development in this story."


def _normalize_narrations(segments: Sequence[dict], narrations: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    for segment, narration in zip(segments, narrations):
        clean = sanitize_text(narration)
        if _looks_like_editor_instruction(clean):
            clean = _fallback_narration_from_segment(segment)
        normalized.append(clean)
    return normalized


def _passthrough(state: GraphState) -> Dict[str, Any]:
    keys = [
        "article_url",
        "max_segments",
        "use_gemini",
        "selected_model",
        "gemini_api_key",
        "retry_round",
    ]
    return {key: state.get(key) for key in keys if key in state}


async def _node_extraction(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    job = ctx["job"]
    loop = asyncio.get_running_loop()
    article_url = state["article_url"]

    extraction_tools = [
        "requests",
        "newspaper3k",
        "readability-lxml",
        "beautifulsoup",
        "json-ld parser",
    ]
    set_agent_state(job, "extraction", status="running", progress=20, summary="Running multi-strategy extraction ranking.")
    set_agent_tools(job, "extraction", extraction_tools)
    set_agent_input(job, "extraction", {"article_url": article_url})

    record_trace_event(
        job,
        "extraction",
        "node_start",
        "Started extraction pass across parser candidates.",
        input_payload={"article_url": article_url},
        tools=extraction_tools,
    )

    article_raw = await loop.run_in_executor(None, scrape_article, article_url)

    record_trace_event(
        job,
        "extraction",
        "node_complete",
        "Article extraction completed with ranked candidates.",
        input_payload={"article_url": article_url},
        tools=["newspaper3k", "readability-lxml", "beautifulsoup", "json-ld parser"],
        output_payload={
            "method": article_raw.get("method"),
            "word_count": article_raw.get("word_count"),
            "candidate_count": len(article_raw.get("candidates", [])),
        },
    )

    append_agent_output(job, "extraction", "Chosen extractor", article_raw.get("method", "unknown"))
    append_agent_output(job, "extraction", "Extracted preview", article_raw.get("text", "")[:900])
    selected_candidate = next(
        (
            item
            for item in article_raw.get("candidates", [])
            if item.get("method") == article_raw.get("method") and item.get("selected")
        ),
        None,
    )
    if selected_candidate:
        append_agent_output(
            job,
            "extraction",
            "Dropped samples",
            selected_candidate.get("dropped_samples", []),
            kind="list",
        )
    append_agent_output(job, "extraction", "Candidates", article_raw.get("candidates", []), kind="table")
    append_agent_output(job, "extraction", "Extractor attempts", article_raw.get("extraction_attempts", []), kind="table")

    set_agent_state(
        job,
        "extraction",
        status="done",
        progress=100,
        summary=f"Selected {article_raw.get('method', 'unknown')} with {article_raw.get('word_count', 0)} cleaned words.",
        metrics={
            "word_count": article_raw.get("word_count", 0),
            "image_count": len(article_raw.get("images", [])),
            "candidates": len(article_raw.get("candidates", [])),
        },
    )

    route_history = list(state.get("route_history", []))
    route_history.append("extract")
    return {**_passthrough(state), "article_raw": article_raw, "route_history": route_history}


async def _node_editor(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    job = ctx["job"]
    loop = asyncio.get_running_loop()

    article_raw = state["article_raw"]
    max_segments = state["max_segments"]
    selected_model = state["selected_model"]
    gemini_api_key = state.get("gemini_api_key", "")
    use_gemini = bool(state.get("use_gemini", True))

    editor_tools = ["segmenter", "narration templates", "gemini llm", "timing normalizer"]
    set_agent_state(job, "editor", status="running", progress=25, summary="Generating story beats and anchor narration.")
    set_agent_tools(job, "editor", editor_tools)
    set_agent_model(job, "editor", selected_model)
    set_agent_input(
        job,
        "editor",
        {
            "max_segments": max_segments,
            "source_title": article_raw.get("title", ""),
            "word_count": article_raw.get("word_count", 0),
        },
    )

    record_trace_event(
        job,
        "editor",
        "node_start",
        "Started editorial planning and narration drafting.",
        input_payload={
            "max_segments": max_segments,
            "source_title": article_raw.get("title", ""),
            "word_count": article_raw.get("word_count", 0),
        },
        tools=editor_tools,
    )

    segments_raw = await loop.run_in_executor(
        None,
        segment_article,
        article_raw["text"],
        max_segments,
        article_raw.get("title", ""),
    )
    narrations = await loop.run_in_executor(
        None,
        generate_narrations,
        segments_raw,
        [article_raw.get("title", "")] * len(segments_raw),
        article_raw["text"],
        use_gemini,
        selected_model,
    )

    record_trace_event(
        job,
        "editor",
        "beats_ready",
        "Story beats segmented and narration draft generated.",
        output_payload={
            "segment_count": len(segments_raw),
            "sample_opening": narrations[0] if narrations else "",
        },
    )

    editorial_directives = {}
    if use_gemini and gemini_api_key:
        editorial_directives = await loop.run_in_executor(
            None,
            partial(
                generate_editorial_plan,
                model_name=selected_model,
                api_key=gemini_api_key,
                source_title=article_raw.get("title", ""),
                segments=segments_raw,
            ),
        )
        if editorial_directives:
            narrations = apply_editorial_directives(narrations, editorial_directives)
            append_agent_output(job, "editor", "LLM editorial directives", editorial_directives, kind="json")

    narrations = _normalize_narrations(segments_raw, narrations)

    segments_raw = _retime_segments(segments_raw, narrations)

    record_trace_event(
        job,
        "editor",
        "node_complete",
        "Editor produced timed narration beats.",
        input_payload={"max_segments": max_segments},
        tools=["segmenter", "generate_narrations"],
        output_payload={
            "segment_count": len(segments_raw),
            "runtime_sec": segments_raw[-1]["end_time"] if segments_raw else 0,
            "gemini_enabled": use_gemini,
            "llm_directives": bool(editorial_directives),
        },
    )

    append_agent_output(job, "editor", "Opening line", narrations[0] if narrations else "")
    append_agent_output(job, "editor", "Closing line", narrations[-1] if narrations else "")

    set_agent_state(
        job,
        "editor",
        status="done",
        progress=100,
        summary=f"Generated {len(segments_raw)} timed beats for newsroom narration.",
        metrics={"segment_count": len(segments_raw), "runtime_sec": segments_raw[-1]["end_time"] if segments_raw else 0},
    )

    route_history = list(state.get("route_history", []))
    route_history.append("editor")
    return {
        **_passthrough(state),
        "segments_raw": segments_raw,
        "narrations": narrations,
        "editorial_directives": editorial_directives,
        "route_history": route_history,
    }


async def _node_packaging_parallel(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    job = ctx["job"]
    loop = asyncio.get_running_loop()

    article_raw = state["article_raw"]
    segments_raw = state["segments_raw"]
    narrations = state["narrations"]
    selected_model = state["selected_model"]
    gemini_api_key = state.get("gemini_api_key", "")
    use_gemini = bool(state.get("use_gemini", True))
    job_id = ctx["job_id"]

    set_agent_state(
        job,
        "packaging",
        status="running",
        progress=30,
        summary="Executing copy and visual-prep in parallel fan-out.",
        branch="parallel",
    )
    packaging_tools = ["broadcast copy generator", "source image prep", "visual planner"]
    set_agent_tools(job, "packaging", packaging_tools)
    set_agent_input(
        job,
        "packaging",
        {
            "segment_count": len(segments_raw),
            "source_images": len(article_raw.get("images", [])),
        },
    )

    record_trace_event(
        job,
        "packaging",
        "node_start",
        "Started packaging fan-out for copy, source assets, and visual planning.",
        input_payload={
            "segment_count": len(segments_raw),
            "source_images": len(article_raw.get("images", [])),
        },
        tools=packaging_tools,
    )

    copy_future = loop.run_in_executor(
        None,
        generate_segment_copy,
        segments_raw,
        article_raw.get("title", ""),
        article_raw["text"],
    )
    source_future = loop.run_in_executor(
        None,
        prepare_source_images,
        article_raw.get("images", []),
        job_id,
    )
    (overall_headline, copy_plan), source_inventory = await asyncio.gather(copy_future, source_future)

    record_trace_event(
        job,
        "packaging",
        "parallel_fanout",
        "Copy generation and source-image preparation completed.",
        output_payload={
            "copy_segments": len(copy_plan),
            "source_assets": len(source_inventory),
        },
    )

    llm_packaging_overrides = {}
    if use_gemini and gemini_api_key:
        llm_packaging_overrides = await loop.run_in_executor(
            None,
            partial(
                generate_packaging_overrides,
                model_name=selected_model,
                api_key=gemini_api_key,
                source_title=article_raw.get("title", ""),
                segments=segments_raw,
                copy_plan=copy_plan,
            ),
        )
        if llm_packaging_overrides:
            copy_plan = apply_packaging_overrides(copy_plan, llm_packaging_overrides)
            append_agent_output(job, "packaging", "LLM packaging overrides", llm_packaging_overrides, kind="json")

    hydrated_packages = _hydrate_copy_plan(segments_raw, narrations, copy_plan)
    visuals = await loop.run_in_executor(
        None,
        plan_visuals,
        segments_raw,
        hydrated_packages,
        article_raw.get("images", []),
        article_raw.get("source_domain", ""),
        job_id,
        source_inventory,
    )

    packaged_segments = _build_segment_records(segments_raw, narrations, hydrated_packages, visuals)

    append_agent_output(job, "packaging", "Overall headline", overall_headline)
    append_agent_output(job, "packaging", "Transitions", [item["transition"] for item in packaged_segments], kind="list")
    append_agent_output(job, "packaging", "Camera motions", [item["camera_motion"] for item in packaged_segments], kind="list")

    record_trace_event(
        job,
        "packaging",
        "parallel_complete",
        "Parallel packaging fan-out completed.",
        input_payload={"segment_count": len(segments_raw)},
        tools=["generate_segment_copy", "prepare_source_images", "plan_visuals"],
        output_payload={
            "overall_headline": overall_headline,
            "source_visuals": sum(1 for item in packaged_segments if item.get("source_visual_used")),
            "ai_support_visuals": sum(1 for item in packaged_segments if item.get("ai_support_visual_prompt")),
            "llm_overrides": bool(llm_packaging_overrides),
        },
        decision="route_to_review",
        route_to="review",
    )

    set_agent_state(
        job,
        "packaging",
        status="done",
        progress=100,
        summary="Built segment copy, layout, visuals, and scene-composition metadata.",
        metrics={
            "source_visuals": sum(1 for item in packaged_segments if item.get("source_visual_used")),
            "support_visuals": sum(1 for item in packaged_segments if item.get("ai_support_visual_prompt")),
        },
    )

    route_history = list(state.get("route_history", []))
    route_history.append("packaging")
    return {
        **_passthrough(state),
        "overall_headline": overall_headline,
        "copy_plan": copy_plan,
        "hydrated_packages": hydrated_packages,
        "source_inventory": source_inventory,
        "visuals": visuals,
        "packaged_segments": packaged_segments,
        "route_history": route_history,
    }


async def _node_review(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    job = ctx["job"]
    loop = asyncio.get_running_loop()

    retry_round = int(state.get("retry_round", 0))
    packaged_segments = state["packaged_segments"]
    article_raw = state["article_raw"]
    selected_model = state["selected_model"]
    gemini_api_key = state.get("gemini_api_key", "")
    use_gemini = bool(state.get("use_gemini", True))

    review_tools = ["qa rubric scorer", "targeted retry router"]
    set_agent_state(job, "review", status="running", progress=45, summary="Scoring package and deciding routes.")
    set_agent_tools(job, "review", review_tools)
    set_agent_input(
        job,
        "review",
        {
            "retry_round": retry_round,
            "segment_count": len(packaged_segments),
        },
    )

    record_trace_event(
        job,
        "review",
        "node_start",
        "Started QA rubric scoring and route evaluation.",
        input_payload={
            "retry_round": retry_round,
            "segment_count": len(packaged_segments),
        },
        tools=review_tools,
    )

    qa_score, review = await loop.run_in_executor(
        None,
        review_broadcast_package,
        packaged_segments,
        article_raw["text"],
        retry_round,
    )

    record_trace_event(
        job,
        "review",
        "rubric_scored",
        "Core QA rubric scores computed.",
        output_payload={
            "average": review.overall_average,
            "passed": review.passed,
            "retry_decision": review.retry_decision,
        },
    )

    weak_segments = review.weak_segments or list(range(len(packaged_segments)))
    qa_critique = {}
    if use_gemini and gemini_api_key:
        qa_critique = await loop.run_in_executor(
            None,
            partial(
                generate_qa_critique,
                model_name=selected_model,
                api_key=gemini_api_key,
                review_payload=review.model_dump(),
                packaged_segments=packaged_segments,
            ),
        )
        if qa_critique:
            append_agent_output(job, "review", "LLM QA critique", qa_critique, kind="json")
            summary = qa_critique.get("summary", "").strip()
            if summary:
                review.notes.append(f"LLM critique: {summary}")

    append_agent_output(job, "review", "QA average", review.overall_average, kind="metric")
    append_agent_output(job, "review", "Retry decision", review.retry_decision)
    append_agent_output(job, "review", "Criteria", [item.model_dump() for item in review.criteria], kind="table")

    route_history = list(state.get("route_history", []))
    route_history.append(f"review:{review.retry_decision}")

    record_trace_event(
        job,
        "review",
        "node_complete",
        "QA review completed with routing decision.",
        input_payload={"retry_round": retry_round},
        tools=["review_broadcast_package"],
        output_payload={
            "average": review.overall_average,
            "passed": review.passed,
            "retry_decision": review.retry_decision,
            "weak_segments": weak_segments,
            "llm_critique": bool(qa_critique),
        },
        decision=review.retry_decision,
        route_to=review.retry_decision,
    )

    set_agent_state(
        job,
        "review",
        status="done",
        progress=100,
        summary=f"QA average {review.overall_average}/5 with decision {review.retry_decision}.",
        metrics={"average": review.overall_average, "passed": review.passed, "retries": retry_round},
    )

    return {
        **_passthrough(state),
        "qa_score": qa_score,
        "review": review,
        "weak_segments": weak_segments,
        "qa_critique": qa_critique,
        "route_history": route_history,
    }


async def _node_retry_editor(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    job = ctx["job"]
    weak = state.get("weak_segments", [])

    segments_raw = copy.deepcopy(state["segments_raw"])
    narrations = list(state["narrations"])
    packaged_segments = state["packaged_segments"]

    set_agent_state(
        job,
        "editor",
        status="running",
        progress=78,
        summary="Targeted editorial retry on weak segments only.",
        retry_increment=True,
        branch="qa_retry",
    )

    record_trace_event(
        job,
        "editor",
        "retry_start",
        "Started targeted editorial retry for weak segments.",
        input_payload={"weak_segments": weak},
        tools=["narration tightening"],
    )

    for weak_index in weak:
        if weak_index >= len(packaged_segments):
            continue
        tightened = _tighten_narration(packaged_segments[weak_index])
        narrations[weak_index] = tightened

    segments_raw = _retime_segments(segments_raw, narrations)

    record_agent_decision(
        job,
        "editor",
        "targeted_retry_complete",
        reason=f"Retightened narration for {len(weak)} weak segments.",
        route_to="packaging_parallel",
    )

    record_trace_event(
        job,
        "editor",
        "retry_complete",
        "Editorial retry finished and routed back to packaging.",
        output_payload={"weak_segments_updated": len(weak)},
        route_to="packaging_parallel",
    )

    set_agent_state(job, "editor", status="done", progress=100, summary="Editorial retry complete.")

    route_history = list(state.get("route_history", []))
    route_history.append("retry_editor")
    return {
        **_passthrough(state),
        "segments_raw": segments_raw,
        "narrations": narrations,
        "retry_round": int(state.get("retry_round", 0)) + 1,
        "route_history": route_history,
    }


async def _node_retry_packaging(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    job = ctx["job"]
    weak = set(state.get("weak_segments", []))

    set_agent_state(
        job,
        "packaging",
        status="running",
        progress=78,
        summary="Targeted packaging retry on weak segments.",
        retry_increment=True,
        branch="qa_retry",
    )

    record_trace_event(
        job,
        "packaging",
        "retry_start",
        "Started targeted packaging retry for weak segments.",
        input_payload={"weak_segments": list(weak)},
        tools=["packaging tightening", "visual planner"],
    )

    segments_raw = state["segments_raw"]
    narrations = state["narrations"]
    copy_plan = list(state["copy_plan"])

    for index in weak:
        if index < len(copy_plan):
            copy_plan[index] = _tighten_packaging(copy_plan[index])

    hydrated_packages = _hydrate_copy_plan(segments_raw, narrations, copy_plan)

    loop = asyncio.get_running_loop()
    visuals = await loop.run_in_executor(
        None,
        plan_visuals,
        segments_raw,
        hydrated_packages,
        state["article_raw"].get("images", []),
        state["article_raw"].get("source_domain", ""),
        ctx["job_id"],
        state.get("source_inventory", []),
    )
    packaged_segments = _build_segment_records(segments_raw, narrations, hydrated_packages, visuals)

    record_agent_decision(
        job,
        "packaging",
        "targeted_retry_complete",
        reason=f"Retightened packaging for {len(weak)} weak segments.",
        route_to="review",
    )

    record_trace_event(
        job,
        "packaging",
        "retry_complete",
        "Packaging retry finished and routed back to QA.",
        output_payload={"weak_segments_updated": len(weak)},
        route_to="review",
    )

    set_agent_state(job, "packaging", status="done", progress=100, summary="Packaging retry complete.")

    route_history = list(state.get("route_history", []))
    route_history.append("retry_packaging")
    return {
        **_passthrough(state),
        "copy_plan": copy_plan,
        "hydrated_packages": hydrated_packages,
        "visuals": visuals,
        "packaged_segments": packaged_segments,
        "retry_round": int(state.get("retry_round", 0)) + 1,
        "route_history": route_history,
    }


async def _node_retry_both(state: GraphState, ctx: Dict[str, Any]) -> Dict[str, Any]:
    current_retry = int(state.get("retry_round", 0))
    mid = await _node_retry_editor(state, ctx)
    merged = {**state, **mid, "retry_round": current_retry}
    merged_state = cast(GraphState, dict(merged))
    result = await _node_retry_packaging(merged_state, ctx)
    result["retry_round"] = current_retry + 1
    return result



def _route_from_review(state: GraphState) -> str:
    review = state.get("review")
    if not review:
        return "finalize"

    retry_round = int(state.get("retry_round", 0))
    if review.passed:
        return "finalize"
    if retry_round >= config.MAX_RETRIES:
        return "finalize"

    decision = review.retry_decision
    if decision == "retry_editor":
        return "retry_editor"
    if decision == "retry_packaging":
        return "retry_packaging"
    if decision == "retry_editor_and_packaging":
        return "retry_both"
    return "finalize"



def _attach_transcript_cues(segments: Sequence[dict]) -> tuple[List[dict], List[dict]]:
    prepared = [dict(segment, transcript_cues=[]) for segment in segments]
    transcript_cues = build_transcript_cues(prepared)
    segment_lookup = {segment["segment_id"]: segment for segment in prepared}
    for cue in transcript_cues:
        segment_lookup.get(cue["segment_id"], {}).setdefault("transcript_cues", []).append(cue)
    return prepared, transcript_cues



def build_news_graph(ctx: Dict[str, Any]):
    graph = StateGraph(GraphState)  # type: ignore[arg-type]

    async def extract_node(state):
        return await _node_extraction(state, ctx)

    async def editor_node(state):
        return await _node_editor(state, ctx)

    async def packaging_node(state):
        return await _node_packaging_parallel(state, ctx)

    async def review_node(state):
        return await _node_review(state, ctx)

    async def retry_editor_node(state):
        return await _node_retry_editor(state, ctx)

    async def retry_packaging_node(state):
        return await _node_retry_packaging(state, ctx)

    async def retry_both_node(state):
        return await _node_retry_both(state, ctx)

    graph.add_node("extract", extract_node)  # type: ignore[arg-type]
    graph.add_node("editor", editor_node)  # type: ignore[arg-type]
    graph.add_node("packaging_parallel", packaging_node)  # type: ignore[arg-type]
    graph.add_node("review", review_node)  # type: ignore[arg-type]
    graph.add_node("retry_editor", retry_editor_node)  # type: ignore[arg-type]
    graph.add_node("retry_packaging", retry_packaging_node)  # type: ignore[arg-type]
    graph.add_node("retry_both", retry_both_node)  # type: ignore[arg-type]

    graph.set_entry_point("extract")
    graph.add_edge("extract", "editor")
    graph.add_edge("editor", "packaging_parallel")
    graph.add_edge("packaging_parallel", "review")

    graph.add_conditional_edges(
        "review",
        _route_from_review,
        {
            "finalize": END,
            "retry_editor": "retry_editor",
            "retry_packaging": "retry_packaging",
            "retry_both": "retry_both",
        },
    )

    graph.add_edge("retry_editor", "packaging_parallel")
    graph.add_edge("retry_packaging", "review")
    graph.add_edge("retry_both", "review")

    return graph.compile()


async def run_graph_pipeline(job: dict, job_id: str, initial_state: GraphState) -> GraphState:
    ctx = {"job": job, "job_id": job_id}
    runner = build_news_graph(ctx)
    final_state = cast(GraphState, await runner.ainvoke(initial_state))

    packaged_segments, transcript_cues = _attach_transcript_cues(final_state["packaged_segments"])
    rundown = build_rundown(packaged_segments)

    final_state["packaged_segments"] = packaged_segments
    final_state["transcript_cues"] = transcript_cues
    final_state["rundown"] = rundown
    final_state["screenplay_text"] = build_screenplay_text(
        final_state["article_url"],
        final_state["article_raw"].get("title", ""),
        final_state["segments_raw"][-1]["end_time"] if final_state.get("segments_raw") else 0,
        packaged_segments,
    )

    return final_state
