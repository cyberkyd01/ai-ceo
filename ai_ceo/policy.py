"""Decides what the CEO may do on its own and what must wait for the owner.

Risk levels on every action:
  read      - looking things up. Always allowed.
  internal  - writes inside the company folder or the product repo (branches, issues, assets). Always allowed.
  publish   - anything the public can see: posts, listings, pull requests to main. Allowed only in
              autonomous mode AND when an integration exists; otherwise queued for approval.
  spend     - costs money. Allowed only when below the auto-spend limit and within monthly budget.
Manual actions (account sign-ups, KYC, legal, anything needing a captcha or a credit card) are never
executed by the system; they become checklists in the approval queue.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .schemas import Action


@dataclass
class Verdict:
    allowed: bool
    reason: str


def evaluate(action: Action, settings: Settings, spent_this_month: float, integration_available: bool) -> Verdict:
    if action.kind == "manual":
        return Verdict(False, "requires a human (account creation, legal, payment details)")
    if action.risk in ("read", "internal"):
        return Verdict(True, "internal change")
    if action.risk == "publish":
        if not integration_available:
            return Verdict(False, "no integration configured for this channel; prepared as a packet")
        if settings.autonomy != "autonomous":
            return Verdict(False, "supervised mode: publishing needs owner approval")
        return Verdict(True, "autonomous mode with integration")
    if action.risk == "spend":
        cost = action.estimated_cost_usd
        if spent_this_month + cost > settings.monthly_budget_usd:
            return Verdict(False, f"would exceed monthly budget ({spent_this_month:.0f} + {cost:.0f} > {settings.monthly_budget_usd:.0f} USD)")
        if settings.autonomy == "autonomous" and cost <= settings.auto_spend_limit_usd:
            return Verdict(True, "within auto-spend limit")
        return Verdict(False, "spend needs owner approval")
    return Verdict(False, "unknown risk level")
