"""Code vertical (FR-3.13–3.17). The sandbox is replaced by a local subprocess that runs the *real*
harness — acceptable only here, where the tests control every line of code it executes."""

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

from app.core.node import RunContext
from app.core.pipeline import validate_pipeline
from app.engine import chat, codecheck, evaluate, retrieval, sandbox
from app.ingest import builder
from app.nodes import generate as G
from test_eval import _version, project  # noqa: F401  (fixture)
from test_retrieval import _cfg

GOOD = "Here it is [1]:\n\n```python\ndef add(a, b):\n    return a + b\n```\n"
BAD = "Here it is [1]:\n\n```python\ndef add(a, b):\n    return a - b\n```\n"
TESTS = "assert add(2, 3) == 5\nassert add(-1, 1) == 0\n"


async def _local_run(files, timeout_s=10):
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in files.items():
            Path(tmp, rel).write_text(text.replace("/work/", f"{Path(tmp).as_posix()}/"), encoding="utf-8")
        p = await asyncio.create_subprocess_exec(sys.executable, "-I", str(Path(tmp, "main.py")),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
    return {"ok": p.returncode == 0, "exit_code": p.returncode, "timed_out": False,
            "stdout": out.decode(), "stderr": err.decode(), "ms": 1.0}


@pytest.fixture
def box(monkeypatch):
    async def ok():
        return True, ""

    monkeypatch.setattr(sandbox, "available", ok)
    monkeypatch.setattr(sandbox, "run_python", _local_run)


class Gen:
    """Scripted model: complete() returns the next reply; records prompts."""

    provider, model_name = "gemini", "m"

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def complete(self, prompt, max_tokens):
        self.prompts.append(prompt)
        return self.replies.pop(0), 10, 5


def test_helpers():
    code = codecheck.extract_code(GOOD)
    assert code == "def add(a, b):\n    return a + b\n" and codecheck.defined_names(code) == {"add"}
    assert codecheck.extract_code("no code here") is None
    assert codecheck.doctests_for(code, ["Example:\n>>> add(1, 2)\n3\n>>> sub(3, 1)\n2\n"]) == ">>> add(1, 2)\n3\n"
    assert codecheck.signature('File "x", line 3\nAssertionError: 3 != 4') == "AssertionError: 3 != 4"
    args = sandbox.docker_args(Path("."), "python:3.12-slim", 10, "n")
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "--memory", "--pids-limit", "no-new-privileges"):
        assert flag in args
    assert args[args.index("--user") + 1] == "65534:65534" and args[-3:] == ["python", "-I", "/work/main.py"]


async def test_verified_first_time(box):
    r = await codecheck.check(Gen(), "add two numbers", GOOD, [], tests=TESTS)
    assert (r["status"], r["test_source"], r["attempts"]) == ("verified", "provided", 1) and r["answer"] == GOOD


async def test_self_corrects_then_passes(box):
    gen = Gen(GOOD)
    r = await codecheck.check(gen, "add two numbers", BAD, [], tests=TESTS)
    assert r["status"] == "verified" and r["attempts"] == 2 and r["answer"] == GOOD.strip()
    assert "AssertionError" in gen.prompts[0] and not r["steps"][0]["ok"] and r["steps"][1]["ok"]


async def test_stops_when_no_progress_and_stays_honest(box):
    gen = Gen(BAD, BAD, BAD)
    r = await codecheck.check(gen, "add two numbers", BAD, [], tests=TESTS, max_steps=4)
    assert r["status"] == "unverified" and r["attempts"] == 2 and len(gen.prompts) == 1  # same error twice → stop


async def test_doctests_generated_tests_and_missing_packages(box):
    r = await codecheck.check(Gen(), "add", GOOD, ["Usage:\n>>> add(2, 2)\n4\n"])
    assert (r["status"], r["test_source"]) == ("verified", "doctest")
    r = await codecheck.check(Gen("assert add(1, 1) == 2"), "add", GOOD, [])
    assert (r["status"], r["test_source"]) == ("verified", "generated")
    r = await codecheck.check(Gen(), "add", GOOD, [], allow_generated=False)
    assert r["status"] == "ran_without_tests"
    needs = "```python\nimport nonexistent_pkg_xyz\n```"
    r = await codecheck.check(Gen(), "x", needs, [], tests="assert True")
    assert r["status"] == "missing_dependency" and "nonexistent_pkg_xyz" in r["error"]
    assert (await codecheck.check(Gen(), "x", "plain prose", []))["status"] == "not_applicable"


async def test_no_docker_no_execution(monkeypatch):
    async def down():
        return False, "The Docker engine isn't running."

    async def must_not_run(*a, **k):
        raise AssertionError("ran without a sandbox")

    monkeypatch.setattr(sandbox, "available", down)
    monkeypatch.setattr(sandbox, "run_python", must_not_run)
    r = await codecheck.check(Gen(), "add", GOOD, [], tests=TESTS)
    assert r["status"] == "sandbox_unavailable" and "Docker" in r["error"]


async def test_chat_runs_the_check(project, box, monkeypatch):  # noqa: F811
    async def stream(self, messages, usage):
        yield BAD

    async def complete(self, prompt, max_tokens):
        return ("assert add(2, 3) == 5" if "assert statements" in prompt else GOOD), 10, 5

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    monkeypatch.setattr(G.ProviderGenerator, "complete", complete)
    cfg = validate_pipeline({**_cfg("numpy"), "verify": {"type": "execution_check"}})
    await builder.sync_build(project, cfg)
    events = [e async for e in chat.answer(project, await _version(cfg), "write add(a, b)")]
    done = events[-1]
    assert done["execution"]["status"] == "verified" and done["execution"]["test_source"] == "generated"
    assert done["answer"] == GOOD.strip() and any(e["type"] == "execution" for e in events)
    (step,) = [s for s in done["trace"] if s["step"] == "execution"]
    assert step["payload"]["attempts"] == 2


async def test_eval_execution_verified_metric(project, box, monkeypatch):  # noqa: F811
    from app.core import evalmetrics as M

    async def stream(self, messages, usage):
        yield BAD

    monkeypatch.setattr(G.ProviderGenerator, "stream", stream)
    cfg = _cfg("numpy")  # no code check: one honest run against the question's tests
    build = await builder.sync_build(project, cfg)
    final = await retrieval.retrieve(RunContext(), build=build, cfg=cfg, question="add")
    a = await evaluate.generate_answer(cfg, "write add", final, build, TESTS)
    assert a["execution"]["status"] == "unverified" and a["execution"]["attempts"] == 1
    graded = [{"correct": "yes", "execution": {"status": "verified", "has_tests": True}},
              {"correct": "no", "execution": {**a["execution"], "has_tests": True}},
              {"correct": "yes", "execution": {"status": "sandbox_unavailable", "has_tests": True}}]
    s = M.answer_summary(graded)
    assert s["exec_verified_rate"] == 0.5 and s["execution"]["tested"] == 2 and s["execution"]["sandbox_unavailable"] == 1


def _docker_up() -> bool:
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", "python:3.12-slim"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _docker_up(), reason="needs a running Docker engine with python:3.12-slim pulled")
async def test_real_sandbox_isolation(monkeypatch):
    monkeypatch.setattr(sandbox, "_available", None)
    net = await sandbox.run_python({"main.py": "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
                                               "    print('open')\nexcept OSError:\n    print('blocked')"})
    assert net["stdout"].strip() == "blocked"
    ro = await sandbox.run_python({"main.py": "try:\n    open('/work/x', 'w')\n    print('writable')\nexcept OSError:\n    print('ro')"})
    assert ro["stdout"].strip() == "ro"
    assert (await sandbox.run_python({"main.py": "import os; print(os.getuid())"}))["stdout"].strip() == "65534"
    slow = await sandbox.run_python({"main.py": "while True: pass"}, timeout_s=2)
    assert slow["timed_out"] and not slow["ok"]
    mem = await sandbox.run_python({"main.py": "b = bytearray(600 * 1024 * 1024)"})
    assert mem["oom"] and not mem["timed_out"]
    r = await codecheck.check(Gen(GOOD), "add", BAD, [], tests=TESTS)
    assert r["status"] == "verified" and r["attempts"] == 2
