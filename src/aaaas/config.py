"""Typed configuration, loaded from the environment with safe defaults.

Zero third-party dependencies on purpose: ``Settings.from_env()`` reads
``AAAAS_*`` variables (and a ``.env`` file if present) and returns plain
dataclasses. Defaults make the whole system run in in-memory demo mode.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class PersonalityMode(str, Enum):
    """Tone layer applied to human-facing messages (never to ledger data)."""

    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    GENZ = "genz"


@dataclass
class OdooSettings:
    in_memory: bool = True
    url: str = "http://localhost:8069"
    db: str = "odoo"
    username: str = "admin"
    password: str = "admin"


@dataclass
class ConfidenceThresholds:
    """Confidence gates from the architecture doc, §6."""

    auto: float = 0.90        # >= auto            -> act autonomously
    auto_flag: float = 0.70   # >= auto_flag       -> act, flag for review
    draft_hitl: float = 0.50  # >= draft_hitl      -> draft + escalate
    # below draft_hitl                              -> pause + notify


@dataclass
class PolicyLimits:
    price_variance_pct: float = 0.03      # 3-way match tolerance (3%)
    payment_hitl_limit: float = 1000.0    # payments above this always HITL
    reminder_auto_max_days: int = 30      # auto-send reminders up to N days late
    bank_match_date_window_days: int = 3  # ± window for bank line matching


@dataclass
class Settings:
    odoo: OdooSettings = field(default_factory=OdooSettings)
    confidence: ConfidenceThresholds = field(default_factory=ConfidenceThresholds)
    policy: PolicyLimits = field(default_factory=PolicyLimits)
    personality: PersonalityMode = PersonalityMode.PROFESSIONAL
    anthropic_api_key: str | None = None
    model: str = "claude-sonnet-4-6"
    finance_channel: str = "#finance"

    @classmethod
    def from_env(cls, environ: dict | None = None) -> "Settings":
        env = dict(os.environ if environ is None else environ)
        _load_dotenv_into(env)

        def b(key: str, default: bool) -> bool:
            return env.get(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}

        def f(key: str, default: float) -> float:
            try:
                return float(env.get(key, default))
            except (TypeError, ValueError):
                return default

        def i(key: str, default: int) -> int:
            try:
                return int(float(env.get(key, default)))
            except (TypeError, ValueError):
                return default

        try:
            personality = PersonalityMode(env.get("AAAAS_PERSONALITY", "professional").lower())
        except ValueError:
            personality = PersonalityMode.PROFESSIONAL

        return cls(
            odoo=OdooSettings(
                in_memory=b("AAAAS_ODOO_IN_MEMORY", True),
                url=env.get("AAAAS_ODOO_URL", "http://localhost:8069"),
                db=env.get("AAAAS_ODOO_DB", "odoo"),
                username=env.get("AAAAS_ODOO_USERNAME", "admin"),
                password=env.get("AAAAS_ODOO_PASSWORD", "admin"),
            ),
            confidence=ConfidenceThresholds(
                auto=f("AAAAS_CONF_AUTO", 0.90),
                auto_flag=f("AAAAS_CONF_AUTO_FLAG", 0.70),
                draft_hitl=f("AAAAS_CONF_DRAFT_HITL", 0.50),
            ),
            policy=PolicyLimits(
                price_variance_pct=f("AAAAS_PRICE_VARIANCE_PCT", 0.03),
                payment_hitl_limit=f("AAAAS_PAYMENT_HITL_LIMIT", 1000.0),
                reminder_auto_max_days=i("AAAAS_REMINDER_AUTO_MAX_DAYS", 30),
            ),
            personality=personality,
            anthropic_api_key=env.get("AAAAS_ANTHROPIC_API_KEY") or None,
            model=env.get("AAAAS_MODEL", "claude-sonnet-4-6"),
            finance_channel=env.get("AAAAS_FINANCE_CHANNEL", "#finance"),
        )


def _load_dotenv_into(env: dict) -> None:
    """Minimal .env loader (no dependency on python-dotenv).

    Only fills keys that are not already set in the environment.
    """
    path = env.get("AAAAS_DOTENV", ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                env.setdefault(key, value)
    except OSError:
        pass
