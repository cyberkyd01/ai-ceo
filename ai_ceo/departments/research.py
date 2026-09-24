"""Research: turns raw ingestion facts into a ProductDossier, and runs market + competitor analysis."""
from __future__ import annotations

import json

from ..context import CEO_IDENTITY, Context
from ..llm import LLM
from ..schemas import MarketAnalysis, ProductDossier

DOSSIER_SYSTEM = CEO_IDENTITY + """

Task: read the raw facts gathered from a repository or server and describe the product honestly.
Base every field on evidence in the facts. Where something is unknown, say 'unknown' rather than guess.
`slug` must be lowercase letters, digits and hyphens only."""

ANALYSIS_SYSTEM = CEO_IDENTITY + """

Task: competitor and market analysis. Use web search to find real, current competitors (direct and
substitutes), their positioning and actual pricing pages, and where the target customers gather.
Cite the URLs you relied on in `sources`. Be concrete about gaps: features competitors lack, segments
they ignore, complaints in their reviews or issue trackers. Prefer 4-8 competitors over a long list."""


def build_dossier(llm: LLM, raw: dict, source: str) -> ProductDossier:
    facts = json.dumps(raw, indent=2)[:60000]
    user = f"Source: {source}\n\nRaw facts:\n{facts}\n\nProduce the ProductDossier."
    return llm.structured("research.dossier", DOSSIER_SYSTEM, user, ProductDossier, effort="medium")


def analyze_market(llm: LLM, ctx: Context) -> MarketAnalysis:
    prior = ctx.analysis.model_dump_json(indent=2) if ctx.analysis else "none"
    user = (f"{ctx.company_block()}\n\n## Prior analysis (may be stale)\n{prior}\n\n"
            "Run a fresh competitor and market analysis for this product.")
    return llm.structured("research.market", ANALYSIS_SYSTEM, user, MarketAnalysis, web=True, max_tokens=24000)
