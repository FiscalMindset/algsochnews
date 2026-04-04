"""
scraper.py — Multi-source article extractor
Attempts 3 methods in priority order and scores each result.
"""

import json
import re
import requests
from typing import Optional
from bs4 import BeautifulSoup
from backend.utils import get_logger, sanitize_text, extract_domain, config

log = get_logger("scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------

def _extract_newspaper(url: str) -> Optional[dict]:
    """Extractor 1: newspaper3k"""
    try:
        import newspaper
        article = newspaper.Article(url, headers=HEADERS, request_timeout=REQUEST_TIMEOUT)
        article.download()
        article.parse()
        if not article.text or len(article.text) < 200:
            return None
        return {
            "title": article.title or "",
            "text": article.text,
            "top_image": article.top_image or None,
            "images": list(article.images)[:20],
            "authors": article.authors or [],
            "published_date": str(article.publish_date) if article.publish_date else None,
            "method": "newspaper3k",
        }
    except Exception as e:
        log.warning(f"newspaper3k failed: {e}")
        return None


def _extract_readability(url: str, html: str) -> Optional[dict]:
    """Extractor 2: readability-lxml"""
    try:
        from readability import Document
        doc = Document(html)
        raw = doc.summary()
        soup = BeautifulSoup(raw, "lxml")
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 200:
            return None
        return {
            "title": doc.title() or "",
            "text": text,
            "top_image": None,
            "images": [],
            "authors": [],
            "published_date": None,
            "method": "readability",
        }
    except Exception as e:
        log.warning(f"readability failed: {e}")
        return None


def _extract_json_ld(url: str, html: str) -> Optional[dict]:
    """Extractor 3: schema.org JSON-LD."""
    try:
        soup = BeautifulSoup(html, "lxml")
        blocks = soup.find_all("script", attrs={"type": "application/ld+json"})
        texts = []
        images = []
        title = ""
        authors = []
        published_date = None

        for block in blocks:
            raw = (block.string or block.get_text() or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                body = item.get("articleBody") or item.get("description")
                if body:
                    texts.append(body)
                if not title:
                    title = item.get("headline") or item.get("name") or ""
                img = item.get("image")
                if isinstance(img, str):
                    images.append(img)
                elif isinstance(img, list):
                    images.extend(i for i in img if isinstance(i, str))
                author = item.get("author")
                if isinstance(author, dict) and author.get("name"):
                    authors.append(author["name"])
                elif isinstance(author, list):
                    authors.extend(a.get("name") for a in author if isinstance(a, dict) and a.get("name"))
                if not published_date:
                    published_date = item.get("datePublished")

        text = sanitize_text(" ".join(texts))
        if len(text) < 200:
            return None

        return {
            "title": title,
            "text": text,
            "top_image": images[0] if images else None,
            "images": images[:20],
            "authors": [a for a in authors if a],
            "published_date": published_date,
            "method": "json_ld",
        }
    except Exception as e:
        log.warning(f"json-ld failed: {e}")
        return None


def _extract_beautifulsoup(url: str, html: str) -> Optional[dict]:
    """Extractor 4: BeautifulSoup fallback"""
    try:
        soup = BeautifulSoup(html, "lxml")

        # Remove cruft
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "button", "iframe", "noscript"]):
            tag.decompose()

        # Title
        title = (
            soup.find("h1") or soup.find("title") or soup.find("meta", {"property": "og:title"})
        )
        title_text = title.get_text(strip=True) if title else ""

        # Extract images from meta
        og_image = soup.find("meta", {"property": "og:image"})
        top_image = og_image["content"] if og_image and og_image.get("content") else None

        # Body text — prioritise article/main tags
        body = (
            soup.find("article") or soup.find("main") or
            soup.find("div", class_=re.compile(r"article|content|story|body|post", re.I))
            or soup.body
        )
        if not body:
            return None

        paragraphs = body.find_all("p")
        text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) < 200:
            return None

        # All images
        imgs = [
            img["src"]
            for img in soup.find_all("img", src=True)
            if img["src"].startswith("http")
        ]

        return {
            "title": title_text,
            "text": text,
            "top_image": top_image,
            "images": imgs[:20],
            "authors": [],
            "published_date": None,
            "method": "beautifulsoup",
        }
    except Exception as e:
        log.warning(f"BeautifulSoup failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(result: dict) -> float:
    """
    Score an extraction result (0.0 – 1.0).
    Factors: text length, noise ratio, metadata richness.
    """
    if not result:
        return 0.0
    text = result.get("text", "")
    word_c = len(text.split())

    # length score (saturates at 800 words)
    length_score = min(word_c / 800, 1.0)

    # noise: ratio of alphabetic chars to total
    alpha = sum(c.isalpha() or c.isspace() for c in text)
    noise_score = alpha / max(len(text), 1)

    # penalty for leftover markup / CMS junk
    lower = text.lower()
    junk_hits = sum(lower.count(token) for token in (" href ", " src ", " cookie ", " subscribe ", " javascript "))
    markup_penalty = min(junk_hits * 0.03, 0.18)

    # metadata bonus
    meta_score = 0.0
    if result.get("title"):
        meta_score += 0.1
    if result.get("top_image"):
        meta_score += 0.1
    if result.get("authors"):
        meta_score += 0.05
    if result.get("published_date"):
        meta_score += 0.05

    # method bonus
    method_bonus = {"newspaper3k": 0.1, "readability": 0.05, "json_ld": 0.07, "beautifulsoup": 0.0}.get(
        result.get("method", ""), 0.0
    )

    score = 0.5 * length_score + 0.3 * noise_score + 0.1 * meta_score + 0.1 * method_bonus - markup_penalty
    return round(min(score, 1.0), 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_article(url: str) -> dict:
    """
    Run all extractors, pick best-scoring result.
    Returns cleaned article dict or raises ValueError.
    """
    log.info(f"Scraping: {url}")

    # Fetch HTML once for extractors 2 & 3
    html = ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.warning(f"HTML fetch failed: {e}")

    candidates = []

    r1 = _extract_newspaper(url)
    if r1:
        candidates.append((r1, _score(r1)))

    if html:
        r2 = _extract_readability(url, html)
        if r2:
            candidates.append((r2, _score(r2)))

        r3 = _extract_json_ld(url, html)
        if r3:
            candidates.append((r3, _score(r3)))

        r4 = _extract_beautifulsoup(url, html)
        if r4:
            candidates.append((r4, _score(r4)))

    if not candidates:
        raise ValueError("All extraction methods failed — could not parse article.")

    # Sort descending by score
    candidates.sort(key=lambda x: x[1], reverse=True)
    best, best_score = candidates[0]
    log.info(f"Best extractor: {best['method']} (score={best_score})")

    # Truncate if very long
    words = best["text"].split()
    if len(words) > config.MAX_ARTICLE_LENGTH // 5:
        best["text"] = " ".join(words[: config.MAX_ARTICLE_LENGTH // 5])
        log.info(f"Article truncated to {config.MAX_ARTICLE_LENGTH // 5} words")

    best["text"] = sanitize_text(best["text"])
    best["title"] = sanitize_text(best.get("title", ""))
    best["url"] = url
    best["source_domain"] = extract_domain(url)
    best["word_count"] = len(best["text"].split())
    best["extraction_score"] = best_score
    best["candidates"] = [
        {
            "method": item["method"],
            "score": score,
            "title": item.get("title", ""),
            "word_count": len(item.get("text", "").split()),
            "image_count": len(item.get("images", [])),
            "selected": item["method"] == best["method"],
        }
        for item, score in candidates
    ]

    return best
