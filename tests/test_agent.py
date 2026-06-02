"""The ReAct brain, driven by a scripted FakeLLM (no API key needed)."""
from __future__ import annotations

from aaaas.agent.brain import Agent, FakeLLM, LLMResponse, ToolCall
from aaaas.agent.confidence import Decision
from aaaas.app import build_bookkeeper
from aaaas.config import Settings
from aaaas.hitl.interface import AutoApproveHITL


def _agent_with(seeded, today, script):
    backend, ids = seeded
    fake = FakeLLM(script)
    bk = build_bookkeeper(Settings(), backend=backend, hitl=AutoApproveHITL(),
                          today=today, llm=fake)
    return Agent(fake, bk.registry), bk, ids


def test_react_loop_executes_a_tool_then_finishes(seeded, today):
    backend, ids = seeded
    script = [
        LLMResponse(
            text="I'll match this bill to its PO.",
            tool_calls=[ToolCall("t1", "match_bill_to_po",
                                 {"bill_id": ids["bill_clean"], "po_ref": "PO-2026-0089"})],
            stop_reason="tool_use",
        ),
        LLMResponse(text="Done — matched within tolerance.", tool_calls=[], stop_reason="end_turn"),
    ]
    agent, bk, ids = _agent_with(seeded, today, script)

    result = agent.run("Match the new vendor bill.")
    assert result.done is True
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.tool == "match_bill_to_po"
    assert step.result["ok"] is True
    assert step.result["decision"] == Decision.AUTO.value
    # The side effect really happened in Odoo.
    bill = bk.client.read("account.move", [ids["bill_clean"]], fields=["purchase_id"])[0]
    assert bill["purchase_id"] == ids["po_clean"]


def test_unknown_tool_is_reported_not_crashed(seeded, today):
    script = [
        LLMResponse(text="", tool_calls=[ToolCall("t1", "does_not_exist", {})],
                    stop_reason="tool_use"),
        LLMResponse(text="ok", tool_calls=[], stop_reason="end_turn"),
    ]
    agent, bk, ids = _agent_with(seeded, today, script)
    result = agent.run("do a thing")
    assert result.steps[0].result["ok"] is False
    assert "Unknown tool" in result.steps[0].result["message"]


def test_bad_arguments_are_reported(seeded, today):
    script = [
        LLMResponse(text="", tool_calls=[ToolCall("t1", "get_vendor_bill", {"wrong": 1})],
                    stop_reason="tool_use"),
        LLMResponse(text="ok", tool_calls=[], stop_reason="end_turn"),
    ]
    agent, bk, ids = _agent_with(seeded, today, script)
    result = agent.run("read a bill")
    assert result.steps[0].result["ok"] is False


def test_max_steps_guard(seeded, today):
    # A script that always asks for a tool would loop forever without the guard.
    looping = [LLMResponse(text="again", tool_calls=[ToolCall("t", "summarize_cash_position", {})],
                           stop_reason="tool_use")] * 50
    agent, bk, ids = _agent_with(seeded, today, looping)
    agent.max_steps = 3
    result = agent.run("loop")
    assert result.done is False
    assert len(result.steps) == 3
