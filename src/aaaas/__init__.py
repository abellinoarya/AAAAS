"""AAAAS — AI Agent as a Service.

V1 vertical: an autonomous bookkeeping agent backed by Odoo as the system
of record. The package is organised as:

    config        — typed settings loaded from the environment
    odoo          — the tool layer: typed client + pluggable backends
                    (real XML-RPC, or an in-memory fake for dev/tests)
    logic         — pure, deterministic financial logic (matching, aging,
                    reconciliation, confidence scoring) — no LLM, no I/O
    tools         — Odoo actions exposed as agent-callable tools
    agent         — the ReAct brain, confidence/escalation policy, prompts,
                    and the configurable personality layer
    hitl          — human-in-the-loop request/decision channels
    memory        — task state and learned vendor→account patterns
    initiative    — scheduled and event-driven runs (the proactive engine)
"""

__version__ = "0.1.0"
