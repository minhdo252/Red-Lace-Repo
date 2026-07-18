from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: str = "postgresql://aitravelmate:aitravelmate@localhost:5432/aitravelmate"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    embedding_dim: int = 1024

    # AI client (see app/ai/client.py)
    # "mock" runs the whole stack with canned responses
    # "live" wires an OpenAI-compatible endpoint (FPT Cloud Marketplace by default)
    # with one API key + model name per capability.
    ai_mode: str = "mock"
    ai_base_url: str = "https://mkp-api.fptcloud.com"

    ai_chat_api_key: str | None = None
    ai_chat_model: str = "GLM-5.2"

    ai_vision_api_key: str | None = None
    ai_vision_model: str = "Qwen2.5-VL-7B-Instruct"

    ai_embed_api_key: str | None = None
    ai_embed_model: str = "Vietnamese_Embedding"
    
    stt_model: str = "FPT.AI-whisper-large-v3-turbo"
    ai_request_timeout_seconds: int = 60

    google_places_api_key: str | None = None


settings = Settings()
