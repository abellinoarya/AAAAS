"""Admin dashboard: the stdlib service layer and a FastAPI smoke test."""
from __future__ import annotations

from datetime import date

import pytest

from aaaas.app import build_bookkeeper
from aaaas.config import Settings
from aaaas.dashboard.service import DashboardHITL, DashboardService
from aaaas.odoo.client import InMemoryBackend
from aaaas.seed import seed_demo_data


def make_service(today=date(2026, 6, 2)) -> DashboardService:
    backend = InMemoryBackend()
    ids = seed_demo_data(backend, today=today)
    bk = build_bookkeeper(Settings(), backend=backend, hitl=DashboardHITL(), today=today)
    return DashboardService(bk, demo_ids=ids)


def _pending_id(service: DashboardService, action: str) -> int:
    for a in service.approvals():
        if a["action"] == action:
            return a["id"]
    raise AssertionError(f"No pending approval for {action}")


def test_demo_batch_populates_queue_and_activity():
    s = make_service()
    s.run_demo_batch()
    # Clean match + exact reconcile auto-process; variance match + posting queue.
    assert len(s.activity) >= 6
    actions = {a["action"] for a in s.approvals()}
    assert "validate_vendor_bill" in actions   # hard HITL -> always queued
    assert "match_bill_to_po" in actions        # over-tolerance -> queued
    m = s.metrics()
    assert m["pending_approval"] == 2
    assert m["auto_processed"] >= 2
    assert m["transactions_processed"] >= 2


def test_approving_executes_the_prepared_action():
    s = make_service()
    s.run_demo_batch()
    pid = _pending_id(s, "validate_vendor_bill")
    s.approve(pid)
    # The bill is now actually posted in Odoo.
    bill = s.bookkeeper.client.read(
        "account.move", [s.demo_ids["bill_clean"]], fields=["state"])[0]
    assert bill["state"] == "posted"
    assert s.metrics()["human_approved"] == 1


def test_rejecting_does_not_execute():
    s = make_service()
    s.run_demo_batch()
    pid = _pending_id(s, "match_bill_to_po")
    s.reject(pid, note="wrong PO")
    # The over-tolerance bill must NOT have been linked.
    bill = s.bookkeeper.client.read(
        "account.move", [s.demo_ids["bill_variance"]], fields=["purchase_id"])[0]
    assert not bill["purchase_id"]
    assert any(r["status"] == "rejected" for r in s.hitl.resolved)


def test_metrics_shape():
    s = make_service()
    s.run_demo_batch()
    m = s.metrics()
    for key in ("transactions_processed", "auto_processed", "pending_approval",
                "paused", "hours_saved", "automation_rate"):
        assert key in m
    assert m["hours_saved"] >= 0


def test_unknown_tool_raises():
    s = make_service()
    with pytest.raises(KeyError):
        s.call_tool("nope")


# --------------------------------------------------------------------------- #
# FastAPI smoke test — skipped unless the dashboard extra is installed.
# --------------------------------------------------------------------------- #
def test_fastapi_endpoints():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")  # required by fastapi's TestClient
    from fastapi.testclient import TestClient

    from aaaas.dashboard.web import create_app

    s = make_service()
    s.run_demo_batch()
    client = TestClient(create_app(s))

    assert client.get("/").status_code == 200
    assert "AAAAS" in client.get("/").text

    metrics = client.get("/api/metrics").json()
    assert "hours_saved" in metrics

    approvals = client.get("/api/approvals").json()
    assert isinstance(approvals, list) and approvals

    pid = approvals[0]["id"]
    r = client.post(f"/api/approvals/{pid}/approve")
    assert r.status_code == 200 and r.json()["ok"] is True

    # Approving removes it from the queue.
    assert all(a["id"] != pid for a in client.get("/api/approvals").json())

    # Unknown id -> 404.
    assert client.post("/api/approvals/9999/reject").status_code == 404
