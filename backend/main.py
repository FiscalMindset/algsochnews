"""
main.py - FastAPI application for Algsoch News.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict

import aiofiles
from fastapi import BackgroundTasks, FastAPI, HTTPException
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
)
from backend.observability import TraceBridge
from backend.transcript_alignment import TranscriptAligner, attach_transcript_to_segments
from backend.tts import synthesize_all
from backend.utils import config, generate_job_id, get_logger
from backend.video_renderer import render_video
from backend.workflow import (
    append_agent_output,
    build_agent_state,
    build_workflow_map,
    record_activity,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")

JOBS: Dict[str, dict] = {}


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

        trace_bridge = TraceBridge(job_id=job_id, article_url=req.article_url)
        job["_trace_bridge"] = trace_bridge

        workflow_overview = job.get("workflow_overview", {})
        workflow_overview.setdefault("retry_policy", {})["max_retry_rounds"] = config.MAX_RETRIES
        workflow_overview["selected_model"] = model_verification.selected_model
        workflow_overview["model_verification_ok"] = model_verification.verification_ok
        job["workflow_overview"] = workflow_overview

        update(8, f"Model selected: {model_verification.selected_model}. Starting LangGraph execution...", "editor")
        graph_state = await run_graph_pipeline(
            job,
            job_id,
            {
                "article_url": req.article_url,
                "max_segments": int(req.max_segments or 6),
                "use_gemini": bool(req.use_gemini),
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

        update(72, "Synthesizing anchor audio...")
        durations = [seg["duration"] for seg in segments_raw]
        audio_paths = await loop.run_in_executor(
            None,
            synthesize_all,
            narrations,
            durations,
            job_id,
        )

        aligner = TranscriptAligner(mode="paced")
        transcript_cues = aligner.align(packaged_segments, audio_durations=durations)
        packaged_segments = attach_transcript_to_segments(packaged_segments, transcript_cues)
        rundown = build_rundown(packaged_segments)
        append_agent_output(job, "packaging", "Transcript cues", len(transcript_cues), kind="metric")
        append_agent_output(job, "packaging", "Rundown items", len(rundown), kind="metric")

        update(86, "Rendering final broadcast video...")
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

        update(95, "Saving script JSON and outputs...")
        out_dir = config.OUTPUT_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

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
            workflow_overview=job.get("workflow_overview", {}),
            model_verification=model_verification,
            route_history=graph_state.get("route_history", []),
        )

        script_path = out_dir / "script.json"
        async with aiofiles.open(script_path, "w") as handle:
            await handle.write(script.model_dump_json(indent=2))

        elapsed = round(time.time() - start, 2)
        result = GenerateResponse(
            success=True,
            job_id=job_id,
            script=script,
            agents=[AgentTrace(**item) for item in snapshot_agents(job)],
            activity_log=job.get("activity_log", []),
            trace_events=[TraceEvent(**item) for item in snapshot_trace_events(job)],
            model_verification=model_verification,
            video_path=str(final_video),
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
                "review": review.model_dump(),
                "model_verification": model_verification.model_dump(),
            }
        )

    except Exception as exc:
        log.exception(f"[{job_id}] Pipeline failed: {exc}")
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
        "result": None,
        "review": None,
        "model_verification": None,
        "agents": build_agent_state(),
        "activity_log": [],
        "trace_events": [],
        "workflow_overview": build_workflow_map(),
    }
    record_activity(JOBS[job_id], f"Job queued for {req.article_url}")

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
async def get_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS[job_id]
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        agents=[AgentTrace(**item) for item in snapshot_agents(job)],
        activity_log=job.get("activity_log", []),
        trace_events=[TraceEvent(**item) for item in snapshot_trace_events(job)],
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
