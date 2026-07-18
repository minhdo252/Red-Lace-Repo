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

    ai_stt_api_key: str | None = None
    stt_model: str = "FPT.AI-whisper-large-v3-turbo"
    ai_request_timeout_seconds: int = 60

    # Backward-compatible names used by earlier project .env examples.
    glm_api_key: str | None = None
    vn_embedding_api_key: str | None = None
    whisper_v3_api_key: str | None = None
    ai_api_key: str | None = None

    # Module 1 latency budgets. The outer deadlines keep a single slow AI
    # capability from holding the complete chat response open indefinitely.
    stt_deadline_seconds: int = 30
    translation_deadline_seconds: int = 15
    orchestrator_deadline_seconds: int = 12
    threat_deadline_seconds: int = 12
    scam_deadline_seconds: int = 12
    # Voice-route fair-price check: transcript item/price extraction + compare_price.
    price_check_deadline_seconds: int = 10
    memory_compression_deadline_seconds: int = 10

    # Audio admission limits are checked before and after decoding.
    max_audio_bytes: int = 10 * 1024 * 1024
    max_audio_duration_seconds: int = 60

    google_places_api_key: str | None = None
    # Server-side-only escape hatch for check_business_existence() while the
    # real Google Places key/project is being sorted out — never settable
    # from a client request, only from the process environment (see
    # app/modules/business_check.py for the banner/logging this triggers).
    mock_google_places: bool = False


settings = Settings()
