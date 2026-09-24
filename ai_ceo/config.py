"""Runtime configuration, loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no external dependency). Existing env vars win."""
    path = path or Path(".env")
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    model: str = "claude-opus-5"
    effort: str = "high"
    max_llm_usd_per_cycle: float = 5.0
    autonomy: str = "supervised"  # supervised | autonomous
    monthly_budget_usd: float = 200.0
    auto_spend_limit_usd: float = 0.0
    home: Path = field(default_factory=lambda: Path("./companies"))
    coder: str = "claude"  # claude | none
    coder_max_turns: int = 80
    integrations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        autonomy = _env("AI_CEO_AUTONOMY", "supervised").lower()
        if autonomy not in ("supervised", "autonomous"):
            autonomy = "supervised"
        return cls(
            model=_env("AI_CEO_MODEL", "claude-opus-5"),
            effort=_env("AI_CEO_EFFORT", "high").lower(),
            max_llm_usd_per_cycle=_float("AI_CEO_MAX_LLM_USD_PER_CYCLE", 5.0),
            autonomy=autonomy,
            monthly_budget_usd=_float("AI_CEO_MONTHLY_BUDGET_USD", 200.0),
            auto_spend_limit_usd=_float("AI_CEO_AUTO_SPEND_LIMIT_USD", 0.0),
            home=Path(_env("AI_CEO_HOME", "./companies")).expanduser(),
            coder=_env("AI_CEO_CODER", "claude").lower(),
            coder_max_turns=int(_env("AI_CEO_CODER_MAX_TURNS", "80") or 80),
            integrations={
                "devto_api_key": _env("DEVTO_API_KEY"),
                "reddit_client_id": _env("REDDIT_CLIENT_ID"),
                "reddit_client_secret": _env("REDDIT_CLIENT_SECRET"),
                "reddit_username": _env("REDDIT_USERNAME"),
                "reddit_password": _env("REDDIT_PASSWORD"),
                "webhook_url": _env("OUTBOUND_WEBHOOK_URL"),
                "stripe_api_key": _env("STRIPE_API_KEY"),
            },
        )

    def has(self, *keys: str) -> bool:
        return all(self.integrations.get(k) for k in keys)
