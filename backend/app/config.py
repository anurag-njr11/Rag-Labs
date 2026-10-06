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

    # LLM providers are configured via <NAME>_API_KEY etc. (see app/llm/provider.py),
    # which pydantic-settings can't enumerate ahead of time.

    # Host headers the API answers to. Blocks DNS-rebinding attacks, where a web
    # page re-points its own domain at 127.0.0.1 to drive this API (and its stored
    # keys) from the browser. Comma-separated; "*" disables the check.
    allowed_hosts: str = "localhost,127.0.0.1,::1,[::1],testserver"

    # Upper bounds that keep a runaway sitemap or upload from eating the machine.
    max_upload_mb: int = 100
    sitemap_max_pages: int = 200
    # A first-use local model download (fastembed embedder, cross-encoder) that hasn't finished by
    # then fails the build / chat turn / sweep cell instead of waiting forever.
    model_download_timeout_s: float = 600.0

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
