# AAAAS — Bookkeeping Agent: Architecture & Strategy

> **Scope:** This document covers the first vertical of the AI Agent as a Service (AAAAS) platform —
> an autonomous bookkeeping agent backed by Odoo as the system of record.
> It is the north star for V1 design, engineering, and go-to-market.

---

## 1. Problem Statement

Mid-size companies on Odoo run their finances through a small accounting team.
The team spends 70–80% of their time on mechanical work:

- Matching vendor invoices to purchase orders
- Coding expenses to the right account/analytic
- Following up on unpaid customer invoices (AR aging)
- Reconciling bank statements
- Preparing draft journal entries for recurring accruals
- Chasing approvals and missing information

This work is **high volume, low judgment, high stakes if wrong.**
It is exactly the profile where an AI agent delivers leverage — not by replacing accountability,
but by doing the legwork so one human can supervise ten times the volume.

---

## 2. Strategic Position

### The wedge

> "Your bookkeeper works 24/7, never misses a due date, and costs a fraction of a salary.
> Your accountant reviews and signs off — legally covered, operationally lean."

This is NOT a "replace your accountant" pitch. It is a **10x leverage** pitch:
- 1 senior accountant + AAAAS bookkeeping agent = the output of a 4-person AP team
- The human retains legal liability and judgment calls
- The agent handles velocity and volume

### Why Odoo is the right substrate

| Property | Why it matters |
|---|---|
| Full XML-RPC / JSON-RPC API | Every UI action is callable programmatically — the agent has the same hands as a human user |
| Modular (Accounting, Purchase, Inventory, AR/AP) | Clean data model — invoices, journal entries, reconciliations are first-class objects |
| Community edition is free | Low barrier for SME customers to adopt; no license negotiation bloat |
| Audit trail built-in (chatter, log notes) | Agent actions are automatically logged where humans already look |

### Why bookkeeping first

1. **Highest volume** of mechanical tasks across all Odoo modules
2. **Clear ROI** — cost per invoice processed is measurable
3. **Odoo Accounting API is mature and stable**
4. **Error is visible and recoverable** — a draft journal entry is not posted until approved
5. **Regulatory moat**: human sign-off is legally required anyway, making HITL a feature not a compromise

---

## 3. Agent Design Philosophy

### Core principles

**Initiative over reactivity.** The agent does not wait to be asked. It runs on schedules,
listens to Odoo events, and surfaces work proactively — "I found 12 unmatched vendor bills,
I've matched 9 automatically, 3 need your eyes."

**Confidence-gated actions.** Every action has a confidence score. High confidence = act autonomously.
Low confidence = draft + escalate to human with explanation. The threshold per action type is configurable.

**Audit-first.** Every action the agent takes is logged in the Odoo chatter with a structured note:
what it did, why, and the confidence level. Humans can always see the agent's reasoning.

**Personality as a layer, not a core.** The agent has a default tone (clear, direct, professional).
A "Gen Z/Alpha" personality mode can be toggled per workspace — appropriate for internal Slack
notifications, toned down for anything that touches external parties or finance reports.

**Fail loud, not silently.** If the agent cannot complete a task (missing data, ambiguous mapping,
API error), it logs a blocker and notifies a human immediately. It never silently skips.

---

## 4. Technical Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AAAAS Platform                          │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐ │
│  │  Scheduler / │    │  Orchestrator│    │  Human-in-the-    │ │
│  │  Trigger     │───▶│  Agent       │◀──▶│  Loop Interface   │ │
│  │  (cron/event)│    │  (LLM brain) │    │  (web/Slack/email)│ │
│  └──────────────┘    └──────┬───────┘    └───────────────────┘ │
│                             │                                   │
│                    Tool calls (structured)                      │
│                             │                                   │
│                    ┌────────▼────────┐                         │
│                    │  Odoo Tool Layer│                         │
│                    │  (API client)   │                         │
│                    └────────┬────────┘                         │
└─────────────────────────────┼───────────────────────────────────┘
                              │ XML-RPC / JSON-RPC
                    ┌─────────▼─────────┐
                    │      Odoo         │
                    │  (System of       │
                    │   Record)         │
                    │  - Accounting     │
                    │  - AP / AR        │
                    │  - Bank           │
                    │  - Purchase       │
                    └───────────────────┘
```

### 4.1 Components

#### Scheduler / Trigger
Fires the agent on:
- **Time-based**: hourly bank statement check, daily AR aging run, monthly closing checklist
- **Event-based**: new vendor bill created in Odoo → immediately attempt 3-way match
- **Manual**: human sends a command via Slack/UI ("reconcile last week's bank")

#### Orchestrator Agent (LLM brain)
- Receives a task (from scheduler or human)
- Reasons step-by-step about what to do (ReAct pattern: Reason → Act → Observe → Repeat)
- Calls tools from the Odoo Tool Layer
- Decides whether to act autonomously or escalate
- Writes its reasoning to the Odoo chatter as a structured log note

#### Odoo Tool Layer
A Python client that wraps Odoo's API into clean, typed function calls.
Each function is a **tool** the agent can call. See Section 5 for the full tool inventory.

#### Human-in-the-Loop (HITL) Interface
When the agent confidence is below threshold or the action is irreversible above a risk limit:
- Sends a structured approval request (via Slack, email, or AAAAS web dashboard)
- Includes: what it wants to do, why, the data it's acting on, and a confidence score
- Waits for approve / reject / modify
- Logs the human decision back to Odoo

---

### 4.2 Agent Reasoning Loop (ReAct)

```
TASK RECEIVED
     │
     ▼
┌─── REASON ──────────────────────────────────┐
│  "I have a new vendor bill. I need to:       │
│   1. Find the matching PO                    │
│   2. Check quantities and prices             │
│   3. Decide if it auto-approves or escalates"│
└─────────────────────────────────────────────┘
     │
     ▼
┌─── ACT ────────────────────────────────────┐
│  call: get_purchase_order(po_ref)           │
│  call: get_vendor_bill(bill_id)             │
└────────────────────────────────────────────┘
     │
     ▼
┌─── OBSERVE ────────────────────────────────┐
│  PO: 100 units @ $50 = $5,000              │
│  Bill: 100 units @ $52 = $5,200            │
│  Variance: +$200 (4%) — above threshold    │
└────────────────────────────────────────────┘
     │
     ▼
┌─── REASON ─────────────────────────────────┐
│  "Price variance > 3% policy limit.         │
│   I should NOT auto-approve.                │
│   I will draft the match and escalate."     │
└────────────────────────────────────────────┘
     │
     ▼
┌─── ACT ────────────────────────────────────┐
│  call: log_note_to_bill(bill_id, reasoning) │
│  call: send_hitl_request(approver, summary) │
└────────────────────────────────────────────┘
     │
     ▼
   WAIT FOR HUMAN → log decision → DONE
```

---

### 4.3 Memory & State

| Layer | What it stores | Technology |
|---|---|---|
| **Short-term** | Current task context, tool call results within a run | In-memory (agent session) |
| **Working memory** | Open tasks, pending HITL requests, retry queue | PostgreSQL (AAAAS DB) |
| **Long-term / semantic** | Past decisions, vendor patterns, account coding history | Vector store (pgvector or Chroma) |
| **System of record** | All financial data — invoices, entries, reconciliations | Odoo (never duplicated) |

Long-term memory is used for **pattern learning**: if the agent sees that vendor "ABC Supplies"
always codes to account 5010 / analytic "Operations", it learns this and applies it without re-asking.

---

## 5. Odoo Tool Inventory (Bookkeeping V1)

Each tool is a Python function the agent calls via the Odoo XML-RPC client.

### Accounts Payable

| Tool | Odoo action | Auto or HITL |
|---|---|---|
| `list_unmatched_vendor_bills()` | Search `account.move` (vendor bills) without PO match | Auto |
| `get_vendor_bill(bill_id)` | Read bill lines, amounts, vendor, due date | Auto |
| `get_purchase_order(po_ref)` | Read PO lines, quantities, prices | Auto |
| `match_bill_to_po(bill_id, po_id)` | Write `purchase_id` on the bill, validate 3-way match | Auto if variance < threshold |
| `validate_vendor_bill(bill_id)` | Post the bill (irreversible) | Always HITL |
| `reject_vendor_bill(bill_id, reason)` | Log rejection note, send vendor notification | HITL |
| `code_expense_line(line_id, account, analytic)` | Set account/analytic on a journal item | Auto if high confidence |

### Accounts Receivable

| Tool | Odoo action | Auto or HITL |
|---|---|---|
| `list_overdue_invoices()` | Search posted customer invoices past due date | Auto |
| `get_invoice(invoice_id)` | Read invoice, customer, aging days | Auto |
| `send_payment_reminder(invoice_id, template)` | Send chatter email via Odoo mail | Auto (below 30 days overdue) |
| `escalate_collection(invoice_id, note)` | Flag for senior AR, log note | HITL |
| `register_payment(invoice_id, amount, date)` | Register manual payment on invoice | HITL |

### Bank Reconciliation

| Tool | Odoo action | Auto or HITL |
|---|---|---|
| `list_unreconciled_bank_lines()` | Fetch unreconciled lines from `account.bank.statement.line` | Auto |
| `find_matching_journal_entry(bank_line)` | Search journal items by amount, date ±3 days, partner | Auto |
| `reconcile_bank_line(bank_line_id, move_line_id)` | Write reconciliation | Auto if exact match |
| `create_adjustment_entry(bank_line_id, account, note)` | Create manual journal entry for unmatched line | HITL |

### Journal Entries & Closing

| Tool | Odoo action | Auto or HITL |
|---|---|---|
| `list_recurring_entries()` | Fetch accrual/recurring journal templates | Auto |
| `draft_recurring_entry(template_id, period)` | Create draft journal entry from template | Auto |
| `post_journal_entry(entry_id)` | Post (irreversible) | Always HITL |
| `get_trial_balance(date_from, date_to)` | Read trial balance report | Auto |
| `flag_anomaly(account_id, note)` | Log unusual balance for human review | Auto |

### Reporting & Initiative

| Tool | Odoo action | Auto or HITL |
|---|---|---|
| `generate_ar_aging_report()` | Read AR aging buckets | Auto |
| `generate_ap_aging_report()` | Read AP aging buckets | Auto |
| `summarize_cash_position()` | Read bank balances + forecasted AP/AR | Auto |
| `push_daily_summary(channel)` | Send Slack/email digest to finance team | Auto |

---

## 6. Confidence & Escalation Policy

```
Confidence ≥ 90%  →  Act autonomously, log to Odoo chatter
Confidence 70–89% →  Act, but flag in daily summary for human review
Confidence 50–69% →  Draft the action, send HITL request, wait
Confidence < 50%  →  Pause, log blocker, notify human immediately
```

**Hard rules that always require HITL regardless of confidence:**
- Posting (finalizing) any journal entry or vendor bill
- Any payment registration above configured limit (default: $1,000)
- Sending any communication to external parties (customers, vendors)
- Any action that modifies a period already closed

---

## 7. Initiative Engine

The agent is not reactive — it actively monitors and surfaces work.

### Daily runs (auto)
- 08:00 — AR aging: flag invoices entering 30/60/90 day buckets
- 09:00 — AP due dates: flag bills due in next 5 days
- 17:00 — Bank reconciliation: attempt auto-match on new bank lines
- 17:30 — Push daily finance summary to finance channel

### Event-driven (real-time)
- New vendor bill created → immediately attempt PO match
- Payment received in bank → immediately attempt invoice reconciliation
- New expense submitted → code to account/analytic, flag for approval

### Monthly (closing support)
- Flag unposted recurring entries
- Check trial balance for anomalies vs prior month
- Generate closing checklist, track completion status

---

## 8. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Agent runtime | Python 3.11+ | Matches Odoo's stack; best AI/ML library support |
| LLM | Claude API (claude-sonnet-4-6 / claude-opus-4-8) | Tool use, reasoning quality, long context for financial docs |
| Agent framework | Custom ReAct loop (thin) | Full control; avoid framework lock-in for V1 |
| Odoo client | `xmlrpc.client` (stdlib) or `odoorpc` | Battle-tested, no extra deps for stdlib option |
| Task queue | Celery + Redis | Async task scheduling, retries, HITL wait states |
| Database (AAAAS) | PostgreSQL | Stores agent state, task queue, HITL requests |
| Vector store | pgvector extension | Long-term memory in same DB, simpler ops |
| HITL delivery | Slack SDK + email (SMTP/SendGrid) | Where finance teams already live |
| API (AAAAS) | FastAPI | Async, typed, auto-docs |
| Config | Pydantic settings + `.env` | Per-customer Odoo creds, thresholds, personality mode |

---

## 9. Data Flow: Vendor Bill (Happy Path)

```
1. Odoo webhook / cron fires → new vendor bill detected
2. Scheduler enqueues task: MATCH_VENDOR_BILL {bill_id: 42}
3. Agent picks up task
4. REASON: "I need the bill details and the matching PO"
5. ACT: call get_vendor_bill(42) → returns bill data
6. ACT: call get_purchase_order("PO-2026-0089") → returns PO data
7. OBSERVE: quantities match, price within 1% threshold
8. REASON: "Confidence 95% — I can auto-match"
9. ACT: call match_bill_to_po(42, "PO-2026-0089")
10. ACT: call log_note_to_bill(42, "Matched by AAAAS agent. Variance: 0.8%. Confidence: 95%.")
11. DONE — bill is matched, awaiting human to post (step they already do)
```

```
Total time: ~8 seconds vs ~5 minutes manual
Zero human time required for the happy path
```

---

## 10. Phased Roadmap

### Phase 1 — Core (Months 1–2)
- [ ] Odoo XML-RPC client with full type coverage for AP/AR/Bank models
- [ ] Vendor bill → PO matching tool + confidence scoring
- [ ] HITL request/response loop via email
- [ ] Odoo chatter logging for all agent actions
- [ ] Daily AP aging run
- [ ] Single-tenant, single Odoo instance

### Phase 2 — Reliability (Months 3–4)
- [ ] Bank reconciliation auto-match
- [ ] AR collection reminder engine
- [ ] Slack HITL interface
- [ ] Long-term memory (vendor → account coding patterns)
- [ ] Retry and error handling hardened
- [x] Admin dashboard (task log, HITL queue, metrics) — FastAPI, `aaaas-dashboard`

### Phase 3 — Scale (Months 5–6)
- [ ] Multi-tenant (one AAAAS deployment, N customer Odoo instances)
- [ ] Monthly closing assistant (recurring entries + checklist)
- [ ] Anomaly detection on trial balance
- [ ] Usage metrics → customer ROI report (time saved, invoices processed)
- [ ] Personality mode toggle per workspace

---

## 11. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hallucinates account code | Medium | High | Always read account from Odoo, never let LLM invent codes |
| Agent posts a journal entry without approval | Low | Critical | Hard rule: `post_journal_entry` is always HITL, no override |
| Odoo API changes between versions | Medium | Medium | Odoo Tool Layer abstracts version diffs; pin per customer |
| Customer doesn't trust agent decisions | High (initially) | Medium | Start in "suggest-only" mode, build trust with audit log |
| Duplicate task execution (at-least-once queue) | Medium | Medium | Idempotency keys on all write tools |
| HITL approver unresponsive | Medium | Low | Escalation chain + auto-expire with safe fallback (don't act) |

---

## 12. What "Done" Looks Like for V1

A finance team at an Odoo SME (50–500 employees) runs AAAAS bookkeeping agent for 30 days.
At the end of 30 days:

- **80%+ of vendor bills** are matched automatically without human touch
- **100% of AR aging** reminders are sent on time without manual action
- **Zero unauthorized postings** — every posted entry was human-approved
- The accountant's daily review takes **30 minutes instead of 3 hours**
- Every agent action is visible in the Odoo chatter — full audit trail
- The customer can see a simple metric: *"Agent processed 340 transactions, saved ~28 hours"*

That last metric is the sales deck for customer #2.

---

*Document version: 0.1 — created during AAAAS Phase 0 planning*
*Owner: AAAAS core team*
*Next review: after Phase 1 completion*
