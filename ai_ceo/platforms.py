"""Registry of places a product can be listed, launched, or discussed.

`api` says whether this system can submit automatically (given credentials). Everything else is
prepared as a ListingPacket the owner submits by hand: most launch platforms forbid automated
account creation and require a human, a captcha, or a verified identity.
"""
from __future__ import annotations

PLATFORMS: list[dict] = [
    # name, kind, fits (categories), api, url, why
    {"name": "Product Hunt", "kind": "launch", "fits": ["developer tool", "B2B SaaS", "consumer app", "browser extension", "mobile app"],
     "api": None, "url": "https://www.producthunt.com/posts/new", "why": "Biggest single-day launch spike; requires a human maker account."},
    {"name": "Hacker News (Show HN)", "kind": "community", "fits": ["developer tool", "CLI", "library", "API", "open source"],
     "api": None, "url": "https://news.ycombinator.com/submit", "why": "Technical early adopters. No posting API; post by hand."},
    {"name": "dev.to", "kind": "content", "fits": ["developer tool", "CLI", "library", "API", "open source", "B2B SaaS"],
     "api": "devto", "url": "https://dev.to", "why": "Long-form technical posts rank on Google and get syndicated."},
    {"name": "Reddit", "kind": "community", "fits": ["*"], "api": "reddit", "url": "https://www.reddit.com",
     "why": "Niche subreddits are where the ICP actually talks. Follow each sub's self-promo rules."},
    {"name": "GitHub (topics, awesome lists, README polish)", "kind": "directory", "fits": ["developer tool", "CLI", "library", "API", "open source"],
     "api": "github", "url": "https://github.com", "why": "Topics + a strong README are free SEO for developer products."},
    {"name": "AlternativeTo", "kind": "directory", "fits": ["*"], "api": None, "url": "https://alternativeto.net/manage-item/",
     "why": "Captures 'alternative to <competitor>' search traffic."},
    {"name": "G2", "kind": "review", "fits": ["B2B SaaS"], "api": None, "url": "https://www.g2.com/products/new",
     "why": "Buyers compare B2B tools here; reviews compound."},
    {"name": "Capterra", "kind": "review", "fits": ["B2B SaaS"], "api": None, "url": "https://www.capterra.com/vendors/sign-up",
     "why": "Same as G2, different audience."},
    {"name": "SaaSHub", "kind": "directory", "fits": ["B2B SaaS", "developer tool"], "api": None, "url": "https://www.saashub.com/submit",
     "why": "Cheap directory backlinks and comparison pages."},
    {"name": "BetaList", "kind": "launch", "fits": ["B2B SaaS", "consumer app"], "api": None, "url": "https://betalist.com/submit",
     "why": "Early-adopter signups pre-launch."},
    {"name": "Indie Hackers", "kind": "community", "fits": ["*"], "api": None, "url": "https://www.indiehackers.com",
     "why": "Founders share revenue and give honest feedback."},
    {"name": "X / Twitter", "kind": "social", "fits": ["*"], "api": "webhook", "url": "https://x.com",
     "why": "Build-in-public threads. Routed through the outbound webhook."},
    {"name": "LinkedIn", "kind": "social", "fits": ["B2B SaaS"], "api": "webhook", "url": "https://www.linkedin.com",
     "why": "B2B buyers. Routed through the outbound webhook."},
    {"name": "Chrome Web Store", "kind": "marketplace", "fits": ["browser extension"], "api": None,
     "url": "https://chrome.google.com/webstore/devconsole", "why": "Required distribution channel; $5 developer fee."},
    {"name": "PyPI / npm / crates.io", "kind": "marketplace", "fits": ["library", "CLI"], "api": None,
     "url": "", "why": "Package registries are the distribution channel for libraries; publish from CI."},
    {"name": "Google Search Console + sitemap", "kind": "seo", "fits": ["*"], "api": None,
     "url": "https://search.google.com/search-console", "why": "Without it you are invisible to organic search."},
    {"name": "Uneed / MicroLaunch / Peerlist Launchpad", "kind": "launch", "fits": ["*"], "api": None, "url": "",
     "why": "Smaller launch sites with easier front pages and backlinks."},
]


def catalog_for(category: str) -> list[dict]:
    cat = category.lower()
    out = []
    for p in PLATFORMS:
        fits = [f.lower() for f in p["fits"]]
        if "*" in fits or any(f in cat or cat in f for f in fits):
            out.append(p)
    return out


def describe(platforms: list[dict]) -> str:
    return "\n".join(f"- {p['name']} [{p['kind']}] api={'yes' if p['api'] else 'manual'}: {p['why']}" for p in platforms)
