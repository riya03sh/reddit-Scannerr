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

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
    )


settings = Settings()