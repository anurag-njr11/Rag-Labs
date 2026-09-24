import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from . import nodes  # noqa: F401  (registers every node type)
from .api import chat, documents, projects, system
from .api import eval as eval_api
from .config import get_settings
from .engine import stores
from .llm import provider as llm

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("raglabs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    db.check_fts5()
    await db.connect(settings.db_path)
    # A server restart interrupts any build that was running.
    async with db.tx() as c:
        await c.execute("UPDATE index_builds SET status='failed', error='Interrupted by a server restart'"
                        " WHERE status='building'")
        await c.execute("UPDATE runs SET status='aborted', error='Interrupted by a server restart'"
                        " WHERE status='running'")
        for table in ("eval_sets", "eval_runs"):
            await c.execute(f"UPDATE {table} SET status='failed', error='Interrupted by a server restart'"
                            " WHERE status='running'")
    if not any(llm.availability(p)[0] for p in llm.PROVIDERS):
        log.warning("No LLM API key set. Add GEMINI_API_KEY or NVIDIA_API_KEY to .env to chat.")
    yield
    await stores.close_all()
    await db.close()


app = FastAPI(title="RAGLabs", version="0.1.0", lifespan=lifespan)
for r in (system.router, projects.router, documents.router, chat.router, eval_api.router):
    app.include_router(r)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "providers": {name: llm.availability(name)[0] for name in llm.PROVIDERS},
    }
