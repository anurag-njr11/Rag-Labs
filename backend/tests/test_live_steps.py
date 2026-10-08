import asyncio

from app.engine.chat import _live


def test_live_yields_steps_before_the_awaitable_finishes():
    async def run():
        q: asyncio.Queue = asyncio.Queue()

        async def work():
            for name in ("a", "b"):
                await asyncio.sleep(0.01)
                q.put_nowait({"type": "step", "step": name})
            await asyncio.sleep(0.01)
            return 42

        out: list = []
        seen = [ev["step"] async for ev in _live(q, work(), out)]
        return seen, out

    seen, out = asyncio.run(run())
    assert seen == ["a", "b"] and out == [42]


def test_summarize_has_confidence_intervals():
    from app.core.evalmetrics import summarize
    s = summarize([1] * 24, 5)
    assert s["mrr"] == 1.0 and s["ci"]["hit_at_k"][0] < 0.9 and s["ci"]["hit_at_k"][1] == 1.0
