"""Working memory (task queue/state) and long-term pattern memory.

``TaskStore`` tracks the agent's open/closed work — the durable queue that
in production lives in PostgreSQL. ``PatternMemory`` is the seed of the
semantic memory described in the architecture doc: it learns, for example,
that bills from "ABC Supplies" code to a given account, so the agent stops
re-asking. Both are in-memory here with optional JSON persistence.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    AWAITING_HUMAN = "awaiting_human"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    id: int
    kind: str                         # e.g. "MATCH_VENDOR_BILL"
    payload: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    note: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class TaskStore:
    """In-memory task queue with status tracking."""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._seq = 0

    def add(self, kind: str, payload: dict | None = None) -> Task:
        self._seq += 1
        task = Task(id=self._seq, kind=kind, payload=payload or {})
        self._tasks[task.id] = task
        return task

    def update(self, task_id: int, status: TaskStatus, note: str = "") -> Task:
        task = self._tasks[task_id]
        task.status = status
        if note:
            task.note = note
        task.updated_at = _now()
        return task

    def pending(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def by_status(self, status: TaskStatus) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == status]

    def all(self) -> list[Task]:
        return list(self._tasks.values())


class PatternMemory:
    """Learns vendor -> (account, analytic) coding habits from approved work."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path
        # vendor_id -> Counter of (account_id, analytic) -> times seen
        self._votes: dict[int, Counter] = defaultdict(Counter)
        if path and os.path.isfile(path):
            self._load()

    def record_coding(self, vendor_id: int, account_id: int, analytic: str = "") -> None:
        self._votes[vendor_id][(account_id, analytic)] += 1
        if self._path:
            self._save()

    def suggest_coding(self, vendor_id: int) -> tuple[tuple[int, str] | None, float]:
        """Return ((account_id, analytic), confidence) for a vendor, or (None, 0)."""
        counter = self._votes.get(vendor_id)
        if not counter:
            return None, 0.0
        (coding, count), = counter.most_common(1)
        total = sum(counter.values())
        # Confidence grows with both consistency and evidence volume.
        consistency = count / total
        volume_factor = min(1.0, total / 5.0)
        return coding, round(0.5 + 0.49 * consistency * volume_factor, 3)

    # ---- persistence ---- #
    def _save(self) -> None:
        serializable = {
            str(vendor): {f"{a}|{an}": n for (a, an), n in counter.items()}
            for vendor, counter in self._votes.items()
        }
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2)

    def _load(self) -> None:
        with open(self._path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for vendor, codings in raw.items():
            for key, n in codings.items():
                account_str, _, analytic = key.partition("|")
                self._votes[int(vendor)][(int(account_str), analytic)] = n
