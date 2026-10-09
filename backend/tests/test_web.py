"""Serving the built web UI, and OPEN_ACCESS for Docker."""

import httpx

from app.config import get_settings
from app.main import app, mount_web
from fastapi import FastAPI


def _client(app, host="203.0.113.5"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(host, 1)), base_url="http://testserver")


async def test_mount_web_serves_assets_and_falls_back_to_index(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.js").write_text("js")
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path.parent / "secret.txt").write_text("nope")
    web = FastAPI()
    mount_web(web, tmp_path)
    async with _client(web) as c:
        assert (await c.get("/assets/a.js")).text == "js"
        assert "app" in (await c.get("/projects/123/configure")).text  # client-side route
        assert "app" in (await c.get("/..%2fsecret.txt")).text and "nope" not in (await c.get("/..%2fsecret.txt")).text
        assert (await c.get("/api/nothing")).status_code == 404


async def test_open_access_lets_a_non_loopback_caller_use_the_api(database, monkeypatch):
    async with _client(app) as c:
        assert (await c.get("/api/projects")).status_code == 401
        monkeypatch.setattr(get_settings(), "open_access", True)
        assert (await c.get("/api/projects")).status_code != 401
