from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core application
    app_name: str = "CiteOps"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_v1_prefix: str = "/v1"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Security / BFF proxy boundary
    citeops_internal_api_key: str = ""
    cors_origins: str = "http://localhost:3000"

    # Database (PostgreSQL 17 + pgvector >= 0.8.0)
    # Runtime uses non-BYPASSRLS `citeops_app` role; migrations use admin `citeops` role
    database_url: str = (
        "postgresql://citeops_app:citeops_app_dev_password@localhost:5433/citeops"
    )
    database_admin_url: str = "postgresql://citeops:citeops_dev_password@localhost:5433/citeops"
    db_pool_min_size: int = Field(default=2, ge=1, le=20)
    db_pool_max_size: int = Field(default=10, ge=2, le=50)

    # Redis & Semantic Cache
    redis_url: str = "redis://localhost:6380/0"
    semantic_cache_threshold: float = Field(default=0.95, ge=0.5, le=1.0)
    semantic_cache_max_entries: int = Field(default=500, ge=10, le=5000)
    cache_ttl_seconds: int = Field(default=86400, ge=60)

    # Rate Limiting
    rate_limit_tenant_rpm: int = Field(default=20, ge=1)
    rate_limit_global_llm_rpm: int = Field(default=12, ge=1)

    # LLM Routing (Free Tier Primary + Fallback + Local Privacy Mode)
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_api_key: str = ""
    gemini_primary_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_thinking_level: Literal["low", "medium", "high"] = "low"

    groq_api_key: str = ""
    groq_fallback_model: str = "llama-3.3-70b-versatile"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"

    # Embeddings
    embedding_provider: Literal["gemini", "fastembed"] = "gemini"
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = Field(default=768, ge=128, le=3072)

    # Cross-Encoder Reranker
    reranker_profile: Literal["light", "base"] = "light"
    rerank_candidate_count: int = Field(default=25, ge=5, le=50)
    min_rerank_score: float = Field(default=0.35, ge=0.0, le=1.0)

    # Langfuse / OpenTelemetry
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator("cors_origins")
    @classmethod
    def normalize_cors(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def reranker_model_name(self) -> str:
        if self.reranker_profile == "base":
            return "BAAI/bge-reranker-base"
        return "Xenova/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
