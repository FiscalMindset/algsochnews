"""
cli.py - Command-line client for Algsoch News backend API.

Usage examples:
  python -m backend.cli health
  python -m backend.cli generate --url https://example.com/story --use-gemini --wait
  python -m backend.cli status --job-id abc123
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any, Dict

import requests

DEFAULT_API = "http://127.0.0.1:8000"


def _api_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    return f"{base}{path}"


def _pretty(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


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


def _poll_until_done(api: str, job_id: str, interval: float, timeout_sec: int, req_timeout: int) -> Dict[str, Any]:
    start = time.time()
    while True:
        status_url = _api_url(api, f"/status/{job_id}")
        response = requests.get(status_url, timeout=req_timeout)
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status")
        progress = payload.get("progress", 0)
        message = payload.get("message", "")
        print(f"[{time.strftime('%H:%M:%S')}] {status} {progress}% - {message}")

        if status in {"done", "failed"}:
            return payload

        if time.time() - start > timeout_sec:
            raise TimeoutError(f"Timed out waiting for job {job_id} after {timeout_sec} seconds")

        time.sleep(interval)


def cmd_generate(args: argparse.Namespace) -> int:
    generate_url = _api_url(args.api, "/generate")
    payload = {
        "article_url": args.url,
        "use_gemini": args.use_gemini,
        "max_segments": args.max_segments,
        "transition_intensity": args.transition_intensity,
        "transition_profile": args.transition_profile,
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
    }))

    if not args.wait:
        return 0

    final_status = _poll_until_done(
        api=args.api,
        job_id=job_id,
        interval=args.interval,
        timeout_sec=args.wait_timeout,
        req_timeout=args.timeout,
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
        "retry_decision": review.get("retry_decision"),
        "video_url": result.get("video_url"),
        "script_url": _api_url(args.api, f"/outputs/{job_id}/script.json"),
    }
    print(_pretty(summary))

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
    )

    print(_pretty({
        "mode": "local",
        "job_id": job_id,
        "status": "pending",
        "message": "Starting in-process pipeline run",
    }))

    asyncio.run(_run_pipeline(job_id, req))

    payload = JOBS.get(job_id, {})
    status = payload.get("status", "failed")
    result = payload.get("result") or {}
    review = payload.get("review") or {}
    runtime_logs = payload.get("runtime_logs") or []

    summary = {
        "mode": "local",
        "job_id": job_id,
        "status": status,
        "selected_model": ((payload.get("model_verification") or {}).get("selected_model")),
        "qa_average": review.get("overall_average"),
        "retry_decision": review.get("retry_decision"),
        "retry_rounds": review.get("retry_rounds"),
        "video_url": result.get("video_url"),
        "video_path": result.get("video_path"),
        "script_path": f"outputs/{job_id}/script.json",
        "runtime_log_lines": len(runtime_logs),
    }
    print(_pretty(summary))

    if args.show_runtime_logs and runtime_logs:
        print("\n--- runtime logs ---")
        for line in runtime_logs:
            print(line)

    return 0 if status == "done" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Algsoch News CLI")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--api", default=DEFAULT_API, help="Base URL of backend API")
        command_parser.add_argument("--timeout", type=int, default=20, help="HTTP request timeout (seconds)")

    health = sub.add_parser("health", help="Check backend health")
    add_common_args(health)
    health.set_defaults(func=cmd_health)

    status = sub.add_parser("status", help="Check status of a job")
    add_common_args(status)
    status.add_argument("--job-id", required=True, help="Job ID returned by /generate")
    status.add_argument("--raw", action="store_true", help="Print full status payload")
    status.set_defaults(func=cmd_status)

    generate = sub.add_parser("generate", help="Submit article URL and optionally wait")
    add_common_args(generate)
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
    local_generate.add_argument("--use-gemini", action="store_true", default=True, help="Enable Gemini refinement")
    local_generate.add_argument("--no-gemini", action="store_false", dest="use_gemini", help="Disable Gemini")
    local_generate.add_argument(
        "--show-runtime-logs",
        action="store_true",
        help="Print captured runtime logs after completion",
    )
    local_generate.set_defaults(func=cmd_local_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
