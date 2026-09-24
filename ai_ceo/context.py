"""Everything a department needs to know about the company, rendered once per cycle."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Settings
from .schemas import MarketAnalysis, ProductDossier, Strategy
from .state import CompanyStore

CEO_IDENTITY = """You are the CEO of a small software company. The owner has delegated the running of the
company to you: research, strategy, marketing, distribution, product decisions, and finance. You act
through a small set of departments and a queue of concrete actions.

How you operate:
- You make evaluated decisions: name the options you considered, the expected impact, your confidence,
  and whether the move is reversible. Prefer cheap reversible experiments over big bets until data says otherwise.
- You compete on a real, defensible unique selling proposition, not on adjectives. Look at what
  competitors actually ship and price, and pick fights you can win.
- Distribution is most of the game for a small product. Be specific about which channels the ideal
  customer already uses and go there with something genuinely useful, never spam.
- You never invent metrics, revenue, customers, or testimonials. If you do not know, say so.
- Actions that need a human (creating accounts, entering payment details, legal, anything with a
  captcha) are prepared as complete packets so the owner can finish them in minutes.
- You are frugal with money and with the owner's attention. Ask them only what you cannot decide."""


@dataclass
class Context:
    settings: Settings
    dossier: ProductDossier
    analysis: MarketAnalysis | None
    strategy: Strategy | None
    metrics: dict[str, float]
    brief: str
    learnings: str
    recent_decisions: list[dict]
    open_actions: list[dict]
    spent_this_month: float
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, store: CompanyStore, settings: Settings) -> "Context":
        dossier_raw = store.get("dossier")
        if not dossier_raw:
            raise RuntimeError("company has no dossier; run `ai-ceo init` first")
        analysis_raw = store.get("analysis")
        strategy_raw = store.get("strategy")
        return cls(
            settings=settings,
            dossier=ProductDossier.model_validate(dossier_raw),
            analysis=MarketAnalysis.model_validate(analysis_raw) if analysis_raw else None,
            strategy=Strategy.model_validate(strategy_raw) if strategy_raw else None,
            metrics=store.latest_metrics(),
            brief=store.read_memory("brief.md"),
            learnings=store.read_memory("learnings.md"),
            recent_decisions=store.recent_decisions(),
            open_actions=[dict(r) for r in store.actions(status="awaiting_approval")] + [dict(r) for r in store.actions(status="queued")],
            spent_this_month=store.spend_this_month_usd(),
        )

    # ---- rendering helpers used inside prompts -------------------------------------
    def company_block(self) -> str:
        parts = [f"# Company: {self.dossier.name}", "## Product dossier", self.dossier.model_dump_json(indent=2)]
        if self.strategy:
            parts += ["## Current strategy", self.strategy.model_dump_json(indent=2)]
        if self.analysis:
            parts += ["## Latest market analysis", self.analysis.model_dump_json(indent=2)]
        parts += ["## Latest metrics", json.dumps(self.metrics or {"note": "no metrics recorded yet"}, indent=2)]
        if self.brief.strip():
            parts += ["## Company brief (memory)", self.brief.strip()]
        if self.learnings.strip():
            parts += ["## Learnings from previous cycles", self.learnings.strip()[-6000:]]
        return "\n\n".join(parts)

    def operations_block(self) -> str:
        s = self.settings
        lines = [
            "## Operating constraints",
            f"- Autonomy mode: {s.autonomy} (supervised = publishing and spending wait for owner approval)",
            f"- Monthly budget: {s.monthly_budget_usd:.0f} USD; spent so far this month: {self.spent_this_month:.2f} USD",
            f"- Auto-spend limit per action: {s.auto_spend_limit_usd:.0f} USD",
            f"- Integrations available: dev.to={'yes' if s.has('devto_api_key') else 'no'}, "
            f"reddit={'yes' if s.has('reddit_client_id', 'reddit_client_secret', 'reddit_username', 'reddit_password') else 'no'}, "
            f"webhook(X/LinkedIn/etc)={'yes' if s.has('webhook_url') else 'no'}, github=yes, "
            f"coder={'Claude Code headless' if s.coder == 'claude' else 'none (issues only)'}",
        ]
        if self.open_actions:
            lines.append("## Actions already queued or awaiting approval (do not duplicate)")
            for a in self.open_actions[:30]:
                lines.append(f"- #{a['id']} [{a['status']}] {a['kind']}: {a['title']}")
        if self.recent_decisions:
            lines.append("## Recent decisions")
            for d in self.recent_decisions[:15]:
                lines.append(f"- {d['created_at'][:10]} {d['title']} (actions: {d.get('statuses') or 'none'})")
        return "\n".join(lines)
