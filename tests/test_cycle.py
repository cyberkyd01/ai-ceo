"""End-to-end cycle against a local folder with a fake model: no network, no API key."""
import json
from pathlib import Path

from ai_ceo.ceo import CEO
from ai_ceo.config import Settings
from ai_ceo.llm import FakeLLM
from ai_ceo.schemas import Action, CyclePlan, Decision


def make_product(tmp_path: Path) -> Path:
    prod = tmp_path / "product"
    prod.mkdir()
    (prod / "README.md").write_text("# Widget\n\nA CLI that converts things.\n")
    (prod / "pyproject.toml").write_text("[project]\nname='widget'\n")
    return prod


def plan_with(kinds):
    actions = []
    for i, (kind, risk, payload) in enumerate(kinds):
        actions.append(Action(kind=kind, title=f"{kind} {i}", risk=risk, department="marketing", payload=payload,
                              estimated_cost_usd=float(payload.get("amount_usd", 0))))
    return CyclePlan(situation="s", priorities=["p"], decisions=[Decision(
        title="d", rationale="r", options_considered=["a"], expected_impact=3, confidence=3,
        reversibility="reversible", actions=actions)], metrics_to_watch=[], questions_for_owner=["Domain?"])


def test_bootstrap_and_cycle_supervised(tmp_path):
    settings = Settings(home=tmp_path / "companies", autonomy="supervised", coder="none")
    plan = plan_with([
        ("write_asset", "internal", {"asset": "launch_post", "brief": "launch"}),
        ("publish_post", "publish", {"channel": "devto", "asset": "launch_post", "brief": "x", "tags": "cli"}),
        ("submit_listing", "publish", {"platform": "Product Hunt"}),
        ("spend", "spend", {"what": "domain", "amount_usd": "12"}),
        ("manual", "internal", {"what": "create PH account", "steps": "go\nsign up"}),
        ("github_issue", "internal", {"brief": "add export"}),
    ])
    llm = FakeLLM(lambda label, schema, user: plan if schema is CyclePlan else None)
    ceo = CEO.bootstrap(str(make_product(tmp_path)), settings, llm, name="Widget")
    assert ceo.store.get("dossier")["name"] == "Widget"

    summary = ceo.run_cycle()
    assert "6 actions" in summary
    statuses = {a["kind"]: a["status"] for a in ceo.store.actions(limit=100)}
    assert statuses["write_asset"] == "done"
    assert statuses["publish_post"] == "awaiting_approval"     # supervised + no dev.to key
    assert statuses["submit_listing"] == "awaiting_approval"   # Product Hunt is manual
    assert statuses["spend"] == "awaiting_approval"
    assert statuses["manual"] == "awaiting_approval"
    assert statuses["github_issue"] == "done"                  # local repo, no remote: spec kept
    # prepared material exists for the owner
    for a in ceo.store.actions(status="awaiting_approval"):
        assert Path(json.loads(a["payload"])["prepared_path"]).exists()
    # research, strategy, finance and reflection all ran and were persisted
    for key in ("analysis", "strategy", "finance"):
        assert ceo.store.get(key)
    assert "ship faster" in ceo.store.read_memory("learnings.md")
    assert ceo.store.read_memory("brief.md").strip() == "Early stage company."
    report = sorted((ceo.store.outputs_dir / "reports").glob("*.md"))[-1].read_text()
    assert "Waiting for you" in report and "Domain?" in report
    assert ceo.store.cycles(1)[0]["status"] == "ok"
    labels = [c[0] for c in llm.calls]
    assert "research.market" in labels and "ceo.decide" in labels and "ceo.reflect" in labels


def test_second_cycle_skips_fresh_research(tmp_path):
    settings = Settings(home=tmp_path / "companies", coder="none")
    llm = FakeLLM()
    ceo = CEO.bootstrap(str(make_product(tmp_path)), settings, llm)
    ceo.run_cycle()
    n = len([c for c in llm.calls if c[0] == "research.market"])
    ceo.run_cycle()
    assert len([c for c in llm.calls if c[0] == "research.market"]) == n


def test_approve_manual_action(tmp_path):
    from ai_ceo.context import Context
    from ai_ceo.executor import Executor
    settings = Settings(home=tmp_path / "companies", coder="none")
    plan = plan_with([("manual", "internal", {"what": "x", "steps": "y"})])
    llm = FakeLLM(lambda label, schema, user: plan if schema is CyclePlan else None)
    ceo = CEO.bootstrap(str(make_product(tmp_path)), settings, llm)
    ceo.run_cycle()
    aid = ceo.store.actions(status="awaiting_approval")[0]["id"]
    ex = Executor(ceo.store, llm, settings, Context.load(ceo.store, settings))
    assert ex.approve(aid) == "done"
    assert ceo.store.action(aid)["status"] == "done"
