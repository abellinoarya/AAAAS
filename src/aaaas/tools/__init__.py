"""Tool assembly: build the full bookkeeping tool registry from a context."""
from __future__ import annotations

from .accounts_payable import build_ap_tools
from .accounts_receivable import build_ar_tools
from .bank import build_bank_tools
from .base import Tool, ToolContext, ToolRegistry, ToolResult, apply_policy, no_params
from .journal import build_journal_tools
from .reporting import build_reporting_tools


def build_registry(ctx: ToolContext) -> ToolRegistry:
    """Assemble every bookkeeping tool into one registry."""
    registry = ToolRegistry()
    registry.extend(build_ap_tools(ctx))
    registry.extend(build_ar_tools(ctx))
    registry.extend(build_bank_tools(ctx))
    registry.extend(build_journal_tools(ctx))
    registry.extend(build_reporting_tools(ctx))
    return registry


__all__ = [
    "build_registry",
    "build_ap_tools",
    "build_ar_tools",
    "build_bank_tools",
    "build_journal_tools",
    "build_reporting_tools",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "apply_policy",
    "no_params",
]
