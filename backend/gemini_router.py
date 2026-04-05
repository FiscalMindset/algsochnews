"""
gemini_router.py - Gemini model verification and selection helpers.

Ensures the application uses a practical, currently available model for
production-style newsroom generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple

import requests

from backend.utils import get_logger

log = get_logger("gemini_router")

MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
PREFERRED_STABLE_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-pro-latest",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
]
MINIMUM_ACCEPTABLE_PREFIXES = (
    "gemini-2.5",
    "gemini-2.0",
    "gemini-pro-latest",
    "gemini-flash-latest",
)


@dataclass
class ModelResolution:
    configured_model: str
    selected_model: str
    available_models: List[str]
    upgraded: bool
    verification_ok: bool
    note: str



def _normalize_model_name(model_name: str) -> str:
    if not model_name:
        return ""
    return model_name.replace("models/", "").strip()



def _is_text_generation_model(model_name: str) -> bool:
    lower = model_name.lower()
    blocked_tokens = (
        "embedding",
        "image",
        "tts",
        "audio",
        "computer-use",
        "deep-research",
        "veo",
        "imagen",
        "aqa",
        "lyria",
        "robotics",
        "gemma",
        "nano-banana",
    )
    return not any(token in lower for token in blocked_tokens)



def _is_strong_enough(model_name: str) -> bool:
    return model_name.startswith(MINIMUM_ACCEPTABLE_PREFIXES)


@lru_cache(maxsize=8)
def _cached_fetch_available_models(api_key: str) -> Tuple[List[str], str]:
    if not api_key:
        return [], "Missing GEMINI_API_KEY"

    try:
        response = requests.get(MODELS_ENDPOINT, params={"key": api_key}, timeout=12)
        payload = response.json() if response.content else {}

        if response.status_code >= 400:
            message = payload.get("error", {}).get("message", f"HTTP {response.status_code}")
            return [], message

        models = []
        for item in payload.get("models", []):
            name = _normalize_model_name(item.get("name", ""))
            methods = item.get("supportedGenerationMethods", [])
            if not name or "generateContent" not in methods:
                continue
            if _is_text_generation_model(name):
                models.append(name)

        models = sorted(set(models))
        if not models:
            return [], "No generateContent Gemini text models were returned"
        return models, "ok"
    except Exception as exc:
        return [], str(exc)



def verify_and_select_model(configured_model: str, api_key: str) -> ModelResolution:
    configured = _normalize_model_name(configured_model) or "gemini-2.5-flash"
    available, status = _cached_fetch_available_models(api_key)

    if not available:
        note = (
            "Gemini model list verification failed. Falling back to configured model. "
            f"Reason: {status}"
        )
        return ModelResolution(
            configured_model=configured,
            selected_model=configured,
            available_models=[],
            upgraded=False,
            verification_ok=False,
            note=note,
        )

    selected = ""
    for candidate in PREFERRED_STABLE_MODELS:
        if candidate in available:
            selected = candidate
            break

    if not selected:
        if configured in available and _is_strong_enough(configured):
            selected = configured
        else:
            selected = available[0]

    upgraded = configured != selected
    if configured in available and _is_strong_enough(configured):
        note = f"Configured model {configured} is valid. Selected best practical model {selected}."
    elif configured in available:
        note = (
            f"Configured model {configured} is available but weaker for this newsroom workload. "
            f"Upgraded to {selected}."
        )
    else:
        note = (
            f"Configured model {configured} is not available to this API key. "
            f"Using {selected} from verified available models."
        )

    return ModelResolution(
        configured_model=configured,
        selected_model=selected,
        available_models=available,
        upgraded=upgraded,
        verification_ok=True,
        note=note,
    )



def build_langchain_chat_model(model_name: str, api_key: str, temperature: float = 0.2):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        max_retries=2,
    )
