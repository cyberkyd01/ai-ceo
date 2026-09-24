from ai_ceo.config import Settings
from ai_ceo.policy import evaluate
from ai_ceo.schemas import Action


def act(kind="publish_post", risk="publish", cost=0.0):
    return Action(kind=kind, title="t", risk=risk, department="marketing", payload={}, estimated_cost_usd=cost)


def test_internal_always_allowed():
    assert evaluate(act("write_asset", "internal"), Settings(), 0, False).allowed


def test_manual_never_auto():
    assert not evaluate(act("manual", "internal"), Settings(autonomy="autonomous"), 0, True).allowed


def test_publish_needs_autonomous_and_integration():
    assert not evaluate(act(), Settings(autonomy="supervised"), 0, True).allowed
    assert not evaluate(act(), Settings(autonomy="autonomous"), 0, False).allowed
    assert evaluate(act(), Settings(autonomy="autonomous"), 0, True).allowed


def test_spend_respects_budget_and_limit():
    s = Settings(autonomy="autonomous", monthly_budget_usd=100, auto_spend_limit_usd=20)
    assert evaluate(act("spend", "spend", 10), s, 0, True).allowed
    assert not evaluate(act("spend", "spend", 50), s, 0, True).allowed          # above auto limit
    assert not evaluate(act("spend", "spend", 10), s, 95, True).allowed         # over monthly budget
    assert not evaluate(act("spend", "spend", 10), Settings(autonomy="supervised"), 0, True).allowed
