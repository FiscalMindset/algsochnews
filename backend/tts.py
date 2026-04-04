"""
tts.py — Offline-first TTS with gTTS cloud fallback.
Generates per-segment WAV/MP3 audio files.
"""

import subprocess
from pathlib import Path
from typing import List
from backend.utils import get_logger, config

log = get_logger("tts")


# ------------------------------------------------------------------ #
# Engine implementations
# ------------------------------------------------------------------ #

def _audio_is_valid(path: Path) -> bool:
    """Return True when ffprobe can detect at least one audio stream."""
    if not path.exists() or path.stat().st_size < 500:
        return False

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return "audio" in result.stdout
    except Exception:
        return False


def _tts_pyttsx3(text: str, dest: Path) -> bool:
    """Offline TTS via pyttsx3 → WAV."""
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 160)   # words per minute
        engine.setProperty("volume", 0.95)

        # Try to pick a good English voice
        voices = engine.getProperty("voices")
        for v in voices:
            if "english" in v.name.lower() or "en_" in v.id.lower():
                engine.setProperty("voice", v.id)
                break

        tmp = dest.with_suffix(".wav")
        engine.save_to_file(text, str(tmp))
        engine.runAndWait()

        if not tmp.exists() or tmp.stat().st_size <= 1000:
            return False

        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(tmp), str(dest)],
                check=True,
                capture_output=True,
            )
        except Exception as e:
            log.warning(f"pyttsx3 ffmpeg conversion failed: {e}")
            return False
        finally:
            tmp.unlink(missing_ok=True)

        if _audio_is_valid(dest):
            return True

        dest.unlink(missing_ok=True)
        log.warning("pyttsx3 produced invalid audio output")
        return False
    except Exception as e:
        log.warning(f"pyttsx3 TTS failed: {e}")
        return False


def _tts_gtts(text: str, dest: Path) -> bool:
    """Cloud TTS via gTTS → MP3."""
    try:
        from gtts import gTTS

        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(str(dest))

        if _audio_is_valid(dest):
            return True
        dest.unlink(missing_ok=True)
        return False
    except Exception as e:
        log.warning(f"gTTS failed: {e}")
        return False


def _create_silent_audio(duration: float, dest: Path) -> bool:
    """
    Create a silent audio file of given duration using ffmpeg.
    Last-resort fallback.
    """
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=mono",
                "-t", str(duration),
                "-q:a", "9",
                "-acodec", "libmp3lame",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
        if _audio_is_valid(dest):
            log.warning(f"Created silent audio for {dest.name}")
            return True
        log.error(f"Silent audio was created but is invalid: {dest}")
        return False
    except Exception as e:
        log.error(f"Silent audio creation failed: {e}")
        return False


# ------------------------------------------------------------------ #
# Public
# ------------------------------------------------------------------ #

def synthesize_segment(
    narration: str,
    dest: Path,
    duration_hint: float = 5.0,
    engine: str = "auto",
) -> Path:
    """
    Synthesize audio for a single segment.
    engine: 'pyttsx3' | 'gtts' | 'auto' (try pyttsx3 first, then gtts)
    Returns path to the audio file.
    """
    dest = dest.with_suffix(".mp3")
    if _audio_is_valid(dest):
        return dest
    dest.unlink(missing_ok=True)

    success = False
    effective_engine = config.TTS_ENGINE if engine == "auto" else engine

    if effective_engine in ("pyttsx3", "auto"):
        success = _tts_pyttsx3(narration, dest)

    if not success and effective_engine in ("gtts", "auto"):
        success = _tts_gtts(narration, dest)

    if not success:
        log.warning(f"All TTS engines failed for segment, using silence.")
        success = _create_silent_audio(duration_hint, dest)

    if not success or not _audio_is_valid(dest):
        raise RuntimeError(f"Could not generate valid audio for {dest.name}")

    return dest


def synthesize_all(
    narrations: List[str],
    durations: List[float],
    job_id: str,
) -> List[Path]:
    """
    Synthesize TTS for all segments.
    Returns list of audio file paths.
    """
    audio_dir = config.MEDIA_DIR / job_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_paths: List[Path] = []
    for i, (text, dur) in enumerate(zip(narrations, durations)):
        dest = audio_dir / f"seg_{i:02d}.mp3"
        log.info(f"TTS segment {i}: {text[:50]}…")
        path = synthesize_segment(text, dest, duration_hint=dur)
        audio_paths.append(path)

    return audio_paths
