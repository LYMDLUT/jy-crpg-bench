"""The budgeted client refuses the call that would pass the budget."""
import asyncio
import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nexus.core import OpenAICompatibleClient, OpenAIConfig, openai_client_registry  # noqa: E402

from jy_crpg_nexus import token_budget  # noqa: E402  registers "budgeted"
from jy_crpg_nexus.token_budget import (  # noqa: E402
    BudgetedClient, TokenBudgetExceededError, TokenMeter, meter_of)


def _usage(prompt, completion, cached=0):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           total_tokens=prompt + completion,
                           prompt_tokens_details=SimpleNamespace(cached_tokens=cached))


class _Fake(OpenAICompatibleClient):
    """An inner client that answers with a fixed usage and remembers calls."""
    calls = 0
    per_call = (100, 50)

    def __init__(self, config):
        super().__init__(config)
        self.seen_args = dict(config.client_args)

    async def _create_completion(self, messages, model=None, **kwargs):
        type(self).calls += 1
        p, c = self.per_call
        return SimpleNamespace(usage=_usage(p, c), choices=[])

    async def _count_tokens(self, **kwargs):
        return 7


if "fake_inner" not in openai_client_registry:
    openai_client_registry.register("fake_inner")(_Fake)


def _client(budget, count="total", **inner):
    cfg = OpenAIConfig(client_args={"inner": "fake_inner", "token_budget": budget,
                                    "count": count, "inner_client_args": inner},
                       request_args={"model": "m"})
    return openai_client_registry.get("budgeted")(cfg)


class MeterTests(unittest.TestCase):
    def test_counts_total_by_default(self):
        m = TokenMeter(1000)
        m.add(_usage(100, 50, cached=20))
        self.assertEqual(m.used, 150)
        self.assertEqual(m.cache_read, 20)
        self.assertEqual(m.left, 850)
        self.assertFalse(m.spent)

    def test_prompt_completion_excludes_nothing_here_but_is_distinct(self):
        m = TokenMeter(120, count="prompt_completion")
        m.add({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 200})
        self.assertEqual(m.used, 150)      # not the provider's 200
        self.assertTrue(m.spent)

    def test_report_shape_is_the_brokers(self):
        m = TokenMeter(10)
        m.add(_usage(3, 4, cached=1))
        self.assertEqual(set(m.report()), {"input", "output", "cacheRead", "cacheWrite", "totalTokens"})

    def test_rejects_bad_config(self):
        with self.assertRaises(ValueError):
            TokenMeter(0)
        with self.assertRaises(ValueError):
            TokenMeter(10, count="words")


class BudgetedClientTests(unittest.TestCase):
    def setUp(self):
        _Fake.calls = 0

    def test_registered_and_wraps_inner(self):
        c = _client(1000, api_key="k")
        self.assertIsInstance(c, BudgetedClient)
        self.assertIsInstance(c.inner, _Fake)
        self.assertEqual(c.inner.seen_args, {"api_key": "k"})
        self.assertIs(meter_of(c), c.meter)
        self.assertIsNone(meter_of(c.inner))

    def test_refuses_once_spent_and_counts_refusals(self):
        c = _client(300)   # each call is 150 tokens: two pass, third is refused
        async def go():
            await c._create_completion([], "m")
            await c._create_completion([], "m")
            with self.assertRaises(TokenBudgetExceededError) as ctx:
                await c._create_completion([], "m")
            return ctx.exception
        exc = asyncio.run(go())
        self.assertEqual(_Fake.calls, 2)
        self.assertEqual(c.meter.refused, 1)
        self.assertTrue(c.meter.spent)
        self.assertEqual(exc.code, "token_budget_exceeded")
        self.assertIn("token_budget_exceeded", str(exc))

    def test_last_call_may_overshoot_but_next_is_refused(self):
        c = _client(200)   # 150 passes (not spent), 300 passes (was not spent before it), then refused
        async def go():
            await c._create_completion([], "m")
            await c._create_completion([], "m")
            with self.assertRaises(TokenBudgetExceededError):
                await c._create_completion([], "m")
        asyncio.run(go())
        self.assertEqual(c.meter.used, 300)   # the overshoot is recorded, not clipped

    def test_delegates_count_tokens_and_unknown_attrs(self):
        c = _client(10)
        self.assertEqual(asyncio.run(c._count_tokens()), 7)
        self.assertEqual(c.seen_args, {})  # __getattr__ reaches the inner

    def test_needs_inner(self):
        cfg = OpenAIConfig(client_args={"token_budget": 5}, request_args={})
        with self.assertRaises(ValueError):
            BudgetedClient(cfg)

    def test_snapshot_has_budget_and_report(self):
        c = _client(1000)
        asyncio.run(c._create_completion([], "m"))
        snap = c.meter.snapshot()
        self.assertEqual(snap["budget"], 1000)
        self.assertEqual(snap["used"], 150)
        self.assertEqual(snap["calls"], 1)
        self.assertEqual(snap["totalTokens"], 150)


if __name__ == "__main__":
    unittest.main()
