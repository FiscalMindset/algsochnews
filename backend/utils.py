"""
utils.py — Shared helpers, logging, config loader
"""
import html
import os
import re
import uuid
import logging
import hashlib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class Config:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    USE_GEMINI: bool = os.getenv("USE_GEMINI", "true").lower() == "true"
    TTS_ENGINE: str = os.getenv("TTS_ENGINE", "gtts")         # gtts | pyttsx3
    OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "./outputs"))
    MEDIA_DIR: Path = Path(os.getenv("MEDIA_DIR", "./media"))
    MAX_ARTICLE_LENGTH: int = int(os.getenv("MAX_ARTICLE_LENGTH", "15000"))
    VIDEO_WIDTH: int = int(os.getenv("VIDEO_WIDTH", "1280"))
    VIDEO_HEIGHT: int = int(os.getenv("VIDEO_HEIGHT", "720"))
    VIDEO_FPS: int = int(os.getenv("VIDEO_FPS", "24"))
    WORDS_PER_SECOND: float = float(os.getenv("WORDS_PER_SECOND", "2.5"))
    QA_THRESHOLD: float = float(os.getenv("QA_THRESHOLD", "0.6"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))

    def __init__(self):
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)


config = Config()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def generate_job_id() -> str:
    return str(uuid.uuid4())[:12].replace("-", "")


def url_to_filename(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def sanitize_text(text: str) -> str:
    """Normalize extracted article text and strip common HTML / entity noise."""
    text = html.unescape(text or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    text = re.sub(r"\b(?:nbsp|amp|quot)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s.,!?;:\-'\"]", " ", text)
    text = re.sub(r"\b(?:lt|gt)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def word_count(text: str) -> int:
    return len(text.split())


def estimate_duration(text: str, wps: float = None) -> float:
    """Estimate audio duration in seconds for a given text."""
    wps = wps or config.WORDS_PER_SECOND
    return max(2.0, word_count(text) / wps)


def extract_domain(url: str) -> str:
    """Extract root domain from URL."""
    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else "unknown"


def chunk_text(text: str, max_words: int = 60) -> list[str]:
    """Split text into chunks of roughly max_words words, at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current, count = [], [], 0
    for sent in sentences:
        w = word_count(sent)
        if count + w > max_words and current:
            chunks.append(" ".join(current))
            current, count = [sent], w
        else:
            current.append(sent)
            count += w
    if current:
        chunks.append(" ".join(current))
    return [c for c in chunks if c.strip()]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
