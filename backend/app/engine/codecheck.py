"""Code vertical (FR-3.13–3.17): generate code → run it in a sandbox → run tests → self-correct.

Code is one of the few domains where "is this answer right?" is machine-checkable, so the answer's
Python is executed and tested instead of judged. Tests come from, in order of how much they prove:

  provided  — tests attached to the eval question (e.g. from the library's own suite)
  doctest   — `>>>` examples in the retrieved documentation that use names the code defines
  generated — asserts the model writes for the question: weaker evidence (both can be wrong together),
              and labelled as such

Governors keep the loop honest: a step cap, a no-progress stop (the same error twice), and an honest
outcome when nothing passes — the best attempt, marked unverified, never a loop that converges on
confident nonsense. Execution happens only in the Docker sandbox (engine/sandbox.py).
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..llm import provider as llm
from . import sandbox

_BLOCK = re.compile(r"```[ \t]*(python|py|python3)?[ \t]*\n(.*?)```", re.S | re.I)
_DEFINED = re.compile(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)|^([A-Za-z_]\w*)\s*=", re.M)
_MISSING = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
RESULT = "RAGLABS_RESULT "

HARNESS = r'''import doctest, json, sys, traceback
out = {"stage": "answer"}
g = {"__name__": "__answer__"}
try:
    exec(compile(open("/work/answer.py", encoding="utf-8").read(), "answer.py", "exec"), g)
    out["stage"] = "tests"
    kind = open("/work/kind.txt", encoding="utf-8").read().strip()
    tests = open("/work/tests.py", encoding="utf-8").read()
    if kind == "doctest":
        parser, runner = doctest.DocTestParser(), doctest.DocTestRunner(verbose=False)
        test = parser.get_doctest(tests, g, "docs", "docs", 0)
        failures = []
        runner.run(test, out=failures.append)
        r = runner.summarize(verbose=False)
        out.update(ok=r.failed == 0, ran=r.attempted, detail="".join(failures)[-4000:])
    elif kind == "none":
        out.update(ok=True, ran=0)
    else:
        exec(compile(tests, "tests.py", "exec"), g)
        out.update(ok=True, ran=tests.count("assert"))
except BaseException:
    out.update(ok=False, detail=traceback.format_exc()[-4000:])
print("RAGLABS_RESULT " + json.dumps(out))
'''

REVISE = """Your previous answer's code failed when it was executed and tested.

Question: {question}

Your answer:
{answer}

What happened when it ran:
{error}

Rewrite the whole answer so the code works. Keep the explanation and the [n] citations to the sources;
fix only what the error shows is wrong. Put the code in one ```python block."""

GENERATE_TESTS = """Write 2 to 4 Python assert statements that check whether the code below correctly answers
the question. Use only the Python standard library and the names the code defines. Don't redefine
anything; no prose, no code fences.

Question: {question}

Code:
{code}"""


def extract_code(answer: str) -> str | None:
    """The answer's Python: fenced blocks labelled python (or unlabelled), joined in order."""
    blocks = [code for lang, code in _BLOCK.findall(answer) if code.strip()]
    return "\n\n".join(b.rstrip() for b in blocks) + "\n" if blocks else None


def defined_names(code: str) -> set[str]:
    return {a or b for a, b in _DEFINED.findall(code)}


def doctests_for(code: str, sources: list[str]) -> str | None:
    """`>>>` examples from the retrieved docs that use a name the answer's code defines."""
    names = defined_names(code)
    keep = []
    for src in sources:
        for ex in re.findall(r"(?:^[ \t]*>>> .*\n(?:[ \t]*\.\.\. .*\n)*(?:(?![ \t]*>>> )[ \t]*\S.*\n)*)", src + "\n", re.M):
            if any(re.search(rf"\b{re.escape(n)}\b", line) for line in ex.splitlines() if ">>>" in line or "..." in line
                   for n in names):
                keep.append(ex.strip("\n"))
    return "\n\n".join(keep) + "\n" if keep else None


def _parse(run: dict[str, Any]) -> dict[str, Any]:
    for line in reversed(run["stdout"].splitlines()):
        if line.startswith(RESULT):
            try:
                return json.loads(line[len(RESULT):])
            except ValueError:
                break
    why = ("timed out (the sandbox's time limit)" if run["timed_out"] else
           "killed: used more than the sandbox's 256 MB of memory" if run.get("oom") else
           run["stderr"].strip()[-2000:] or f"exit code {run['exit_code']}")
    return {"ok": False, "stage": "sandbox", "detail": why}


def signature(detail: str) -> str:
    """The error, without line numbers and addresses — to notice the same failure twice."""
    last = [ln for ln in (detail or "").strip().splitlines() if ln.strip()][-1:] or [""]
    return re.sub(r"0x[0-9a-f]+|line \d+", "#", last[0])


async def check(gen: Any, question: str, answer: str, sources: list[str], *, tests: str | None = None,
                max_steps: int = 3, allow_generated: bool = True, timeout_s: int = 10) -> dict[str, Any]:
    """-> {status, answer, test_source, attempts, steps: [...], tokens_in, tokens_out}. status is one of
    verified · unverified (tests kept failing) · ran_without_tests · missing_dependency · sandbox_unavailable
    · not_applicable (no Python in the answer)."""
    code = extract_code(answer)
    usage = {"tokens_in": 0, "tokens_out": 0}
    if code is None:
        return {"status": "not_applicable", "answer": answer, "steps": [], **usage}
    ok, why = await sandbox.available()
    if not ok:
        return {"status": "sandbox_unavailable", "answer": answer, "steps": [], "error": why, **usage}

    async def llm_call(prompt: str, max_tokens: int) -> str:
        text, tin, tout = await gen.complete(prompt, max_tokens)
        usage["tokens_in"] += tin
        usage["tokens_out"] += tout
        return text

    if tests:
        source, kind, test_code = "provided", "asserts", tests
    elif doc := doctests_for(code, sources):
        source, kind, test_code = "doctest", "doctest", doc
    elif allow_generated:
        try:
            test_code = re.sub(r"^```\w*\s*|\s*```$", "", (await llm_call(GENERATE_TESTS.format(question=question, code=code), 400)).strip())
            source, kind = "generated", "asserts"
        except llm.ProviderError:
            source, kind, test_code = "none", "none", ""
    else:
        source, kind, test_code = "none", "none", ""

    steps: list[dict[str, Any]] = []
    current, last_sig = answer, None
    for step in range(max_steps):
        run = await sandbox.run_python({"answer.py": code, "tests.py": test_code, "kind.txt": kind, "main.py": HARNESS},
                                       timeout_s)
        res = _parse(run)
        steps.append({"step": step + 1, "ok": bool(res.get("ok")), "stage": res.get("stage"),
                      "tests_run": res.get("ran"), "detail": (res.get("detail") or "")[-1500:], "ms": run["ms"]})
        if res.get("ok"):
            status = "verified" if source != "none" else "ran_without_tests"
            return {"status": status, "answer": current, "test_source": source, "tests": test_code,
                    "attempts": step + 1, "steps": steps, **usage}
        if m := _MISSING.search(res.get("detail") or ""):
            return {"status": "missing_dependency", "answer": current, "test_source": source, "tests": test_code,
                    "attempts": step + 1, "steps": steps, "error": f"The sandbox image has no '{m.group(1)}' package "
                    "(set SANDBOX_IMAGE to an image that has it).", **usage}
        sig = signature(res.get("detail", ""))
        if sig == last_sig or step == max_steps - 1:
            break  # no progress, or out of steps: stop instead of looping on the same mistake
        last_sig = sig
        try:
            revised = await llm_call(REVISE.format(question=question, answer=current, error=steps[-1]["detail"]), 2048)
        except llm.ProviderError:
            break
        new_code = extract_code(revised)
        if not new_code:
            break
        current, code = revised.strip(), new_code
    return {"status": "unverified", "answer": current, "test_source": source, "tests": test_code,
            "attempts": len(steps), "steps": steps, **usage}
