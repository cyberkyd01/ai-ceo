"""Pydantic models shared by every department. Each has an `example()` used by tests/dry runs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- product ----------

class ProductDossier(Strict):
    name: str
    slug: str
    source: str = Field(description="GitHub URL or VPS host the company was created from")
    one_liner: str
    description: str
    category: str = Field(description="e.g. developer tool, B2B SaaS, consumer app, CLI, library, API")
    stack: list[str]
    features: list[str]
    target_users: str
    monetization: str = Field(description="How it makes (or could make) money; 'none yet' if unknown")
    live_urls: list[str]
    maturity: Literal["idea", "prototype", "mvp", "growing", "established"]
    notable_gaps: list[str] = Field(description="Obvious missing pieces: docs, tests, landing page, pricing, analytics")

    @classmethod
    def example(cls) -> "ProductDossier":
        return cls(name="Example", slug="example", source="https://github.com/acme/example", one_liner="Does X for Y",
                   description="A tool.", category="developer tool", stack=["python"], features=["a"],
                   target_users="developers", monetization="none yet", live_urls=[], maturity="mvp",
                   notable_gaps=["no landing page"])


# ---------------------------------------------------------------- research ---------

class Competitor(Strict):
    name: str
    url: str
    positioning: str
    pricing: str
    strengths: list[str]
    weaknesses: list[str]


class MarketAnalysis(Strict):
    market_summary: str
    market_size_note: str = Field(description="Best available signal on size/growth, with the source named")
    competitors: list[Competitor]
    gaps: list[str] = Field(description="Things competitors do badly or not at all")
    threats: list[str]
    opportunities: list[str]
    ideal_customer_profile: str
    channels_where_customers_are: list[str] = Field(description="Communities, platforms, search terms")
    sources: list[str]

    @classmethod
    def example(cls) -> "MarketAnalysis":
        return cls(market_summary="Crowded but growing.", market_size_note="unknown",
                   competitors=[Competitor(name="Rival", url="https://rival.example", positioning="cheap",
                                           pricing="$10/mo", strengths=["brand"], weaknesses=["slow"])],
                   gaps=["no self-hosting"], threats=["big incumbents"], opportunities=["indie devs"],
                   ideal_customer_profile="solo developers", channels_where_customers_are=["Hacker News"],
                   sources=["https://rival.example"])


# ---------------------------------------------------------------- strategy ---------

class OKR(Strict):
    objective: str
    key_results: list[str]
    horizon_days: int


class Strategy(Strict):
    usp: str = Field(description="One sentence. The single reason to choose us over every competitor.")
    positioning_statement: str
    ideal_customer_profile: str
    pricing_model: str
    differentiators: list[str] = Field(description="Concrete capabilities we have or will build that competitors lack")
    do_not_do: list[str] = Field(description="Explicit non-goals so effort is not diluted")
    okrs: list[OKR]
    biggest_risks: list[str]

    @classmethod
    def example(cls) -> "Strategy":
        return cls(usp="Fastest self-hosted option.", positioning_statement="For devs who...",
                   ideal_customer_profile="solo devs", pricing_model="freemium",
                   differentiators=["self-host"], do_not_do=["enterprise SSO"],
                   okrs=[OKR(objective="Launch", key_results=["100 stars"], horizon_days=30)],
                   biggest_risks=["no distribution"])


# ---------------------------------------------------------------- decisions --------

ActionKind = Literal[
    "github_issue",        # write a spec as an issue on the product repo
    "implement_feature",   # have the coder implement a spec on a branch and open a PR
    "publish_post",        # article / announcement (dev.to, reddit, webhook, or manual packet)
    "submit_listing",      # register/list the product on a platform (API where possible, else packet)
    "write_asset",         # produce a marketing asset into the company outputs folder
    "spend",               # any action that costs money (ads, tools, domains)
    "manual",              # something only a human can do: account creation, KYC, legal
]
Risk = Literal["read", "internal", "publish", "spend"]


class Action(Strict):
    kind: ActionKind
    title: str
    risk: Risk
    department: Literal["research", "strategy", "marketing", "distribution", "engineering", "finance"]
    payload: dict[str, str] = Field(description="Kind-specific fields. See department docs.")
    estimated_cost_usd: float = 0.0


class Decision(Strict):
    title: str
    rationale: str
    options_considered: list[str]
    expected_impact: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    reversibility: Literal["reversible", "partially_reversible", "irreversible"]
    actions: list[Action]


class CyclePlan(Strict):
    situation: str = Field(description="Two or three sentences: where the company is right now")
    priorities: list[str] = Field(description="Ordered. What matters most this cycle and why")
    decisions: list[Decision]
    metrics_to_watch: list[str]
    questions_for_owner: list[str] = Field(description="Only things the CEO truly cannot decide alone")

    @classmethod
    def example(cls) -> "CyclePlan":
        return cls(situation="Early.", priorities=["launch"], decisions=[Decision(
            title="Write launch post", rationale="Need awareness", options_considered=["ads"],
            expected_impact=4, confidence=3, reversibility="reversible",
            actions=[Action(kind="write_asset", title="Launch post", risk="internal", department="marketing",
                            payload={"asset": "launch_post"})])],
            metrics_to_watch=["stars"], questions_for_owner=[])


# ---------------------------------------------------------------- outputs ----------

class MarketingAsset(Strict):
    asset_type: str
    title: str
    body_markdown: str
    channel_notes: str = Field(description="Where/how to use it, best time, tags")

    @classmethod
    def example(cls) -> "MarketingAsset":
        return cls(asset_type="launch_post", title="Hello", body_markdown="# Hi", channel_notes="dev.to")


class FeatureSpec(Strict):
    title: str
    problem: str
    proposed_solution: str
    acceptance_criteria: list[str]
    out_of_scope: list[str]
    competitor_reference: str = Field(description="Which competitor gap this closes, or 'none'")
    effort: Literal["small", "medium", "large"]

    @classmethod
    def example(cls) -> "FeatureSpec":
        return cls(title="Add export", problem="No export", proposed_solution="CSV button",
                   acceptance_criteria=["button exists"], out_of_scope=["PDF"], competitor_reference="none",
                   effort="small")


class ListingPacket(Strict):
    platform: str
    product_name: str
    tagline: str = Field(description="<= 60 chars")
    short_description: str = Field(description="<= 260 chars")
    long_description: str
    categories: list[str]
    tags: list[str]
    links: dict[str, str]
    assets_needed: list[str] = Field(description="logo sizes, screenshots, video")
    submission_steps: list[str]

    @classmethod
    def example(cls) -> "ListingPacket":
        return cls(platform="Product Hunt", product_name="Example", tagline="Does X", short_description="Does X for Y.",
                   long_description="...", categories=["Developer Tools"], tags=["cli"], links={"site": "https://x"},
                   assets_needed=["logo 240x240"], submission_steps=["Create account"])


class Reflection(Strict):
    what_worked: list[str]
    what_did_not: list[str]
    learnings: list[str] = Field(description="Durable lessons to carry into future cycles")
    strategy_still_valid: bool
    suggested_strategy_changes: list[str]
    brief_update: str = Field(description="3-6 sentences: the standing company brief, rewritten to reflect the current state")

    @classmethod
    def example(cls) -> "Reflection":
        return cls(what_worked=[], what_did_not=[], learnings=["ship faster"], strategy_still_valid=True,
                   suggested_strategy_changes=[], brief_update="Early stage company.")


class FinanceView(Strict):
    unit_economics: str
    burn_note: str
    budget_allocation: dict[str, float] = Field(description="Department -> USD for the coming month")
    revenue_levers: list[str]
    stop_doing_if: list[str] = Field(description="Kill criteria for current spend")

    @classmethod
    def example(cls) -> "FinanceView":
        return cls(unit_economics="unknown", burn_note="none", budget_allocation={"marketing": 50.0},
                   revenue_levers=["paid tier"], stop_doing_if=["no signups in 30 days"])
