"""Marketing: produces concrete assets (posts, threads, landing copy, SEO plans, outreach) into outputs/."""
from __future__ import annotations

from ..context import CEO_IDENTITY, Context
from ..llm import LLM
from ..schemas import MarketingAsset
from ..state import CompanyStore

SYSTEM = CEO_IDENTITY + """

Task: write one marketing asset. Write for the ideal customer, in their language, leading with the
problem and the USP. No hype words, no invented numbers or testimonials. If the asset is for a
community (Reddit, Hacker News), it must be useful on its own even to people who never click through,
and it must follow that community's self-promotion norms. Markdown only in `body_markdown`."""

ASSET_GUIDES = {
    "launch_post": "A launch announcement article (600-1200 words): problem, why existing tools fall short, what this does differently, how to start, honest limitations.",
    "show_hn": "A Show HN submission: a title under 80 chars starting with 'Show HN:' and a first-comment body (150-300 words) explaining what it is, why you built it, and what feedback you want.",
    "reddit_post": "A subreddit post. Payload gives the subreddit. Lead with value, mention the product once, invite discussion.",
    "twitter_thread": "A build-in-public thread of 5-8 tweets, each under 280 characters, numbered.",
    "linkedin_post": "A LinkedIn post (150-250 words) for a B2B buyer: outcome first, then how.",
    "landing_copy": "Landing page copy: hero headline, subheadline, three benefit blocks with concrete outcomes, how it works, pricing block, FAQ (5 questions), CTA.",
    "seo_plan": "An SEO plan: 15 target keywords with intent and difficulty guess, 6 article briefs (title, target keyword, outline), and internal linking notes.",
    "outreach_email": "A cold email under 120 words to a specific persona in the ICP, plus two follow-ups. Personalization placeholders in {braces}.",
    "newsletter": "A newsletter issue (300-500 words) for existing users: what shipped, why it matters, what is next.",
    "comparison_page": "A '<Product> vs <Competitor>' comparison page: honest table of differences, who each is best for, migration notes.",
}


def write_asset(llm: LLM, ctx: Context, store: CompanyStore, asset_type: str, brief: str, extra: dict | None = None) -> tuple[MarketingAsset, str]:
    guide = ASSET_GUIDES.get(asset_type, f"An asset of type '{asset_type}' as described in the brief.")
    details = "\n".join(f"- {k}: {v}" for k, v in (extra or {}).items() if k not in ("asset", "brief"))
    user = (f"{ctx.company_block()}\n\n## Asset to write\nType: {asset_type}\nGuide: {guide}\nBrief from the CEO: {brief}\n{details}")
    asset = llm.structured(f"marketing.{asset_type}", SYSTEM, user, MarketingAsset)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in asset.title.lower())[:60].strip("-") or asset_type
    path = store.write_output(f"marketing/{asset_type}/{safe}.md",
                              f"# {asset.title}\n\n_Channel notes: {asset.channel_notes}_\n\n{asset.body_markdown}\n")
    return asset, str(path)
