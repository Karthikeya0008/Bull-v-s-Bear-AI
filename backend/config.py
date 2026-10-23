"""Application settings, loaded from environment variables and the .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All tunable settings. Paths are resolved relative to the project root."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = Path("data")
    sqlite_path: Path = Path("data/app.db")
    chroma_dir: Path = Path("data/chroma")
    config_dir: Path = Path("config")

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    nli_model: str = "cross-encoder/nli-deberta-v3-small"

    chunk_size: int = 1200
    chunk_overlap: int = 200

    watcher_interval_minutes: int = 360
    watcher_lookback_days: int = 45
    http_timeout_seconds: int = 60
    http_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    cerebras_api_key: str = ""
    llm_provider_order: str = "gemini,groq,openrouter,cerebras"
    debater_provider: str = "gemini"
    judge_provider: str = "groq"

    def resolve(self, path: Path) -> Path:
        """Return ``path`` as an absolute path anchored at the project root."""
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def raw_dir(self) -> Path:
        return self.resolve(self.data_dir) / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.resolve(self.data_dir) / "processed"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
