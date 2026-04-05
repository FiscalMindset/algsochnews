"""
observability.py - Internal trace events plus optional LangFuse forwarding.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from backend.utils import get_logger

log = get_logger("observability")


class TraceBridge:
    """
    Capture workflow events to a local in-memory trace and optionally mirror
    them to LangFuse if credentials are present.
    """

    def __init__(self, job_id: str, article_url: str):
        self.job_id = job_id
        self.article_url = article_url
        self.enabled = False
        self.trace = None
        self.client = None

        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()

        if not (public_key and secret_key):
            return

        try:
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            trace_factory = getattr(self.client, "trace", None)
            if not callable(trace_factory):
                raise RuntimeError("Langfuse client does not expose trace()")
            self.trace = trace_factory(
                id=job_id,
                name="algsoch-newsroom-run",
                input={"article_url": article_url},
                metadata={"app": "Algsoch News"},
            )
            self.enabled = True
            log.info("LangFuse tracing is enabled for this run.")
        except Exception as exc:
            log.warning(f"LangFuse initialization failed, using local trace only: {exc}")
            self.enabled = False

    def capture(self, event: Dict[str, Any]) -> None:
        if not self.enabled or not self.trace:
            return
        try:
            event_fn = getattr(self.trace, "event", None)
            if not callable(event_fn):
                return
            event_fn(
                name=event.get("event_type", "agent_event"),
                input=event.get("input_payload"),
                output=event.get("output_payload"),
                metadata={
                    "agent_key": event.get("agent_key"),
                    "agent_name": event.get("agent_name"),
                    "message": event.get("message"),
                    "decision": event.get("decision"),
                    "route_to": event.get("route_to"),
                    "metrics": event.get("metrics", {}),
                    "tools": event.get("tools", []),
                },
            )
        except Exception as exc:
            log.warning(f"LangFuse event capture failed: {exc}")

    def finalize(self, output: Dict[str, Any]) -> None:
        if not self.enabled or not self.trace:
            return
        try:
            update_fn = getattr(self.trace, "update", None)
            if callable(update_fn):
                update_fn(output=output)
            if self.client:
                self.client.flush()
        except Exception as exc:
            log.warning(f"LangFuse finalize failed: {exc}")
