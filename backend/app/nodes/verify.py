"""Verify slot: check the answer against the sources it was given before returning it.

One LLM call (the answer's own model, temperature 0) splits the answer into claims and grades
each one twice: against every source together (is the claim grounded?) and against each source
it cites (does that citation actually support it?). The first drives the grounding check, the
second citation-support checking.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Literal

from ..core.node import Node, NodeConfig, register, ui_field
from ..llm import provider as llm

VERDICTS = ("yes", "partial", "no")
SOURCE_CHARS = 1500  # per source shown to the checker; claims rarely need more

CHECK_PROMPT = """You check whether an answer is supported by the numbered sources it was written from.

Split the answer into its factual claims (usually one per sentence). Skip greetings, restated
questions and statements that the sources don't cover the question. For each claim give:
- "claim": the claim, quoted or closely paraphrased from the answer
- "cited": an object mapping each source number the claim cites with [n] to "yes", "partial" or
  "no": does THAT source on its own support the claim? Use {{}} if the claim cites nothing.
- "supported": "yes", "partial" or "no": do the sources together support the claim?

Judge only against the sources, never your own knowledge. Return only JSON:
{{"claims": [{{"claim": "...", "cited": {{"1": "yes"}}, "supported": "yes"}}]}}

Question: {question}

Sources:
{sources}

Answer:
{answer}"""


class NoVerifyConfig(NodeConfig):
    validate_output: bool = ui_field(
        False, title="Remove unsourced links and contacts",
        description="Deterministic output validation: URLs, email addresses and phone numbers that appear in "
                    "no source are removed from the answer — e.g. an exfiltration link a prompt injection asked "
                    "for. It can't stop a link or contact that a poisoned document itself contains. The answer "
                    "is then sent in one piece instead of streamed, so nothing unvalidated is shown.")


@register("verify", "none", title="No grounding check",
          description="Return the answer as generated (output validation can still run).")
class NoVerify(Node):
    Config = NoVerifyConfig


class GroundingCheckConfig(NoVerifyConfig):
    on_fail: Literal["retry_with_more_context", "flag"] = ui_field(
        "retry_with_more_context", title="If a claim isn't supported",
        description="Retry: answer again with twice the results and context budget, then check again. "
                    "Flag: return the answer marked as not grounded.",
        json_schema_extra={"enum_labels": {"retry_with_more_context": "Retry with more context",
                                           "flag": "Flag the answer"}},
    )
    max_retries: int = ui_field(1, ge=0, le=2, title="Max retries",
                                description="Each retry is another retrieval, answer and check.")


@register("verify", "grounding_check", title="Grounding check",
          description="An extra LLM call grades every claim, and every citation, against the sources. "
                      "Adds the cost and latency of one call (plus a retry when it fails).")
class GroundingCheck(Node):
    Config = GroundingCheckConfig

    async def check(self, gen: Any, question: str, answer: str,
                    included: list[dict[str, Any]]) -> dict[str, Any]:
        """-> verification dict (see `summarize`) plus tokens_in/tokens_out/cost_usd for the caller.
        A failed check call never fails the answer: it comes back as status "error", grounded None."""
        sources = "\n\n".join(f"[{i}] {c['text'][:SOURCE_CHARS]}" for i, c in enumerate(included, start=1))
        prompt = CHECK_PROMPT.format(question=question, sources=sources or "(none)", answer=answer)
        try:
            text, tin, tout = await gen.complete(prompt, 2048)
        except llm.ProviderError as e:
            return {**summarize(None), "error": str(e), "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        return {**summarize(parse_claims(text, len(included))), "tokens_in": tin, "tokens_out": tout,
                "cost_usd": llm.cost_usd(gen.provider, gen.model_name, tin, tout)}


class ExecutionCheckConfig(NoVerifyConfig):
    max_steps: int = ui_field(3, ge=1, le=4, title="Max attempts",
                              description="Each failed run is fed back to the model to fix the code, up to this many runs. "
                                          "It also stops when the same error comes back twice.")
    allow_generated_tests: bool = ui_field(
        True, title="Let the model write tests",
        description="When the question has no tests and the docs have no usable >>> examples, the model writes asserts "
                    "— weaker evidence (code and test can be wrong together), so it's labelled as such.")
    timeout_s: int = ui_field(10, ge=2, le=60, advanced=True, title="Time limit per run (s)")


@register("verify", "execution_check", title="Code check (sandboxed)",
          description="For code answers: run the answer's Python in a Docker sandbox (no network, memory and time caps) "
                      "against tests — the question's own, >>> examples from the docs, or model-written — and let the "
                      "model fix failures. Needs Docker running.")
class ExecutionCheck(Node):
    Config = ExecutionCheckConfig


def _json(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0) if m else text)


def parse_claims(text: str, n_sources: int) -> list[dict[str, Any]] | None:
    """The checker's claims, with unknown verdicts and out-of-range source numbers dropped.
    None if the reply isn't usable JSON."""
    try:
        raw = _json(text).get("claims")
    except (ValueError, AttributeError):
        return None
    if not isinstance(raw, list):
        return None
    claims = []
    for c in raw:
        if not isinstance(c, dict) or str(c.get("supported", "")).lower() not in VERDICTS:
            continue
        cited = c.get("cited") if isinstance(c.get("cited"), dict) else {}
        claims.append({
            "claim": str(c.get("claim") or "").strip(),
            "supported": str(c["supported"]).lower(),
            "cited": {int(k): str(v).lower() for k, v in cited.items()
                      if str(k).isdigit() and 1 <= int(k) <= n_sources and str(v).lower() in VERDICTS},
        })
    return claims


def summarize(claims: list[dict[str, Any]] | None) -> dict[str, Any]:
    """grounded = no claim the sources contradict or lack ("partial" passes, but is counted).
    score = mean claim support (yes 1, partial 0.5, no 0); no claims (e.g. "I don't know") = grounded.
    citations = per source number: "no" if it fails any claim citing it, else "partial" if any, else "yes"."""
    if claims is None:
        return {"status": "error", "grounded": None, "score": None, "claims": [], "citations": {}}
    pts = {"yes": 1.0, "partial": 0.5, "no": 0.0}
    cites: dict[int, str] = {}
    for c in claims:
        for n, v in c["cited"].items():
            cur = cites.get(n, "yes")
            cites[n] = "no" if "no" in (cur, v) else "partial" if "partial" in (cur, v) else "yes"
    return {
        "status": "ok",
        "grounded": all(c["supported"] != "no" for c in claims),
        "score": round(sum(pts[c["supported"]] for c in claims) / len(claims), 3) if claims else 1.0,
        "claims": claims,
        "citations": cites,
    }


_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]\"'`]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# A leading + or at least one separator, so plain numbers (IDs, amounts) aren't mistaken for phones.
_PHONE = re.compile(r"(?<![\w.])(?:\+\d[\d ().-]{5,}\d|\(?\d{1,4}\)?(?:[ .-]\d{2,4}){1,3})(?![\w])")
_DATE = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}")


def _phone_ok(p: str, digits: str) -> bool:
    """Kept: dates, short numbers (< 7 digits), and numbers that appear in the sources."""
    d = re.sub(r"\D", "", p)
    return bool(_DATE.fullmatch(p.strip())) or len(d) < 7 or d in digits


def filter_unsourced(answer: str, sources: list[str]) -> tuple[str, list[str]]:
    """Remove URLs, emails and phone numbers that appear in no source -> (answer, removed). Deterministic:
    a link or contact the model "learned" from an injected instruction can't reach the user."""
    corpus = "\n".join(sources).lower()
    digits = re.sub(r"\D", "", corpus)
    removed: list[str] = []

    def check(kind: str, present: Any) -> Any:
        def sub(m: re.Match[str]) -> str:
            raw = m.group(0).rstrip(".,;:!?")
            if present(raw):
                return m.group(0)
            removed.append(raw)
            return f"[{kind} removed: not in the sources]" + m.group(0)[len(raw):]
        return sub

    answer = _URL.sub(check("link", lambda u: u.lower() in corpus), answer)
    answer = _EMAIL.sub(check("email", lambda e: e.lower() in corpus), answer)
    answer = _PHONE.sub(check("phone number", lambda p: _phone_ok(p, digits)), answer)
    return answer, removed


def output_validation(cfg: dict[str, Any]) -> bool:
    return bool((cfg.get("verify") or {}).get("validate_output"))


def more_context(cfg: dict[str, Any]) -> dict[str, Any]:
    """The retry config: twice the results, rerank survivors and context budget (within field limits)."""
    new = copy.deepcopy(cfg)
    rt, rr, pr = new["retrieve"], new["rerank"], new["prompt"]
    rt["top_k"] = min(50, int(rt["top_k"]) * 2)
    rt["candidates"] = max(int(rt.get("candidates", 40)), rt["top_k"])
    if "top_n" in rr:
        rr["top_n"] = min(50, int(rr["top_n"]) * 2)
    pr["max_context_tokens"] = min(100000, int(pr["max_context_tokens"]) * 2)
    return new
