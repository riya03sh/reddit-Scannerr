from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "reddit-scanner-backend/0.1"

    gemini_api_key: str

    supabase_url: str
    supabase_service_role_key: str

    environment: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
