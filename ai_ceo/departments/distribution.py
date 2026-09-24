"""Distribution: decides where the product should exist and prepares complete listing packets."""
from __future__ import annotations

from ..context import CEO_IDENTITY, Context
from ..llm import LLM
from ..platforms import PLATFORMS
from ..schemas import ListingPacket
from ..state import CompanyStore

SYSTEM = CEO_IDENTITY + """

Task: prepare a complete, copy-paste-ready listing packet for one platform. Respect that platform's
field limits (tagline length, description length, tag counts). `submission_steps` must be the exact
clicks a human needs, including account creation if required, and any fees. Links must be real URLs
from the dossier; never invent a domain."""


def platform_entry(name: str) -> dict | None:
    lname = name.lower()
    for p in PLATFORMS:
        if p["name"].lower() == lname or lname in p["name"].lower():
            return p
    return None


def listing_packet(llm: LLM, ctx: Context, store: CompanyStore, platform: str, notes: str = "") -> tuple[ListingPacket, str]:
    entry = platform_entry(platform) or {"name": platform, "kind": "unknown", "url": "", "why": ""}
    user = (f"{ctx.company_block()}\n\n## Platform\n{entry['name']} ({entry['kind']}) {entry.get('url', '')}\n"
            f"Why it matters: {entry.get('why', '')}\nCEO notes: {notes}\n\nProduce the ListingPacket.")
    packet = llm.structured("distribution.packet", SYSTEM, user, ListingPacket, effort="medium")
    safe = "".join(c if c.isalnum() else "-" for c in entry["name"].lower()).strip("-")
    md = [f"# Listing packet: {packet.platform}", "", f"**Tagline:** {packet.tagline}", "",
          f"**Short description:** {packet.short_description}", "", "## Long description", packet.long_description, "",
          "## Categories / tags", ", ".join(packet.categories), ", ".join(packet.tags), "", "## Links"]
    md += [f"- {k}: {v}" for k, v in packet.links.items()]
    md += ["", "## Assets needed"] + [f"- {a}" for a in packet.assets_needed]
    md += ["", "## Submission steps"] + [f"{i}. {s}" for i, s in enumerate(packet.submission_steps, 1)]
    path = store.write_output(f"distribution/{safe}.md", "\n".join(md) + "\n")
    return packet, str(path)
