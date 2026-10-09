import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import access, db, vault
from . import nodes  # noqa: F401  (registers every node type)
from .api import chat, documents, projects, system
from .api import compute as compute_api
from .api import external as external_api
from .api import keys, otel as otel_api
from .api import recipes as recipes_api
from .api import corpus, eval as eval_api
from .config import get_settings
from .engine import stores
from .llm import provider as llm

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
vault.install_log_redaction()
log = logging.getLogger("raglabs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    vault.install_log_redaction()  # again: uvicorn sets up its handlers after import
    vault.master_key()  # fail fast on a malformed RAGLABS_SECRET_KEY
    db.check_fts5()
    await db.connect(settings.db_path)
    # A server restart interrupts any build that was running.
    async with db.tx() as c:
        await c.execute("UPDATE index_builds SET status='failed', error='Interrupted by a server restart'"
                        " WHERE status='building'")
        await c.execute("UPDATE runs SET status='aborted', error='Interrupted by a server restart'"
                        " WHERE status='running'")
        for table in ("eval_sets", "eval_runs", "sweeps", "corpus_reports"):
            await c.execute(f"UPDATE {table} SET status='failed', error='Interrupted by a server restart'"
                            " WHERE status='running'")
    await llm.load()
    if not any(llm.availability(p)[0] for p in llm.PROVIDERS):
        log.warning("No LLM provider configured. Add one in Settings → Providers, or set e.g. "
                    "GEMINI_API_KEY / OPENAI_API_KEY in .env, to chat.")
    yield
    await stores.close_all()
    await db.close()


app = FastAPI(title="RAGLabs", version="0.1.0", lifespan=lifespan)
_hosts = [h.strip() for h in get_settings().allowed_hosts.split(",") if h.strip()]
app.add_middleware(access.KeyMiddleware)
if "*" not in _hosts:  # added last, so it runs first: a bad Host header never reaches the key check
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)
for r in (system.router, projects.router, documents.router, chat.router, eval_api.router, corpus.router,
          compute_api.router, keys.router, recipes_api.router, external_api.router, otel_api.router):
    app.include_router(r)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "providers": {name: llm.availability(name)[0] for name in llm.PROVIDERS},
    }


def mount_web(app: FastAPI, web: Path) -> None:
    """Serve the built web UI (installed package / Docker image). In development Vite serves it instead."""
    app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (web / path).resolve()
        return FileResponse(file if file.is_file() and file.is_relative_to(web.resolve()) else web / "index.html")


if (get_settings().web_dir / "index.html").is_file():
    mount_web(app, get_settings().web_dir)
