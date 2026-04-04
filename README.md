# Algsoch News

AI-powered news URL to dynamic broadcast screenplay and video generator.

## What It Does

Given a public news article URL, this project:

- extracts the article content
- segments it into broadcast-friendly sections
- generates headlines and narration
- prepares visuals
- synthesizes audio
- renders a news-style video output

## Tech Stack

- Backend: FastAPI, Python
- Frontend: React, Vite
- Media pipeline: FFmpeg
- Optional AI refinement: Gemini

## Project Structure

```text
backend/    FastAPI app and generation pipeline
frontend/   React frontend
media/      Generated intermediate assets (ignored by git)
outputs/    Generated video/script outputs (ignored by git)
```

## Environment Setup

Create a local `.env` file from `.env.example`.

Example:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-1.5-flash
USE_GEMINI=true
TTS_ENGINE=gtts
OUTPUT_DIR=./outputs
MEDIA_DIR=./media
MAX_ARTICLE_LENGTH=15000
VIDEO_WIDTH=1280
VIDEO_HEIGHT=720
VIDEO_FPS=24
WORDS_PER_SECOND=2.5
QA_THRESHOLD=0.6
MAX_RETRIES=2
```

## Run Locally

Backend:

```bash
cd /Volumes/algsoch/agentic
./venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd /Volumes/algsoch/agentic/frontend
npm install
npm run dev
```

Open the frontend URL shown by Vite, usually:

```text
http://localhost:5173
```

If port `5173` is busy, Vite will automatically choose another port such as `5174`.

## API Endpoints

- `GET /health`
- `POST /generate`
- `GET /status/{job_id}`
- `GET /outputs/{job_id}/final_video.mp4`
- `GET /outputs/{job_id}/script.json`

## Notes

- `.env`, `venv/`, `frontend/node_modules/`, `media/`, and `outputs/` are intentionally excluded from git.
- If your local FFmpeg build does not support `drawtext`, video rendering still works but text overlays may be skipped.
