"""Groq - fast, cloud-hosted, free tier at 30 req/min (2x Gemini's free tier).
Same interface as gemini_client.py / ollama_client.py."""
import json
from groq import Groq
from config import settings
from services.gemini_client import CONTENT_MODE_PROMPT, COMPETITOR_MODE_PROMPT, _normalize_competitor_result

_client = None


def get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def _call(prompt: str, model: str) -> dict:
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content.strip()
    return json.loads(text)


def classify_content_mode(business_context: str, keywords: list[str], title: str, body: str) -> dict:
    prompt = CONTENT_MODE_PROMPT.format(
        business_context=business_context,
        keywords=", ".join(keywords),
        title=title,
        body=body[:2000],
    )
    return _call(prompt, model=settings.groq_model)


def classify_competitor_mode(company_name: str, product_description: str, competitors: list[str], title: str, body: str) -> dict:
    prompt = COMPETITOR_MODE_PROMPT.format(
        company_name=company_name,
        product_description=product_description,
        competitors=", ".join(competitors),
        title=title,
        body=body[:2000],
    )
    return _normalize_competitor_result(_call(prompt, model=settings.groq_competitor_model))