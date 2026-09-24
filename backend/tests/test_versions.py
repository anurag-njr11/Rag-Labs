import app.main  # noqa: F401  (registers node types)
from app.api import projects as api
from app.core.pipeline import recommended_pipeline


async def test_activation_log(database):
    p = await api.create_project(api.ProjectIn(name="P"))
    v1 = p["active_version"]
    cfg = recommended_pipeline()
    cfg["retrieve"]["top_k"] = 4
    v2 = (await api.create_version(p["id"], api.VersionIn(config=cfg, note="warmer", build=False)))["version"]

    await api.activate_version(p["id"], v1["id"])
    await api.activate_version(p["id"], v1["id"])  # already active: not logged again

    d1 = await api.get_version(p["id"], v1["id"])
    assert [a["previous_version"] for a in d1["activations"]] == [2, None]
    d2 = await api.get_version(p["id"], v2["id"])
    assert [a["previous_version"] for a in d2["activations"]] == [1]
    assert (await api.get_project(p["id"]))["active_version_id"] == v1["id"]
