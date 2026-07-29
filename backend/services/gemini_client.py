import json
from functools import lru_cache
import google.generativeai as genai
from config import settings
import time
from google.api_core.exceptions import ResourceExhausted

def _call(prompt: str) -> dict:
    model = get_model()
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            break
        except ResourceExhausted as e:
            wait = 30  # free tier resets quickly; safe fixed backoff
            print(f"Gemini rate limit hit, waiting {wait}s before retry ({attempt+1}/3)...")
            time.sleep(wait)
    else:
        raise RuntimeError("Gemini rate limit exceeded after 3 retries")

    text = response.text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

@lru_cache
def get_model():
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel("gemini-3.5-flash-lite")


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

Determine: does this post express dissatisfaction with one of the named competitors,
and would the client's product plausibly address that pain point?

Respond ONLY with JSON, no markdown fences, no preamble:
{{
  "competitor_mentioned": "<name or null>",
  "pain_point": "<short description or null>",
  "switch_intent": <true/false>,
  "score": <0-100 integer>,
  "reasoning": "<one sentence>"
}}
"""


def _call(prompt: str) -> dict:
    model = get_model()
    response = model.generate_content(prompt)
    text = response.text.strip()
    # Gemini sometimes wraps JSON in ```json fences despite instructions
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


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
    return _call(prompt)
