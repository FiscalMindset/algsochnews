"""
main.py - FastAPI application for Algsoch News.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import aiofiles
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.broadcast import build_rundown
from backend.gemini_router import verify_and_select_model
from backend.langgraph_pipeline import run_graph_pipeline
from backend.models import (
    ArticleData,
    GenerateRequest,
    GenerateResponse,
    JobStatusResponse,
    ModelVerification,
    RundownCue,
    Script,
    Segment,
    TraceEvent,
    TranscriptCue,
    AgentTrace,
    RenderQualityReview,
)
from backend.observability import TraceBridge
from backend.render_review import evaluate_render_quality
from backend.transcript_alignment import TranscriptAligner, attach_transcript_to_segments
from backend.tts import synthesize_all
from backend.utils import config, generate_job_id, get_logger
from backend.video_renderer import render_video
from backend.workflow import (
    append_agent_output,
    build_agent_state,
    build_workflow_map,
    record_activity,
    record_trace_event,
    set_agent_input,
    set_agent_state,
    set_agent_tools,
    snapshot_agents,
    snapshot_trace_events,
)

log = get_logger("main")

app = FastAPI(
    title="Algsoch News",
    description="LangGraph-powered multi-agent newsroom for URL to broadcast package generation.",
    version="3.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


def _cors_origins(raw: str) -> List[str]:
    values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    return values or ["*"]


cors_origins = _cors_origins(config.CORS_ALLOWED_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=not (len(cors_origins) == 1 and cors_origins[0] == "*"),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")

JOBS: Dict[str, dict] = {}
RUNTIME_LOG_LIMIT = 4000
STATUS_POLL_LOG_INTERVAL_SEC = 1.2


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _timeline_for_agent(trace_events: List[dict], agent_key: str) -> List[dict]:
    events = sorted(
        [event for event in trace_events if event.get("agent_key") == agent_key],
        key=lambda item: float(item.get("ts") or 0.0),
    )
    rows: List[dict] = []
    previous_ts: float | None = None
    for index, event in enumerate(events, start=1):
        ts_value = event.get("ts")
        current_ts = float(ts_value) if isinstance(ts_value, (int, float)) else None
        delta = None
        if current_ts is not None and previous_ts is not None:
            delta = round(max(0.0, current_ts - previous_ts), 3)
        rows.append(
            {
                "step": index,
                "ts": current_ts,
                "delta_seconds_from_previous": delta,
                "event_type": event.get("event_type", ""),
                "message": event.get("message", ""),
                "tools": event.get("tools", []),
                "decision": event.get("decision"),
                "route_to": event.get("route_to"),
                "input_payload": event.get("input_payload"),
                "output_payload": event.get("output_payload"),
                "metrics": event.get("metrics", {}),
            }
        )
        if current_ts is not None:
            previous_ts = current_ts
    return rows


def _build_all_agents_audit_payload(
    job: dict,
    review_payload: dict | None,
    workflow_overview: dict,
    model_verification_payload: dict | None,
) -> dict:
    agents = snapshot_agents(job)
    trace_events = snapshot_trace_events(job)
    payload_agents = []
    for agent in agents:
        payload_agents.append(
            {
                "key": agent.get("key"),
                "name": agent.get("name"),
                "role": agent.get("role"),
                "status": agent.get("status"),
                "progress": int(agent.get("progress") or 0),
                "llm_model": agent.get("llm_model"),
                "retry_count": int(agent.get("retry_count") or 0),
                "node_visits": int(agent.get("node_visits") or 0),
                "event_count": int(agent.get("event_count") or 0),
                "started_at": agent.get("started_at"),
                "finished_at": agent.get("finished_at"),
                "summary": agent.get("summary", ""),
                "branch": agent.get("branch"),
                "current_input": agent.get("current_input"),
                "tools_used": agent.get("tools_used", []),
                "decisions": agent.get("decisions", []),
                "metrics": agent.get("metrics", {}),
                "outputs": agent.get("outputs", []),
                "timeline": _timeline_for_agent(trace_events, str(agent.get("key") or "")),
            }
        )

    return {
        "generated_at": _now_iso(),
        "workflow_overview": workflow_overview or {},
        "model_verification": model_verification_payload or None,
        "review": review_payload or None,
        "agent_count": len(payload_agents),
        "agents": payload_agents,
    }


def _compliance_check(key: str, label: str, passed: bool, detail: str) -> dict:
    return {
        "key": key,
        "label": label,
        "passed": bool(passed),
        "status": "pass" if passed else "fail",
        "detail": detail,
    }


def _build_compliance_report(
    workflow_overview: dict,
    review_payload: dict | None,
    packaged_segments: List[dict],
    route_history: List[str],
    video_ready: bool,
) -> dict:
    sequential_path = workflow_overview.get("sequential_path", []) or []
    parallel_stage = workflow_overview.get("parallel_stage") or {}
    conditional_edges = workflow_overview.get("conditional_edges", []) or []

    runtime_sec = float(packaged_segments[-1].get("end_time", 0.0)) if packaged_segments else 0.0
    duration_ok = 60 <= runtime_sec <= 120

    headlines = [str(seg.get("main_headline", "")).strip().lower() for seg in packaged_segments if seg.get("main_headline")]
    unique_headline_ratio = round(len(set(headlines)) / max(len(headlines), 1), 3)
    headline_ok = unique_headline_ratio >= 0.75

    visual_covered = sum(
        1
        for seg in packaged_segments
        if seg.get("layout") and (seg.get("source_image_url") or seg.get("ai_support_visual_prompt") or seg.get("scene_image_url"))
    )
    visual_coverage_ratio = round(visual_covered / max(len(packaged_segments), 1), 3)
    visual_ok = visual_coverage_ratio >= 0.85

    review_payload = review_payload or {}
    qa_average = float(review_payload.get("overall_average") or 0.0)
    qa_passed = bool(review_payload.get("passed"))
    hard_failures = list(review_payload.get("hard_failures") or [])
    targeted_retry_ok = bool(isinstance(review_payload.get("weak_segments"), list))

    checks = [
        _compliance_check(
            "langgraph_workflow",
            "LangGraph workflow",
            workflow_overview.get("engine") == "langgraph",
            f"engine={workflow_overview.get('engine', 'n/a')}",
        ),
        _compliance_check(
            "sequential_flow",
            "Sequential flow",
            len(sequential_path) >= 4,
            f"steps={len(sequential_path)}",
        ),
        _compliance_check(
            "parallel_step",
            "Parallel step",
            bool(parallel_stage) and len(parallel_stage.get("tasks", []) or []) >= 2,
            f"tasks={(parallel_stage.get('tasks') or [])}",
        ),
        _compliance_check(
            "conditional_edges",
            "Conditional edges",
            len(conditional_edges) >= 3,
            f"edges={len(conditional_edges)}",
        ),
        _compliance_check(
            "targeted_retry",
            "Targeted retry mechanism",
            targeted_retry_ok,
            f"decision={review_payload.get('retry_decision', 'n/a')}; weak_segments={len(review_payload.get('weak_segments') or [])}",
        ),
        _compliance_check(
            "qa_gate",
            "QA gate (avg>=4, no hard failures)",
            qa_passed and qa_average >= 4 and not hard_failures,
            f"avg={qa_average:.2f}; hard_failures={hard_failures}",
        ),
        _compliance_check(
            "duration_fit",
            "Duration 60-120 seconds",
            duration_ok,
            f"runtime={runtime_sec:.1f}s",
        ),
        _compliance_check(
            "headline_variation",
            "Headline variation by segment",
            headline_ok,
            f"unique_ratio={unique_headline_ratio:.2f}",
        ),
        _compliance_check(
            "visual_coverage",
            "Visual coverage across segments",
            visual_ok,
            f"coverage_ratio={visual_coverage_ratio:.2f}",
        ),
        _compliance_check(
            "output_package",
            "Client-ready output package",
            bool(packaged_segments) and video_ready,
            f"segments={len(packaged_segments)}; video_ready={video_ready}",
        ),
    ]

    pass_count = sum(1 for check in checks if check["passed"])
    return {
        "generated_at": _now_iso(),
        "overall_status": "pass" if pass_count == len(checks) else "needs_attention",
        "pass_count": pass_count,
        "total_count": len(checks),
        "checks": checks,
        "qa_average": round(qa_average, 2),
        "runtime_sec": round(runtime_sec, 2),
        "route_history": route_history,
    }


def _write_client_pack(out_dir: Path, job_id: str) -> Path:
    script_path = out_dir / "script.json"
    video_path = out_dir / "final_video.mp4"
    audit_path = out_dir / "all_agents_audit.json"
    compliance_path = out_dir / "compliance_report.json"
    zip_path = out_dir / "client_pack.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if script_path.exists():
            archive.write(script_path, arcname="script.json")
        if video_path.exists():
            archive.write(video_path, arcname="final_video.mp4")
        if audit_path.exists():
            archive.write(audit_path, arcname="all_agents_audit.json")
        if compliance_path.exists():
            archive.write(compliance_path, arcname="compliance_report.json")

        archive.writestr(
            "README.txt",
            (
                f"Algsoch client delivery pack\n"
                f"job_id: {job_id}\n"
                f"generated_at: {_now_iso()}\n"
                f"contents: script.json, final_video.mp4, all_agents_audit.json, compliance_report.json\n"
            ),
        )

    return zip_path


def _append_runtime_log(job_id: str, line: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return

    logs = job.setdefault("runtime_logs", [])
    logs.append(line)
    if len(logs) > RUNTIME_LOG_LIMIT:
        del logs[:-RUNTIME_LOG_LIMIT]


class _RuntimeLogMirrorHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return

        # Mirror runtime logs to all active jobs so the frontend can render
        # a terminal-like stream during orchestration.
        for job_id, job in JOBS.items():
            if job.get("status") in {"pending", "processing"}:
                _append_runtime_log(job_id, line)


def _install_runtime_log_mirror() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, _RuntimeLogMirrorHandler):
            return

    handler = _RuntimeLogMirrorHandler(level=logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)


_install_runtime_log_mirror()


async def _run_pipeline(job_id: str, req: GenerateRequest) -> None:
    job = JOBS[job_id]
    loop = asyncio.get_running_loop()
    start = time.time()

    def update(progress: int, message: str, agent_key: str | None = None) -> None:
        job["progress"] = progress
        job["message"] = message
        if agent_key:
            record_activity(job, message, agent_key=agent_key)
        else:
            record_activity(job, message)
        log.info(f"[{job_id}] {progress}% - {message}")

    try:
        job["status"] = "processing"

        update(3, "Verifying Gemini model availability and initializing orchestration...")
        model_resolution = verify_and_select_model(config.GEMINI_MODEL, config.GEMINI_API_KEY)
        model_verification = ModelVerification(
            configured_model=model_resolution.configured_model,
            selected_model=model_resolution.selected_model,
            available_models=model_resolution.available_models,
            upgraded=model_resolution.upgraded,
            verification_ok=model_resolution.verification_ok,
            note=model_resolution.note,
        )
        job["model_verification"] = model_verification.model_dump()
        llm_enhanced = bool(req.use_gemini and config.USE_GEMINI and bool(config.GEMINI_API_KEY))
        transition_intensity = (req.transition_intensity or "standard").lower()
        transition_profile = (req.transition_profile or "auto").lower()

        trace_bridge = TraceBridge(job_id=job_id, article_url=req.article_url)
        job["_trace_bridge"] = trace_bridge

        workflow_overview = job.get("workflow_overview", {})
        workflow_overview.setdefault("retry_policy", {})["max_retry_rounds"] = config.MAX_RETRIES
        workflow_overview["selected_model"] = model_verification.selected_model
        workflow_overview["model_verification_ok"] = model_verification.verification_ok
        workflow_overview["llm_enhanced"] = llm_enhanced
        workflow_overview["transition_intensity"] = transition_intensity
        workflow_overview["transition_profile"] = transition_profile
        job["workflow_overview"] = workflow_overview

        update(8, f"Model selected: {model_verification.selected_model}. Starting LangGraph execution...", "editor")
        graph_state = await run_graph_pipeline(
            job,
            job_id,
            {
                "article_url": req.article_url,
                "max_segments": int(req.max_segments or 6),
                "use_gemini": bool(req.use_gemini),
                "transition_intensity": transition_intensity,
                "transition_profile": transition_profile,
                "selected_model": model_verification.selected_model,
                "gemini_api_key": config.GEMINI_API_KEY,
                "retry_round": 0,
                "route_history": [],
                "article_raw": {},
                "segments_raw": [],
                "narrations": [],
                "copy_plan": [],
                "overall_headline": "",
                "hydrated_packages": [],
                "source_inventory": [],
                "visual_blueprint": [],
                "visuals": [],
                "packaged_segments": [],
                "review": None,
                "qa_score": 0.0,
                "weak_segments": [],
                "editorial_directives": {},
                "qa_critique": {},
                "transcript_cues": [],
                "rundown": [],
                "screenplay_text": "",
            },
        )

        review = graph_state["review"]
        qa_score = float(graph_state["qa_score"])
        article_raw = graph_state["article_raw"]
        segments_raw = graph_state["segments_raw"]
        narrations = graph_state["narrations"]
        visuals = graph_state["visuals"]
        overall_headline = graph_state["overall_headline"]
        packaged_segments = graph_state["packaged_segments"]
        render_review_payload = None

        target_runtime = segments_raw[-1]["end_time"] if segments_raw else 0
        set_agent_state(
            job,
            "video_generation",
            status="running",
            progress=18,
            summary="Synthesizing audio and preparing final video render.",
        )
        set_agent_tools(
            job,
            "video_generation",
            [
                "tts synthesis",
                "transcript aligner",
                "ffmpeg renderer",
            ],
        )
        set_agent_input(
            job,
            "video_generation",
            {
                "segment_count": len(segments_raw),
                "target_runtime_sec": target_runtime,
            },
        )
        record_trace_event(
            job,
            "video_generation",
            "node_start",
            "Video generation stage started: audio synthesis and final render pipeline.",
            input_payload={
                "segment_count": len(segments_raw),
                "target_runtime_sec": target_runtime,
            },
            tools=["synthesize_all", "TranscriptAligner", "render_video"],
        )

        update(72, "Synthesizing anchor audio...", "video_generation")
        record_trace_event(
            job,
            "video_generation",
            "audio_synthesis_start",
            "Started anchor audio synthesis for all segments.",
            metrics={"segment_count": len(segments_raw)},
        )
        durations = [seg["duration"] for seg in segments_raw]
        audio_paths = await loop.run_in_executor(
            None,
            synthesize_all,
            narrations,
            durations,
            job_id,
        )
        append_agent_output(job, "video_generation", "Audio clips", len(audio_paths), kind="metric")
        record_trace_event(
            job,
            "video_generation",
            "audio_synthesis_complete",
            "Audio synthesis complete.",
            output_payload={"audio_clips": len(audio_paths)},
        )

        aligner = TranscriptAligner(mode="paced")
        transcript_cues = aligner.align(packaged_segments, audio_durations=durations)
        packaged_segments = attach_transcript_to_segments(packaged_segments, transcript_cues)
        rundown = build_rundown(packaged_segments)
        append_agent_output(job, "video_generation", "Transcript cues", len(transcript_cues), kind="metric")
        append_agent_output(job, "packaging", "Transcript cues", len(transcript_cues), kind="metric")
        append_agent_output(job, "packaging", "Rundown items", len(rundown), kind="metric")

        update(86, "Rendering final broadcast video...", "video_generation")
        record_trace_event(
            job,
            "video_generation",
            "video_render_start",
            "Started final FFmpeg render.",
            metrics={"runtime_sec": target_runtime},
        )
        final_video = await loop.run_in_executor(
            None,
            render_video,
            segments_raw,
            visuals,
            narrations,
            audio_paths,
            [seg["main_headline"] for seg in packaged_segments],
            overall_headline,
            job_id,
        )
        job["preview_video_url"] = f"/outputs/{job_id}/final_video.mp4"
        append_agent_output(job, "video_generation", "Final video", f"/outputs/{job_id}/final_video.mp4")
        record_trace_event(
            job,
            "video_generation",
            "video_render_complete",
            "Final FFmpeg render complete.",
            output_payload={"video_url": f"/outputs/{job_id}/final_video.mp4"},
        )
        record_trace_event(
            job,
            "video_generation",
            "node_complete",
            "Video generation completed with synthesized audio and rendered MP4.",
            output_payload={
                "audio_clips": len(audio_paths),
                "transcript_cues": len(transcript_cues),
                "video_url": f"/outputs/{job_id}/final_video.mp4",
                "runtime_sec": target_runtime,
            },
        )
        set_agent_state(
            job,
            "video_generation",
            status="done",
            progress=100,
            summary="Audio, transcript alignment, and final render completed.",
            metrics={
                "audio_clips": len(audio_paths),
                "runtime_sec": round(target_runtime, 2),
            },
        )

        update(92, "Running render QA checks for final media quality...", "render_review")
        set_agent_state(
            job,
            "render_review",
            status="running",
            progress=35,
            summary="Checking runtime fidelity, stream integrity, captions, and narration quality.",
        )
        set_agent_tools(
            job,
            "render_review",
            [
                "ffprobe",
                "render quality rubric",
                "gemini render critique",
            ],
        )
        set_agent_input(
            job,
            "render_review",
            {
                "target_runtime_sec": target_runtime,
                "segment_count": len(packaged_segments),
                "transcript_cues": len(transcript_cues),
            },
        )
        record_trace_event(
            job,
            "render_review",
            "node_start",
            "Started render QA review stage.",
            input_payload={
                "target_runtime_sec": target_runtime,
                "segment_count": len(packaged_segments),
                "transcript_cues": len(transcript_cues),
            },
            tools=["ffprobe", "render quality rubric", "gemini render critique"],
        )

        render_review_payload = await loop.run_in_executor(
            None,
            lambda: evaluate_render_quality(
                video_path=final_video,
                segments=packaged_segments,
                transcript_cues=transcript_cues,
                target_runtime_sec=target_runtime,
                use_gemini=bool(req.use_gemini),
                model_name=model_verification.selected_model,
                api_key=config.GEMINI_API_KEY,
            ),
        )

        append_agent_output(job, "render_review", "Render QA score", render_review_payload.get("overall_score", 0), kind="metric")
        append_agent_output(job, "render_review", "Render QA summary", render_review_payload.get("summary", ""))
        append_agent_output(job, "render_review", "Render QA report", render_review_payload, kind="json")
        record_trace_event(
            job,
            "render_review",
            "node_complete",
            "Render QA review completed.",
            output_payload={
                "overall_score": render_review_payload.get("overall_score"),
                "passed": render_review_payload.get("passed"),
                "verdict": render_review_payload.get("verdict"),
            },
            decision="pass" if render_review_payload.get("passed") else "review",
            route_to="finalize",
        )
        set_agent_state(
            job,
            "render_review",
            status="done",
            progress=100,
            summary=render_review_payload.get("summary", "Render QA completed."),
            metrics={
                "overall_score": render_review_payload.get("overall_score", 0),
                "passed": render_review_payload.get("passed", False),
            },
        )

        update(95, "Saving script JSON and outputs...")
        out_dir = config.OUTPUT_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        final_video_path = Path(final_video)

        review_payload = review.model_dump() if review is not None else None
        workflow_overview = dict(job.get("workflow_overview", {}))
        compliance_report = _build_compliance_report(
            workflow_overview=workflow_overview,
            review_payload=review_payload,
            packaged_segments=packaged_segments,
            route_history=graph_state.get("route_history", []),
            video_ready=final_video_path.exists(),
        )
        workflow_overview["compliance_report"] = compliance_report
        workflow_overview["final_runtime_sec"] = round(float(target_runtime or 0.0), 2)
        workflow_overview["route_history"] = graph_state.get("route_history", [])
        job["workflow_overview"] = workflow_overview

        article_model = ArticleData(
            title=article_raw.get("title", ""),
            text=article_raw.get("text", "")[:2500],
            url=article_raw.get("url", req.article_url),
            top_image=article_raw.get("top_image"),
            images=article_raw.get("images", [])[:12],
            authors=article_raw.get("authors", []),
            published_date=article_raw.get("published_date"),
            source_domain=article_raw.get("source_domain", ""),
            word_count=article_raw.get("word_count", 0),
            extraction_method=article_raw.get("method", "unknown"),
            extraction_score=article_raw.get("extraction_score", 0.0),
            extraction_candidates=article_raw.get("candidates", []),
            extraction_attempts=article_raw.get("extraction_attempts", []),
        )

        script = Script(
            article_url=req.article_url,
            source_title=article_raw.get("title", ""),
            article=article_model,
            segments=[Segment(**segment) for segment in packaged_segments],
            live_transcript=[TranscriptCue(**cue) for cue in transcript_cues],
            rundown=[RundownCue(**item) for item in rundown],
            total_duration=segments_raw[-1]["end_time"] if segments_raw else 0,
            video_duration_sec=int(round(segments_raw[-1]["end_time"])) if segments_raw else 0,
            overall_headline=overall_headline,
            screenplay_text=graph_state["screenplay_text"],
            qa_score=qa_score,
            review=review,
            render_review=(RenderQualityReview(**render_review_payload) if render_review_payload else None),
            workflow_overview=workflow_overview,
            model_verification=model_verification,
            route_history=graph_state.get("route_history", []),
            llm_enhanced=llm_enhanced,
        )

        script_path = out_dir / "script.json"
        async with aiofiles.open(script_path, "w") as handle:
            await handle.write(script.model_dump_json(indent=2))

        audit_payload = _build_all_agents_audit_payload(
            job=job,
            review_payload=review_payload,
            workflow_overview=workflow_overview,
            model_verification_payload=model_verification.model_dump(),
        )
        audit_path = out_dir / "all_agents_audit.json"
        async with aiofiles.open(audit_path, "w") as handle:
            await handle.write(json.dumps(audit_payload, indent=2, default=str))

        compliance_path = out_dir / "compliance_report.json"
        async with aiofiles.open(compliance_path, "w") as handle:
            await handle.write(json.dumps(compliance_report, indent=2, default=str))

        _write_client_pack(out_dir, job_id)

        elapsed = round(time.time() - start, 2)

        result = GenerateResponse(
            success=True,
            job_id=job_id,
            script=script,
            agents=[AgentTrace(**item) for item in snapshot_agents(job)],
            activity_log=job.get("activity_log", []),
            trace_events=[TraceEvent(**item) for item in snapshot_trace_events(job)],
            runtime_logs=job.get("runtime_logs", []),
            model_verification=model_verification,
            video_path=str(final_video_path),
            video_url=f"/outputs/{job_id}/final_video.mp4",
            processing_time=elapsed,
        )

        if trace_bridge:
            trace_bridge.finalize(
                {
                    "job_id": job_id,
                    "qa_score": qa_score,
                    "video_url": f"/outputs/{job_id}/final_video.mp4",
                    "selected_model": model_verification.selected_model,
                }
            )

        job.update(
            {
                "status": "done",
                "progress": 100,
                "message": "Algsoch News package generated successfully.",
                "result": result.model_dump(),
                "review": review_payload,
                "model_verification": model_verification.model_dump(),
            }
        )

    except Exception as exc:
        log.exception(f"[{job_id}] Pipeline failed: {exc}")
        for agent in job.get("agents", []):
            if agent.get("status") != "running":
                continue
            key = agent.get("key")
            if not key:
                continue
            try:
                set_agent_state(
                    job,
                    key,
                    status="failed",
                    summary="Stage aborted due to pipeline failure.",
                )
            except Exception:
                pass
        job.update(
            {
                "status": "failed",
                "progress": 0,
                "message": str(exc),
                "result": GenerateResponse(
                    success=False,
                    job_id=job_id,
                    agents=[AgentTrace(**item) for item in snapshot_agents(job)],
                    activity_log=job.get("activity_log", []),
                    trace_events=[TraceEvent(**item) for item in snapshot_trace_events(job)],
                    runtime_logs=job.get("runtime_logs", []),
                    model_verification=(
                        ModelVerification(**job["model_verification"])
                        if isinstance(job.get("model_verification"), dict)
                        else None
                    ),
                    error=str(exc),
                    processing_time=round(time.time() - start, 2),
                ).model_dump(),
            }
        )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "Algsoch News",
        "version": "3.0.0",
        "configured_model": config.GEMINI_MODEL,
    }


@app.post("/generate", response_model=dict)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    if not req.article_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL - must start with http(s)://")

    job_id = generate_job_id()
    JOBS[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Job queued...",
        "preview_video_url": None,
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
    record_activity(JOBS[job_id], f"Job queued for {req.article_url}")
    _append_runtime_log(
        job_id,
        f"{time.strftime('%H:%M:%S')} [INFO] main: Job queued for {req.article_url}",
    )

    background_tasks.add_task(_run_pipeline, job_id, req)

    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Job queued",
        "agents": JOBS[job_id]["agents"],
        "trace_events": JOBS[job_id]["trace_events"],
        "workflow_overview": JOBS[job_id]["workflow_overview"],
    }


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str, request: Request):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]

    if job.get("status") in {"pending", "processing"}:
        now = time.time()
        last = float(job.get("last_status_poll_log_ts") or 0.0)
        if now - last >= STATUS_POLL_LOG_INTERVAL_SEC:
            host = request.client.host if request.client else "127.0.0.1"
            port = request.client.port if request.client else 0
            _append_runtime_log(
                job_id,
                f'INFO:     {host}:{port} - "GET /status/{job_id} HTTP/1.1" 200 OK',
            )
            job["last_status_poll_log_ts"] = now

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        preview_video_url=job.get("preview_video_url"),
        agents=[AgentTrace(**item) for item in snapshot_agents(job)],
        activity_log=job.get("activity_log", []),
        trace_events=[TraceEvent(**item) for item in snapshot_trace_events(job)],
        runtime_logs=job.get("runtime_logs", []),
        workflow_overview=job.get("workflow_overview", {}),
        review=job.get("review"),
        model_verification=job.get("model_verification"),
        result=job.get("result"),
    )


@app.get("/outputs/{job_id}/final_video.mp4")
async def stream_video(job_id: str):
    path = config.OUTPUT_DIR / job_id / "final_video.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video not yet available")
    return FileResponse(str(path), media_type="video/mp4", filename="algsoch_news_video.mp4")


@app.get("/outputs/{job_id}/script.json")
async def get_script(job_id: str):
    path = config.OUTPUT_DIR / job_id / "script.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Script not yet available")
    async with aiofiles.open(path, "r") as handle:
        content = await handle.read()
    return JSONResponse(content=json.loads(content))


@app.get("/outputs/{job_id}/client_pack.zip")
async def get_client_pack(job_id: str):
    path = config.OUTPUT_DIR / job_id / "client_pack.zip"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Client pack not yet available")
    return FileResponse(
        str(path),
        media_type="application/zip",
        filename=f"algsoch_client_pack_{job_id}.zip",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
