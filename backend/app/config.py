from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = REPO_DIR / "data"

    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_default_model: str = "gemini-2.5-flash"
    gemini_default_embed_model: str = "gemini-embedding-001"

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_default_model: str = "nvidia/nemotron-3-super-120b-a12b"
    nvidia_default_embed_model: str = "nvidia/llama-3.2-nv-embedqa-1b-v1"

    # Upper bounds that keep a runaway sitemap or upload from eating the machine.
    max_upload_mb: int = 100
    sitemap_max_pages: int = 200

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def stores_dir(self) -> Path:
        return self.data_dir / "stores"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.raw_dir, self.cache_dir, self.stores_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
