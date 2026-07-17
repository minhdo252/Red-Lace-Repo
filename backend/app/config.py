from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: str = "postgresql://aitravelmate:aitravelmate@localhost:5432/aitravelmate"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    embedding_dim: int = 384

    # AI client (see app/ai/client.py) — "mock" runs the whole stack with canned
    # responses so the orchestrator loop is testable with no external key.
    ai_mode: str = "mock"
    ai_api_key: str | None = None
    ai_model: str | None = None

    google_places_api_key: str | None = None


settings = Settings()
