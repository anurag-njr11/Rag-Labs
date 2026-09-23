from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from ..core.pipeline import PipelineError, catalog, index_config_hash, recommended_pipeline, validate_pipeline
from ..ingest import jobs
from ..llm import provider as llm

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


@router.get("/providers")
async def providers() -> list[dict]:
    out = []
    for name, p in llm.PROVIDERS.items():
        ok, reason = llm.availability(name)
        out.append({"name": name, "title": p.title, "available": ok, "reason": reason,
                    "signup_url": p.signup_url, "default_model": p.default_model})
    return out


@router.get("/providers/{name}/models")
async def provider_models(name: str, kind: str = Query("chat", pattern="^(chat|embed)$")) -> dict:
    if name not in llm.PROVIDERS:
        raise HTTPException(404, "unknown provider")
    return {"models": await llm.list_models(name, kind)}


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
