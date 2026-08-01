import json
from functools import lru_cache
import google.generativeai as genai
from config import settings
import time
from google.api_core.exceptions import ResourceExhausted

@lru_cache
def get_model():
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel("gemini-1.5-flash")


CONTENT_MODE_PROMPT = """You are scoring a Reddit post for genuine buying intent relevant to a business.

Business context: {business_context}
Keywords tracked: {keywords}

Post title: {title}
Post body: {body}

Respond ONLY with JSON, no markdown fences, no preamble:
{{"intent_score": <0-100 integer>, "reasoning": "<one sentence>"}}
"""

COMPETITOR_MODE_PROMPT = """You are analyzing a Reddit post for competitor displacement signal.

Client company: {company_name}
Client product: {product_description}
Competitors to watch: {competitors}

Post title: {title}
Post body: {body}

This post was NOT pre-filtered by keyword match, so most posts you see will have
nothing to do with any of the named competitors. Only flag a post as signal if the
text gives you an actual, specific reason to connect it to one of the named
competitors:
  - it names one directly
  - it names an obvious misspelling of one of them
  - it clearly, unambiguously implies one of them ("our current PM tool that has
    a Kanban board and power-ups" strongly implies Trello) - not just "any SaaS
    tool" or "a project management app" in the abstract

Do NOT flag a post just because it describes a generic pain point (task overload,
distraction, hard to find users, unclear positioning, etc.) that many products in
this category could plausibly solve - that is not competitor signal, that is
category-level chatter. Do NOT invent a competitor name that isn't in the
"Competitors to watch" list above, even if the post mentions some other real
product by name. If you cannot point to specific text in the post that ties it to
one of the named competitors, the correct answer is the JSON null literal for
competitor_mentioned - that will be the correct answer for the large majority of
posts you see, and returning null is not a failure, it's the expected default.

Respond ONLY with JSON, no markdown fences, no preamble. Use the JSON null literal
(not the string "null") when there is no match. This exact shape:
{{
  "competitor_mentioned": <name as a string, or JSON null>,
  "pain_point": <short description as a string, or JSON null>,
  "switch_intent": <true or false, JSON booleans not strings>,
  "score": <0-100 integer, 0 if competitor_mentioned is null>,
  "reasoning": "<one sentence citing the specific text that justifies this call>"
}}
"""


def _call(prompt: str) -> dict:
    model = get_model()
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            break
        except ResourceExhausted:
            wait = 30  # free tier resets quickly; safe fixed backoff
            print(f"Gemini rate limit hit, waiting {wait}s before retry ({attempt+1}/3)...")
            time.sleep(wait)
    else:
        raise RuntimeError("Gemini rate limit exceeded after 3 retries")

    text = response.text.strip()
    # Gemini sometimes wraps JSON in ```json fences despite instructions
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def _normalize_competitor_result(result) -> dict:
    """Small/fast models don't always respect the requested JSON shape: seen in
    practice wrapping the object in a list, emitting the *string* "null"/"none"
    instead of an actual null, a string "true"/"false" instead of a boolean, or
    dropping keys (e.g. no "reasoning") entirely. Coerce all of that into the
    shape callers can rely on rather than trusting the model's literal output."""
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        result = {}

    mentioned = result.get("competitor_mentioned")
    if isinstance(mentioned, str) and mentioned.strip().lower() in ("null", "none", ""):
        mentioned = None

    switch_intent = result.get("switch_intent", False)
    if isinstance(switch_intent, str):
        switch_intent = switch_intent.strip().lower() == "true"

    return {
        "competitor_mentioned": mentioned,
        "pain_point": result.get("pain_point") if mentioned else None,
        "switch_intent": bool(switch_intent) if mentioned else False,
        "score": result.get("score", 0) if mentioned else 0,
        "reasoning": result.get("reasoning") or "",
    }


def classify_content_mode(business_context: str, keywords: list[str], title: str, body: str) -> dict:
    prompt = CONTENT_MODE_PROMPT.format(
        business_context=business_context,
        keywords=", ".join(keywords),
        title=title,
        body=body[:2000],  # keep prompt size sane
    )
    return _call(prompt)


def classify_competitor_mode(company_name: str, product_description: str, competitors: list[str], title: str, body: str) -> dict:
    prompt = COMPETITOR_MODE_PROMPT.format(
        company_name=company_name,
        product_description=product_description,
        competitors=", ".join(competitors),
        title=title,
        body=body[:2000],
    )
    return _normalize_competitor_result(_call(prompt))
