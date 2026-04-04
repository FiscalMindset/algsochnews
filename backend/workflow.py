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
                "branch": None,
                "updated_at": now,
            }
        )
    return agents


def build_workflow_map() -> dict:
    return {
        "sequential_path": [
            "Article Extraction Agent",
            "News Editor Agent",
            "Visual Packaging Agent",
            "QA / Evaluation Agent",
        ],
        "parallel_stage": {
            "label": "Packaging fan-out",
            "tasks": [
                "Headline + subheadline generation",
                "Visual planning + layout routing",
            ],
        },
        "conditional_edges": [
            "qa_pass -> finalize",
            "qa_retry_editor -> editor",
            "qa_retry_packaging -> packaging",
        ],
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
    agent["updated_at"] = now


def append_agent_output(
    job: dict,
    agent_key: str,
    label: str,
    value: Any,
    kind: str = "text",
) -> None:
    agent = find_agent(job, agent_key)
    outputs = agent.setdefault("outputs", [])
    outputs.append({"label": label, "value": value, "kind": kind})
    if len(outputs) > 12:
        del outputs[:-12]
    agent["updated_at"] = time.time()


def snapshot_agents(job: dict) -> List[dict]:
    return deepcopy(job.get("agents", []))

