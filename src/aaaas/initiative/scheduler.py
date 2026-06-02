"""The initiative engine — what makes the agent proactive, not reactive.

Two drivers, matching the architecture doc §7:

  * ``ScheduledJob`` — time-based runs (daily AR aging, AP due-date sweep,
    end-of-day reconciliation, the evening summary).
  * ``EventRule``    — Odoo events the agent reacts to in real time
    (a new vendor bill arrives -> match it immediately).

The engine is deliberately framework-free: it computes *which* tasks are due
and hands each to the ``Agent``. A real deployment wires the ``due_at`` clock
to cron/Celery and the events to Odoo webhooks; the decision logic is here and
unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..agent.brain import Agent, RunResult


@dataclass
class ScheduledJob:
    name: str
    hour: int                 # 0-23, local finance-team time
    minute: int
    task: str                 # natural-language task handed to the agent
    description: str = ""


@dataclass
class EventRule:
    event: str                # e.g. "vendor_bill.created"
    task_template: str        # may reference {id} etc. from the event payload
    description: str = ""

    def render(self, payload: dict) -> str:
        try:
            return self.task_template.format(**payload)
        except (KeyError, IndexError):
            return self.task_template


# The proactive defaults from the architecture doc.
DEFAULT_SCHEDULE: list[ScheduledJob] = [
    ScheduledJob("ar_aging", 8, 0,
                 "Generate the AR aging report and flag every invoice that just "
                 "entered the 30, 60, or 90 day bucket.",
                 "Daily AR aging sweep."),
    ScheduledJob("ap_due", 9, 0,
                 "List open vendor bills due within the next 5 days and flag them.",
                 "Daily AP due-date sweep."),
    ScheduledJob("bank_recon", 17, 0,
                 "Reconcile every unreconciled bank line you can match with high "
                 "confidence; flag the rest.",
                 "End-of-day bank reconciliation."),
    ScheduledJob("daily_summary", 17, 30,
                 "Push the daily finance summary to the team channel.",
                 "Evening digest to the finance team."),
]

DEFAULT_EVENT_RULES: list[EventRule] = [
    EventRule("vendor_bill.created",
              "A new vendor bill (id {id}) just arrived. Read it, find its purchase "
              "order, and match them. Escalate if anything is off.",
              "Real-time 3-way match on new vendor bills."),
    EventRule("bank_line.created",
              "A new bank line (id {id}) just posted. Try to reconcile it against an "
              "open customer invoice.",
              "Real-time reconciliation on new bank lines."),
]


@dataclass
class InitiativeEngine:
    """Decides what's due and runs it through the agent."""

    agent: Agent
    schedule: list[ScheduledJob] = field(default_factory=lambda: list(DEFAULT_SCHEDULE))
    event_rules: list[EventRule] = field(default_factory=lambda: list(DEFAULT_EVENT_RULES))

    def due_jobs(self, hour: int, minute: int) -> list[ScheduledJob]:
        """Jobs scheduled for exactly this hour:minute."""
        return [j for j in self.schedule if j.hour == hour and j.minute == minute]

    def run_due(self, hour: int, minute: int) -> list[tuple[str, RunResult]]:
        return [(j.name, self.agent.run(j.task)) for j in self.due_jobs(hour, minute)]

    def handle_event(self, event: str, payload: dict | None = None) -> list[tuple[str, RunResult]]:
        payload = payload or {}
        out: list[tuple[str, RunResult]] = []
        for rule in self.event_rules:
            if rule.event == event:
                out.append((rule.event, self.agent.run(rule.render(payload))))
        return out
