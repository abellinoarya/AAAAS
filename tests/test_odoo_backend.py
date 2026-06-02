"""The in-memory Odoo fake: CRUD, domains, and chatter."""
from __future__ import annotations

import pytest

from aaaas.odoo.client import InMemoryBackend, OdooClient


@pytest.fixture
def client():
    backend = InMemoryBackend()
    return OdooClient(backend), backend


def test_create_read_write(client):
    c, _ = client
    rid = c.create("res.partner", {"name": "ACME", "credit": 10})
    assert isinstance(rid, int)
    rows = c.read("res.partner", [rid], fields=["name", "credit"])
    assert rows[0]["name"] == "ACME"
    c.write("res.partner", rid, {"credit": 99})
    assert c.read("res.partner", [rid], fields=["credit"])[0]["credit"] == 99


def test_search_read_domain_operators(client):
    c, _ = client
    c.create("account.move", {"move_type": "in_invoice", "state": "draft", "amount_total": 100})
    c.create("account.move", {"move_type": "in_invoice", "state": "posted", "amount_total": 200})
    c.create("account.move", {"move_type": "out_invoice", "state": "draft", "amount_total": 50})

    draft_bills = c.search_read(
        "account.move", [["move_type", "=", "in_invoice"], ["state", "=", "draft"]])
    assert len(draft_bills) == 1
    assert draft_bills[0]["amount_total"] == 100

    big = c.search_read("account.move", [["amount_total", ">=", 150]])
    assert len(big) == 1

    in_set = c.search_read("account.move", [["state", "in", ["draft", "posted"]]])
    assert len(in_set) == 3


def test_count(client):
    c, _ = client
    c.create("res.partner", {"name": "A"})
    c.create("res.partner", {"name": "B"})
    assert c.count("res.partner") == 2
    assert c.count("res.partner", [["name", "=", "A"]]) == 1


def test_message_post_records_chatter(client):
    c, backend = client
    rid = c.create("account.move", {"name": "X"})
    c.log_note("account.move", rid, "hello world")
    assert backend.get_chatter("account.move", rid) == ["hello world"]


def test_unsupported_operator_raises(client):
    c, _ = client
    c.create("res.partner", {"name": "A"})
    with pytest.raises(ValueError):
        c.search_read("res.partner", [["name", "=~", "A"]])
