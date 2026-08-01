"""Ollama - local, free, no API key. Same interface as gemini_client.py / groq_client.py.
Requires `ollama serve` running locally with the configured model pulled."""
import json
import httpx
from config import settings
from services.gemini_client import CONTENT_MODE_PROMPT, COMPETITOR_MODE_PROMPT, _normalize_competitor_result

BASE_URL = "http://localhost:11434"


def _call(prompt: str) -> dict:
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{BASE_URL}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            },
        )
        response.raise_for_status()
        text = response.json()["response"].strip()
    return json.loads(text)


def classify_content_mode(business_context: str, keywords: list[str], title: str, body: str) -> dict:
    prompt = CONTENT_MODE_PROMPT.format(
        business_context=business_context,
        keywords=", ".join(keywords),
        title=title,
        body=body[:2000],
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
