"""Exercises the production request path with a stub client: parameter shape, pause_turn
continuation, refusal handling, and JSON parsing. No network."""
from types import SimpleNamespace

import pytest

from ai_ceo.llm import Claude, ModelRefused
from ai_ceo.schemas import FinanceView


def response(stop, text=None):
    content = [SimpleNamespace(type="text", text=text)] if text else []
    return SimpleNamespace(stop_reason=stop, content=content, usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                           stop_details=SimpleNamespace(category="cyber"))


class StubMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def make(responses):
    msgs = StubMessages(responses)
    client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return Claude(model="claude-opus-5", effort="high", budget_usd=1.0, client=client), msgs


def test_request_shape_and_pause_turn():
    good = FinanceView.example().model_dump_json()
    llm, msgs = make([response("pause_turn"), response("end_turn", good)])
    out = llm.structured("t", "sys", "user", FinanceView, web=True)
    assert out.budget_allocation == {"marketing": 50.0}
    first = msgs.calls[0]
    assert first["model"] == "claude-opus-5"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"]["effort"] == "high"
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["betas"]
    assert first["tools"][0]["type"] == "web_search_20260209"
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # continuation carries the paused assistant turn
    assert msgs.calls[1]["messages"][-1]["role"] == "assistant"
    assert llm.usage.calls == 2 and llm.usage.usd > 0


def test_refusal_raises():
    llm, _ = make([response("refusal")])
    with pytest.raises(ModelRefused):
        llm.structured("t", "sys", "user", FinanceView)


def test_budget_cap():
    llm, _ = make([response("end_turn", FinanceView.example().model_dump_json())])
    llm.usage.usd = 5.0
    from ai_ceo.llm import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        llm.structured("t", "sys", "user", FinanceView)
