"""Thin wrapper around the Anthropic SDK.

One entry point, `Claude.structured()`, runs a (possibly tool-using) turn and returns a
validated Pydantic object. Web research is done with Anthropic's server-side web_search /
web_fetch tools, so nothing runs locally. Usage is metered so the CEO can stop when a cycle
exceeds its LLM budget.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# USD per million tokens (input, output). Used only for budget accounting.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 12},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
]


class BudgetExceeded(RuntimeError):
    pass


class ModelRefused(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    usd: float = 0.0
    log: list[dict[str, Any]] = field(default_factory=list)

    def add(self, model: str, inp: int, out: int, label: str) -> None:
        pin, pout = PRICES.get(model, (5.0, 25.0))
        cost = inp / 1e6 * pin + out / 1e6 * pout
        self.input_tokens += inp
        self.output_tokens += out
        self.calls += 1
        self.usd += cost
        self.log.append({"label": label, "model": model, "in": inp, "out": out, "usd": round(cost, 4)})


class LLM(Protocol):
    usage: Usage

    def structured(self, label: str, system: str, user: str, schema: type[T], *, web: bool = False,
                   effort: str | None = None, max_tokens: int = 16000) -> T: ...


class Claude:
    """Production LLM backed by the Anthropic API."""

    def __init__(self, model: str = "claude-opus-5", effort: str = "high", budget_usd: float | None = None,
                 client: Any = None):
        import anthropic  # imported lazily so tests can run without the package configured

        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.budget_usd = budget_usd
        self.usage = Usage()

    def _check_budget(self) -> None:
        if self.budget_usd is not None and self.usage.usd >= self.budget_usd:
            raise BudgetExceeded(f"LLM spend {self.usage.usd:.2f} USD reached the per-cycle cap {self.budget_usd:.2f}")

    def structured(self, label: str, system: str, user: str, schema: type[T], *, web: bool = False,
                   effort: str | None = None, max_tokens: int = 16000) -> T:
        self._check_budget()
        json_schema = schema.model_json_schema()
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        request: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort or self.effort,
                "format": {"type": "json_schema", "schema": json_schema},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if web:
            request["tools"] = WEB_TOOLS

        for _ in range(8):  # pause_turn continuations for long web-research turns
            response = self.client.beta.messages.create(messages=messages, **request)
            self.usage.add(self.model, response.usage.input_tokens, response.usage.output_tokens, label)
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                raise ModelRefused(f"{label}: model declined ({getattr(details, 'category', 'unknown')})")
            if response.stop_reason == "max_tokens":
                raise RuntimeError(f"{label}: output truncated at max_tokens={max_tokens}")
            text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
            return schema.model_validate_json(text)
        raise RuntimeError(f"{label}: turn still paused after 8 continuations")


class FakeLLM:
    """Deterministic stand-in for tests and `--dry-run`. Returns handler(schema, user) or a
    minimal valid instance built from the schema's example factory."""

    def __init__(self, handler=None):
        self.handler = handler
        self.usage = Usage()
        self.calls: list[tuple[str, type[BaseModel], str]] = []

    def structured(self, label, system, user, schema, *, web=False, effort=None, max_tokens=16000):
        self.calls.append((label, schema, user))
        self.usage.add("claude-opus-5", 1000, 500, label)
        if self.handler:
            out = self.handler(label, schema, user)
            if out is not None:
                return out
        example = getattr(schema, "example", None)
        if example is None:
            raise NotImplementedError(f"FakeLLM has no example for {schema.__name__}")
        return example()


def pretty(obj: BaseModel) -> str:
    return json.dumps(obj.model_dump(mode="json"), indent=2)
