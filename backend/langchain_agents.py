"""
langchain_agents.py - Structured LangChain/Gemini helpers for newsroom agents.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from backend.gemini_router import build_langchain_chat_model
from backend.utils import get_logger, sanitize_text

log = get_logger("langchain_agents")


class EditorialBeat(BaseModel):
    segment_index: int
    story_beat: str = ""
    editorial_focus: str = ""
    narration_tweak: str = ""


class EditorialPlan(BaseModel):
    opening_hook: str = ""
    closing_line: str = ""
    beats: List[EditorialBeat] = Field(default_factory=list)
    rationale_summary: str = ""


class PackagingOverride(BaseModel):
    segment_index: int
    main_headline: str = ""
    subheadline: str = ""
    top_tag: str = ""
    lower_third: str = ""
    ticker_text: str = ""
    ai_support_visual_prompt: str = ""
    control_room_cue: str = ""
    rationale: str = ""


class PackagingPlan(BaseModel):
    segments: List[PackagingOverride] = Field(default_factory=list)


class QACritique(BaseModel):
    summary: str = ""
    route_suggestion: str = "finalize"
    weak_segments: List[int] = Field(default_factory=list)
    quick_fixes: List[str] = Field(default_factory=list)



def _safe_llm(model_name: str, api_key: str):
    if not api_key:
        return None
    try:
        return build_langchain_chat_model(model_name=model_name, api_key=api_key, temperature=0.2)
    except Exception as exc:
        log.warning(f"Could not initialize LangChain chat model: {exc}")
        return None



def _clip(text: str, words: int) -> str:
    clean = sanitize_text(text)
    tokens = clean.split()
    return " ".join(tokens[:words]).strip()



def generate_editorial_plan(
    *,
    model_name: str,
    api_key: str,
    source_title: str,
    segments: List[dict],
) -> Dict[str, Any]:
    llm = _safe_llm(model_name, api_key)
    if not llm:
        return {}

    try:
        from langchain_core.prompts import ChatPromptTemplate

        structured = llm.with_structured_output(EditorialPlan)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the News Editor Agent for a live TV newsroom package. "
                    "Return concise, factual, broadcast-ready beat guidance. "
                    "Do not invent facts."
                ),
                (
                    "human",
                    "Source title: {source_title}\n"
                    "Segments JSON: {segments_json}\n"
                    "Provide: opening hook, closing line, and per-segment beat directives."
                ),
            ]
        )
        chain = prompt | structured
        response = chain.invoke(
            {
                "source_title": source_title,
                "segments_json": [
                    {
                        "segment_index": idx,
                        "segment_type": seg.get("segment_type", "body"),
                        "text": _clip(seg.get("text", ""), 90),
                    }
                    for idx, seg in enumerate(segments)
                ],
            }
        )
        if isinstance(response, BaseModel):
            return response.model_dump()
        if isinstance(response, dict):
            return response
        return {}
    except Exception as exc:
        log.warning(f"Editorial planning with LangChain failed: {exc}")
        return {}



def generate_packaging_overrides(
    *,
    model_name: str,
    api_key: str,
    source_title: str,
    segments: List[dict],
    copy_plan: List[dict],
) -> Dict[str, Any]:
    llm = _safe_llm(model_name, api_key)
    if not llm:
        return {}

    try:
        from langchain_core.prompts import ChatPromptTemplate

        structured = llm.with_structured_output(PackagingPlan)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Visual Packaging Agent for a broadcast control room. "
                    "Improve short overlays, tags, and cues while staying factual."
                ),
                (
                    "human",
                    "Source title: {source_title}\n"
                    "Segments JSON: {segments_json}\n"
                    "Current copy plan JSON: {copy_plan_json}\n"
                    "Return segment-wise packaging overrides only where they improve quality."
                ),
            ]
        )
        chain = prompt | structured
        response = chain.invoke(
            {
                "source_title": source_title,
                "segments_json": [
                    {
                        "segment_index": idx,
                        "segment_type": seg.get("segment_type", "body"),
                        "text": _clip(seg.get("text", ""), 80),
                    }
                    for idx, seg in enumerate(segments)
                ],
                "copy_plan_json": copy_plan,
            }
        )
        if isinstance(response, BaseModel):
            return response.model_dump()
        if isinstance(response, dict):
            return response
        return {}
    except Exception as exc:
        log.warning(f"Packaging refinement with LangChain failed: {exc}")
        return {}



def generate_qa_critique(
    *,
    model_name: str,
    api_key: str,
    review_payload: Dict[str, Any],
    packaged_segments: List[dict],
) -> Dict[str, Any]:
    llm = _safe_llm(model_name, api_key)
    if not llm:
        return {}

    try:
        from langchain_core.prompts import ChatPromptTemplate

        structured = llm.with_structured_output(QACritique)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are QA / Evaluation Agent assistant. "
                    "Summarize issues and suggest focused retry route. "
                    "Use only available evidence."
                ),
                (
                    "human",
                    "Review JSON: {review_json}\n"
                    "Segment snapshot: {segment_snapshot}\n"
                    "Return concise QA critique."
                ),
            ]
        )
        chain = prompt | structured
        response = chain.invoke(
            {
                "review_json": review_payload,
                "segment_snapshot": [
                    {
                        "segment_id": seg.get("segment_id"),
                        "headline": seg.get("main_headline", ""),
                        "layout": seg.get("layout", ""),
                        "top_tag": seg.get("top_tag", ""),
                    }
                    for seg in packaged_segments
                ],
            }
        )
        if isinstance(response, BaseModel):
            return response.model_dump()
        if isinstance(response, dict):
            return response
        return {}
    except Exception as exc:
        log.warning(f"QA critique with LangChain failed: {exc}")
        return {}



def apply_editorial_directives(
    narrations: List[str],
    directives: Dict[str, Any],
) -> List[str]:
    if not directives:
        return narrations

    updated = list(narrations)
    beats = directives.get("beats", [])
    for beat in beats:
        try:
            idx = int(beat.get("segment_index", -1))
        except Exception:
            continue
        if idx < 0 or idx >= len(updated):
            continue
        tweak = sanitize_text(beat.get("narration_tweak", "")).strip()
        if 8 <= len(tweak.split()) <= 60:
            updated[idx] = tweak

    opening = sanitize_text(directives.get("opening_hook", "")).strip()
    if opening and len(updated) > 0 and 8 <= len(opening.split()) <= 45:
        updated[0] = opening

    closing = sanitize_text(directives.get("closing_line", "")).strip()
    if closing and len(updated) > 1 and 8 <= len(closing.split()) <= 45:
        updated[-1] = closing

    return updated



def apply_packaging_overrides(copy_plan: List[dict], overrides: Dict[str, Any]) -> List[dict]:
    if not overrides:
        return copy_plan

    updated = [dict(item) for item in copy_plan]
    for item in overrides.get("segments", []):
        try:
            idx = int(item.get("segment_index", -1))
        except Exception:
            continue
        if idx < 0 or idx >= len(updated):
            continue

        main = sanitize_text(item.get("main_headline", "")).strip()
        sub = sanitize_text(item.get("subheadline", "")).strip()
        lower = sanitize_text(item.get("lower_third", "")).strip()
        ticker = sanitize_text(item.get("ticker_text", "")).strip()
        tag = sanitize_text(item.get("top_tag", "")).upper().strip()

        if 2 <= len(main.split()) <= 7:
            updated[idx]["main_headline"] = main
        if 4 <= len(sub.split()) <= 12:
            updated[idx]["subheadline"] = sub
        if lower:
            updated[idx]["lower_third"] = " ".join(lower.split()[:12])
        if ticker:
            updated[idx]["ticker_text"] = " ".join(ticker.split()[:14])
        if tag and len(tag.split()) <= 2:
            updated[idx]["top_tag"] = tag[:20]

        prompt = sanitize_text(item.get("ai_support_visual_prompt", "")).strip()
        if prompt:
            updated[idx]["ai_support_visual_prompt"] = " ".join(prompt.split()[:35])

        rationale = sanitize_text(item.get("rationale", "")).strip()
        if rationale:
            updated[idx]["headline_reason"] = " ".join(rationale.split()[:40])

    return updated
