"""An OpenAI client that stops the model once a token budget is spent.

Registered with Nexus as ``budgeted``. It wraps whichever real client the
config names and adds one thing: a running sum of ``usage.total_tokens`` over
every completion it returned. When the sum reaches ``token_budget`` the next
call is refused with ``TokenBudgetExceededError``. The Host's LLM bridge turns
that into a failed model call inside the runtime, the CLI agent exits on it,
and the task closes the game run with ``reason: tokens``.

Why here and not in the game server: the server counts decisions, which it
sees; tokens are on the provider's meter, which only the process that calls
the model sees. Nexus routes every call of a sandboxed agent through the
Host's client, so this is the one place the count is complete.

Config::

    openai_clients:
      main:
        name: budgeted
        config:
          client_args:
            inner: openai                 # the real client's registry name
            token_budget: 2000000         # total tokens across the run
            count: total                  # or prompt_completion: exclude cache fields
            inner_client_args: {...}      # what the inner client would have got
          request_args: {...}             # passed through to the inner client
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from nexus.core import OpenAICompatibleClient, OpenAIConfig, openai_client_registry

logger = logging.getLogger(__name__)

TOKEN_BUDGET_EXCEEDED_CODE = "token_budget_exceeded"


class TokenBudgetExceededError(RuntimeError):
    """The run's token budget is spent; no further completion is made."""

    code = TOKEN_BUDGET_EXCEEDED_CODE

    def __init__(self, used: int, budget: int):
        super().__init__(
            f"{TOKEN_BUDGET_EXCEEDED_CODE}: {used} tokens used of a {budget} token budget; "
            f"the benchmark run is over")
        self.used = used
        self.budget = budget


class TokenMeter:
    """The running sum, kept apart from the client so a task can read it."""

    def __init__(self, budget: int, count: str = "total"):
        if budget <= 0:
            raise ValueError("token_budget must be positive")
        if count not in ("total", "prompt_completion"):
            raise ValueError("count must be total or prompt_completion")
        self.budget = budget
        self.count = count
        self.prompt = 0
        self.completion = 0
        self.total = 0
        self.cache_read = 0
        self.cache_write = 0
        self.calls = 0
        self.refused = 0
        self._lock = asyncio.Lock()

    @property
    def used(self) -> int:
        if self.count == "prompt_completion":
            return self.prompt + self.completion
        return self.total

    @property
    def left(self) -> int:
        return max(0, self.budget - self.used)

    @property
    def spent(self) -> bool:
        return self.used >= self.budget

    def add(self, usage: Any) -> None:
        """Book one completion's usage. Accepts the SDK's usage object or a
        dict; missing fields count as zero, since a provider that reports no
        meter cannot be charged for what it did not say."""
        if usage is None:
            return
        get = (usage.get if isinstance(usage, dict)
               else lambda k, d=None: getattr(usage, k, d))
        prompt = int(get("prompt_tokens", 0) or 0)
        completion = int(get("completion_tokens", 0) or 0)
        total = get("total_tokens")
        total = int(total) if total is not None else prompt + completion
        details = get("prompt_tokens_details") or {}
        dget = (details.get if isinstance(details, dict)
                else lambda k, d=None: getattr(details, k, d))
        self.cache_read += int(dget("cached_tokens", 0) or 0)
        self.cache_write += int(get("cache_creation_input_tokens", 0) or 0)
        self.prompt += prompt
        self.completion += completion
        self.total += total
        self.calls += 1

    def report(self) -> dict[str, int]:
        """The shape the broker's usage endpoint wants."""
        return {"input": self.prompt, "output": self.completion,
                "cacheRead": self.cache_read, "cacheWrite": self.cache_write,
                "totalTokens": self.total}

    def snapshot(self) -> dict[str, Any]:
        return {"budget": self.budget, "count": self.count, "used": self.used,
                "left": self.left, "spent": self.spent, "calls": self.calls,
                "refused": self.refused, **self.report()}


# One meter per client instance; tasks find theirs through the client.
@openai_client_registry.register("budgeted")
class BudgetedClient(OpenAICompatibleClient):
    """Wraps another registered client and enforces a token budget."""

    def __init__(self, config: OpenAIConfig):
        super().__init__(config)
        args = dict(config.client_args)
        inner_name = args.pop("inner", None)
        if not inner_name:
            raise ValueError("budgeted client needs client_args.inner: the real client's name")
        budget = int(args.pop("token_budget"))
        count = str(args.pop("count", "total"))
        inner_args = args.pop("inner_client_args", None)
        if inner_args is None:
            # Anything left over is the inner client's own configuration.
            inner_args = args
        inner_cls = openai_client_registry.get(inner_name)
        inner_config = OpenAIConfig(client_args=copy.deepcopy(inner_args),
                                    request_args=copy.deepcopy(config.request_args),
                                    enforced_request_args=copy.deepcopy(config.enforced_request_args))
        self.inner: OpenAICompatibleClient = inner_cls(inner_config)
        self.meter = TokenMeter(budget, count)
        # The bridge asks the client these; answer for the inner one.
        self.supports_request_meta = getattr(self.inner, "supports_request_meta", False)
        self.supports_native_responses_compaction = getattr(
            self.inner, "supports_native_responses_compaction", False)

    def __getattr__(self, name: str) -> Any:
        # Anything this wrapper does not define is the inner client's:
        # compact_response, provider-specific helpers, and so on. Only reached
        # when normal lookup fails, so the wrapper's own attributes win.
        inner = self.__dict__.get("inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    async def _create_completion(self, messages, model=None, **kwargs):
        meter = self.meter
        async with meter._lock:
            if meter.spent:
                meter.refused += 1
                logger.warning("token budget spent: %s/%s, refusing call #%s",
                               meter.used, meter.budget, meter.calls + meter.refused)
                raise TokenBudgetExceededError(meter.used, meter.budget)
        # The inner client's own create_completion carries the observe/cache
        # decorators and the runner-timeout credit; call the private hook so
        # those are not applied twice on one call.
        response = await self.inner._create_completion(messages, model, **kwargs)
        async with meter._lock:
            meter.add(getattr(response, "usage", None))
            if meter.spent:
                logger.info("token budget reached after this call: %s/%s",
                            meter.used, meter.budget)
        return response

    async def _count_tokens(self, **kwargs):
        return await self.inner._count_tokens(**kwargs)

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


def meter_of(client: Any) -> TokenMeter | None:
    """The meter behind a client, if it is a budgeted one."""
    return getattr(client, "meter", None) if isinstance(client, BudgetedClient) else None
