"""
broadcast.py — Broadcast package helpers for structured segment copy and screenplay text.
"""

from __future__ import annotations

import re
from typing import List, Sequence

from backend.headline_gen import STOPWORDS, build_headline, extract_keywords, generate_overall_headline
from backend.utils import sanitize_text


TOP_TAGS = ["BREAKING", "LIVE", "DEVELOPING", "UPDATE", "LATEST", "ALERT"]
STORY_PROFILE_KEYWORDS = {
    "crisis": {
        "breaking", "blast", "attack", "fire", "flood", "quake", "crash", "evacuation",
        "casualties", "deaths", "rescue", "emergency", "disaster", "hostage", "war",
    },
    "sports": {
        "match", "tournament", "league", "goal", "final", "semifinal", "championship",
        "athlete", "coach", "score", "penalty", "stadium", "innings", "wins",
    },
    "politics": {
        "parliament", "senate", "cabinet", "minister", "election", "bill", "policy",
        "government", "opposition", "campaign", "democracy", "voter", "party", "diplomatic",
    },
}

TRANSITION_GRAMMAR = {
    "general": {
        "subtle": {
            "intro": ["dissolve", "wipe_reveal"],
            "body": ["hard_cut", "dissolve", "slide_left", "wipe_left"],
            "penultimate": ["dissolve", "wipe_left"],
            "outro": "dip_to_black",
        },
        "standard": {
            "intro": ["wipe_reveal", "push_right", "dissolve", "slide_right"],
            "body": ["hard_cut", "dissolve", "slide_left", "push_left", "wipe_left", "zoom_in", "slide_right", "push_right", "pixel_flow", "dissolve"],
            "penultimate": ["dissolve", "push_left", "wipe_left", "zoom_in"],
            "outro": "dip_to_black",
        },
        "dramatic": {
            "intro": ["stinger", "wipe_reveal", "push_right", "dissolve"],
            "body": ["hard_cut", "stinger", "slide_left", "push_left", "pixel_flow", "zoom_in", "dissolve"],
            "penultimate": ["stinger", "zoom_in", "push_left"],
            "outro": "dip_to_black",
        },
    },
    "crisis": {
        "subtle": {
            "intro": ["wipe_reveal", "dissolve"],
            "body": ["hard_cut", "dissolve", "wipe_left", "push_left"],
            "penultimate": ["dissolve", "wipe_left"],
            "outro": "dip_to_black",
        },
        "standard": {
            "intro": ["wipe_reveal", "push_right", "dissolve"],
            "body": ["hard_cut", "wipe_left", "push_left", "dissolve", "slide_left", "zoom_in"],
            "penultimate": ["stinger", "push_left", "dissolve"],
            "outro": "dip_to_black",
        },
        "dramatic": {
            "intro": ["stinger", "wipe_reveal", "push_right"],
            "body": ["hard_cut", "stinger", "push_left", "wipe_left", "zoom_in", "pixel_flow"],
            "penultimate": ["stinger", "push_left", "zoom_in"],
            "outro": "dip_to_black",
        },
    },
    "sports": {
        "subtle": {
            "intro": ["slide_right", "dissolve"],
            "body": ["slide_left", "push_left", "dissolve", "hard_cut"],
            "penultimate": ["push_left", "dissolve"],
            "outro": "dip_to_black",
        },
        "standard": {
            "intro": ["slide_right", "push_right", "dissolve"],
            "body": ["slide_left", "push_left", "zoom_in", "dissolve", "hard_cut", "slide_right"],
            "penultimate": ["zoom_in", "push_left", "dissolve"],
            "outro": "dip_to_black",
        },
        "dramatic": {
            "intro": ["stinger", "slide_right", "push_right"],
            "body": ["slide_left", "stinger", "push_left", "zoom_in", "pixel_flow", "hard_cut"],
            "penultimate": ["stinger", "zoom_in", "push_left"],
            "outro": "dip_to_black",
        },
    },
    "politics": {
        "subtle": {
            "intro": ["dissolve", "wipe_reveal"],
            "body": ["dissolve", "wipe_left", "push_left", "hard_cut"],
            "penultimate": ["dissolve", "push_left"],
            "outro": "dip_to_black",
        },
        "standard": {
            "intro": ["wipe_reveal", "dissolve", "push_right"],
            "body": ["dissolve", "wipe_left", "push_left", "slide_left", "hard_cut"],
            "penultimate": ["push_left", "dissolve", "zoom_in"],
            "outro": "dip_to_black",
        },
        "dramatic": {
            "intro": ["stinger", "wipe_reveal", "dissolve"],
            "body": ["dissolve", "stinger", "push_left", "wipe_left", "slide_left", "hard_cut"],
            "penultimate": ["stinger", "push_left", "dissolve"],
            "outro": "dip_to_black",
        },
    },
}
PREFERRED_HEADLINE_TOKENS = {
    "fire", "blaze", "engines", "fatalities", "casualties", "traffic",
    "police", "cause", "probe", "operations", "damage", "smoke",
    "market", "response", "investigators",
}
GENERIC_HEADLINE_TOKENS = {
    "story", "update", "report", "reports", "remain", "remains", "news", "latest",
    "details", "issue", "incident", "event", "situation", "coverage",
}
LOW_SIGNAL_RE = re.compile(
    r"(this\s+article\s+is\s+about|for\s+the\s+.*\s+see)|"
    r"(listen\s+to|watch\s+the\s+full|full\s+discussion|podcast|"
    r"apple\s+podcasts?|spotify|youtube)",
    re.IGNORECASE,
)


def _is_low_signal_sentence(text: str) -> bool:
    cleaned = sanitize_text(text).strip()
    if not cleaned:
        return True
    if LOW_SIGNAL_RE.search(cleaned):
        return True
    return len(cleaned.split()) < 4


def _normalize_transition_intensity(value: str | None) -> str:
    intensity = (value or "standard").strip().lower()
    if intensity not in {"subtle", "standard", "dramatic"}:
        return "standard"
    return intensity


def _normalize_transition_profile(value: str | None) -> str:
    profile = (value or "auto").strip().lower()
    if profile in {"auto", "general", "crisis", "sports", "politics"}:
        return profile
    return "auto"


def _infer_story_profile(article_title: str, article_text: str, segments: Sequence[dict]) -> str:
    corpus_parts = [article_title, article_text]
    corpus_parts.extend(segment.get("text", "") for segment in segments[:4])
    corpus = sanitize_text(" ".join(corpus_parts)).lower()
    if not corpus:
        return "general"

    scores = {
        profile: sum(corpus.count(keyword) for keyword in keywords)
        for profile, keywords in STORY_PROFILE_KEYWORDS.items()
    }
    winner = max(scores, key=scores.get)
    return winner if scores[winner] > 0 else "general"


def _pick_transition(
    index: int,
    total: int,
    segment_type: str,
    previous: str | None,
    transition_profile: str,
    transition_intensity: str,
) -> str:
    if total <= 1:
        return "hard_cut"

    profile_grammar = TRANSITION_GRAMMAR.get(transition_profile, TRANSITION_GRAMMAR["general"])
    grammar = profile_grammar.get(transition_intensity, profile_grammar["standard"])

    if index == total - 1 or segment_type == "outro":
        return grammar.get("outro", "dip_to_black")

    if segment_type == "intro":
        pool = grammar.get("intro", ["dissolve"])
    elif index == total - 2:
        pool = grammar.get("penultimate", ["dissolve"])
    else:
        pool = grammar.get("body", ["dissolve"])

    if transition_intensity == "dramatic" and "stinger" in pool:
        major_marks = {1, max(1, total // 2)}
        if index in major_marks and previous != "stinger":
            return "stinger"

    transition = pool[index % len(pool)]

    if transition == previous:
        idx = pool.index(transition) if transition in pool else 0
        transition = pool[(idx + 1) % len(pool)]

    if transition == previous:
        transition = "dissolve"

    return transition


def seconds_to_timecode(value: float) -> str:
    seconds = max(0, int(round(value)))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _truncate_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(" ,.;:") + "..."


def _trim_trailing_stopwords(text: str) -> str:
    words = text.split()
    while words and words[-1].lower() in STOPWORDS:
        words.pop()
    return " ".join(words)


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", sanitize_text(text))
    for part in parts:
        if len(part.split()) >= 4 and not _is_low_signal_sentence(part):
            return part.strip()
    for part in parts:
        if len(part.split()) >= 4:
            return part.strip()
    return sanitize_text(text)


def _headline_case(text: str) -> str:
    words = text.split()
    cleaned = []
    for word in words:
        if word.isupper():
            cleaned.append(word)
        else:
            cleaned.append(word.capitalize())
    return " ".join(cleaned)


def _headline_phrase(text: str, max_words: int = 6) -> str:
    sentence = _first_sentence(text)
    words = []
    for raw in re.findall(r"[A-Za-z0-9']+", sentence):
        token = raw.lower()
        if token in STOPWORDS or len(token) < 3:
            continue
        words.append(raw.capitalize() if not raw.isupper() else raw)
    if len(words) >= 2:
        return " ".join(words[:max_words])
    return _headline_case(_truncate_words(sentence, max_words).rstrip("."))


def _headline_key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _headline_is_weak(text: str) -> bool:
    tokens = [token.lower() for token in re.findall(r"[a-zA-Z0-9']+", text)]
    if len(tokens) < 3 or len(tokens) > 6:
        return True
    unique = len(set(tokens))
    if unique < max(2, len(tokens) - 1):
        return True
    generic_count = sum(1 for token in tokens if token in GENERIC_HEADLINE_TOKENS or token in STOPWORDS)
    if generic_count >= max(2, len(tokens) - 1):
        return True
    if all(token in GENERIC_HEADLINE_TOKENS for token in tokens):
        return True
    return False


def _fallback_headline(text: str, segment_type: str) -> str:
    tokens = []
    for raw in re.findall(r"[A-Za-z0-9']+", _first_sentence(text)):
        token = raw.lower()
        if len(token) < 4 or token in STOPWORDS:
            continue
        tokens.append(raw.capitalize())
    base = " ".join(tokens[:3])
    if not base:
        if segment_type == "intro":
            return "Breaking Story Update"
        if segment_type == "outro":
            return "Latest Verified Update"
        return "Developing Story Update"
    return _headline_case(_truncate_words(base, 6).rstrip("."))


def _ensure_unique_headline(headline: str, used: set[str], used_keys: set[str]) -> str:
    normalized = _headline_key(headline)
    if headline not in used and normalized not in used_keys:
        used.add(headline)
        used_keys.add(normalized)
        return headline

    base = " ".join(headline.split()[:5]) or "Story Update"
    suffix = 2
    while True:
        candidate = f"{base} {suffix}"
        candidate = _headline_case(_truncate_words(candidate, 6).rstrip("."))
        key = _headline_key(candidate)
        if candidate not in used and key not in used_keys:
            used.add(candidate)
            used_keys.add(key)
            return candidate
        suffix += 1


def _rule_based_headline(text: str, article_title: str, segment_type: str) -> str | None:
    lower = text.lower()
    if segment_type == "intro" and article_title:
        return _headline_case(_trim_trailing_stopwords(_truncate_words(article_title, 7).rstrip(".")))
    if segment_type == "outro":
        if any(token in lower for token in ("fire", "blaze", "smoke")):
            return "Fire Response Continues"
        return "Latest Verified Update"

    rules = [
        (("fire engines", "multiple fire"), "Fire Engines Rushed In"),
        (("no fatalities", "no casualties", "fatalities confirmed"), "No Casualties Confirmed Yet"),
        (("traffic", "barricades"), "Traffic Diverted Near Scene"),
        (("investigators", "possible cause", "cause blaze", "probe"), "Cause Of Blaze Under Review"),
        (("smoke",), "Smoke Rises Above Market"),
        (("damage", "assessments"), "Damage Assessment Underway"),
        (("firefighting operations", "operations continue"), "Firefighting Operations Continue"),
        (("police",), "Police Secure Surrounding Area"),
        (("fire", "blaze"), "Major Fire Hits Market"),
    ]
    for needles, headline in rules:
        if any(needle in lower for needle in needles):
            return headline
    return None


def _make_subheadline(text: str, main_headline: str) -> str:
    sentence = _first_sentence(text)
    sentence = re.sub(r"\s+", " ", sentence).strip()
    words = sentence.split()
    if not words:
        return "Latest verified details from the source report"

    trimmed = _truncate_words(sentence, 9)
    if trimmed.lower() == main_headline.lower():
        trimmed = _truncate_words(sentence, 11)
    return _headline_case(trimmed.rstrip("."))


def _story_beat_for_segment(index: int, total: int, segment_type: str) -> str:
    segment_type = (segment_type or "body").lower()
    if index == 0 or segment_type == "intro":
        return "Hook"
    if index == total - 1 or segment_type == "outro":
        return "Closing"

    if total <= 3:
        return "Key development + Impact / response"
    if total == 4:
        if index == 1:
            return "Context"
        if index == 2:
            return "Key development + Impact / response"
        return "Key development"

    if index == 1:
        return "Context"
    if index == total - 2:
        return "Impact / response"
    return "Key development"


def _beat_label_for_subheadline(story_beat: str) -> str:
    normalized = (story_beat or "").lower()
    if "hook" in normalized:
        return "Breaking"
    if "context" in normalized:
        return "Context"
    if "impact" in normalized or "response" in normalized:
        return "Impact"
    if "closing" in normalized:
        return "What next"
    return "Development"


def _subheadline_key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _ensure_unique_subheadline(
    subheadline: str,
    story_beat: str,
    used_subheadline_keys: set[str],
) -> str:
    beat_label = _beat_label_for_subheadline(story_beat)
    base = _headline_case(_truncate_words(subheadline, 11).rstrip("."))
    if beat_label.lower() not in base.lower():
        base = _headline_case(_truncate_words(f"{beat_label}: {base}", 11).rstrip("."))

    key = _subheadline_key(base)
    if key and key not in used_subheadline_keys:
        used_subheadline_keys.add(key)
        return base

    suffix = 2
    while True:
        candidate = _headline_case(_truncate_words(f"{base} {suffix}", 11).rstrip("."))
        candidate_key = _subheadline_key(candidate)
        if candidate_key and candidate_key not in used_subheadline_keys:
            used_subheadline_keys.add(candidate_key)
            return candidate
        suffix += 1


def _facts_from_segment(text: str) -> List[str]:
    facts = []
    for chunk in re.split(r"(?<=[.!?])\s+|;\s+", sanitize_text(text)):
        chunk = chunk.strip()
        if _is_low_signal_sentence(chunk):
            continue
        if len(chunk.split()) >= 5:
            facts.append(_truncate_words(chunk, 14))
        if len(facts) == 3:
            break
    return facts


def _segment_focus(segment_type: str, index: int, total: int) -> str:
    if segment_type == "intro":
        return "Open with the strongest verified hook and establish why the story matters now."
    if segment_type == "outro":
        return "Close with the latest verified status and a clear forward-looking handoff."
    if index == 1:
        return "Add operational detail and move from headline into response on the ground."
    if index == total - 2:
        return "Bring in consequences, restrictions, or accountability details before the close."
    return "Advance the story with a fresh beat so the package keeps moving."


def _make_lower_third(main_headline: str, subheadline: str) -> str:
    lead = _truncate_words(main_headline, 6).rstrip(".")
    support = _truncate_words(subheadline, 8).rstrip(".")
    if support and support.lower() != lead.lower():
        return f"{lead} | {support}"
    return lead


def _make_ticker_text(main_headline: str, facts: Sequence[str], segment_type: str) -> str:
    if segment_type == "intro":
        prefix = "Breaking"
    elif segment_type == "outro":
        prefix = "Latest"
    else:
        prefix = "Update"

    detail = _truncate_words(facts[0], 10).rstrip(".") if facts else _truncate_words(main_headline, 8).rstrip(".")
    return f"{prefix}: {detail}"


def _split_for_cues(text: str, max_words: int = 8) -> List[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", sanitize_text(text)) if part.strip()]
    chunks: List[str] = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) <= max_words:
            chunks.append(sentence)
            continue
        for start in range(0, len(words), max_words):
            chunk = " ".join(words[start:start + max_words]).strip()
            if chunk:
                chunks.append(chunk)
    return chunks or [sanitize_text(text)]


def build_transcript_cues(segments: Sequence[dict]) -> List[dict]:
    cues: List[dict] = []
    for segment in segments:
        chunks = _split_for_cues(segment.get("anchor_narration", ""))
        duration = max(segment.get("duration", 0.0), 0.1)
        cursor = float(segment.get("start_time", 0.0))
        total_words = max(sum(len(chunk.split()) for chunk in chunks), 1)

        for cue_index, chunk in enumerate(chunks, start=1):
            word_share = len(chunk.split()) / total_words
            chunk_duration = round(max(1.1, duration * word_share), 2)
            end = min(float(segment.get("end_time", cursor + chunk_duration)), round(cursor + chunk_duration, 2))
            cues.append(
                {
                    "id": f"s{segment['segment_id']}-c{cue_index}",
                    "segment_id": segment["segment_id"],
                    "start_time": round(cursor, 2),
                    "end_time": end,
                    "start_timecode": seconds_to_timecode(cursor),
                    "end_timecode": seconds_to_timecode(end),
                    "text": chunk,
                    "speaker": "anchor",
                    "emphasis": segment.get("top_tag", ""),
                    "lane": "program",
                }
            )
            cursor = end

        if cues:
            cues[-1]["end_time"] = float(segment.get("end_time", cues[-1]["end_time"]))
            cues[-1]["end_timecode"] = segment.get("end_timecode", cues[-1]["end_timecode"])

    return cues


def build_rundown(segments: Sequence[dict]) -> List[dict]:
    rundown: List[dict] = []
    for segment in segments:
        rundown.append(
            {
                "segment_id": segment["segment_id"],
                "slug": segment.get("main_headline", ""),
                "start_timecode": segment.get("start_timecode", ""),
                "end_timecode": segment.get("end_timecode", ""),
                "editorial_focus": segment.get("editorial_focus", ""),
                "lower_third": segment.get("lower_third", ""),
                "ticker_text": segment.get("ticker_text", ""),
                "camera_motion": segment.get("camera_motion", ""),
                "visual_source_kind": segment.get("visual_source_kind", ""),
                "control_room_cue": segment.get("control_room_cue", ""),
                "director_note": segment.get("director_note", ""),
            }
        )
    return rundown


def generate_segment_copy(
    segments: Sequence[dict],
    article_title: str,
    article_text: str,
    transition_intensity: str = "standard",
    transition_profile: str = "auto",
) -> tuple[str, List[dict]]:
    """
    Return the overall program headline and per-segment copy metadata.
    """
    keywords = extract_keywords(article_text)
    overall = generate_overall_headline(article_title, keywords)
    used = {overall}
    used_keys = {_headline_key(overall)}
    used_subheadline_keys: set[str] = set()

    resolved_intensity = _normalize_transition_intensity(transition_intensity)
    requested_profile = _normalize_transition_profile(transition_profile)
    resolved_profile = _infer_story_profile(article_title, article_text, segments) if requested_profile == "auto" else requested_profile

    packages = []
    total = len(segments)
    previous_transition: str | None = None
    for index, seg in enumerate(segments):
        segment_text_for_copy = sanitize_text(seg["text"])
        story_beat = _story_beat_for_segment(index, total, seg["segment_type"])
        if _is_low_signal_sentence(segment_text_for_copy):
            segment_text_for_copy = sanitize_text(article_title or segment_text_for_copy)

        candidate_pool: List[str] = []
        if index == 0 and article_title:
            candidate_pool.append(_headline_case(_trim_trailing_stopwords(_truncate_words(article_title, 7).rstrip("."))))

        rule_headline = _rule_based_headline(segment_text_for_copy, article_title, seg["segment_type"])
        if rule_headline:
            candidate_pool.append(rule_headline)

        phrase_headline = _headline_phrase(segment_text_for_copy, 5)
        if phrase_headline:
            candidate_pool.append(phrase_headline)

        seg_keywords = extract_keywords(segment_text_for_copy, top_n=10)
        preferred_bigrams = [
            kw for kw in seg_keywords
            if " " in kw and any(token in kw.split() for token in PREFERRED_HEADLINE_TOKENS)
        ]
        keyword_headline = preferred_bigrams[0] if preferred_bigrams else build_headline(segment_text_for_copy, keywords, set(used))
        if keyword_headline:
            candidate_pool.append(keyword_headline)

        candidate_pool.append(_fallback_headline(segment_text_for_copy, seg["segment_type"]))

        selected_headline = ""
        for candidate in candidate_pool:
            normalized_candidate = _headline_case(_truncate_words(candidate.replace(" — Update", " Update"), 6).rstrip("."))
            if not normalized_candidate:
                continue
            key = _headline_key(normalized_candidate)
            if key in used_keys:
                continue
            if _headline_is_weak(normalized_candidate):
                continue
            selected_headline = normalized_candidate
            break

        if not selected_headline:
            for candidate in candidate_pool:
                normalized_candidate = _headline_case(_truncate_words(candidate.replace(" — Update", " Update"), 6).rstrip("."))
                if not normalized_candidate:
                    continue
                key = _headline_key(normalized_candidate)
                if key not in used_keys:
                    selected_headline = normalized_candidate
                    break

        if not selected_headline:
            selected_headline = _fallback_headline(segment_text_for_copy, seg["segment_type"])

        main_headline = _ensure_unique_headline(selected_headline, used, used_keys)
        subheadline = _make_subheadline(segment_text_for_copy, main_headline)
        if len(subheadline.split()) < 5:
            subheadline = _headline_case(_truncate_words(_first_sentence(segment_text_for_copy), 10).rstrip("."))
        subheadline = _ensure_unique_subheadline(subheadline, story_beat, used_subheadline_keys)

        if seg["segment_type"] == "intro":
            top_tag = "BREAKING"
        elif seg["segment_type"] == "outro":
            top_tag = "LATEST"
        else:
            top_tag = TOP_TAGS[min(index, len(TOP_TAGS) - 1)]

        transition = _pick_transition(
            index,
            total,
            seg["segment_type"],
            previous_transition,
            resolved_profile,
            resolved_intensity,
        )
        previous_transition = transition
        facts = _facts_from_segment(segment_text_for_copy)
        editorial_focus = f"{story_beat}: {_segment_focus(seg['segment_type'], index, total)}"
        lower_third = _make_lower_third(main_headline, subheadline)
        ticker_text = _make_ticker_text(main_headline, facts, seg["segment_type"])

        packages.append(
            {
                "segment_id": index + 1,
                "main_headline": main_headline,
                "subheadline": subheadline,
                "top_tag": top_tag,
                "transition": transition,
                "story_beat": story_beat,
                "transition_profile": resolved_profile,
                "transition_intensity": resolved_intensity,
                "editorial_focus": editorial_focus,
                "lower_third": lower_third,
                "ticker_text": ticker_text,
                "headline_reason": (
                    f"Headline tracks the {story_beat.lower()} beat in segment {index + 1} "
                    f"and keeps on-screen copy short."
                ),
                "source_excerpt": _truncate_words(_first_sentence(segment_text_for_copy), 18),
                "factual_points": facts,
            }
        )

    return overall, packages


def build_screenplay_text(
    article_url: str,
    source_title: str,
    total_duration: float,
    segments: Sequence[dict],
) -> str:
    lines = [
        f"Source title: {source_title}",
        f"Article URL: {article_url}",
        f"Target runtime: {seconds_to_timecode(total_duration)}",
        "",
    ]
    for segment in segments:
        lines.extend(
            [
                (
                    f"Segment {segment['segment_id']} "
                    f"[{segment['start_timecode']} - {segment['end_timecode']}] "
                    f"{segment['top_tag']}"
                ),
                f"Layout: {segment['layout']}",
                f"Main headline: {segment['main_headline']}",
                f"Subheadline: {segment['subheadline']}",
                f"Lower third: {segment.get('lower_third', '')}",
                f"Ticker: {segment.get('ticker_text', '')}",
                f"Anchor narration: {segment['anchor_narration']}",
                f"Left panel: {segment['left_panel']}",
                f"Right panel: {segment['right_panel']}",
                f"Camera motion: {segment.get('camera_motion', '')}",
                f"Control room cue: {segment.get('control_room_cue', '')}",
                f"Transition: {segment['transition']}",
                "",
            ]
        )
    return "\n".join(lines).strip()
