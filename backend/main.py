"""
main.py — FastAPI application for AI News Video Generator.
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict

import aiofiles
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.models import (
    GenerateRequest,
    GenerateResponse,
    JobStatusResponse,
    Script,
    Segment,
    ArticleData,
)
from backend.utils import get_logger, config, generate_job_id
from backend.scraper import scrape_article
from backend.segmenter import segment_article
from backend.headline_gen import generate_all_headlines
from backend.narration import generate_narrations
from backend.visual_planner import plan_visuals
from backend.tts import synthesize_all
from backend.video_renderer import render_video
from backend.qa import compute_qa_score, identify_weak_segments

log = get_logger("main")

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AI News Video Generator",
    description="Convert any public news article into a professional AI news video.",
    version="1.0.0",
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

# In-memory job store (replace with Redis in production)
JOBS: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------

async def _run_pipeline(job_id: str, req: GenerateRequest) -> None:
    """Full async pipeline: scrape → segment → headline → narrate → TTS → visual → video."""
    def update(progress: int, message: str):
        JOBS[job_id].update({"progress": progress, "message": message})
        log.info(f"[{job_id}] {progress}% — {message}")

    try:
        JOBS[job_id]["status"] = "processing"
        start = time.time()

        # ---- STEP 1: Scrape ----
        update(5, "Extracting article…")
        article_raw = await asyncio.get_event_loop().run_in_executor(
            None, scrape_article, req.article_url
        )

        # ---- STEP 2: Segment ----
        update(15, "Segmenting article…")
        segments_raw = await asyncio.get_event_loop().run_in_executor(
            None,
            segment_article,
            article_raw["text"],
            req.max_segments,
            article_raw.get("title", ""),
        )

        # ---- STEP 3: Headlines ----
        update(25, "Generating headlines…")
        overall_headline, headlines = await asyncio.get_event_loop().run_in_executor(
            None,
            generate_all_headlines,
            article_raw.get("title", ""),
            segments_raw,
            article_raw["text"],
        )

        # ---- STEP 4: Narration ----
        update(35, "Writing narration scripts…")
        narrations = await asyncio.get_event_loop().run_in_executor(
            None,
            generate_narrations,
            segments_raw,
            headlines,
            article_raw["text"],
            req.use_gemini,
        )

        # ---- STEP 5: QA Pass 1 ----
        update(44, "Running QA check…")
        visuals_tmp = [{"image_path": "placeholder"} for _ in segments_raw]
        score1, detail1 = compute_qa_score(segments_raw, narrations, visuals_tmp)

        # Retry weak narrations (up to MAX_RETRIES)
        if not detail1["passed"] and config.MAX_RETRIES > 0:
            update(47, "Retrying weak narrations…")
            weak_idxs = identify_weak_segments(narrations, segments_raw)
            for attempt in range(config.MAX_RETRIES):
                for idx in weak_idxs:
                    from backend.narration import generate_narrations as _gen
                    fixed = _gen(
                        [segments_raw[idx]],
                        [headlines[idx]],
                        article_raw["text"],
                        use_gemini=True,
                    )
                    narrations[idx] = fixed[0]
                score_new, detail_new = compute_qa_score(segments_raw, narrations, visuals_tmp)
                log.info(f"Retry {attempt+1}: QA score {score_new:.3f}")
                if detail_new["passed"]:
                    break

        # ---- STEP 6: Visual planning ----
        update(55, "Preparing visuals…")
        visuals = await asyncio.get_event_loop().run_in_executor(
            None,
            plan_visuals,
            segments_raw,
            headlines,
            article_raw.get("images", []),
            article_raw.get("source_domain", ""),
            job_id,
        )

        # ---- STEP 7: TTS ----
        update(65, "Synthesizing audio narrations…")
        durations = [s["duration"] for s in segments_raw]
        audio_paths = await asyncio.get_event_loop().run_in_executor(
            None,
            synthesize_all,
            narrations,
            durations,
            job_id,
        )

        # ---- STEP 8: Video render ----
        update(78, "Rendering video segments…")
        final_video = await asyncio.get_event_loop().run_in_executor(
            None,
            render_video,
            segments_raw,
            visuals,
            narrations,
            audio_paths,
            headlines,
            overall_headline,
            job_id,
        )

        # ---- QA Final ----
        update(92, "Final quality check…")
        qa_score, qa_detail = compute_qa_score(segments_raw, narrations, visuals)

        # ---- Save script.json ----
        update(95, "Saving outputs…")
        out_dir = config.OUTPUT_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        segments_out = []
        for i, (seg, vis, narr, headline) in enumerate(
            zip(segments_raw, visuals, narrations, headlines)
        ):
            segments_out.append(
                Segment(
                    index=i,
                    start_time=seg["start_time"],
                    end_time=seg["end_time"],
                    headline=headline,
                    narration=narr,
                    image_url=vis.get("image_url"),
                    image_path=vis.get("image_path"),
                    visual_prompt=vis.get("visual_prompt", ""),
                )
            )

        article_model = ArticleData(
            title=article_raw.get("title", ""),
            text=article_raw["text"][:2000],   # truncate for JSON
            url=article_raw["url"],
            top_image=article_raw.get("top_image"),
            images=article_raw.get("images", [])[:10],
            authors=article_raw.get("authors", []),
            published_date=article_raw.get("published_date"),
            source_domain=article_raw.get("source_domain", ""),
            word_count=article_raw.get("word_count", 0),
            extraction_method=article_raw.get("method", "unknown"),
        )

        script = Script(
            article=article_model,
            segments=segments_out,
            total_duration=segments_raw[-1]["end_time"],
            overall_headline=overall_headline,
            qa_score=qa_score,
        )

        script_path = out_dir / "script.json"
        async with aiofiles.open(script_path, "w") as f:
            await f.write(script.model_dump_json(indent=2))

        elapsed = round(time.time() - start, 2)
        log.info(f"[{job_id}] Done in {elapsed}s — video: {final_video}")

        video_url = f"/outputs/{job_id}/final_video.mp4"

        JOBS[job_id].update(
            {
                "status": "done",
                "progress": 100,
                "message": "Video generated successfully!",
                "result": GenerateResponse(
                    success=True,
                    job_id=job_id,
                    script=script,
                    video_path=str(final_video),
                    video_url=video_url,
                    processing_time=elapsed,
                ).model_dump(),
            }
        )

    except Exception as exc:
        log.exception(f"[{job_id}] Pipeline failed: {exc}")
        JOBS[job_id].update(
            {
                "status": "failed",
                "progress": 0,
                "message": str(exc),
                "result": GenerateResponse(
                    success=False,
                    job_id=job_id,
                    error=str(exc),
                    processing_time=round(time.time() - start, 2),
                ).model_dump(),
            }
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/generate", response_model=dict)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    """
    Accept a news article URL and kick off the async generation pipeline.
    Returns a job_id immediately; poll /status/{job_id} for updates.
    """
    if not req.article_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL — must start with http(s)://")

    job_id = generate_job_id()
    JOBS[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Job queued…",
        "result": None,
    }

    background_tasks.add_task(_run_pipeline, job_id, req)
    log.info(f"Job {job_id} queued for: {req.article_url}")

    return {"job_id": job_id, "status": "pending", "message": "Job queued"}


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
        result=job.get("result"),
    )


@app.get("/outputs/{job_id}/final_video.mp4")
async def stream_video(job_id: str):
    path = config.OUTPUT_DIR / job_id / "final_video.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video not yet available")
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename="news_video.mp4",
    )


@app.get("/outputs/{job_id}/script.json")
async def get_script(job_id: str):
    path = config.OUTPUT_DIR / job_id / "script.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Script not yet available")
    async with aiofiles.open(path, "r") as f:
        content = await f.read()
    return JSONResponse(content=json.loads(content))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
