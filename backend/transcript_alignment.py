"""
transcript_alignment.py - Transcript cue alignment with ASR-ready extension points.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from backend.broadcast import seconds_to_timecode
from backend.utils import config, sanitize_text


class TranscriptAligner:
    """
    Align transcript cues to segment timing.

    Current mode uses deterministic text pacing with optional audio duration hints.
    This class is intentionally structured to support future ASR/forced-alignment
    backends (Whisper, Vosk, CTC aligners) without changing callers.
    """

    def __init__(self, mode: str = "paced"):
        self.mode = mode

    @staticmethod
    def _word_count(text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", text))

    @staticmethod
    def _split_caption_chunks(text: str, max_words: int = 8) -> List[str]:
        cleaned = sanitize_text(text).strip()
        if not cleaned:
            return []

        sentence_parts = [
            part.strip()
            for part in re.findall(r"[^.!?]+[.!?]?", cleaned)
            if part and part.strip()
        ]

        chunks: List[str] = []
        for sentence in sentence_parts:
            end_mark = sentence[-1] if sentence and sentence[-1] in ".!?" else ""
            core = sentence[:-1].strip() if end_mark else sentence
            words = core.split()
            if not words:
                continue

            for start in range(0, len(words), max_words):
                part_words = words[start:start + max_words]
                chunk = " ".join(part_words)
                if start + max_words >= len(words) and end_mark:
                    chunk = f"{chunk}{end_mark}"
                chunks.append(chunk)

        return chunks or [cleaned]

    @staticmethod
    def _pause_weight(chunk: str) -> float:
        tail = chunk.strip()[-1:] if chunk.strip() else ""
        if tail in {".", "?", "!"}:
            return 0.16
        if tail in {",", ";", ":"}:
            return 0.08
        return 0.0

    def align(
        self,
        segments: Sequence[dict],
        audio_durations: Optional[Sequence[float]] = None,
    ) -> List[Dict]:
        if self.mode == "paced":
            return self._align_paced(segments, audio_durations=audio_durations)
        return self._align_paced(segments, audio_durations=audio_durations)

    def _align_paced(
        self,
        segments: Sequence[dict],
        audio_durations: Optional[Sequence[float]] = None,
    ) -> List[Dict]:
        cues: List[Dict] = []

        for idx, segment in enumerate(segments):
            narration = sanitize_text(segment.get("anchor_narration", "")).strip()
            if not narration:
                continue

            start = float(segment.get("start_time", 0.0))
            end = float(segment.get("end_time", start + 2.0))
            segment_duration = max(end - start, 0.8)

            if audio_durations and idx < len(audio_durations):
                audio_duration = float(audio_durations[idx])
                segment_duration = max(0.8, min(segment_duration, audio_duration + 0.35))

            chunks = self._split_caption_chunks(narration, max_words=8)
            total_words = max(self._word_count(narration), 1)

            # Keep cue pacing close to spoken cadence instead of fixed-size slices.
            spoken_wps = max(2.0, min(5.0, total_words / max(segment_duration, 0.8)))
            weighted_durations: List[float] = []
            for chunk in chunks:
                chunk_words = max(self._word_count(chunk), 1)
                base = chunk_words / spoken_wps
                bounded = max(0.55, min(3.2, base))
                weighted_durations.append(bounded + self._pause_weight(chunk))

            total_weight = max(sum(weighted_durations), 0.01)
            scale = segment_duration / total_weight

            cursor = start
            for chunk_idx, (chunk, weight) in enumerate(zip(chunks, weighted_durations), start=1):
                chunk_dur = max(0.45, round(weight * scale, 2))
                chunk_end = round(min(end, cursor + chunk_dur), 2)

                if chunk_end <= cursor:
                    chunk_end = round(min(end, cursor + 0.45), 2)

                cues.append(
                    {
                        "id": f"s{segment['segment_id']}-c{chunk_idx}",
                        "segment_id": int(segment["segment_id"]),
                        "start_time": round(cursor, 2),
                        "end_time": chunk_end,
                        "start_timecode": seconds_to_timecode(cursor),
                        "end_timecode": seconds_to_timecode(chunk_end),
                        "text": chunk,
                        "speaker": "anchor",
                        "emphasis": segment.get("top_tag", ""),
                        "lane": "program",
                    }
                )
                cursor = chunk_end

            if cues:
                cues[-1]["end_time"] = round(end, 2)
                cues[-1]["end_timecode"] = seconds_to_timecode(end)

        return cues


def attach_transcript_to_segments(segments: Sequence[dict], cues: Sequence[dict]) -> List[dict]:
    by_segment: Dict[int, List[dict]] = {}
    for cue in cues:
        by_segment.setdefault(int(cue["segment_id"]), []).append(dict(cue))

    updated: List[dict] = []
    for segment in segments:
        seg = dict(segment)
        seg["transcript_cues"] = by_segment.get(int(seg["segment_id"]), [])
        updated.append(seg)
    return updated
