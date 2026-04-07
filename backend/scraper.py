"""
scraper.py — Multi-source article extractor
Attempts 3 methods in priority order and scores each result.
"""

from collections import Counter
import json
import re
import requests
from typing import List, Optional, Tuple
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
MIN_PRIMARY_WORDS = 120
MIN_FALLBACK_WORDS = 80
JUNK_LINE_RE = re.compile(
    r"(cookie|subscribe|newsletter|sign in|advertis|privacy policy|terms of use|all rights reserved)",
    re.IGNORECASE,
)
PROMOTIONAL_LINE_RE = re.compile(
    r"(listen\s+to|watch\s+the\s+full|full\s+discussion|podcast|episode\s+\d+|"
    r"apple\s+podcasts?|spotify|youtube|follow\s+us|join\s+our\s+channel|"
    r"read\s+more\s+at|download\s+our\s+app|click\s+here|"
    r"whatsapp\s+channel|support\s+us|reporting\s+fund|write\s+to\s+us|"
    r"send\s+your\s+thoughts|quick\s+feedback\s+form)",
    re.IGNORECASE,
)
BOILERPLATE_OPENERS_RE = re.compile(
    r"(this\s+article\s+is\s+about|for\s+the\s+.*\s+see|photo\s+of|image\s+credit)",
    re.IGNORECASE,
)


def _has_min_words(text: str, min_words: int = MIN_PRIMARY_WORDS) -> bool:
    return len((text or "").split()) >= min_words


# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------


def _looks_promotional(chunk: str) -> bool:
    lower = chunk.lower().strip()
    if not lower:
        return False
    if not PROMOTIONAL_LINE_RE.search(lower):
        return False

    # Promotional lines are usually short CTA statements, not factual reporting.
    token_count = len(lower.split())
    return token_count <= 48


def _looks_boilerplate(chunk: str) -> bool:
    lower = chunk.lower().strip()
    if not lower:
        return False

    if BOILERPLATE_OPENERS_RE.search(lower):
        return True

    if lower.startswith("for the ") and " see " in lower:
        return True

    return False


def _clean_article_text_with_meta(text: str) -> Tuple[str, dict]:
    text = sanitize_text(text)
    # Drop repetitive junk lines that often survive extraction.
    cleaned_lines = []
    dropped_samples = []
    raw_chunks = []
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        raw_chunks.append(chunk)
        if len(chunk.split()) < 4:
            if len(dropped_samples) < 3:
                dropped_samples.append(chunk)
            continue
        if JUNK_LINE_RE.search(chunk):
            if len(dropped_samples) < 3:
                dropped_samples.append(chunk)
            continue
        if _looks_promotional(chunk):
            if len(dropped_samples) < 3:
                dropped_samples.append(chunk)
            continue
        if _looks_boilerplate(chunk):
            if len(dropped_samples) < 3:
                dropped_samples.append(chunk)
            continue
        cleaned_lines.append(chunk)

    text = " ".join(cleaned_lines)
    text = re.sub(r"\s+", " ", text).strip()
    raw_word_count = len(" ".join(raw_chunks).split())
    cleaned_word_count = len(text.split())
    kept_ratio = round(cleaned_word_count / max(raw_word_count, 1), 3)
    return text, {
        "raw_word_count": raw_word_count,
        "cleaned_word_count": cleaned_word_count,
        "kept_ratio": kept_ratio,
        "dropped_samples": dropped_samples,
    }


def _clean_article_text(text: str) -> str:
    cleaned, _ = _clean_article_text_with_meta(text)
    return cleaned


def _preview_excerpt(text: str, words: int = 36) -> str:
    parts = text.split()
    if len(parts) <= words:
        return " ".join(parts)
    return " ".join(parts[:words]).rstrip(" ,.;:") + "..."


def _dedupe_http_images(images: List[str], limit: int = 20) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for img in images:
        if not isinstance(img, str):
            continue
        if not img.startswith("http"):
            continue
        if img in seen:
            continue
        seen.add(img)
        deduped.append(img)
        if len(deduped) >= limit:
            break
    return deduped


def _summarize_dom_tags(soup: BeautifulSoup, limit: int = 6) -> List[str]:
    counts = Counter()
    for node in soup.find_all(True):
        name = (node.name or "").strip().lower()
        if not name or name in {"script", "style", "noscript"}:
            continue
        counts[name] += 1
    return [f"{name}:{count}" for name, count in counts.most_common(limit)]


def _describe_container(node) -> str:
    if node is None or not getattr(node, "name", None):
        return "unknown"
    name = str(node.name).lower()
    node_id = node.get("id") if hasattr(node, "get") else None
    classes = node.get("class") if hasattr(node, "get") else []
    class_suffix = ""
    if classes:
        class_suffix = "." + ".".join(str(value) for value in classes[:2])
    id_suffix = f"#{node_id}" if node_id else ""
    return f"{name}{id_suffix}{class_suffix}"

def _extract_newspaper(url: str) -> Optional[dict]:
    """Extractor 1: newspaper3k"""
    try:
        import newspaper
        article = newspaper.Article(url, headers=HEADERS, request_timeout=REQUEST_TIMEOUT)
        article.download()
        article.parse()
        if not _has_min_words(article.text, MIN_PRIMARY_WORDS):
            return None
        images = list(article.images)[:20]
        authors = article.authors or []
        return {
            "title": article.title or "",
            "text": article.text,
            "top_image": article.top_image or None,
            "images": images,
            "authors": authors,
            "published_date": str(article.publish_date) if article.publish_date else None,
            "method": "newspaper3k",
            "selector_used": "newspaper3k::article",
            "dom_tags": [],
            "extraction_signals": [
                "newspaper3k parser extracted article body and metadata.",
            ],
            "method_details": {
                "image_count": len(images),
                "author_count": len(authors),
            },
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
        summary_soup = BeautifulSoup(raw, "lxml")
        content_container = summary_soup.find(["article", "main", "section", "div"]) or summary_soup
        text = summary_soup.get_text(separator=" ")
        text = _clean_article_text(text)
        if not _has_min_words(text, MIN_PRIMARY_WORDS):
            return None
        paragraph_count = len(summary_soup.find_all("p"))
        return {
            "title": doc.title() or "",
            "text": text,
            "top_image": None,
            "images": [],
            "authors": [],
            "published_date": None,
            "method": "readability",
            "selector_used": "readability::summary",
            "dom_tags": _summarize_dom_tags(content_container),
            "extraction_signals": [
                "Readability summary selected the primary article content.",
                f"Detected {paragraph_count} paragraph tags in summary output.",
            ],
            "method_details": {
                "paragraph_count": paragraph_count,
                "container": _describe_container(content_container),
            },
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
        text = _clean_article_text(text)
        if not _has_min_words(text, MIN_PRIMARY_WORDS):
            return None

        return {
            "title": title,
            "text": text,
            "top_image": images[0] if images else None,
            "images": images[:20],
            "authors": [a for a in authors if a],
            "published_date": published_date,
            "method": "json_ld",
            "selector_used": "script[type=application/ld+json]",
            "dom_tags": ["script:application/ld+json"],
            "extraction_signals": [
                f"Parsed {len(blocks)} JSON-LD script blocks.",
                f"Collected {len(texts)} text fields from schema payload.",
            ],
            "method_details": {
                "json_ld_blocks": len(blocks),
                "text_fields": len(texts),
            },
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
        text = _clean_article_text(text)

        if not _has_min_words(text, MIN_PRIMARY_WORDS):
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
            "selector_used": _describe_container(body),
            "dom_tags": _summarize_dom_tags(body),
            "extraction_signals": [
                "Removed script/style/nav/footer elements before text extraction.",
                f"Primary container: {_describe_container(body)}.",
            ],
            "method_details": {
                "paragraph_count": len(paragraphs),
                "image_count": len(imgs),
            },
        }
    except Exception as e:
        log.warning(f"BeautifulSoup failed: {e}")
        return None


def _extract_trafilatura(url: str, html: str) -> Optional[dict]:
    """Extractor 5: trafilatura (optional)."""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
            output_format="json",
        )
        if not extracted:
            return None
        payload = json.loads(extracted)
        text = _clean_article_text(payload.get("text", ""))
        if not _has_min_words(text, MIN_PRIMARY_WORDS):
            return None
        return {
            "title": payload.get("title", ""),
            "text": text,
            "top_image": None,
            "images": [],
            "authors": payload.get("author", []) if isinstance(payload.get("author"), list) else [],
            "published_date": payload.get("date"),
            "method": "trafilatura",
            "selector_used": "trafilatura::main_content",
            "dom_tags": [],
            "extraction_signals": [
                "Trafilatura extracted cleaned long-form article text.",
            ],
            "method_details": {
                "source": "trafilatura",
            },
        }
    except Exception as e:
        log.warning(f"trafilatura failed: {e}")
        return None


def _extract_jina_reader(url: str) -> Optional[dict]:
    """Extractor 6: jina.ai reader proxy fallback for JS-heavy / bot-protected pages."""
    try:
        raw_url = (url or "").strip()
        if not raw_url:
            return None
        if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = f"https://{raw_url}"

        endpoints = [f"https://r.jina.ai/{raw_url}"]
        if raw_url.startswith("https://"):
            endpoints.append(f"https://r.jina.ai/http://{raw_url.removeprefix('https://')}")

        for endpoint in endpoints:
            try:
                resp = requests.get(endpoint, headers=HEADERS, timeout=REQUEST_TIMEOUT + 10)
                resp.raise_for_status()
            except Exception:
                continue

            raw_text = resp.text or ""
            cleaned = _clean_article_text(raw_text)
            if not _has_min_words(cleaned, MIN_PRIMARY_WORDS):
                continue

            first_line = next((line.strip() for line in raw_text.splitlines() if line.strip()), "")
            title = sanitize_text(first_line)

            return {
                "title": title,
                "text": cleaned,
                "top_image": None,
                "images": [],
                "authors": [],
                "published_date": None,
                "method": "jina_reader",
                "selector_used": "r.jina.ai::reader_proxy",
                "dom_tags": [],
                "extraction_signals": [
                    "Reader proxy extracted text from a JS-heavy or extraction-resistant page.",
                ],
                "method_details": {
                    "endpoint": endpoint,
                },
            }

        return None
    except Exception as e:
        log.warning(f"jina reader fallback failed: {e}")
        return None


def _extract_raw_html_text(url: str, html: str) -> Optional[dict]:
    """Extractor 7: last-resort full-page text extraction."""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()

        text = _clean_article_text(soup.get_text(separator=" ", strip=True))
        if not _has_min_words(text, MIN_FALLBACK_WORDS):
            return None

        title_node = soup.find("h1") or soup.find("title")
        title = sanitize_text(title_node.get_text(strip=True) if title_node else "")

        return {
            "title": title,
            "text": text,
            "top_image": None,
            "images": [],
            "authors": [],
            "published_date": None,
            "method": "raw_html",
            "selector_used": "document::full_text_fallback",
            "dom_tags": _summarize_dom_tags(soup),
            "extraction_signals": [
                "Used full-page text fallback because primary extractors found insufficient article body.",
            ],
            "method_details": {
                "fallback": "full_page_text",
            },
        }
    except Exception as e:
        log.warning(f"raw html fallback failed: {e}")
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
    junk_hits = sum(lower.count(token) for token in (" href ", " src ", " cookie ", " subscribe ", " javascript ", " sign in "))
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
    method_bonus = {
        "newspaper3k": 0.1,
        "readability": 0.07,
        "json_ld": 0.07,
        "beautifulsoup": 0.02,
        "trafilatura": 0.08,
        "jina_reader": 0.06,
        "raw_html": 0.01,
    }.get(
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
    attempts = []

    def _register_candidate(method_name: str, result: Optional[dict], reason_if_failed: str) -> None:
        if not result:
            attempts.append(
                {
                    "method": method_name,
                    "status": "failed",
                    "reason": reason_if_failed,
                }
            )
            return

        cleaned, cleaning_meta = _clean_article_text_with_meta(result.get("text", ""))
        result["text"] = cleaned
        result["cleaning_meta"] = cleaning_meta
        result["method"] = method_name
        score = _score(result)
        candidates.append((result, score))
        attempts.append(
            {
                "method": method_name,
                "status": "accepted",
                "reason": "Extractor returned usable cleaned article text.",
                "word_count": cleaning_meta.get("cleaned_word_count", 0),
                "kept_ratio": cleaning_meta.get("kept_ratio", 0.0),
                "preview_excerpt": _preview_excerpt(cleaned),
                "selector_used": result.get("selector_used", ""),
                "dom_tags": result.get("dom_tags", []),
                "extraction_signals": result.get("extraction_signals", []),
                "method_details": result.get("method_details", {}),
            }
        )

    r1 = _extract_newspaper(url)
    _register_candidate("newspaper3k", r1, "Extractor returned no usable article text.")

    r6 = _extract_jina_reader(url)
    _register_candidate("jina_reader", r6, "Reader proxy fallback returned insufficient article text.")

    if html:
        r2 = _extract_readability(url, html)
        _register_candidate("readability", r2, "Extractor returned no usable article text.")

        r3 = _extract_json_ld(url, html)
        _register_candidate("json_ld", r3, "No valid article body found in JSON-LD metadata.")

        r4 = _extract_beautifulsoup(url, html)
        _register_candidate("beautifulsoup", r4, "DOM fallback extractor could not produce clean article text.")

        r5 = _extract_trafilatura(url, html)
        _register_candidate("trafilatura", r5, "Trafilatura parser returned insufficient content.")

        r7 = _extract_raw_html_text(url, html)
        _register_candidate("raw_html", r7, "Full-page fallback text was too short or too noisy.")
    else:
        attempts.extend(
            [
                {
                    "method": "readability",
                    "status": "failed",
                    "reason": "HTML fetch failed before readability extraction.",
                },
                {
                    "method": "json_ld",
                    "status": "failed",
                    "reason": "HTML fetch failed before JSON-LD extraction.",
                },
                {
                    "method": "beautifulsoup",
                    "status": "failed",
                    "reason": "HTML fetch failed before BeautifulSoup extraction.",
                },
                {
                    "method": "trafilatura",
                    "status": "failed",
                    "reason": "HTML fetch failed before Trafilatura extraction.",
                },
                {
                    "method": "raw_html",
                    "status": "failed",
                    "reason": "HTML fetch failed before full-page fallback extraction.",
                },
            ]
        )

    if not candidates:
        raise ValueError(
            "All extraction methods failed - URL may block automated extraction or has too little article text. "
            "Try a direct article URL pattern like /news/<slug> or /article/<slug> (avoid homepages, category pages, and login-only pages)."
        )

    # Sort descending by score
    candidates.sort(key=lambda x: x[1], reverse=True)
    best, best_score = candidates[0]
    log.info(f"Best extractor: {best['method']} (score={best_score})")

    # Truncate if very long
    words = best["text"].split()
    if len(words) > config.MAX_ARTICLE_LENGTH // 5:
        best["text"] = " ".join(words[: config.MAX_ARTICLE_LENGTH // 5])
        log.info(f"Article truncated to {config.MAX_ARTICLE_LENGTH // 5} words")

    best["text"] = _clean_article_text(best["text"])
    best["title"] = sanitize_text(best.get("title", ""))
    best["url"] = url
    best["source_domain"] = extract_domain(url)
    best["word_count"] = len(best["text"].split())
    best["extraction_score"] = best_score
    deduped_images = _dedupe_http_images(best.get("images", []), limit=20)

    # If the best text extractor has sparse/empty imagery, borrow images from
    # other accepted candidates so visual planning can still ground to source.
    image_fallback_applied = False
    if not deduped_images:
        fallback_pool: List[str] = []
        for candidate_result, _score_value in candidates[1:]:
            top = candidate_result.get("top_image")
            if isinstance(top, str) and top.startswith("http"):
                fallback_pool.append(top)
            fallback_pool.extend(candidate_result.get("images", []))
        deduped_images = _dedupe_http_images(fallback_pool, limit=20)
        if deduped_images:
            image_fallback_applied = True
            if not best.get("top_image"):
                best["top_image"] = deduped_images[0]

    best["images"] = deduped_images
    best["image_fallback_applied"] = image_fallback_applied

    candidate_rows = []
    for item, score in candidates:
        cleaning_meta = item.get("cleaning_meta", {})
        selected = item["method"] == best["method"]
        candidate_rows.append(
            {
                "method": item["method"],
                "score": score,
                "title": item.get("title", ""),
                "word_count": len(item.get("text", "").split()),
                "image_count": len(item.get("images", [])),
                "selected": selected,
                "preview_excerpt": _preview_excerpt(item.get("text", "")),
                "kept_ratio": cleaning_meta.get("kept_ratio", 1.0),
                "dropped_samples": cleaning_meta.get("dropped_samples", []),
                "image_preview": item.get("images", [])[:3],
                "status": "accepted",
                "reason": (
                    "Selected as best extraction candidate for downstream pipeline."
                    if selected
                    else "Valid extraction candidate but lower quality score than selected method."
                ),
                "selector_used": item.get("selector_used", ""),
                "dom_tags": item.get("dom_tags", []),
                "extraction_signals": item.get("extraction_signals", []),
                "method_details": item.get("method_details", {}),
            }
        )

    accepted_methods = {row["method"] for row in candidate_rows}
    for attempt in attempts:
        if attempt.get("status") != "failed":
            continue
        if attempt["method"] in accepted_methods:
            continue
        candidate_rows.append(
            {
                "method": attempt["method"],
                "score": 0.0,
                "title": "",
                "word_count": 0,
                "image_count": 0,
                "selected": False,
                "preview_excerpt": "",
                "kept_ratio": 0.0,
                "dropped_samples": [],
                "image_preview": [],
                "status": "failed",
                "reason": attempt.get("reason", "Extractor failed."),
                "selector_used": "",
                "dom_tags": [],
                "extraction_signals": [],
                "method_details": {},
            }
        )

    best["candidates"] = candidate_rows
    best["extraction_attempts"] = attempts

    return best
