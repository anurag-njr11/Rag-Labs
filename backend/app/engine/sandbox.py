"""Isolated code execution for the code vertical (FR-3.16): Docker, or nothing.

Model-written code never runs on the host. Each run gets a throwaway container with no network, a
memory / CPU / process cap, a read-only root filesystem, an unprivileged user, a small writable /tmp,
and a hard timeout (enforced inside the container and again from outside). The code arrives through a
read-only mount. If Docker isn't available the caller gets SandboxUnavailable — there is deliberately
no "just run it locally" fallback.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import get_settings

OUTPUT_CAP = 20_000  # chars of stdout/stderr kept


class SandboxUnavailable(RuntimeError):
    pass


_available: tuple[float, bool, str] | None = None


async def available() -> tuple[bool, str]:
    """(ok, reason) — cached for a minute so a stopped daemon is noticed but not probed every call."""
    global _available
    if _available and time.monotonic() - _available[0] < 60:
        return _available[1], _available[2]
    if not shutil.which("docker"):
        ok, why = False, "Docker isn't installed; code checks need it for isolation."
    else:
        try:
            p = await asyncio.create_subprocess_exec("docker", "info", "--format", "{{.ServerVersion}}",
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(p.communicate(), 15)
            ok = p.returncode == 0 and bool(out.strip())
            why = "" if ok else "The Docker engine isn't running. Start Docker Desktop (or dockerd) to run code checks."
        except (OSError, asyncio.TimeoutError):
            ok, why = False, "Docker didn't respond. Start Docker Desktop (or dockerd) to run code checks."
    _available = (time.monotonic(), ok, why)
    return ok, why


def docker_args(work: Path, image: str, timeout_s: int, name: str) -> list[str]:
    return ["docker", "run", "--rm", "--name", name,
            "--network", "none", "--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--pids-limit", "64",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
            "-v", f"{work.resolve().as_posix()}:/work:ro", "-w", "/work",
            image, "timeout", "-s", "KILL", str(timeout_s), "python", "-I", "/work/main.py"]


async def run_python(files: dict[str, str], timeout_s: int = 10) -> dict[str, Any]:
    """Run /work/main.py (plus any other files) in a fresh container ->
    {ok, exit_code, stdout, stderr, ms, timed_out, oom}."""
    ok, why = await available()
    if not ok:
        raise SandboxUnavailable(why)
    image = get_settings().sandbox_image
    name = f"raglabs-sbx-{time.monotonic_ns()}"
    with tempfile.TemporaryDirectory(prefix="raglabs-sbx-") as tmp:
        work = Path(tmp)
        for rel, text in files.items():
            (work / rel).write_text(text, encoding="utf-8")
        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(*docker_args(work, image, timeout_s, name),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s + 30)  # + image start
        except asyncio.TimeoutError:
            timed_out = True
            kill = await asyncio.create_subprocess_exec("docker", "kill", name, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL)
            await kill.wait()
            out, err = await proc.communicate()
    code = proc.returncode if proc.returncode is not None else -1
    ms = round((time.perf_counter() - t0) * 1000, 1)
    # 137 = SIGKILL: from `timeout` when the time ran out, else the kernel's OOM killer (the memory cap).
    timed_out = timed_out or code == 124 or (code == 137 and ms >= timeout_s * 1000 * 0.95)
    return {"ok": code == 0, "exit_code": code, "timed_out": timed_out, "oom": code == 137 and not timed_out,
            "stdout": out.decode("utf-8", "replace")[-OUTPUT_CAP:], "stderr": err.decode("utf-8", "replace")[-OUTPUT_CAP:],
            "ms": ms}
