"""
workflow.py — Lightweight workflow state helpers for the broadcast pipeline.
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional


AGENT_BLUEPRINTS = [
    {
        "key": "extraction",
        "name": "Article Extraction Agent",
        "role": "Fetches, cleans, and ranks article extraction candidates.",
    },
    {
        "key": "editor",
        "name": "News Editor Agent",
        "role": "Builds story beats and anchor-ready narration.",
    },
    {
        "key": "packaging",
        "name": "Visual Packaging Agent",
        "role": "Creates segment headlines, subheadlines, layouts, visuals, and transitions.",
    },
    {
        "key": "review",
        "name": "QA / Evaluation Agent",
        "role": "Scores the package, decides retries, and validates the final handoff.",
    },
    {
        "key": "video_generation",
        "name": "Video Generation Agent",
        "role": "Synthesizes audio, aligns transcript cues, and renders the final MP4 output.",
    },
    {
        "key": "render_review",
        "name": "Render QA Agent",
        "role": "Reviews rendered media quality, caption coverage, and runtime fidelity before finalize.",
    },
]


def build_agent_state() -> List[dict]:
    agents = []
    now = time.time()
    for blueprint in AGENT_BLUEPRINTS:
        agents.append(
            {
                **blueprint,
                "status": "pending",
                "progress": 0,
                "summary": "",
                "retry_count": 0,
                "started_at": None,
                "finished_at": None,
                "outputs": [],
                "metrics": {},
                "current_input": None,
                "tools_used": [],
                "decisions": [],
                "event_count": 0,
                "node_visits": 0,
                "llm_model": None,
                "branch": None,
                "updated_at": now,
            }
        )
    return agents


def build_workflow_map() -> dict:
    return {
        "engine": "langgraph",
        "sequential_path": [
            "Article Extraction Agent",
            "News Editor Agent",
            "Visual Packaging Agent",
            "QA / Evaluation Agent",
            "Video Generation Agent",
            "Render QA Agent",
        ],
        "parallel_stage": {
            "label": "Packaging fan-out",
            "tasks": [
                "Headline + subheadline generation",
                "Visual blueprint + layout routing",
            ],
        },
        "conditional_edges": [
            "qa_pass -> video_generation",
            "qa_retry_editor -> editor",
            "qa_retry_packaging -> packaging",
            "qa_retry_editor_and_packaging -> editor+packaging",
            "video_generation -> render_review",
            "render_review -> finalize",
        ],
        "retry_policy": {
            "targeted": True,
            "max_retry_rounds": None,
        },
    }


def find_agent(job: dict, agent_key: str) -> dict:
    for agent in job.setdefault("agents", build_agent_state()):
        if agent["key"] == agent_key:
            return agent
    raise KeyError(f"Unknown agent key: {agent_key}")


def record_activity(job: dict, message: str, agent_key: Optional[str] = None) -> None:
    activity = job.setdefault("activity_log", [])
    timestamp = time.strftime("%H:%M:%S")
    if agent_key:
        agent = find_agent(job, agent_key)
        activity.append(f"{timestamp} · {agent['name']}: {message}")
    else:
        activity.append(f"{timestamp} · {message}")
    if len(activity) > 40:
        del activity[:-40]


def set_agent_state(
    job: dict,
    agent_key: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    summary: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    branch: Optional[str] = None,
    retry_increment: bool = False,
) -> None:
    agent = find_agent(job, agent_key)
    now = time.time()
    if status:
        agent["status"] = status
        if status == "running" and not agent["started_at"]:
            agent["started_at"] = now
        if status in {"done", "failed"}:
            agent["finished_at"] = now
    if progress is not None:
        agent["progress"] = progress
    if summary is not None:
        agent["summary"] = summary
    if metrics:
        agent.setdefault("metrics", {}).update(metrics)
    if branch is not None:
        agent["branch"] = branch
    if retry_increment:
        agent["retry_count"] += 1
    if status == "running":
        agent["node_visits"] = agent.get("node_visits", 0) + 1
    agent["updated_at"] = now


def set_agent_input(job: dict, agent_key: str, payload: Any) -> None:
    agent = find_agent(job, agent_key)
    agent["current_input"] = payload
    agent["updated_at"] = time.time()


def set_agent_tools(job: dict, agent_key: str, tools: List[str]) -> None:
    agent = find_agent(job, agent_key)
    existing = set(agent.get("tools_used", []))
    merged = list(existing.union(set(tools)))
    merged.sort()
    agent["tools_used"] = merged
    agent["updated_at"] = time.time()


def set_agent_model(job: dict, agent_key: str, model_name: str) -> None:
    if not model_name:
        return
    agent = find_agent(job, agent_key)
    agent["llm_model"] = model_name
    agent["updated_at"] = time.time()


def append_agent_output(
    job: dict,
    agent_key: str,
    label: str,
    value: Any,
    kind: str = "text",
    artifact_type: str = "output",
) -> None:
    agent = find_agent(job, agent_key)
    outputs = agent.setdefault("outputs", [])
    outputs.append(
        {
            "label": label,
            "value": value,
            "kind": kind,
            "artifact_type": artifact_type,
            "timestamp": time.time(),
        }
    )
    if len(outputs) > 12:
        del outputs[:-12]
    agent["updated_at"] = time.time()


def record_agent_decision(
    job: dict,
    agent_key: str,
    decision: str,
    *,
    reason: str = "",
    route_to: Optional[str] = None,
) -> None:
    agent = find_agent(job, agent_key)
    message = decision if not reason else f"{decision}: {reason}"
    decisions = agent.setdefault("decisions", [])
    decisions.append(message)
    if len(decisions) > 8:
        del decisions[:-8]
    append_agent_output(
        job,
        agent_key,
        label="Decision",
        value={"decision": decision, "reason": reason, "route_to": route_to},
        kind="json",
        artifact_type="decision",
    )
    record_activity(job, message, agent_key=agent_key)
    agent["updated_at"] = time.time()


def record_trace_event(
    job: dict,
    agent_key: str,
    event_type: str,
    message: str,
    *,
    input_payload: Any = None,
    tools: Optional[List[str]] = None,
    output_payload: Any = None,
    decision: Optional[str] = None,
    route_to: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    agent = find_agent(job, agent_key)
    event = {
        "ts": time.time(),
        "agent_key": agent_key,
        "agent_name": agent["name"],
        "event_type": event_type,
        "message": message,
        "input_payload": input_payload,
        "tools": tools or [],
        "output_payload": output_payload,
        "decision": decision,
        "route_to": route_to,
        "metrics": metrics or {},
    }
    events = job.setdefault("trace_events", [])
    events.append(event)
    if len(events) > 400:
        del events[:-400]
    agent["event_count"] = agent.get("event_count", 0) + 1
    if input_payload is not None:
        set_agent_input(job, agent_key, input_payload)
    if tools:
        set_agent_tools(job, agent_key, tools)
    if output_payload is not None:
        append_agent_output(job, agent_key, "Event Output", output_payload, kind="json", artifact_type="output")
    if decision:
        record_agent_decision(job, agent_key, decision, route_to=route_to)
    record_activity(job, message, agent_key=agent_key)

    trace_bridge = job.get("_trace_bridge")
    if trace_bridge:
        try:
            trace_bridge.capture(event)
        except Exception:
            pass


def snapshot_agents(job: dict) -> List[dict]:
    return deepcopy(job.get("agents", []))


def snapshot_trace_events(job: dict) -> List[dict]:
    return deepcopy(job.get("trace_events", []))

