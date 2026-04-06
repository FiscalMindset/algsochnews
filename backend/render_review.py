"""
render_review.py - Render quality review for generated newsroom videos.

Combines deterministic media checks with optional Gemini-assisted critique.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pydantic import BaseModel, Field

from backend.gemini_router import build_langchain_chat_model
from backend.utils import get_logger

log = get_logger("render_review")


_INSTRUCTION_RE = re.compile(
    r"^(state|shift|emphasize|convey|stress|frame|open|focus|mention|use|keep)\b",
    re.IGNORECASE,
)


class _RenderLLMReview(BaseModel):
    verdict: str = "review"
    summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


def _probe_video(path: Path) -> Dict[str, Any]:
    telemetry: Dict[str, Any] = {
        "duration_sec": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "has_video_stream": False,
        "has_audio_stream": False,
        "audio_codec": "",
        "video_codec": "",
    }

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        payload = json.loads(result.stdout or "{}")
    except Exception as exc:
        log.warning(f"ffprobe failed for {path}: {exc}")
        return telemetry

    format_obj = payload.get("format") or {}
    try:
        telemetry["duration_sec"] = float(format_obj.get("duration") or 0.0)
    except Exception:
        telemetry["duration_sec"] = 0.0

    for stream in payload.get("streams", []):
        codec_type = (stream.get("codec_type") or "").lower()
        if codec_type == "video":
            telemetry["has_video_stream"] = True
            telemetry["width"] = int(stream.get("width") or 0)
            telemetry["height"] = int(stream.get("height") or 0)
            telemetry["video_codec"] = stream.get("codec_name") or ""

            fps_raw = stream.get("avg_frame_rate") or ""
            if isinstance(fps_raw, str) and "/" in fps_raw:
                left, right = fps_raw.split("/", 1)
                try:
                    telemetry["fps"] = float(left) / max(float(right), 1.0)
                except Exception:
                    pass
        elif codec_type == "audio":
            telemetry["has_audio_stream"] = True
            telemetry["audio_codec"] = stream.get("codec_name") or ""

    return telemetry


def _instruction_like_count(segments: Sequence[dict]) -> int:
    hits = 0
    for segment in segments:
        narration = str(segment.get("anchor_narration") or "").strip().lower()
        if not narration:
            continue
        if _INSTRUCTION_RE.search(narration):
            hits += 1
            continue
        if any(
            phrase in narration
            for phrase in (
                "set the stage",
                "shift tone",
                "stress the phrase",
                "emphasize the words",
            )
        ):
            hits += 1
    return hits


def _llm_render_review(
    *,
    model_name: str,
    api_key: str,
    telemetry: Dict[str, Any],
    strengths: List[str],
    issues: List[str],
    recommendations: List[str],
) -> Dict[str, Any]:
    if not api_key:
        return {}

    try:
        from langchain_core.prompts import ChatPromptTemplate

        llm = build_langchain_chat_model(model_name=model_name, api_key=api_key, temperature=0.1)
        structured = llm.with_structured_output(_RenderLLMReview)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the Render QA Agent for a newsroom video pipeline. "
                    "Assess render quality telemetry and return concise findings. "
                    "Do not invent media metrics.",
                ),
                (
                    "human",
                    "Telemetry: {telemetry}\n"
                    "Known strengths: {strengths}\n"
                    "Known issues: {issues}\n"
                    "Current recommendations: {recommendations}\n"
                    "Return verdict + concise summary + prioritized recommendations.",
                ),
            ]
        )

        chain = prompt | structured
        response = chain.invoke(
            {
                "telemetry": telemetry,
                "strengths": strengths,
                "issues": issues,
                "recommendations": recommendations,
            }
        )
        if isinstance(response, BaseModel):
            return response.model_dump()
        if isinstance(response, dict):
            return response
    except Exception as exc:
        log.warning(f"LLM render review failed: {exc}")

    return {}


def evaluate_render_quality(
    *,
    video_path: Path,
    segments: Sequence[dict],
    transcript_cues: Sequence[dict],
    target_runtime_sec: float,
    use_gemini: bool,
    model_name: str,
    api_key: str,
) -> Dict[str, Any]:
    telemetry = _probe_video(video_path)

    score = 5.0
    strengths: List[str] = []
    issues: List[str] = []
    recommendations: List[str] = []

    if telemetry.get("has_video_stream"):
        strengths.append("Final MP4 contains a video stream.")
    else:
        issues.append("Final MP4 does not expose a readable video stream.")
        recommendations.append("Re-run FFmpeg render and verify input scene images are valid.")
        score -= 2.0

    if telemetry.get("has_audio_stream"):
        strengths.append("Final MP4 contains an audio stream.")
    else:
        issues.append("Final MP4 does not expose a readable audio stream.")
        recommendations.append("Re-run TTS synthesis and verify clip concat includes audio maps.")
        score -= 2.0

    width = int(telemetry.get("width") or 0)
    height = int(telemetry.get("height") or 0)
    if width >= 1280 and height >= 720:
        strengths.append(f"Render resolution is {width}x{height}.")
    else:
        issues.append(f"Render resolution is lower than expected: {width}x{height}.")
        recommendations.append("Ensure render target is fixed at 1280x720 for broadcast layout stability.")
        score -= 0.7

    video_duration = float(telemetry.get("duration_sec") or 0.0)
    delta = abs(video_duration - float(target_runtime_sec or 0.0))
    telemetry["target_runtime_sec"] = round(float(target_runtime_sec or 0.0), 2)
    telemetry["duration_delta_sec"] = round(delta, 2)
    if delta <= 1.0:
        strengths.append("Rendered duration closely matches the planned runtime.")
    elif delta <= 2.5:
        issues.append(f"Rendered duration differs from plan by {delta:.2f}s.")
        recommendations.append("Adjust per-segment timing normalization to reduce duration drift.")
        score -= 0.4
    else:
        issues.append(f"Rendered duration drift is high ({delta:.2f}s).")
        recommendations.append("Rebalance segment durations before synthesis to match target runtime.")
        score -= 1.0

    cue_count = len(transcript_cues)
    segment_count = len(segments)
    telemetry["segment_count"] = segment_count
    telemetry["transcript_cue_count"] = cue_count
    if cue_count >= max(segment_count, 1):
        strengths.append("Transcript cues are available for playback/caption sync.")
    else:
        issues.append("Transcript cue coverage is sparse for the rendered timeline.")
        recommendations.append("Increase cue segmentation density for smoother live captions.")
        score -= 0.5

    instruction_hits = _instruction_like_count(segments)
    telemetry["instruction_like_narration_hits"] = instruction_hits
    if instruction_hits == 0:
        strengths.append("Anchor narration appears broadcast-style instead of directive text.")
    else:
        issues.append(f"{instruction_hits} segment(s) still look instruction-like in narration.")
        recommendations.append("Regenerate affected narration beats with factual declarative lines.")
        score -= min(1.5, 0.5 * instruction_hits)

    score = max(1.0, min(5.0, round(score, 2)))
    passed = score >= 4.0 and telemetry.get("has_video_stream") and telemetry.get("has_audio_stream")
    verdict = "pass" if passed else "review"

    summary = (
        f"Render QA score {score}/5. "
        f"Duration delta {telemetry['duration_delta_sec']}s, "
        f"resolution {width}x{height}, cues {cue_count}."
    )

    if use_gemini and api_key:
        llm = _llm_render_review(
            model_name=model_name,
            api_key=api_key,
            telemetry=telemetry,
            strengths=strengths,
            issues=issues,
            recommendations=recommendations,
        )
        if llm:
            verdict = llm.get("verdict") or verdict
            summary = llm.get("summary") or summary
            strengths = llm.get("strengths") or strengths
            issues = llm.get("issues") or issues
            recommendations = llm.get("recommendations") or recommendations

    return {
        "passed": bool(passed),
        "overall_score": score,
        "summary": summary,
        "verdict": verdict,
        "strengths": strengths,
        "issues": issues,
        "recommendations": recommendations,
        "telemetry": telemetry,
    }
