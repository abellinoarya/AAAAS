# AAAAS — AI Agent as a Service

> An autonomous **bookkeeping agent** that does the finance team's mechanical
> work on top of **Odoo**, while a human keeps the sign-off. The AI brings
> velocity; the human keeps accountability. One accountant supervising ten
> agents instead of ten accountants.

This repo is **Phase 1** of the AAAAS platform: a complete, runnable vertical
slice of the bookkeeping agent. It runs end-to-end with **zero external
services** — no Odoo, no API key, no network — thanks to an in-memory Odoo
fake and a scripted LLM, so you can see the whole thing work in seconds.

📄 Full design rationale: [`docs/bookkeeping-agent-architecture.md`](docs/bookkeeping-agent-architecture.md)

---

## Quickstart

```bash
# 1. Run the full bookkeeping walkthrough (no installs needed)
python -m aaaas.cli                      # PYTHONPATH=src if not installed
python -m aaaas.cli --personality genz   # toggle the personality layer

# 2. Watch the agent's ReAct loop drive the tools
python examples/demo_agent_react.py

# 3. Launch the admin dashboard (approval queue + ROI metrics)
pip install -e ".[dashboard]"
aaaas-dashboard                          # http://127.0.0.1:8000

# 4. Run the test suite
pip install -e ".[dev,dashboard]"
python -m pytest
```

> The core package depends on **the Python standard library alone**. The only
> optional dependency is the `anthropic` SDK, needed solely to swap the scripted
> brain for a real Claude model.

---

## What it does

The demo (`python -m aaaas.cli`) walks the whole loop:

| Step | What happens | Policy outcome |
|---|---|---|
| Clean vendor bill vs PO | totals match exactly | **auto-match** (99% confidence) |
| Over-tolerance bill (4% > PO) | exceeds the 3% tolerance | **escalates to a human** |
| AR aging | buckets open invoices by days overdue | report |
| Payment reminders | recent overdue auto, old debt escalates | mixed |
| Bank reconciliation | exact match auto, orphan line | **auto** vs **pause** |
| Post a bill | irreversible ledger action | **always human-approved** |
| Daily summary | collects everything needing a human | digest |

Every action is written to the Odoo **chatter** as an audit note.

## Admin dashboard

`aaaas-dashboard` serves a single-page admin UI (FastAPI) showing:

- **ROI metrics** — transactions processed, hours saved, automation rate
- **Approval queue** — actions the agent prepared but that need a human
  (over-tolerance matches, bill postings); **Approve** executes the prepared
  action in Odoo, **Reject** discards it — the async "prepare now, decide later"
  pattern a real finance team needs
- **Activity feed** — every tool call with its confidence and escalation decision

The dashboard is a thin veneer over a stdlib `DashboardService`, so all of its
logic (queue, approvals, metrics) is unit-tested without a web server.

```
GET  /                          HTML dashboard
GET  /api/metrics               ROI metrics
GET  /api/approvals             pending approval queue
POST /api/approvals/{id}/approve   execute the prepared action
POST /api/approvals/{id}/reject    discard it
GET  /api/activity              recent activity feed
```

---

## Architecture

```
        Scheduler / Events                Human-in-the-loop
        (initiative engine)               (approve / reject)
                │                                 ▲
                ▼                                 │
        ┌───────────────┐   tool calls    ┌──────────────────┐
        │  Agent (brain)│ ───────────────▶│  Odoo Tool Layer │
        │  ReAct loop   │ ◀─────────────── │  (typed client)  │
        │  Claude/Fake  │   observations   └────────┬─────────┘
        └───────────────┘                           │ execute_kw
                │ confidence gating         ┌────────▼─────────┐
                ▼                           │      Odoo        │
        confidence ≥ .90 → act             │ (system of record)│
        ≥ .70 → act + flag                 │  XML-RPC  or      │
        ≥ .50 → draft + escalate           │  in-memory fake   │
        < .50 → pause + notify             └──────────────────┘
        + HARD rules: posting, payments, external comms → always human
```

**Design choices that matter:**

- **The LLM never computes the numbers.** All money decisions (3-way matching,
  aging, reconciliation, confidence scoring) live in `logic.py` as pure,
  deterministic, unit-tested functions. The LLM *orchestrates* which to run and
  talks to humans — it never invents an amount or an account code.
- **One escalation chokepoint.** Every tool that writes routes through
  `apply_policy()`, so the confidence gates and hard-HITL rules can't be
  bypassed. Posting a bill or moving money **always** requires a human, no
  matter how confident the agent is. This is the legal firewall, in code.
- **Pluggable everything.** The Odoo backend (`XmlRpcBackend` ↔ `InMemoryBackend`),
  the LLM (`AnthropicLLM` ↔ `FakeLLM`), and the HITL channel
  (`ConsoleHITL` / `QueueHITL` / auto) are all swapped in one place: `app.py`.
- **Personality is a layer, not the core.** Tone (professional / friendly /
  genz) wraps *internal* messages only; anything reaching a customer or vendor
  is always rendered professionally. Trust comes from accuracy, not jokes.

---

## Project layout

```
src/aaaas/
  config.py            Typed settings from env (stdlib only)
  logic.py             Pure financial logic: matching, aging, reconciliation
  app.py               Composition root — wires settings → backend → agent
  cli.py               The runnable demo
  seed.py              Deterministic demo/test data
  odoo/
    client.py          OdooBackend (XML-RPC + in-memory fake) + typed client
    models.py          Typed views over Odoo records
  tools/
    base.py            Tool/registry framework + apply_policy (the chokepoint)
    accounts_payable.py    bills, 3-way match, expense coding, posting
    accounts_receivable.py overdue invoices, reminders, collections
    bank.py            bank line reconciliation
    journal.py         recurring drafts + hard-gated posting
    reporting.py       aging reports, cash position, daily digest
  agent/
    brain.py           ReAct loop + LLM clients (Anthropic + Fake)
    confidence.py      escalation policy + hard-HITL action set
    personality.py     the tone layer
    prompts.py         system prompt
  hitl/interface.py    human approval channels
  memory/store.py      task state + learned vendor→account patterns
  initiative/scheduler.py  scheduled jobs + event rules (the proactive engine)
  dashboard/
    service.py         stdlib service: approval queue + ROI metrics
    web.py             FastAPI app + single-page admin UI
tests/                 64 tests, runs in ~1s, no network
.github/workflows/     CI: pytest on Python 3.10–3.12
examples/              runnable demos
docs/                  architecture & strategy
```

---

## Going to production

Everything above runs against fakes. To point it at the real world, change only
configuration / `app.py`:

**Connect a real Odoo** — set in `.env` (see `.env.example`):
```bash
AAAAS_ODOO_IN_MEMORY=false
AAAAS_ODOO_URL=https://your-odoo.example.com
AAAAS_ODOO_DB=yourdb
AAAAS_ODOO_USERNAME=...
AAAAS_ODOO_PASSWORD=...      # use an API key in real deployments
```
`make_backend()` then returns the `XmlRpcBackend`, which speaks Odoo's standard
external API. The tools are unchanged.

**Use a real Claude brain:**
```bash
pip install anthropic
export AAAAS_ANTHROPIC_API_KEY=sk-ant-...
export AAAAS_MODEL=claude-sonnet-4-6
```
`make_llm()` returns `AnthropicLLM` and the agent reasons for itself.

**Wire real approvals** — implement a `HITLChannel` (Slack/email/web) by
subclassing the interface in `hitl/interface.py`; `QueueHITL` already models the
async "prepare now, human decides later" pattern.

---

## Status

Phase 1 (core) is implemented and tested. See the roadmap in the
[architecture doc](docs/bookkeeping-agent-architecture.md#10-phased-roadmap)
for Phase 2 (reliability: real Slack HITL, semantic memory, admin dashboard)
and Phase 3 (scale: multi-tenant, monthly closing, ROI reporting).
