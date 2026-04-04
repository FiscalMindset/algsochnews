"""
headline_gen.py — Rule-based keyword extraction and headline building.
No LLM required — uses frequency analysis and stop-word filtering.
"""

import re
import string
from collections import Counter
from typing import List
from backend.utils import get_logger, word_count

log = get_logger("headline_gen")

# ------------------------------------------------------------------ #
# Extended stop-word list
# ------------------------------------------------------------------ #
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "dare",
    "this", "that", "these", "those", "it", "its", "he", "she", "they",
    "we", "you", "i", "me", "him", "her", "them", "us", "my", "your",
    "his", "her", "their", "our", "also", "just", "not", "more", "very",
    "about", "into", "after", "before", "between", "through", "during",
    "then", "than", "if", "when", "while", "who", "which", "what", "how",
    "where", "why", "as", "such", "so", "no", "other", "some", "any",
    "all", "both", "many", "much", "few", "new", "said", "says", "say",
    "one", "two", "three", "four", "five", "first", "second", "last",
    "including", "according", "however", "therefore", "because", "although",
}


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    return [t for t in text.split() if t and t not in STOPWORDS and len(t) > 2]


def _bigrams(tokens: List[str]) -> List[str]:
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def extract_keywords(text: str, top_n: int = 15) -> List[str]:
    """
    Extract top keywords using unigram + bigram frequency.
    Returns deduplicated sorted keyword list.
    """
    tokens = _tokenize(text)
    unigram_freq = Counter(tokens)
    bigram_freq = Counter(_bigrams(tokens))

    # Score bigrams higher if both constituent words score high
    scores: dict[str, float] = {}
    for word, cnt in unigram_freq.items():
        scores[word] = cnt

    for bigram, cnt in bigram_freq.most_common(50):
        w1, w2 = bigram.split()
        u_score = (unigram_freq[w1] + unigram_freq[w2]) / 2
        scores[bigram] = cnt * 1.4 + u_score * 0.3   # bigram boost

    top = sorted(scores, key=scores.get, reverse=True)[:top_n]
    return top


def _title_case(text: str) -> str:
    """Title-case a phrase, preserving all-caps abbreviations."""
    words = text.split()
    result = []
    for w in words:
        if w.isupper() and len(w) > 1:
            result.append(w)
        else:
            result.append(w.capitalize())
    return " ".join(result)


def build_headline(segment_text: str, article_keywords: List[str], used: set) -> str:
    """
    Build a short (≤ 8 words) headline for a segment.
    Strategy:
    1. Pick top keywords present in segment.
    2. Compose a concise phrase.
    3. Avoid repeating headlines.
    """
    seg_tokens = set(_tokenize(segment_text))
    # rank article keywords by presence in this segment
    relevant = [kw for kw in article_keywords if any(t in seg_tokens for t in kw.split())]

    if not relevant:
        # Fall back to the first sentence, truncated
        first_sent = re.split(r"[.!?]", segment_text)[0].strip()
        words = first_sent.split()[:8]
        candidate = _title_case(" ".join(words))
    else:
        # Build headline from top 2 relevant keywords
        phrase_parts = relevant[:2]
        candidate = _title_case(" ".join(phrase_parts))

    # Ensure uniqueness
    base = candidate
    suffix = 1
    while candidate in used:
        candidate = f"{base} — Update {suffix}"
        suffix += 1

    used.add(candidate)
    return candidate


def generate_overall_headline(title: str, keywords: List[str]) -> str:
    """
    Generate the main video headline from article title + keywords.
    """
    if title and len(title.split()) >= 4:
        # Clean and truncate the title
        clean = re.sub(r"\s*[|\-–—]\s*.*$", "", title).strip()
        words = clean.split()[:10]
        return _title_case(" ".join(words))
    else:
        return _title_case(" ".join(keywords[:6]))


def generate_all_headlines(
    article_title: str,
    segments: List[dict],
    article_text: str,
) -> tuple[str, List[str]]:
    """
    Returns (overall_headline, list_of_segment_headlines).
    """
    keywords = extract_keywords(article_text)
    log.debug(f"Top keywords: {keywords[:10]}")

    overall = generate_overall_headline(article_title, keywords)
    log.info(f"Overall headline: {overall!r}")

    used_headlines: set = {overall}
    seg_headlines = []
    for seg in segments:
        h = build_headline(seg["text"], keywords, used_headlines)
        seg_headlines.append(h)

    return overall, seg_headlines
