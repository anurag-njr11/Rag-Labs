from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sse_starlette.sse import EventSourceResponse

from ..core.pipeline import PipelineError, catalog, index_config_hash, recommended_pipeline, validate_pipeline
from ..ingest import jobs
from ..llm import provider as llm
from ..llm.presets import PRESETS

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/nodes")
async def nodes() -> list[dict]:
    return catalog()


@router.get("/pipelines/recommended")
async def recommended() -> dict:
    return recommended_pipeline()


@router.post("/pipelines/validate")
async def validate(body: dict) -> dict:
    try:
        cfg = validate_pipeline(body.get("config", {}))
    except PipelineError as e:
        return {"valid": False, "errors": e.errors}
    return {"valid": True, "config": cfg, "index_config_hash": index_config_hash(cfg)}


class ProviderIn(BaseModel):
    """A provider as edited in Settings → Providers. Omitted fields keep their
    current value; an empty `api_key` keeps the stored key."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None  # required on create
    title: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    supports_reasoning: bool | None = None
    key_required: bool | None = None
    headers: dict[str, str] | None = None


def _provider_out(p: llm.Provider) -> dict:
    ok, reason = llm.availability(p.name)
    return {**p.public(), "available": ok, "reason": reason, "enabled": p.name in llm.PROVIDERS}


@router.get("/providers")
async def providers() -> list[dict]:
    """The providers offered as Generate types (pinned presets + every configured one)."""
    return [_provider_out(p) for p in llm.PROVIDERS.values()]


@router.get("/providers/presets")
async def provider_presets() -> list[dict]:
    """Every built-in preset, with its current state, for the "Add provider" picker."""
    every = llm.resolve_all()
    return [_provider_out(every[name]) for name in PRESETS]


@router.post("/providers", status_code=201)
async def create_provider(body: ProviderIn) -> dict:
    if not body.name:
        raise HTTPException(422, "name is required")
    if body.name in llm.PROVIDERS and llm.get(body.name).source in ("ui", "custom-ui", "custom-env"):
        raise HTTPException(409, f"provider {body.name!r} already exists")
    return await _save(body.name, body)


@router.patch("/providers/{name}")
async def update_provider(name: str, body: ProviderIn) -> dict:
    if name not in llm.resolve_all():
        raise HTTPException(404, "unknown provider")
    return await _save(name, body)


async def _save(name: str, body: ProviderIn) -> dict:
    try:
        p = await llm.save(name, body.model_dump(exclude={"name"}, exclude_unset=True))
    except llm.ProviderError as e:
        raise HTTPException(422, str(e)) from e
    return _provider_out(p)


@router.delete("/providers/{name}", status_code=204)
async def delete_provider(name: str) -> None:
    """Forget the UI settings for a provider. A preset falls back to .env/defaults;
    a custom provider disappears (pipelines using it then fail with a clear error)."""
    await llm.remove(name)


@router.post("/providers/test")
async def test_draft_provider(body: ProviderIn) -> dict:
    """Try unsaved settings: does the endpoint answer /models with this key?
    Missing fields fall back to the named provider's current settings."""
    base = llm.resolve_all().get(body.name or "")
    base_url = body.base_url or (base.base_url if base else "")
    if not base_url:
        raise HTTPException(422, "base_url is required")
    key = body.api_key or (base.api_key if base else "")
    headers = body.headers if body.headers is not None else (base.headers if base else {})
    return await llm.probe(base_url, key, headers, title=body.title or (base.title if base else "Provider"))


@router.post("/providers/{name}/test")
async def test_provider(name: str) -> dict:
    p = llm.resolve_all().get(name)
    if p is None:
        raise HTTPException(404, "unknown provider")
    return await llm.probe(p.base_url, p.api_key, p.headers, title=p.title)


@router.get("/providers/{name}/models")
async def provider_models(name: str, kind: str = Query("chat", pattern="^(chat|embed)$")) -> dict:
    if name not in llm.resolve_all():
        raise HTTPException(404, "unknown provider")
    try:
        return {"models": await llm.list_models(name, kind)}
    except llm.ProviderError:
        return {"models": []}


@router.get("/jobs/{job_id}")
async def job(job_id: str) -> dict:
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found (it may have finished long ago)")
    return j.summary()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> EventSourceResponse:
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found")

    async def gen():
        async for e in j.stream():
            yield {"event": e["type"], "data": json.dumps(e)}

    return EventSourceResponse(gen())


@router.get("/projects/{project_id}/jobs")
async def project_jobs(project_id: str) -> list[dict]:
    return [j.summary() for j in jobs.active_for(project_id)]
