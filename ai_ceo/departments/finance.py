"""Finance: unit economics, budget allocation, kill criteria. Cheap; runs every cycle."""
from __future__ import annotations

from ..context import CEO_IDENTITY, Context
from ..llm import LLM
from ..schemas import FinanceView

SYSTEM = CEO_IDENTITY + """

Task: act as the finance lead. Work only from the metrics and budget you are given; if revenue is
unknown, say so and describe what to instrument first. Allocate the monthly budget across departments
(marketing, distribution, engineering, tools) and state explicit kill criteria for any spend."""


def review(llm: LLM, ctx: Context) -> FinanceView:
    user = f"{ctx.company_block()}\n\n{ctx.operations_block()}\n\nProduce the FinanceView for the coming month."
    return llm.structured("finance.review", SYSTEM, user, FinanceView, effort="medium")
