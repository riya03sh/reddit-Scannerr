from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "reddit-scanner-backend/0.1"

    gemini_api_key: str = ""
    supabase_url: str
    supabase_service_role_key: str

    environment: str = "development"
    data_source: str = "mock"

    llm_provider: str = "gemini"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    # Competitor mode gets a bigger/slower model: lower volume (fewer subreddits,
    # no keyword pre-filter) can absorb the cost, and testing showed the small
    # instant model hallucinating competitor mentions even after prompt tightening.
    groq_competitor_model: str = "llama-3.3-70b-versatile"
    ollama_model: str = "llama3.1"

    # Gap between LLM calls in the ingestion worker, to stay under free-tier
    # rate limits. Groq allows 30 req/min (2s is enough); Gemini's free tier is
    # slower and wants ~4s. Local Ollama needs no throttle at all.
    llm_request_interval_seconds: float = 2.0

    # Content matches at or above this 0-100 intent score also become leads, on top
    # of whatever competitor mode finds. Set above the typical scanner's
    # min_score_threshold (which only decides what's worth showing at all) so the
    # lead list stays a shortlist of people worth contacting, not every match.
    lead_score_threshold: float = 80.0

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
    )


settings = Settings()