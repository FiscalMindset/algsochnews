"""
main.py — FastAPI application for AI News Broadcast Generator.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, List, Sequence

import aiofiles
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.broadcast import (
    build_rundown,
    build_screenplay_text,
    build_transcript_cues,
    generate_segment_copy,
    seconds_to_timecode,
)
from backend.models import (
    ArticleData,
    GenerateRequest,
    GenerateResponse,
    JobStatusResponse,
    Script,
    Segment,
)
from backend.narration import generate_narrations
from backend.qa import review_broadcast_package
from backend.scraper import scrape_article
from backend.segmenter import segment_article
from backend.tts import synthesize_all
from backend.utils import config, estimate_duration, generate_job_id, get_logger, sanitize_text
from backend.video_renderer import render_video
from backend.visual_planner import plan_visuals, prepare_source_images
from backend.workflow import (
    append_agent_output,
    build_agent_state,
    build_workflow_map,
    record_activity,
    set_agent_state,
    snapshot_agents,
)

log = get_logger("main")

app = FastAPI(
    title="AI News Broadcast Generator",
    description="Convert any public news article into a structured AI news package.",
    version="2.0.0",
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
        record = {
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
        records.append(record)
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


def _attach_transcript_cues(segments: Sequence[dict]) -> tuple[List[dict], List[dict]]:
    prepared = [dict(segment, transcript_cues=[]) for segment in segments]
    transcript_cues = build_transcript_cues(prepared)
    segment_lookup = {segment["segment_id"]: segment for segment in prepared}
    for cue in transcript_cues:
        segment_lookup.get(cue["segment_id"], {}).setdefault("transcript_cues", []).append(cue)
    return prepared, transcript_cues


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
        log.info(f"[{job_id}] {progress}% — {message}")

    try:
        job["status"] = "processing"

        # 1. Extraction agent
        set_agent_state(
            job,
            "extraction",
            status="running",
            progress=15,
            summary="Fetching article HTML and comparing extraction candidates.",
        )
        update(6, "Article Extraction Agent is cleaning the source article...", "extraction")
        article_raw = await loop.run_in_executor(None, scrape_article, req.article_url)
        append_agent_output(job, "extraction", "Chosen extractor", article_raw.get("method", "unknown"))
        append_agent_output(job, "extraction", "Source title", article_raw.get("title", ""))
        append_agent_output(job, "extraction", "Word count", article_raw.get("word_count", 0), kind="metric")
        append_agent_output(job, "extraction", "Candidates", article_raw.get("candidates", []), kind="table")
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

        # 2. Editor agent
        set_agent_state(
            job,
            "editor",
            status="running",
            progress=10,
            summary="Building story beats and anchor narration.",
        )
        update(20, "News Editor Agent is creating story beats and narration...", "editor")
        segments_raw = await loop.run_in_executor(
            None,
            segment_article,
            article_raw["text"],
            req.max_segments,
            article_raw.get("title", ""),
        )
        narrations = await loop.run_in_executor(
            None,
            generate_narrations,
            segments_raw,
            [article_raw.get("title", "")] * len(segments_raw),
            article_raw["text"],
            req.use_gemini,
        )
        segments_raw = _retime_segments(segments_raw, narrations)
        append_agent_output(job, "editor", "Beat count", len(segments_raw), kind="metric")
        append_agent_output(job, "editor", "Opening line", narrations[0] if narrations else "")
        append_agent_output(job, "editor", "Closing line", narrations[-1] if narrations else "")
        set_agent_state(
            job,
            "editor",
            status="done",
            progress=100,
            summary=f"Generated {len(segments_raw)} timed story beats for the anchor rundown.",
            metrics={"segment_count": len(segments_raw), "runtime_sec": segments_raw[-1]["end_time"] if segments_raw else 0},
        )

        # 3. Packaging agent with real parallel fan-out
        set_agent_state(
            job,
            "packaging",
            status="running",
            progress=15,
            summary="Running parallel headline packaging and source-image preparation.",
            branch="parallel",
        )
        update(38, "Visual Packaging Agent is running copy and source-image prep in parallel...", "packaging")
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
        append_agent_output(job, "packaging", "Source visuals used", sum(1 for item in packaged_segments if item["source_visual_used"]), kind="metric")
        append_agent_output(job, "packaging", "AI support visuals", sum(1 for item in packaged_segments if item["ai_support_visual_prompt"]), kind="metric")
        append_agent_output(job, "packaging", "Transitions", [item["transition"] for item in packaged_segments], kind="list")
        append_agent_output(job, "packaging", "Camera motions", [item["camera_motion"] for item in packaged_segments], kind="list")
        set_agent_state(
            job,
            "packaging",
            status="done",
            progress=100,
            summary="Finished segment headlines, layouts, support visuals, and scene composition.",
            metrics={
                "source_visuals": sum(1 for item in packaged_segments if item["source_visual_used"]),
                "support_visuals": sum(1 for item in packaged_segments if item["ai_support_visual_prompt"]),
            },
        )

        # 4. QA agent + targeted retries
        retry_round = 0
        set_agent_state(
            job,
            "review",
            status="running",
            progress=30,
            summary="Scoring the package against broadcast-quality criteria.",
        )
        update(58, "QA / Evaluation Agent is reviewing structure, hook, headlines, and visuals...", "review")
        qa_score, review = await loop.run_in_executor(None, review_broadcast_package, packaged_segments, article_raw["text"], retry_round)
        job["review"] = review.model_dump()

        while not review.passed and retry_round < config.MAX_RETRIES:
            retry_round += 1
            decision = review.retry_decision
            record_activity(job, f"QA requested {decision} on retry round {retry_round}.", agent_key="review")

            if decision in {"retry_editor", "retry_editor_and_packaging"}:
                set_agent_state(
                    job,
                    "editor",
                    status="running",
                    progress=75,
                    summary="QA requested stronger narration on weak beats.",
                    branch="qa_retry",
                    retry_increment=True,
                )
                update(61, "News Editor Agent is revising weak narration beats...", "editor")
                weak = review.weak_segments or list(range(len(packaged_segments)))
                for weak_index in weak:
                    packaged_segments[weak_index]["anchor_narration"] = _tighten_narration(packaged_segments[weak_index])
                    packaged_segments[weak_index]["narration"] = packaged_segments[weak_index]["anchor_narration"]
                    narrations[weak_index] = packaged_segments[weak_index]["anchor_narration"]
                segments_raw = _retime_segments(segments_raw, narrations)
                set_agent_state(
                    job,
                    "editor",
                    status="done",
                    progress=100,
                    summary="Editorial retry tightened weak narration beats for broadcast tone.",
                )

            if decision in {"retry_packaging", "retry_editor_and_packaging"}:
                set_agent_state(
                    job,
                    "packaging",
                    status="running",
                    progress=75,
                    summary="QA requested stronger on-screen packaging and visual balance.",
                    branch="qa_retry",
                    retry_increment=True,
                )
                update(64, "Visual Packaging Agent is tightening headlines and layout coverage...", "packaging")
                copy_plan = [_tighten_packaging(segment) for segment in packaged_segments]
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
                set_agent_state(
                    job,
                    "packaging",
                    status="done",
                    progress=100,
                    summary="Packaging retry tightened overlay copy and refreshed scene composition.",
                )

            hydrated_packages = _hydrate_copy_plan(segments_raw, narrations, copy_plan)
            packaged_segments = _build_segment_records(segments_raw, narrations, hydrated_packages, visuals)
            qa_score, review = await loop.run_in_executor(None, review_broadcast_package, packaged_segments, article_raw["text"], retry_round)
            job["review"] = review.model_dump()

        append_agent_output(job, "review", "QA average", review.overall_average, kind="metric")
        append_agent_output(job, "review", "Retry decision", review.retry_decision)
        append_agent_output(job, "review", "Criteria", [item.model_dump() for item in review.criteria], kind="table")
        set_agent_state(
            job,
            "review",
            status="done",
            progress=100,
            summary=f"QA completed with average {review.overall_average}/5 after {retry_round} retry rounds.",
            metrics={"average": review.overall_average, "passed": review.passed, "retries": retry_round},
        )

        packaged_segments, transcript_cues = _attach_transcript_cues(packaged_segments)
        rundown = build_rundown(packaged_segments)
        append_agent_output(job, "packaging", "Transcript cues", len(transcript_cues), kind="metric")
        append_agent_output(job, "packaging", "Rundown items", len(rundown), kind="metric")

        # 5. TTS
        update(76, "Synthesizing anchor audio...", "editor")
        durations = [seg["duration"] for seg in segments_raw]
        audio_paths = await loop.run_in_executor(
            None,
            synthesize_all,
            narrations,
            durations,
            job_id,
        )

        # 6. Render video
        update(88, "Rendering broadcast scenes into the final video...", "packaging")
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

        # 7. Save outputs
        update(95, "Saving screenplay JSON and final outputs...")
        out_dir = config.OUTPUT_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        article_model = ArticleData(
            title=article_raw.get("title", ""),
            text=article_raw["text"][:2500],
            url=article_raw["url"],
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

        screenplay_text = build_screenplay_text(
            req.article_url,
            article_raw.get("title", ""),
            segments_raw[-1]["end_time"] if segments_raw else 0,
            packaged_segments,
        )

        script = Script(
            article_url=req.article_url,
            source_title=article_raw.get("title", ""),
            article=article_model,
            segments=[Segment(**segment) for segment in packaged_segments],
            live_transcript=transcript_cues,
            rundown=rundown,
            total_duration=segments_raw[-1]["end_time"] if segments_raw else 0,
            video_duration_sec=int(round(segments_raw[-1]["end_time"])) if segments_raw else 0,
            overall_headline=overall_headline,
            screenplay_text=screenplay_text,
            qa_score=qa_score,
            review=review,
            workflow_overview=job.get("workflow_overview", {}),
        )

        script_path = out_dir / "script.json"
        async with aiofiles.open(script_path, "w") as handle:
            await handle.write(script.model_dump_json(indent=2))

        elapsed = round(time.time() - start, 2)
        log.info(f"[{job_id}] Done in {elapsed}s — video: {final_video}")

        result = GenerateResponse(
            success=True,
            job_id=job_id,
            script=script,
            agents=snapshot_agents(job),
            activity_log=job.get("activity_log", []),
            video_path=str(final_video),
            video_url=f"/outputs/{job_id}/final_video.mp4",
            processing_time=elapsed,
        )

        job.update(
            {
                "status": "done",
                "progress": 100,
                "message": "Broadcast package generated successfully.",
                "result": result.model_dump(),
                "review": review.model_dump(),
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
                    agents=snapshot_agents(job),
                    activity_log=job.get("activity_log", []),
                    error=str(exc),
                    processing_time=round(time.time() - start, 2),
                ).model_dump(),
            }
        )


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/generate", response_model=dict)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    if not req.article_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL — must start with http(s)://")

    job_id = generate_job_id()
    JOBS[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Job queued…",
        "result": None,
        "review": None,
        "agents": build_agent_state(),
        "activity_log": [],
        "workflow_overview": build_workflow_map(),
    }
    record_activity(JOBS[job_id], f"Job queued for {req.article_url}")

    background_tasks.add_task(_run_pipeline, job_id, req)
    log.info(f"Job {job_id} queued for: {req.article_url}")

    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Job queued",
        "agents": JOBS[job_id]["agents"],
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
        agents=snapshot_agents(job),
        activity_log=job.get("activity_log", []),
        workflow_overview=job.get("workflow_overview", {}),
        review=job.get("review"),
        result=job.get("result"),
    )


@app.get("/outputs/{job_id}/final_video.mp4")
async def stream_video(job_id: str):
    path = config.OUTPUT_DIR / job_id / "final_video.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video not yet available")
    return FileResponse(str(path), media_type="video/mp4", filename="news_video.mp4")


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
