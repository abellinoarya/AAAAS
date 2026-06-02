"""Show the agent's ReAct loop driving real tools — no API key required.

A ``FakeLLM`` plays the role of the reasoning brain with a fixed script, so
you can watch the full Reason -> Act -> Observe cycle (and the confidence
gating / escalation) without any network. Swap ``FakeLLM`` for ``AnthropicLLM``
(set AAAAS_ANTHROPIC_API_KEY) to let a real Claude model decide the steps.

Run:  python examples/demo_agent_react.py
"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aaaas.agent.brain import Agent, FakeLLM, LLMResponse, ToolCall  # noqa: E402
from aaaas.app import build_bookkeeper  # noqa: E402
from aaaas.config import Settings  # noqa: E402
from aaaas.hitl.interface import AutoApproveHITL  # noqa: E402
from aaaas.odoo.client import InMemoryBackend  # noqa: E402
from aaaas.seed import seed_demo_data  # noqa: E402


def main() -> None:
    today = date(2026, 6, 2)
    backend = InMemoryBackend()
    ids = seed_demo_data(backend, today=today)

    # A scripted "brain": it inspects the queue, matches the clean bill,
    # tries the over-tolerance bill (which escalates), then reports back.
    script = [
        LLMResponse(
            text="Let me see what unmatched bills are waiting.",
            tool_calls=[ToolCall("a", "list_unmatched_vendor_bills", {})],
            stop_reason="tool_use",
        ),
        LLMResponse(
            text="Two bills. I'll match the ABC one to its PO.",
            tool_calls=[ToolCall("b", "match_bill_to_po",
                                 {"bill_id": ids["bill_clean"], "po_ref": "PO-2026-0089"})],
            stop_reason="tool_use",
        ),
        LLMResponse(
            text="Now the Globex bill against its PO.",
            tool_calls=[ToolCall("c", "match_bill_to_po",
                                 {"bill_id": ids["bill_variance"], "po_ref": "PO-2026-0090"})],
            stop_reason="tool_use",
        ),
        LLMResponse(
            text=("Handled both. ABC matched cleanly and is ready to post. "
                  "Globex is 4% over its PO, so I flagged it for a human. "
                  "Nothing was posted without approval."),
            tool_calls=[], stop_reason="end_turn",
        ),
    ]

    fake = FakeLLM(script)
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoApproveHITL(),
                          today=today, llm=fake)
    agent = Agent(fake, bk.registry)

    result = agent.run("Work through today's unmatched vendor bills.")

    print("\n=== Agent reasoning trace ===")
    for i, step in enumerate(result.steps, 1):
        print(f"\nStep {i}: {step.tool}({step.input})")
        print(f"  -> ok={step.result['ok']} "
              f"decision={step.result.get('decision')} "
              f"conf={step.result.get('confidence')}")
        print(f"     {step.result['message']}")

    print("\n=== Final summary ===")
    print(result.final)


if __name__ == "__main__":
    main()
