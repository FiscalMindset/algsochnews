"""
cli.py - Command-line client for Algsoch News backend API.

Usage examples:
  python -m backend.cli health
  python -m backend.cli generate --url https://example.com/story --use-gemini --wait
    python -m backend.cli wizard
  python -m backend.cli status --job-id abc123
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, cast

import requests

if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

DEFAULT_API = "http://127.0.0.1:8000"
_COLOR_MODE = "auto"

_ANSI_RESET = "\033[0m"
_ANSI_STATUS = {
    "pending": "36",     # cyan
    "processing": "34",  # blue
    "done": "32",        # green
    "failed": "31",      # red
}
_ANSI_LOG_LEVEL = {
    "DEBUG": "90",   # bright black
    "INFO": "37",    # white
    "WARNING": "33", # yellow
    "ERROR": "31",   # red
    "CRITICAL": "35",# magenta
}
_SPINNER_FRAMES = ["|", "/", "-", "\\"]
_STAGE_HINTS: list[tuple[str, str]] = [
    ("verifying gemini", "model-check"),
    ("starting langgraph", "orchestration"),
    ("scraping", "extraction"),
    ("extract", "extraction"),
    ("segment", "segmentation"),
    ("narration", "narration"),
    ("editor", "editorial"),
    ("packag", "packaging"),
    ("review", "qa-review"),
    ("render", "render"),
    ("saving", "persist"),
    ("skipping", "delivery"),
]
_AGENT_ORDER = ["extraction", "editor", "packaging", "review", "video_generation", "render_review"]
_AGENT_LABELS = {
    "extraction": "Extract",
    "editor": "Editor",
    "packaging": "Package",
    "review": "QA",
    "video_generation": "Video",
    "render_review": "RenderQA",
}
_AGENT_ICONS = {
    "pending": "○",
    "running": "▶",
    "done": "●",
    "failed": "✖",
}
_AGENT_STATUS_COLOR = {
    "pending": "90",
    "running": "36",
    "done": "32",
    "failed": "31",
}
_STREAMING_LOGGER_NAMES = {
    "main",
    "scraper",
    "pipeline",
    "segmenter",
    "narration",
    "langchain_agents",
    "visual_planner",
    "qa",
    "video_renderer",
    "render_review",
    "tts",
    "headline_gen",
    "gemini_router",
    "observability",
    "html_frame_renderer",
}


def _supports_color() -> bool:
    if _COLOR_MODE == "always":
        return True
    if _COLOR_MODE == "never":
        return False
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("CLICOLOR_FORCE") == "1":
        return True
    if os.getenv("TERM", "").lower() == "dumb":
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _set_color_mode(mode: str) -> None:
    global _COLOR_MODE
    _COLOR_MODE = mode if mode in {"auto", "always", "never"} else "auto"


def _paint(text: str, ansi_code: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{ansi_code}m{text}{_ANSI_RESET}"


def _progress_bar(progress: int, width: int = 24) -> str:
    clamped = max(0, min(100, int(progress or 0)))
    filled = int(round((clamped / 100.0) * width))
    return f"{'#' * filled}{'-' * (width - filled)}"


def _stage_from_message(message: str) -> str:
    text = (message or "").lower()
    for hint, stage in _STAGE_HINTS:
        if hint in text:
            return stage
    return "orchestration"


def _format_live_line(status: str, progress: int, message: str) -> str:
    status_norm = str(status or "pending").lower()
    status_tag = status_norm.upper()
    status_tag = _paint(status_tag, _ANSI_STATUS.get(status_norm, "37"))
    bar = _progress_bar(progress)
    if _supports_color():
        bar = _paint(bar, "36")
    stage = _stage_from_message(message)
    stage_tag = _paint(stage, "35") if _supports_color() else stage
    return (
        f"[{time.strftime('%H:%M:%S')}] "
        f"{status_tag} {int(progress or 0):>3}% [{bar}] "
        f"{stage_tag} | {message}"
    )


def _colorize_runtime_log_line(line: str) -> str:
    match = re.search(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]", line)
    if not match:
        return line
    level = match.group(1)
    color = _ANSI_LOG_LEVEL.get(level, "37")
    return _paint(line, color)


def _format_artifact_line(kind: str, file_path: Path, exists: bool) -> str:
    marker = "OK" if exists else "MISSING"
    marker_color = "32" if exists else "31"
    marker_text = _paint(marker, marker_color)
    kind_text = _paint(kind, "36")
    path_text = _paint(str(file_path.resolve()), "96")
    return f" - [{marker_text}] {kind_text}: {path_text}"


def _mute_stream_handlers_for_runtime_streaming(enable: bool) -> list[tuple[logging.Logger, list[logging.Handler]]]:
    if not enable:
        return []

    detached: list[tuple[logging.Logger, list[logging.Handler]]] = []
    for logger_name in _STREAMING_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        stream_handlers = [handler for handler in logger.handlers if isinstance(handler, logging.StreamHandler)]
        removed_handlers: list[logging.Handler] = list(stream_handlers)
        if not removed_handlers:
            continue
        for handler in removed_handlers:
            logger.removeHandler(handler)
        detached.append((logger, removed_handlers))
    return detached


def _restore_stream_handlers(detached: list[tuple[logging.Logger, list[logging.Handler]]]) -> None:
    for logger, handlers in detached:
        for handler in handlers:
            if handler not in logger.handlers:
                logger.addHandler(handler)


def _resolve_local_artifacts(job_id: str, result: Dict[str, Any]) -> dict:
    from backend.utils import config

    output_dir = config.OUTPUT_DIR / job_id
    script_file = output_dir / "script.json"
    video_value = result.get("video_path")
    video_file = Path(video_value) if isinstance(video_value, str) and video_value else (output_dir / "final_video.mp4")
    return {
        "output_dir": output_dir,
        "script_file": script_file,
        "video_file": video_file,
    }


def _read_script_snapshot(script_file: Path) -> dict | None:
    try:
        with script_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None

    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        return None

    script_candidate = payload.get("script")
    if isinstance(script_candidate, dict):
        script_obj = cast(Dict[str, Any], script_candidate)
    else:
        script_obj = cast(Dict[str, Any], payload)

    segments = script_obj.get("segments") or []
    article_candidate = payload.get("article")
    article = cast(Dict[str, Any], article_candidate) if isinstance(article_candidate, dict) else {}
    headline = (
        script_obj.get("overall_headline")
        or payload.get("source_title")
        or article.get("title")
        or ""
    )

    return {
        "headline": str(headline).strip(),
        "segment_count": len(segments) if isinstance(segments, list) else 0,
        "article_words": int(article.get("word_count") or 0),
    }


def _read_script_preview(script_file: Path, max_segments: int = 3, narration_chars: int = 140) -> dict | None:
    snapshot = _read_script_snapshot(script_file)
    if not snapshot:
        return None

    try:
        with script_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return snapshot

    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        return snapshot

    script_candidate = payload.get("script")
    script_obj = cast(Dict[str, Any], script_candidate) if isinstance(script_candidate, dict) else cast(Dict[str, Any], payload)
    raw_segments = script_obj.get("segments")
    segments: list[Any] = raw_segments if isinstance(raw_segments, list) else []

    segment_preview: list[dict] = []
    for idx, segment in enumerate(segments[: max(1, max_segments)], start=1):
        if not isinstance(segment, dict):
            continue
        narration = str(segment.get("narration") or "").strip()
        narration_short = narration[:narration_chars].strip()
        if narration and len(narration) > narration_chars:
            narration_short += "..."
        segment_preview.append(
            {
                "index": idx,
                "type": str(segment.get("type") or "body"),
                "headline": str(segment.get("main_headline") or segment.get("headline") or "").strip(),
                "subheadline": str(segment.get("subheadline") or "").strip(),
                "narration": narration_short,
            }
        )

    snapshot["segment_preview"] = segment_preview
    return snapshot


def _agent_state_signature(payload: Dict[str, Any]) -> tuple:
    agents_raw = payload.get("agents")
    agents: list[Any] = agents_raw if isinstance(agents_raw, list) else []
    by_key: Dict[str, Dict[str, Any]] = {
        str(agent.get("key")): agent
        for agent in agents
        if isinstance(agent, dict) and agent.get("key")
    }

    signature: list[tuple[Any, ...]] = []
    for key in _AGENT_ORDER:
        agent = by_key.get(key, {})
        signature.append(
            (
                key,
                str(agent.get("status") or "pending"),
                int(agent.get("progress") or 0),
                int(agent.get("retry_count") or 0),
                str(agent.get("summary") or ""),
            )
        )
    review_raw = payload.get("review")
    review: Dict[str, Any] = review_raw if isinstance(review_raw, dict) else {}
    signature.append(("route", str(review.get("final_decision") or review.get("retry_decision") or "")))
    return tuple(signature)


def _render_agent_graph_lines(payload: Dict[str, Any]) -> list[str]:
    agents_raw = payload.get("agents")
    agents: list[Any] = agents_raw if isinstance(agents_raw, list) else []
    by_key: Dict[str, Dict[str, Any]] = {
        str(agent.get("key")): agent
        for agent in agents
        if isinstance(agent, dict) and agent.get("key")
    }

    tokens: list[str] = []
    for key in _AGENT_ORDER:
        agent = by_key.get(key, {})
        status = str(agent.get("status") or "pending").lower()
        progress = int(agent.get("progress") or 0)
        label = _AGENT_LABELS.get(key, key)
        icon = _AGENT_ICONS.get(status, "?")
        color = _AGENT_STATUS_COLOR.get(status, "37")
        token = f"{_paint(icon, color)} {_paint(label, color)} {progress:>3}%"
        tokens.append(token)

    lines = [f"Agent Graph: {' -> '.join(tokens)}"]

    active_notes: list[str] = []
    for key in _AGENT_ORDER:
        agent = by_key.get(key, {})
        status = str(agent.get("status") or "pending").lower()
        if status not in {"running", "failed"}:
            continue
        summary = str(agent.get("summary") or "").strip()
        if not summary:
            continue
        label = _AGENT_LABELS.get(key, key)
        active_notes.append(f"  {label}: {summary}")
    lines.extend(active_notes[:3])

    review_raw = payload.get("review")
    review: Dict[str, Any] = review_raw if isinstance(review_raw, dict) else {}
    decision = str(review.get("final_decision") or review.get("retry_decision") or "").strip()
    if decision:
        lines.append(f"  Route decision: {decision}")

    return lines


def _truncate_text(value: str, max_len: int = 140) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3].rstrip()}..."


def _summarize_input_payload(payload: Any, max_items: int = 4) -> str:
    if payload is None:
        return "-"
    if isinstance(payload, dict):
        parts: list[str] = []
        for key in list(payload.keys())[:max_items]:
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                parts.append(f"{key}={value}")
            elif isinstance(value, list):
                parts.append(f"{key}=list[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}=dict[{len(value)}]")
            else:
                parts.append(f"{key}={type(value).__name__}")
        if len(payload.keys()) > max_items:
            parts.append("...")
        return _truncate_text(", ".join(parts) if parts else "dict")
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    return _truncate_text(str(payload))


def _get_active_agent(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    agents_raw = payload.get("agents")
    agents: list[Any] = agents_raw if isinstance(agents_raw, list) else []
    by_key: Dict[str, Dict[str, Any]] = {
        str(agent.get("key")): agent
        for agent in agents
        if isinstance(agent, dict) and agent.get("key")
    }

    for key in _AGENT_ORDER:
        agent = by_key.get(key)
        if not agent:
            continue
        if str(agent.get("status") or "pending").lower() == "running":
            return agent

    non_pending = [
        agent
        for agent in by_key.values()
        if str(agent.get("status") or "pending").lower() != "pending"
    ]
    if not non_pending:
        return None
    non_pending.sort(key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)
    return non_pending[0]


def _agent_focus_signature(payload: Dict[str, Any]) -> tuple:
    agent = _get_active_agent(payload)
    if not agent:
        return (None,)
    outputs = agent.get("outputs") or []
    latest_label = ""
    if outputs and isinstance(outputs[-1], dict):
        latest_label = str(outputs[-1].get("label") or "")
    return (
        str(agent.get("key") or ""),
        str(agent.get("status") or "pending"),
        int(agent.get("progress") or 0),
        int(agent.get("event_count") or 0),
        int(agent.get("retry_count") or 0),
        int(len(outputs)),
        latest_label,
        len(payload.get("trace_events") or []),
    )


def _render_agent_focus_lines(payload: Dict[str, Any]) -> list[str]:
    agent = _get_active_agent(payload)
    if not agent:
        return []

    key = str(agent.get("key") or "")
    status = str(agent.get("status") or "pending").lower()
    progress = int(agent.get("progress") or 0)
    label = _AGENT_LABELS.get(key, key)
    icon = _AGENT_ICONS.get(status, "?")
    color = _AGENT_STATUS_COLOR.get(status, "37")
    tools = agent.get("tools_used") or []
    outputs = agent.get("outputs") or []
    latest_output = outputs[-1] if outputs and isinstance(outputs[-1], dict) else {}
    latest_label = str(latest_output.get("label") or "-")
    latest_kind = str(latest_output.get("kind") or "text")
    model_name = str(agent.get("llm_model") or "-")
    trace_count = len(payload.get("trace_events") or [])

    line_1 = (
        f"Agent Focus: {_paint(icon, color)} {_paint(label, color)} "
        f"{status.upper()} {progress:>3}% | trace={trace_count} "
        f"events={int(agent.get('event_count') or 0)} retries={int(agent.get('retry_count') or 0)}"
    )
    line_2 = f"  input: {_summarize_input_payload(agent.get('current_input'))}"
    line_3 = f"  work: model={_truncate_text(model_name, 50)} | tools={_truncate_text(', '.join(str(item) for item in tools) or '-', 120)}"
    line_4 = f"  output: latest={_truncate_text(latest_label, 80)} ({latest_kind}), total={len(outputs)}"
    return [line_1, line_2, line_3, line_4]


def _agent_trace_block_signature(payload: Dict[str, Any]) -> tuple:
    agent = _get_active_agent(payload)
    if not agent:
        return (None,)

    key = str(agent.get("key") or "")
    status = str(agent.get("status") or "pending")
    progress = int(agent.get("progress") or 0)
    event_count = int(agent.get("event_count") or 0)

    outputs = agent.get("outputs") or []
    last_output = outputs[-1] if outputs and isinstance(outputs[-1], dict) else {}
    last_output_label = str(last_output.get("label") or "")
    last_output_ts = float(last_output.get("timestamp") or 0.0)

    decisions = agent.get("decisions") or []
    last_decision = str(decisions[-1] if decisions else "")

    trace_events_raw = payload.get("trace_events")
    trace_events: list[Any] = trace_events_raw if isinstance(trace_events_raw, list) else []
    last_agent_event = next(
        (
            event
            for event in reversed(trace_events)
            if isinstance(event, dict) and str(event.get("agent_key") or "") == key
        ),
        {},
    )
    last_event_type = str(last_agent_event.get("event_type") or "")
    last_event_message = _truncate_text(str(last_agent_event.get("message") or ""), 100)

    return (
        key,
        status,
        progress,
        event_count,
        len(outputs),
        last_output_label,
        last_output_ts,
        len(decisions),
        last_decision,
        len(trace_events),
        last_event_type,
        last_event_message,
    )


def _render_agent_trace_block(payload: Dict[str, Any], max_events: int = 2, max_outputs: int = 3) -> list[str]:
    agent = _get_active_agent(payload)
    if not agent:
        return []

    key = str(agent.get("key") or "")
    label = _AGENT_LABELS.get(key, key)
    status = str(agent.get("status") or "pending").lower()
    progress = int(agent.get("progress") or 0)
    retries = int(agent.get("retry_count") or 0)
    events = int(agent.get("event_count") or 0)
    branch = str(agent.get("branch") or "-")
    color = _AGENT_STATUS_COLOR.get(status, "37")

    tools = agent.get("tools_used") or []
    outputs = agent.get("outputs") or []
    decisions = agent.get("decisions") or []

    lines = [
        f"[Trace Block: {_paint(label, color)}]",
        f"  status: {status.upper()} {progress:>3}% | retries={retries} events={events} branch={branch}",
        f"  input: {_summarize_input_payload(agent.get('current_input'))}",
        f"  tools: {_truncate_text(', '.join(str(item) for item in tools) or '-', 140)}",
    ]

    trace_events_raw = payload.get("trace_events")
    trace_events: list[Any] = trace_events_raw if isinstance(trace_events_raw, list) else []
    agent_events = [
        event
        for event in trace_events
        if isinstance(event, dict) and str(event.get("agent_key") or "") == key
    ]
    if agent_events:
        lines.append("  recent_events:")
        for event in agent_events[-max_events:]:
            event_type = str(event.get("event_type") or "event")
            message = _truncate_text(str(event.get("message") or ""), 120)
            decision = str(event.get("decision") or "").strip()
            route_to = str(event.get("route_to") or "").strip()
            suffix = ""
            if decision:
                suffix = f" | decision={decision}"
                if route_to:
                    suffix += f"->{route_to}"
            lines.append(f"   - {event_type}: {message}{suffix}")

    if outputs:
        lines.append("  recent_outputs:")
        for output in outputs[-max_outputs:]:
            if not isinstance(output, dict):
                continue
            label_text = str(output.get("label") or "output")
            kind = str(output.get("kind") or "text")
            value = output.get("value")
            if isinstance(value, (dict, list)):
                value_text = _summarize_input_payload(value, max_items=3)
            else:
                value_text = _truncate_text(str(value or ""), 100)
            lines.append(f"   - {label_text} [{kind}]: {value_text}")

    if decisions:
        lines.append(f"  decisions: {_truncate_text(' | '.join(str(item) for item in decisions[-2:]), 140)}")

    return lines


def _format_heartbeat_line(payload: Dict[str, Any], tick: int) -> str:
    frame = _SPINNER_FRAMES[tick % len(_SPINNER_FRAMES)]
    agent = _get_active_agent(payload)
    if not agent:
        return f"  {frame} waiting for first agent update..."

    key = str(agent.get("key") or "")
    status = str(agent.get("status") or "pending").lower()
    progress = int(agent.get("progress") or 0)
    label = _AGENT_LABELS.get(key, key)
    color = _AGENT_STATUS_COLOR.get(status, "37")
    trace_count = len(payload.get("trace_events") or [])
    outputs = len(agent.get("outputs") or [])
    return (
        f"  {_paint(frame, '36')} {_paint(label, color)} working "
        f"{progress:>3}% | status={status} trace={trace_count} outputs={outputs}"
    )


def _render_agent_trace_summary(payload: Dict[str, Any]) -> list[str]:
    agents_raw = payload.get("agents")
    agents: list[Any] = agents_raw if isinstance(agents_raw, list) else []
    by_key: Dict[str, Dict[str, Any]] = {
        str(agent.get("key")): agent
        for agent in agents
        if isinstance(agent, dict) and agent.get("key")
    }

    lines = ["\nAgent Trace Summary:"]
    for key in _AGENT_ORDER:
        agent = by_key.get(key, {})
        status = str(agent.get("status") or "pending").lower()
        progress = int(agent.get("progress") or 0)
        outputs = len(agent.get("outputs") or [])
        events = int(agent.get("event_count") or 0)
        retries = int(agent.get("retry_count") or 0)
        label = _AGENT_LABELS.get(key, key)
        color = _AGENT_STATUS_COLOR.get(status, "37")
        status_tag = _paint(status.upper(), color)
        lines.append(
            f" - {label:<8} {status_tag:<10} {progress:>3}% | events={events} outputs={outputs} retries={retries}"
        )
    lines.append(f" - total trace events: {len(payload.get('trace_events') or [])}")
    return lines


def _api_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    return f"{base}{path}"


def _pretty(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _should_include_json(output_mode: str) -> bool:
    return output_mode in {"json", "both"}


def _should_include_video(output_mode: str) -> bool:
    return output_mode in {"video", "both"}


def _prompt_text(prompt: str, default: str = "", allow_blank: bool = False) -> str:
    label = f"{prompt} [{default}]" if default else prompt
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        if default:
            return default
        if allow_blank:
            return ""
        print("Value is required.")


def _prompt_choice(prompt: str, choices: list[str], default: str) -> str:
    options = "/".join(choices)
    default = default if default in choices else choices[0]
    while True:
        value = input(f"{prompt} ({options}) [{default}]: ").strip().lower()
        if not value:
            return default
        if value in choices:
            return value
        print(f"Invalid value '{value}'. Choose one of: {options}")


def _prompt_bool(prompt: str, default: bool) -> bool:
    default_label = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{default_label}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _prompt_int(prompt: str, default: int, min_value: int, max_value: int) -> int:
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            parsed = int(value)
        except ValueError:
            print("Please enter a valid integer.")
            continue
        if parsed < min_value or parsed > max_value:
            print(f"Please enter a value between {min_value} and {max_value}.")
            continue
        return parsed


def _prompt_float(prompt: str, default: float, min_value: float) -> float:
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            parsed = float(value)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if parsed < min_value:
            print(f"Please enter a value >= {min_value}.")
            continue
        return parsed


def cmd_health(args: argparse.Namespace) -> int:
    url = _api_url(args.api, "/health")
    response = requests.get(url, timeout=args.timeout)
    response.raise_for_status()
    print(_pretty(response.json()))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    url = _api_url(args.api, f"/status/{args.job_id}")
    response = requests.get(url, timeout=args.timeout)
    response.raise_for_status()
    payload = response.json()

    if args.raw:
        print(_pretty(payload))
        return 0

    summary = {
        "job_id": payload.get("job_id"),
        "status": payload.get("status"),
        "progress": payload.get("progress"),
        "message": payload.get("message"),
        "selected_model": (payload.get("model_verification") or {}).get("selected_model"),
        "trace_events": len(payload.get("trace_events") or []),
        "qa_average": ((payload.get("review") or {}).get("overall_average")),
        "retry_decision": ((payload.get("review") or {}).get("retry_decision")),
        "video_url": (((payload.get("result") or {}).get("video_url"))),
    }
    print(_pretty(summary))
    return 0


def _poll_until_done(
    api: str,
    job_id: str,
    interval: float,
    timeout_sec: int,
    req_timeout: int,
    show_agent_graph: bool = False,
    show_trace_blocks: bool = False,
) -> Dict[str, Any]:
    start = time.time()
    last_signature: tuple | None = None
    last_focus_signature: tuple | None = None
    last_trace_block_signature: tuple | None = None
    while True:
        status_url = _api_url(api, f"/status/{job_id}")
        response = requests.get(status_url, timeout=req_timeout)
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status")
        progress = payload.get("progress", 0)
        message = payload.get("message", "")
        print(_format_live_line(str(status), int(progress or 0), str(message)))

        if show_trace_blocks:
            focus_signature = _agent_focus_signature(payload)
            if focus_signature != last_focus_signature:
                for line in _render_agent_focus_lines(payload):
                    print(line)
                last_focus_signature = focus_signature

            trace_block_signature = _agent_trace_block_signature(payload)
            if trace_block_signature != last_trace_block_signature:
                for line in _render_agent_trace_block(payload):
                    print(line)
                last_trace_block_signature = trace_block_signature

        if show_agent_graph:
            signature = _agent_state_signature(payload)
            if signature != last_signature:
                for line in _render_agent_graph_lines(payload):
                    print(line)
                last_signature = signature

        if status in {"done", "failed"}:
            return payload

        if time.time() - start > timeout_sec:
            raise TimeoutError(f"Timed out waiting for job {job_id} after {timeout_sec} seconds")

        time.sleep(interval)


def cmd_generate(args: argparse.Namespace) -> int:
    generate_url = _api_url(args.api, "/generate")
    output_mode = str(getattr(args, "output", "both") or "both")
    delivery_mode = str(getattr(args, "delivery_mode", "full_video") or "full_video")
    payload = {
        "article_url": args.url,
        "use_gemini": args.use_gemini,
        "max_segments": args.max_segments,
        "transition_intensity": args.transition_intensity,
        "transition_profile": args.transition_profile,
        "delivery_mode": delivery_mode,
    }

    response = requests.post(generate_url, json=payload, timeout=args.timeout)
    if response.status_code >= 400:
        try:
            print(_pretty(response.json()))
        except Exception:
            print(response.text)
        response.raise_for_status()

    queued = response.json()
    job_id = queued.get("job_id")
    if not job_id:
        print(_pretty(queued))
        raise RuntimeError("No job_id returned by /generate")

    print(_pretty({
        "job_id": job_id,
        "status": queued.get("status"),
        "message": queued.get("message"),
        "workflow_engine": ((queued.get("workflow_overview") or {}).get("engine")),
        "delivery_mode": delivery_mode,
        "output_mode": output_mode,
    }))

    if not args.wait:
        return 0

    final_status = _poll_until_done(
        api=args.api,
        job_id=job_id,
        interval=args.interval,
        timeout_sec=args.wait_timeout,
        req_timeout=args.timeout,
        show_agent_graph=bool(getattr(args, "agent_graph", False)),
        show_trace_blocks=bool(getattr(args, "trace_blocks", True)),
    )

    status = final_status.get("status")
    result = final_status.get("result") or {}
    review = final_status.get("review") or {}
    model = (final_status.get("model_verification") or {}).get("selected_model")

    summary = {
        "job_id": job_id,
        "status": status,
        "selected_model": model,
        "qa_average": review.get("overall_average"),
        "retry_decision": review.get("final_decision") or review.get("retry_decision"),
        "decision_reason": review.get("decision_reason"),
        "output_mode": output_mode,
        "delivery_mode": delivery_mode,
    }
    if _should_include_video(output_mode):
        summary["video_url"] = result.get("video_url")
    if _should_include_json(output_mode):
        summary["script_url"] = _api_url(args.api, f"/outputs/{job_id}/script.json")
    print(_pretty(summary))

    if bool(getattr(args, "agent_graph", False)) or bool(getattr(args, "trace_blocks", True)):
        for line in _render_agent_trace_summary(final_status):
            print(line)

    return 0 if status == "done" else 1


def cmd_local_generate(args: argparse.Namespace) -> int:
    from backend.main import JOBS, _append_runtime_log, _run_pipeline
    from backend.models import GenerateRequest
    from backend.utils import generate_job_id
    from backend.workflow import build_agent_state, build_workflow_map

    job_id = args.job_id or generate_job_id()
    JOBS[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Job queued...",
        "result": None,
        "review": None,
        "model_verification": None,
        "agents": build_agent_state(),
        "activity_log": [],
        "trace_events": [],
        "runtime_logs": [],
        "last_status_poll_log_ts": 0.0,
        "workflow_overview": build_workflow_map(),
    }
    _append_runtime_log(job_id, f"{time.strftime('%H:%M:%S')} [INFO] main: Local job queued for {args.url}")

    req = GenerateRequest(
        article_url=args.url,
        use_gemini=args.use_gemini,
        max_segments=args.max_segments,
        transition_intensity=args.transition_intensity,
        transition_profile=args.transition_profile,
        delivery_mode=args.delivery_mode,
    )

    print(_pretty({
        "mode": "local",
        "job_id": job_id,
        "status": "pending",
        "message": "Starting in-process pipeline run",
    }))

    watch = bool(getattr(args, "watch", True))
    interval = max(0.3, float(getattr(args, "interval", 1.5)))
    animate = bool(getattr(args, "animate", True)) and watch
    stream_runtime_logs = bool(getattr(args, "stream_runtime_logs", False))
    show_agent_graph = bool(getattr(args, "agent_graph", True))
    show_trace_blocks = bool(getattr(args, "trace_blocks", True)) and watch
    detached_handlers = _mute_stream_handlers_for_runtime_streaming(stream_runtime_logs)

    try:
        if watch:
            runner_error: Dict[str, Any] = {}

            def _run_in_thread() -> None:
                try:
                    asyncio.run(_run_pipeline(job_id, req))
                except Exception as exc:  # pragma: no cover - defensive surfacing to caller
                    runner_error["error"] = exc

            worker = threading.Thread(target=_run_in_thread, daemon=True)
            worker.start()

            last_state: tuple[str, int, str] | None = None
            last_runtime_log_index = 0
            last_agent_signature: tuple | None = None
            last_focus_signature: tuple | None = None
            last_trace_block_signature: tuple | None = None
            spinner_tick = 0
            idle_ticks = 0

            if show_agent_graph:
                print("Agent Graph Legend: pending=○ running=▶ done=● failed=✖")

            while worker.is_alive():
                payload = JOBS.get(job_id, {})
                status = str(payload.get("status") or "pending")
                progress = int(payload.get("progress") or 0)
                message = str(payload.get("message") or "")
                state = (status, progress, message)
                if state != last_state:
                    print(_format_live_line(status, progress, message))
                    last_state = state
                    idle_ticks = 0
                else:
                    idle_ticks += 1

                focus_signature = _agent_focus_signature(payload)
                if focus_signature != last_focus_signature:
                    for line in _render_agent_focus_lines(payload):
                        print(line)
                    last_focus_signature = focus_signature
                elif animate and idle_ticks > 0 and idle_ticks % 2 == 0:
                    print(_format_heartbeat_line(payload, spinner_tick))

                if show_trace_blocks:
                    trace_block_signature = _agent_trace_block_signature(payload)
                    if trace_block_signature != last_trace_block_signature:
                        for line in _render_agent_trace_block(payload):
                            print(line)
                        last_trace_block_signature = trace_block_signature

                if show_agent_graph:
                    signature = _agent_state_signature(payload)
                    if signature != last_agent_signature:
                        for line in _render_agent_graph_lines(payload):
                            print(line)
                        last_agent_signature = signature

                if stream_runtime_logs:
                    runtime_logs = payload.get("runtime_logs") or []
                    if last_runtime_log_index < len(runtime_logs):
                        for line in runtime_logs[last_runtime_log_index:]:
                            print(_colorize_runtime_log_line(str(line)))
                        last_runtime_log_index = len(runtime_logs)

                time.sleep(interval)
                spinner_tick += 1

            worker.join()
            if runner_error.get("error"):
                raise runner_error["error"]

            payload = JOBS.get(job_id, {})
            status = str(payload.get("status") or "failed")
            progress = int(payload.get("progress") or 0)
            message = str(payload.get("message") or "")
            state = (status, progress, message)
            if state != last_state:
                print(_format_live_line(status, progress, message))
        else:
            asyncio.run(_run_pipeline(job_id, req))
    finally:
        _restore_stream_handlers(detached_handlers)

    payload = JOBS.get(job_id, {})
    status = payload.get("status", "failed")
    result = payload.get("result") or {}
    review = payload.get("review") or {}
    runtime_logs = payload.get("runtime_logs") or []
    output_mode = str(getattr(args, "output", "both") or "both")
    artifacts = _resolve_local_artifacts(job_id, result)
    script_file = artifacts["script_file"]
    video_file = artifacts["video_file"]
    output_dir = artifacts["output_dir"]

    summary = {
        "mode": "local",
        "job_id": job_id,
        "status": status,
        "selected_model": ((payload.get("model_verification") or {}).get("selected_model")),
        "qa_average": review.get("overall_average"),
        "retry_decision": review.get("final_decision") or review.get("retry_decision"),
        "decision_reason": review.get("decision_reason"),
        "retry_rounds": review.get("retry_rounds"),
        "delivery_mode": args.delivery_mode,
        "output_mode": output_mode,
        "runtime_log_lines": len(runtime_logs),
        "output_dir": str(output_dir.resolve()),
    }
    if _should_include_video(output_mode):
        summary["video_url"] = result.get("video_url")
        summary["video_path"] = str(video_file)
        summary["video_abs_path"] = str(video_file.resolve())
        summary["video_exists"] = bool(video_file.exists())
    if _should_include_json(output_mode):
        summary["script_path"] = str(script_file)
        summary["script_abs_path"] = str(script_file.resolve())
        summary["script_exists"] = bool(script_file.exists())
    print(_pretty(summary))

    if status == "done":
        print("\nDelivered artifacts:")
        if _should_include_json(output_mode):
            marker = "OK" if script_file.exists() else "MISSING"
            print(_format_artifact_line("script", script_file, script_file.exists()))
            show_script_preview = bool(getattr(args, "script_preview", True))
            print_script_json = bool(getattr(args, "print_script_json", False))
            preview_segments = max(1, int(getattr(args, "script_preview_segments", 3) or 3))

            if script_file.exists() and show_script_preview:
                snapshot = _read_script_preview(script_file, max_segments=preview_segments)
                if snapshot:
                    headline = snapshot.get("headline") or "(untitled)"
                    segment_count = int(snapshot.get("segment_count") or 0)
                    article_words = int(snapshot.get("article_words") or 0)
                    print("   Script snapshot:")
                    print(f"    - headline: {headline}")
                    print(f"    - segments: {segment_count}")
                    if article_words > 0:
                        print(f"    - source words: {article_words}")
                    for segment in snapshot.get("segment_preview") or []:
                        if not isinstance(segment, dict):
                            continue
                        seg_idx = int(segment.get("index") or 0)
                        seg_type = str(segment.get("type") or "body")
                        seg_head = str(segment.get("headline") or "").strip() or "(no headline)"
                        seg_sub = str(segment.get("subheadline") or "").strip()
                        seg_narr = str(segment.get("narration") or "").strip()
                        print(f"    - S{seg_idx} [{seg_type}] {seg_head}")
                        if seg_sub:
                            print(f"      sub: {seg_sub}")
                        if seg_narr:
                            print(f"      narr: {seg_narr}")
            if script_file.exists() and print_script_json:
                try:
                    with script_file.open("r", encoding="utf-8") as handle:
                        print("\n--- script.json ---")
                        print(handle.read())
                except Exception as exc:
                    print(f"Could not print full script JSON: {exc}")
        if _should_include_video(output_mode):
            marker = "OK" if video_file.exists() else "MISSING"
            print(_format_artifact_line("video", video_file, video_file.exists()))

    if show_agent_graph or show_trace_blocks:
        for line in _render_agent_trace_summary(payload):
            print(line)

    if args.show_runtime_logs and runtime_logs:
        if stream_runtime_logs:
            print("\n--- runtime logs already streamed live; skipping replay ---")
        else:
            print("\n--- runtime logs ---")
            for line in runtime_logs:
                print(_colorize_runtime_log_line(str(line)))

    return 0 if status == "done" else 1


def cmd_wizard(args: argparse.Namespace) -> int:
    print("Algsoch Interactive Wizard")
    print("Answer the prompts. Press Enter to accept defaults.\n")

    mode_default = str(getattr(args, "mode", "local") or "local")
    max_segments_default = int(getattr(args, "max_segments", 6))
    use_gemini_default = bool(getattr(args, "use_gemini", True))
    transition_intensity_default = str(getattr(args, "transition_intensity", "standard") or "standard")
    transition_profile_default = str(getattr(args, "transition_profile", "auto") or "auto")
    output_default = str(getattr(args, "output", "both") or "both")
    delivery_default = str(getattr(args, "delivery_mode", "full_video") or "full_video")
    api_default = str(getattr(args, "api", DEFAULT_API) or DEFAULT_API)
    timeout_default = int(getattr(args, "timeout", 20))
    wait_timeout_default = int(getattr(args, "wait_timeout", 900))
    interval_default = float(getattr(args, "interval", 2.0))
    watch_default = bool(getattr(args, "watch", True))
    stream_default = bool(getattr(args, "stream_runtime_logs", True))
    animate_default = bool(getattr(args, "animate", True))
    trace_blocks_default = bool(getattr(args, "trace_blocks", True))
    show_logs_default = bool(getattr(args, "show_runtime_logs", False))
    agent_graph_default = bool(getattr(args, "agent_graph", True))
    script_preview_default = bool(getattr(args, "script_preview", True))
    script_preview_segments_default = int(getattr(args, "script_preview_segments", 3) or 3)
    print_script_default = bool(getattr(args, "print_script_json", False))
    quick_default = bool(getattr(args, "quick", True))
    quick_bootstrap = bool(getattr(args, "quick", True))
    if mode_default not in {"api", "local"}:
        mode_default = "local"
    if quick_bootstrap:
        print("Quick mode active: URL + video choice prompts only.")
    last_exit = 0

    while True:
        if quick_bootstrap:
            mode = mode_default
            quick_mode = True
        else:
            mode = _prompt_choice("Run mode", ["api", "local"], mode_default)
            quick_mode = _prompt_bool("Quick flow (URL + video choice only)", quick_default)

        if quick_mode:
            url = _prompt_text("Article URL")
            want_video = _prompt_bool("Need final video output", output_default in {"video", "both"})
            if want_video:
                output_mode = "both"
                delivery_mode = "full_video"
            else:
                output_mode = "json"
                delivery_mode = "editorial_only"
            print(f"Output set to {output_mode}; delivery mode {delivery_mode}.")

            max_segments = max_segments_default
            use_gemini = use_gemini_default
            transition_intensity = transition_intensity_default
            transition_profile = transition_profile_default
        else:
            url = _prompt_text("Article URL")
            max_segments = _prompt_int("Max segments (4-12)", max_segments_default, 4, 12)
            use_gemini = _prompt_bool("Use Gemini editorial refinement", use_gemini_default)
            transition_intensity = _prompt_choice(
                "Transition intensity",
                ["subtle", "standard", "dramatic"],
                transition_intensity_default,
            )
            transition_profile = _prompt_choice(
                "Transition profile",
                ["auto", "general", "crisis", "sports", "politics"],
                transition_profile_default,
            )
            output_mode = _prompt_choice(
                "Output preference",
                ["json", "video", "both"],
                output_default,
            )
            if output_mode == "json":
                delivery_mode = "editorial_only"
                print("Delivery mode set to editorial_only for JSON-only output.")
            else:
                delivery_mode = _prompt_choice(
                    "Delivery mode",
                    ["full_video", "editorial_only"],
                    delivery_default if delivery_default in {"full_video", "editorial_only"} else "full_video",
                )

        if mode == "api":
            if quick_mode:
                api = api_default
                timeout = timeout_default
                wait = True
                poll_interval = interval_default
                wait_timeout = wait_timeout_default
                show_agent_graph = agent_graph_default
                show_trace_blocks = trace_blocks_default
            else:
                api = _prompt_text("Backend API URL", api_default)
                timeout = _prompt_int("HTTP timeout (seconds)", timeout_default, 1, 300)
                wait = _prompt_bool("Wait for completion", True)
                poll_interval = _prompt_float("Polling interval (seconds)", interval_default, 0.5)
                wait_timeout = _prompt_int("Wait timeout (seconds)", wait_timeout_default, 10, 7200)
                show_agent_graph = _prompt_bool("Show live agent graph", agent_graph_default) if wait else False
                show_trace_blocks = _prompt_bool("Show detailed per-agent trace blocks", trace_blocks_default) if wait else False

            run_args = argparse.Namespace(
                api=api,
                timeout=timeout,
                url=url,
                max_segments=max_segments,
                transition_intensity=transition_intensity,
                transition_profile=transition_profile,
                use_gemini=use_gemini,
                delivery_mode=delivery_mode,
                output=output_mode,
                wait=wait,
                interval=poll_interval,
                wait_timeout=wait_timeout,
                agent_graph=show_agent_graph,
                trace_blocks=show_trace_blocks,
            )
            last_exit = cmd_generate(run_args)
        else:
            if quick_mode:
                show_runtime_logs = show_logs_default
                watch = watch_default
                show_agent_graph = agent_graph_default if watch else False
                show_trace_blocks = trace_blocks_default if watch else False
                local_interval = max(0.3, interval_default)
                stream_runtime_logs = stream_default if watch else False
                animate = animate_default if watch else False
                show_script_preview = script_preview_default
                script_preview_segments = script_preview_segments_default
                print_script_json = print_script_default
                custom_job = ""
            else:
                show_runtime_logs = _prompt_bool("Show runtime logs after completion", show_logs_default)
                watch = _prompt_bool("Watch live progress in terminal", watch_default)
                show_agent_graph = _prompt_bool("Show live agent graph", agent_graph_default) if watch else False
                show_trace_blocks = _prompt_bool("Show detailed per-agent trace blocks", trace_blocks_default) if watch else False
                local_interval = max(0.3, interval_default)
                if watch:
                    local_interval = _prompt_float("Live refresh interval (seconds)", local_interval, 0.3)
                stream_runtime_logs = _prompt_bool("Stream runtime logs live", stream_default) if watch else False
                animate = _prompt_bool("Show heartbeat animation", animate_default) if watch else False
                show_script_preview = _prompt_bool("Show script preview at completion", script_preview_default)
                script_preview_segments = script_preview_segments_default
                if show_script_preview:
                    script_preview_segments = _prompt_int("Script preview segments", script_preview_segments_default, 1, 12)
                print_script_json = _prompt_bool("Print full script JSON at completion", print_script_default)
                custom_job = _prompt_text("Custom job ID (optional)", "", allow_blank=True)

            run_args = argparse.Namespace(
                url=url,
                job_id=custom_job,
                max_segments=max_segments,
                transition_intensity=transition_intensity,
                transition_profile=transition_profile,
                use_gemini=use_gemini,
                delivery_mode=delivery_mode,
                output=output_mode,
                show_runtime_logs=show_runtime_logs,
                watch=watch,
                interval=local_interval,
                stream_runtime_logs=stream_runtime_logs,
                animate=animate,
                agent_graph=show_agent_graph,
                trace_blocks=show_trace_blocks,
                script_preview=show_script_preview,
                script_preview_segments=script_preview_segments,
                print_script_json=print_script_json,
            )
            last_exit = cmd_local_generate(run_args)

        run_again = _prompt_bool("Run another article", False)
        if not run_again:
            return last_exit

        mode_default = mode
        quick_default = quick_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Algsoch News CLI")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--api", default=DEFAULT_API, help="Base URL of backend API")
        command_parser.add_argument("--timeout", type=int, default=20, help="HTTP request timeout (seconds)")

    def add_display_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--color",
            choices=["auto", "always", "never"],
            default="auto",
            help="ANSI color mode for terminal output",
        )

    def add_agent_view_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--agent-graph",
            action="store_true",
            default=True,
            help="Show live per-agent workflow graph updates",
        )
        command_parser.add_argument(
            "--no-agent-graph",
            action="store_false",
            dest="agent_graph",
            help="Disable live per-agent workflow graph updates",
        )
        command_parser.add_argument(
            "--trace-blocks",
            action="store_true",
            default=True,
            help="Show detailed per-agent input/work/output/trace blocks",
        )
        command_parser.add_argument(
            "--no-trace-blocks",
            action="store_false",
            dest="trace_blocks",
            help="Disable detailed per-agent trace blocks",
        )

    def add_script_view_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--script-preview",
            action="store_true",
            default=True,
            help="Show structured script preview at completion",
        )
        command_parser.add_argument(
            "--no-script-preview",
            action="store_false",
            dest="script_preview",
            help="Disable script preview at completion",
        )
        command_parser.add_argument(
            "--script-preview-segments",
            type=int,
            default=3,
            help="How many leading segments to print in script preview",
        )
        command_parser.add_argument(
            "--print-script-json",
            action="store_true",
            help="Print full script.json content at completion",
        )

    health = sub.add_parser("health", help="Check backend health")
    add_common_args(health)
    add_display_args(health)
    health.set_defaults(func=cmd_health)

    status = sub.add_parser("status", help="Check status of a job")
    add_common_args(status)
    add_display_args(status)
    status.add_argument("--job-id", required=True, help="Job ID returned by /generate")
    status.add_argument("--raw", action="store_true", help="Print full status payload")
    status.set_defaults(func=cmd_status)

    generate = sub.add_parser("generate", help="Submit article URL and optionally wait")
    add_common_args(generate)
    add_display_args(generate)
    add_agent_view_args(generate)
    generate.add_argument("--url", required=True, help="Public article URL")
    generate.add_argument("--max-segments", type=int, default=6, help="Max segments (4 to 12)")
    generate.add_argument(
        "--transition-intensity",
        choices=["subtle", "standard", "dramatic"],
        default="standard",
        help="Transition pacing intensity",
    )
    generate.add_argument(
        "--transition-profile",
        choices=["auto", "general", "crisis", "sports", "politics"],
        default="auto",
        help="Transition grammar profile",
    )
    generate.add_argument(
        "--delivery-mode",
        choices=["full_video", "editorial_only"],
        default="full_video",
        help="Output delivery mode",
    )
    generate.add_argument(
        "--output",
        choices=["json", "video", "both"],
        default="both",
        help="Which artifact links to print in completion summary",
    )
    generate.add_argument("--use-gemini", action="store_true", default=True, help="Enable Gemini refinement")
    generate.add_argument("--no-gemini", action="store_false", dest="use_gemini", help="Disable Gemini")
    generate.add_argument("--wait", action="store_true", help="Poll until completion")
    generate.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    generate.add_argument("--wait-timeout", type=int, default=900, help="Max wait time in seconds")
    generate.set_defaults(func=cmd_generate)

    local_generate = sub.add_parser(
        "local-generate",
        help="Run pipeline locally in-process (no API server required)",
    )
    add_display_args(local_generate)
    add_agent_view_args(local_generate)
    add_script_view_args(local_generate)
    local_generate.add_argument("--url", required=True, help="Public article URL")
    local_generate.add_argument("--job-id", default="", help="Optional explicit job ID")
    local_generate.add_argument("--max-segments", type=int, default=6, help="Max segments (4 to 12)")
    local_generate.add_argument(
        "--transition-intensity",
        choices=["subtle", "standard", "dramatic"],
        default="standard",
        help="Transition pacing intensity",
    )
    local_generate.add_argument(
        "--transition-profile",
        choices=["auto", "general", "crisis", "sports", "politics"],
        default="auto",
        help="Transition grammar profile",
    )
    local_generate.add_argument(
        "--delivery-mode",
        choices=["full_video", "editorial_only"],
        default="full_video",
        help="Output delivery mode",
    )
    local_generate.add_argument(
        "--output",
        choices=["json", "video", "both"],
        default="both",
        help="Which artifact paths to print in completion summary",
    )
    local_generate.add_argument("--use-gemini", action="store_true", default=True, help="Enable Gemini refinement")
    local_generate.add_argument("--no-gemini", action="store_false", dest="use_gemini", help="Disable Gemini")
    local_generate.add_argument(
        "--show-runtime-logs",
        action="store_true",
        help="Print captured runtime logs after completion",
    )
    local_generate.add_argument(
        "--watch",
        action="store_true",
        default=True,
        help="Show live progress updates in terminal while local run is executing",
    )
    local_generate.add_argument(
        "--no-watch",
        action="store_false",
        dest="watch",
        help="Disable live progress watch for local run",
    )
    local_generate.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="Live progress polling interval in seconds for local run",
    )
    local_generate.add_argument(
        "--stream-runtime-logs",
        action="store_true",
        default=True,
        help="Stream runtime log lines during local run",
    )
    local_generate.add_argument(
        "--no-stream-runtime-logs",
        action="store_false",
        dest="stream_runtime_logs",
        help="Disable live runtime log streaming",
    )
    local_generate.add_argument(
        "--animate",
        action="store_true",
        default=True,
        help="Show heartbeat animation lines while agents are working",
    )
    local_generate.add_argument(
        "--no-animate",
        action="store_false",
        dest="animate",
        help="Disable heartbeat animation lines",
    )
    local_generate.set_defaults(func=cmd_local_generate)

    wizard = sub.add_parser("wizard", help="Interactive prompt flow for generation")
    add_display_args(wizard)
    add_agent_view_args(wizard)
    add_script_view_args(wizard)
    wizard.add_argument("--mode", choices=["api", "local"], default="local", help="Default run mode in prompt")
    wizard.add_argument("--api", default=DEFAULT_API, help="Default API base URL in prompt mode")
    wizard.add_argument("--timeout", type=int, default=20, help="Default HTTP timeout")
    wizard.add_argument("--max-segments", type=int, default=6, help="Default max segment value")
    wizard.add_argument(
        "--transition-intensity",
        choices=["subtle", "standard", "dramatic"],
        default="standard",
        help="Default transition intensity",
    )
    wizard.add_argument(
        "--transition-profile",
        choices=["auto", "general", "crisis", "sports", "politics"],
        default="auto",
        help="Default transition profile",
    )
    wizard.add_argument("--use-gemini", action="store_true", default=True, help="Default Gemini setting")
    wizard.add_argument("--no-gemini", action="store_false", dest="use_gemini", help="Default Gemini setting")
    wizard.add_argument(
        "--delivery-mode",
        choices=["full_video", "editorial_only"],
        default="full_video",
        help="Default delivery mode in prompt mode",
    )
    wizard.add_argument(
        "--output",
        choices=["json", "video", "both"],
        default="both",
        help="Default output preference in prompt mode",
    )
    wizard.add_argument("--interval", type=float, default=2.0, help="Default polling interval for API mode")
    wizard.add_argument("--wait-timeout", type=int, default=900, help="Default wait timeout for API mode")
    wizard.add_argument("--show-runtime-logs", action="store_true", help="Default runtime log display for local mode")
    wizard.add_argument("--watch", action="store_true", default=True, help="Default live progress watch for local mode")
    wizard.add_argument("--no-watch", action="store_false", dest="watch", help="Disable live progress watch by default")
    wizard.add_argument("--stream-runtime-logs", action="store_true", default=True, help="Default runtime log streaming for local mode")
    wizard.add_argument("--no-stream-runtime-logs", action="store_false", dest="stream_runtime_logs", help="Disable runtime log streaming by default")
    wizard.add_argument("--animate", action="store_true", default=True, help="Enable heartbeat animation in local watch mode")
    wizard.add_argument("--no-animate", action="store_false", dest="animate", help="Disable heartbeat animation by default")
    wizard.add_argument("--quick", action="store_true", default=True, help="Default to quick two-input flow (URL + video choice)")
    wizard.add_argument("--no-quick", action="store_false", dest="quick", help="Default to full detailed prompt flow")
    wizard.set_defaults(func=cmd_wizard)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["wizard"]

    parser = build_parser()
    args = parser.parse_args(argv)
    _set_color_mode(str(getattr(args, "color", "auto") or "auto"))
    try:
        return args.func(args)
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
