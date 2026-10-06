from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    channel_url: str = "https://www.youtube.com/@BhajanMarg/videos"
    channel_shorts_url: str = "https://www.youtube.com/@BhajanMarg/shorts"
    channel_streams_url: str = "https://www.youtube.com/@BhajanMarg/streams"

    # Runtime provider selection. Local mode preserves the existing stack.
    app_mode: str = "local"
    llm_provider: str = "ollama"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    qdrant_api_key: str = ""
    qdrant_dense_model: str = "sentence-transformers/all-minilm-l6-v2"
    qdrant_bm25_model: str = "qdrant/bm25"
    cors_origins: str = "http://localhost:8000"
    llm_timeout_seconds: float = 35
    chat_timeout_seconds: float = 180
    qdrant_timeout_seconds: float = 30
    validate_answer_claims: bool = True

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "bhajan_marg_chunks"

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"

    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_enabled: bool = True

    dense_candidates: int = 40
    sparse_candidates: int = 40
    fused_candidates: int = 50
    final_sources: int = 5
    context_neighbors: int = 1

    strong_evidence_threshold: float = 0.72
    related_evidence_threshold: float = 0.45
    use_llm_evidence_judge: bool = True

    data_dir: str = "./data"
    sqlite_path: str = "./data/bhajan.db"
    transcript_dir: str = "./data/transcripts"
    temp_dir: str = "./data/tmp"
    corpus_intelligence_dir: str = "./data/corpus_intelligence"
    corpus_intelligence_on_ingest: bool = False

    daily_update_enabled: bool = True
    daily_update_hour: int = 2
    daily_update_minute: int = 15
    daily_scan_latest: int = 40
    timezone: str = "Asia/Kolkata"

    subtitle_langs: str = "hi.*,en.*"
    whisper_fallback: bool = False
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    ytdlp_cookies_from_browser: str = ""
    admin_token: str = ""

    def ensure_dirs(self):
        for p in (self.data_dir, self.transcript_dir, self.temp_dir, self.corpus_intelligence_dir):
            Path(p).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
