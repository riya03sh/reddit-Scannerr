"""
Turn a product URL into a scanner configuration.

Fetches the page, asks the LLM what the product is and who talks about it, then
- and this is the part that matters - checks the answer against live Reddit
before returning it. An unchecked suggestion is worse than none here: this
project has already shipped scanners pointed at a subreddit whose newest post
was seven years old, and keyword sets that matched 0 of 800 posts. Both looked
completely reasonable in the config UI.
"""
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import httpx

from config import settings
from services.prefilter import matches_keywords

# Suggestions are graded against a live sample of each subreddit.
SAMPLE_SIZE = 60
STALE_AFTER_DAYS = 30
MIN_POSTS = 20


class SuggestionError(Exception):
    """The URL couldn't be turned into a usable suggestion."""


# ---- fetching the product page ----

def _assert_public_url(url: str) -> None:
    """Refuse anything that isn't a public http(s) address.

    The URL comes from a signed-in user but is fetched by the server, so without
    this a request for http://169.254.169.254/ or a localhost port turns this
    endpoint into a probe of our own infrastructure.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SuggestionError("URL must start with http:// or https://")
    if not parsed.hostname:
        raise SuggestionError("that doesn't look like a URL")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise SuggestionError(f"couldn't resolve {parsed.hostname}")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise SuggestionError("that URL points to a private address")


_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description|og:title)["\'][^>]+content=["\']([^"\']+)',
    re.I,
)


def fetch_page_text(url: str, max_chars: int = 6000) -> str:
    """Page title, meta description and visible body text, roughly."""
    _assert_public_url(url)
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": settings.reddit_user_agent})
            response.raise_for_status()
            html = response.text
    except httpx.HTTPStatusError as e:
        raise SuggestionError(f"the site returned {e.response.status_code}")
    except httpx.HTTPError:
        raise SuggestionError("couldn't reach that URL")

    parts = []
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if title:
        parts.append(title.group(1))
    parts.extend(_META_RE.findall(html))

    body = _TAG_RE.sub(" ", html)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"&[a-z]+;", " ", body)
    parts.append(body)

    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(text) < 60:
        raise SuggestionError("couldn't read enough text from that page")
    return text[:max_chars]


# ---- asking the model ----

SUGGEST_PROMPT = """You are configuring a Reddit monitoring tool for the business described below.

Website text:
{page_text}

Return JSON only, no markdown fences, no preamble:
{{
  "company_name": "<the business's name>",
  "product_description": "<2-3 sentences: what it does, who for, what problem it solves>",
  "subreddits": ["<12-16 subreddit names, no r/ prefix>"],
  "keywords": ["<15-20 SINGLE words>"],
  "competitors": ["<6-10 named competing products>"]
}}

Rules that matter:
- subreddits: real, active, general-interest communities where this product's
  CUSTOMERS talk about their problems - not where the company would advertise.
  Prefer large established subreddits. Suggest generously; bad ones get filtered
  out afterwards.
- keywords: SINGLE WORDS ONLY. Never phrases. These are matched literally against
  post text, so "conversion tracking broken" matches almost nothing while
  "conversion", "tracking" and "broken" each match plenty. Pick words that appear
  in posts from someone with the problem, not marketing language.
- competitors: actual product names a customer would mention by name.
"""


def _call_llm(prompt: str) -> dict:
    if settings.llm_provider == "groq":
        from services.groq_client import _call
        return _call(prompt, model=settings.groq_model)
    if settings.llm_provider == "ollama":
        from services.ollama_client import _call
        return _call(prompt)
    from services.gemini_client import _call
    return _call(prompt)


# ---- checking the answer against reality ----

def _fetcher():
    if settings.data_source == "reddit":
        from services.reddit_client import fetch_new_posts
    elif settings.data_source == "arctic_shift":
        from services.arctic_shift_client import fetch_new_posts
    else:
        from services.mock_client import fetch_new_posts
    return fetch_new_posts


def validate_subreddits(names: list[str]) -> tuple[list[dict], list[dict]]:
    """Split suggestions into ones with a live audience and ones without.

    A suggested subreddit can be misspelled, private, empty, or years dead -
    all of which look identical in a config screen and produce a scanner that
    silently returns nothing.
    """
    from datetime import datetime, timezone

    fetch = _fetcher()
    keep, drop = [], []
    for name in names:
        clean = name.strip().lstrip("/").removeprefix("r/").strip()
        if not clean:
            continue
        try:
            posts = fetch(clean, limit=SAMPLE_SIZE)
        except Exception:
            drop.append({"name": clean, "reason": "couldn't be reached"})
            continue

        if len(posts) < MIN_POSTS:
            drop.append({"name": clean, "reason": f"only {len(posts)} posts available"})
            continue

        newest = max(p["created_at"] for p in posts)
        age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(newest, tz=timezone.utc)).days
        if age_days > STALE_AFTER_DAYS:
            drop.append({"name": clean, "reason": f"newest post is {age_days} days old"})
            continue

        keep.append({"name": clean, "sample_posts": len(posts), "newest_post_days": age_days, "_posts": posts})
    return keep, drop


def score_keywords(keywords: list[str], sampled: list[dict]) -> dict:
    """What fraction of real posts these keywords actually select.

    The prefilter runs before the LLM, so a keyword set that matches nothing
    makes the whole scanner silently dead no matter how good the model is.
    """
    posts = [p for s in sampled for p in s["_posts"]]
    if not posts:
        return {"pass_rate": None, "sampled_posts": 0, "per_keyword": {}}

    matched = sum(1 for p in posts if matches_keywords(p["title"], p["body"], keywords))
    per_keyword = {
        kw: sum(1 for p in posts if matches_keywords(p["title"], p["body"], [kw]))
        for kw in keywords
    }
    return {
        "pass_rate": round(matched / len(posts), 3),
        "sampled_posts": len(posts),
        "per_keyword": per_keyword,
    }


def suggest_from_url(url: str) -> dict:
    """Full pipeline: page -> model -> validated, graded suggestion."""
    page_text = fetch_page_text(url)

    try:
        raw = _call_llm(SUGGEST_PROMPT.format(page_text=page_text))
    except Exception as e:
        raise SuggestionError(f"couldn't analyse that page: {e}")
    if not isinstance(raw, dict):
        raise SuggestionError("the model returned an unexpected shape")

    # Models still emit phrases here despite the instruction; a multi-word keyword
    # is the single most common way to end up with a scanner that matches nothing,
    # so split them into their component words rather than passing them through.
    keywords, seen = [], set()
    for kw in raw.get("keywords", []) or []:
        for word in str(kw).lower().split():
            word = word.strip(",.\"'()")
            if len(word) > 2 and word not in seen:
                seen.add(word)
                keywords.append(word)

    kept, dropped = validate_subreddits(raw.get("subreddits", []) or [])
    grading = score_keywords(keywords, kept) if keywords else {"pass_rate": None}

    return {
        "company_name": (raw.get("company_name") or "").strip(),
        "product_description": (raw.get("product_description") or "").strip(),
        "subreddits": [{k: v for k, v in s.items() if k != "_posts"} for s in kept],
        "rejected_subreddits": dropped,
        "keywords": keywords,
        "competitors": [str(c).strip() for c in (raw.get("competitors") or []) if str(c).strip()],
        "keyword_grading": grading,
    }
