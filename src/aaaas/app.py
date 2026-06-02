"""Composition root: turn a ``Settings`` into a wired, ready agent.

This is the one place that knows how all the pieces fit: settings -> Odoo
backend -> client -> tool context -> registry -> brain. Everything else
depends on abstractions, so swapping the in-memory backend for a real Odoo,
or the fake LLM for Claude, happens only here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .agent.brain import Agent, AnthropicLLM, LLMClient
from .agent.personality import Personality
from .config import Settings
from .hitl.interface import HITLChannel, ConsoleHITL, AutoApproveHITL
from .memory.store import PatternMemory
from .odoo.client import InMemoryBackend, OdooClient, OdooBackend, XmlRpcBackend
from .tools import build_registry
from .tools.base import ToolContext, ToolRegistry


@dataclass
class Bookkeeper:
    """A fully wired bookkeeping agent and the context behind it."""

    settings: Settings
    client: OdooClient
    context: ToolContext
    registry: ToolRegistry
    agent: Agent

    # convenience passthroughs
    def run(self, task: str):
        return self.agent.run(task)

    @property
    def notices(self) -> list[str]:
        return self.context.notices


def make_backend(settings: Settings) -> OdooBackend:
    if settings.odoo.in_memory:
        return InMemoryBackend()
    return XmlRpcBackend(
        url=settings.odoo.url,
        db=settings.odoo.db,
        username=settings.odoo.username,
        password=settings.odoo.password,
    )


def make_llm(settings: Settings) -> LLMClient | None:
    """A real Claude brain if an API key is configured, else None."""
    if settings.anthropic_api_key:
        return AnthropicLLM(settings.anthropic_api_key, model=settings.model)
    return None


def build_bookkeeper(
    settings: Settings | None = None,
    *,
    backend: OdooBackend | None = None,
    llm: LLMClient | None = None,
    hitl: HITLChannel | None = None,
    today: date | None = None,
) -> Bookkeeper:
    """Wire everything. Any dependency can be injected (tests do exactly this)."""
    settings = settings or Settings.from_env()
    backend = backend or make_backend(settings)
    client = OdooClient(backend)

    context = ToolContext(
        client=client,
        settings=settings,
        hitl=hitl or (ConsoleHITL() if not settings.odoo.in_memory else AutoApproveHITL()),
        personality=Personality(settings.personality),
        memory=PatternMemory(),
        today=today or date.today(),
    )
    registry = build_registry(context)

    llm = llm or make_llm(settings)
    if llm is None:
        # No LLM available (no key, offline). The deterministic tools and the
        # initiative engine still work; only the conversational brain is absent.
        agent = Agent(_NullLLM(), registry)
    else:
        agent = Agent(llm, registry)

    return Bookkeeper(settings, client, context, registry, agent)


class _NullLLM:
    """Stand-in when no LLM is configured: ends the turn immediately.

    Tools remain fully usable directly; the initiative engine can still call
    deterministic flows. Only free-form reasoning is unavailable.
    """

    def complete(self, system, messages, tools):
        from .agent.brain import LLMResponse
        return LLMResponse(
            text="No LLM configured — set AAAAS_ANTHROPIC_API_KEY to enable the "
                 "reasoning brain. Deterministic tools are still available.",
            tool_calls=[],
            stop_reason="end_turn",
        )
