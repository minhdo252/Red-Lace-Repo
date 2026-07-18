from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: str = "postgresql://aitravelmate:aitravelmate@localhost:5432/aitravelmate"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    embedding_dim: int = 1024

    # AI client (see app/ai/client.py) — "mock" runs the whole stack with canned
    # responses so the orchestrator loop is testable with no external key.
    # "live" wires an OpenAI-compatible endpoint (FPT Cloud Marketplace by
    # default) with one API key + model name per capability, since a single
    # provider can expose different models/keys for chat vs vision vs embed.
    ai_mode: str = "mock"
    ai_base_url: str = "https://mkp-api.fptcloud.com"

    ai_chat_api_key: str | None = None
    ai_chat_model: str = "GLM-5.2"

    ai_vision_api_key: str | None = None
    ai_vision_model: str = "Qwen2.5-VL-7B-Instruct"

    ai_embed_api_key: str | None = None
    ai_embed_model: str = "Vietnamese_Embedding"

    google_places_api_key: str | None = None
    # Server-side-only escape hatch for check_business_existence() while the
    # real Google Places key/project is being sorted out — never settable
    # from a client request, only from the process environment (see
    # app/modules/business_check.py for the banner/logging this triggers).
    mock_google_places: bool = False


settings = Settings()
