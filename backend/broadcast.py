"""
broadcast.py — Broadcast package helpers for structured segment copy and screenplay text.
"""

from __future__ import annotations

import re
from typing import List, Sequence

from backend.headline_gen import STOPWORDS, build_headline, extract_keywords, generate_overall_headline
from backend.utils import sanitize_text


TOP_TAGS = ["BREAKING", "LIVE", "DEVELOPING", "UPDATE", "LATEST", "ALERT"]
TRANSITIONS = ["cut", "crossfade", "slide", "cut", "crossfade", "fade_out"]
PREFERRED_HEADLINE_TOKENS = {
    "fire", "blaze", "engines", "fatalities", "casualties", "traffic",
    "police", "cause", "probe", "operations", "damage", "smoke",
    "market", "response", "investigators",
}


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


def _facts_from_segment(text: str) -> List[str]:
    facts = []
    for chunk in re.split(r"(?<=[.!?])\s+|;\s+", sanitize_text(text)):
        chunk = chunk.strip()
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
) -> tuple[str, List[dict]]:
    """
    Return the overall program headline and per-segment copy metadata.
    """
    keywords = extract_keywords(article_text)
    overall = generate_overall_headline(article_title, keywords)
    used = {overall}

    packages = []
    total = len(segments)
    for index, seg in enumerate(segments):
        if index == 0 and article_title:
            main_headline = _headline_case(_trim_trailing_stopwords(_truncate_words(article_title, 7).rstrip(".")))
        else:
            rule_headline = _rule_based_headline(seg["text"], article_title, seg["segment_type"])
            if rule_headline:
                main_headline = rule_headline
            else:
                seg_keywords = extract_keywords(seg["text"], top_n=10)
                preferred_bigrams = [
                    kw for kw in seg_keywords
                    if " " in kw and any(token in kw.split() for token in PREFERRED_HEADLINE_TOKENS)
                ]
                keyword_headline = preferred_bigrams[0] if preferred_bigrams else build_headline(seg["text"], keywords, set(used))
                phrase_headline = _headline_phrase(seg["text"], 5)
                main_headline = phrase_headline if len(phrase_headline.split()) >= 3 else keyword_headline
            main_headline = _headline_case(_truncate_words(main_headline.replace(" — Update", " Update"), 6).rstrip("."))
        used.add(main_headline)
        subheadline = _make_subheadline(seg["text"], main_headline)

        if seg["segment_type"] == "intro":
            top_tag = "BREAKING"
        elif seg["segment_type"] == "outro":
            top_tag = "LATEST"
        else:
            top_tag = TOP_TAGS[min(index, len(TOP_TAGS) - 1)]

        transition = TRANSITIONS[min(index, len(TRANSITIONS) - 1)]
        if index == total - 1:
            transition = "fade_out"
        facts = _facts_from_segment(seg["text"])
        editorial_focus = _segment_focus(seg["segment_type"], index, total)
        lower_third = _make_lower_third(main_headline, subheadline)
        ticker_text = _make_ticker_text(main_headline, facts, seg["segment_type"])

        packages.append(
            {
                "segment_id": index + 1,
                "main_headline": main_headline,
                "subheadline": subheadline,
                "top_tag": top_tag,
                "transition": transition,
                "story_beat": seg["segment_type"],
                "editorial_focus": editorial_focus,
                "lower_third": lower_third,
                "ticker_text": ticker_text,
                "headline_reason": (
                    f"Headline focuses on the strongest beat in segment {index + 1} "
                    f"and keeps on-screen copy short."
                ),
                "source_excerpt": _truncate_words(_first_sentence(seg["text"]), 18),
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
