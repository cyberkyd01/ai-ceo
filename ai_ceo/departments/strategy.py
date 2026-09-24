"""Strategy: USP, positioning, pricing, OKRs. Re-run when the analysis changes or a reflection says the
strategy is no longer valid."""
from __future__ import annotations

from ..context import CEO_IDENTITY, Context
from ..llm import LLM
from ..schemas import Strategy

SYSTEM = CEO_IDENTITY + """

Task: set or revise the company strategy. The USP must be something competitors demonstrably do not
offer (check the analysis) and something this product can credibly deliver given its stack and
maturity. Pricing must be grounded in competitor pricing. OKRs must be measurable with the metrics
this company can actually collect. Keep `do_not_do` honest: a small team cannot chase everything."""


def formulate(llm: LLM, ctx: Context, reason: str) -> Strategy:
    user = f"{ctx.company_block()}\n\n{ctx.operations_block()}\n\nReason for (re)formulating strategy: {reason}\n\nProduce the Strategy."
    return llm.structured("strategy.formulate", SYSTEM, user, Strategy)
