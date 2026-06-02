"""Pluggable Odoo backends + a typed high-level client.

``OdooBackend`` is the single seam between AAAAS and Odoo: one method,
``execute_kw``, mirroring Odoo's external API. ``XmlRpcBackend`` speaks to
a real instance; ``InMemoryBackend`` is a faithful fake implementing the
subset of the ORM the agent uses (search/read/write/create/message_post),
so every layer above runs identically with no Odoo to connect to.
"""
from __future__ import annotations

import itertools
from typing import Any, Protocol


class OdooBackend(Protocol):
    def execute_kw(
        self, model: str, method: str, args: list, kwargs: dict | None = None
    ) -> Any:
        ...


# --------------------------------------------------------------------------- #
# Real Odoo over XML-RPC
# --------------------------------------------------------------------------- #
class XmlRpcBackend:
    """Talks to a live Odoo via the standard-library xmlrpc client.

    Lazily authenticates on first call. No third-party dependency.
    """

    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self._uid: int | None = None
        self._models = None

    def _connect(self) -> None:
        import xmlrpc.client  # stdlib

        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._uid = common.authenticate(self.db, self.username, self.password, {})
        if not self._uid:
            raise PermissionError("Odoo authentication failed — check credentials.")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def execute_kw(
        self, model: str, method: str, args: list, kwargs: dict | None = None
    ) -> Any:
        if self._uid is None:
            self._connect()
        return self._models.execute_kw(
            self.db, self._uid, self.password, model, method, args, kwargs or {}
        )


# --------------------------------------------------------------------------- #
# In-memory fake Odoo
# --------------------------------------------------------------------------- #
_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "in": lambda a, b: a in b,
    "not in": lambda a, b: a not in b,
    "like": lambda a, b: str(b) in str(a),
    "ilike": lambda a, b: str(b).lower() in str(a).lower(),
}


def _match(record: dict, domain: list) -> bool:
    """Evaluate an Odoo search domain (flat AND; '&' operators ignored)."""
    for clause in domain:
        if clause in ("&", "|", "!"):
            continue  # treat everything as AND — enough for our queries
        field, op, value = clause
        fn = _OPS.get(op)
        if fn is None:
            raise ValueError(f"InMemoryBackend: unsupported operator {op!r}")
        if not fn(record.get(field), value):
            return False
    return True


class InMemoryBackend:
    """A small but faithful Odoo fake.

    Data is ``{model: {id: record}}``. Chatter posted via ``message_post``
    is captured so tests and demos can assert on the audit trail.
    """

    def __init__(self) -> None:
        self.data: dict[str, dict[int, dict]] = {}
        self.chatter: dict[tuple[str, int], list[str]] = {}
        self._ids = itertools.count(1)

    # ---- seeding helpers (test/demo only) ---- #
    def insert(self, model: str, record: dict) -> int:
        rec = dict(record)
        rec_id = rec.get("id") or next(self._ids)
        rec["id"] = rec_id
        self.data.setdefault(model, {})[rec_id] = rec
        return rec_id

    def get_chatter(self, model: str, rec_id: int) -> list[str]:
        return list(self.chatter.get((model, rec_id), []))

    # ---- the backend contract ---- #
    def execute_kw(
        self, model: str, method: str, args: list, kwargs: dict | None = None
    ) -> Any:
        kwargs = kwargs or {}
        table = self.data.setdefault(model, {})
        handler = getattr(self, f"_m_{method}", None)
        if handler is None:
            raise NotImplementedError(
                f"InMemoryBackend has no handler for {model}.{method}"
            )
        return handler(table, model, args, kwargs)

    # ---- method handlers ---- #
    def _m_search(self, table, model, args, kwargs) -> list[int]:
        domain = args[0] if args else []
        ids = [rid for rid, rec in table.items() if _match(rec, domain)]
        ids = self._order(table, ids, kwargs.get("order"))
        return self._limit(ids, kwargs.get("limit"))

    def _m_search_read(self, table, model, args, kwargs) -> list[dict]:
        domain = args[0] if args else []
        ids = [rid for rid, rec in table.items() if _match(rec, domain)]
        ids = self._order(table, ids, kwargs.get("order"))
        ids = self._limit(ids, kwargs.get("limit"))
        return [self._project(table[rid], kwargs.get("fields")) for rid in ids]

    def _m_search_count(self, table, model, args, kwargs) -> int:
        domain = args[0] if args else []
        return sum(1 for rec in table.values() if _match(rec, domain))

    def _m_read(self, table, model, args, kwargs) -> list[dict]:
        ids = args[0] if args else []
        if isinstance(ids, int):
            ids = [ids]
        fields = kwargs.get("fields") or (args[1] if len(args) > 1 else None)
        return [self._project(table[i], fields) for i in ids if i in table]

    def _m_create(self, table, model, args, kwargs) -> int:
        vals = args[0] if args else kwargs.get("vals", {})
        return self.insert(model, vals)

    def _m_write(self, table, model, args, kwargs) -> bool:
        ids, vals = args[0], args[1]
        if isinstance(ids, int):
            ids = [ids]
        for i in ids:
            if i in table:
                table[i].update(vals)
        return True

    def _m_unlink(self, table, model, args, kwargs) -> bool:
        ids = args[0]
        if isinstance(ids, int):
            ids = [ids]
        for i in ids:
            table.pop(i, None)
        return True

    def _m_message_post(self, table, model, args, kwargs) -> int:
        ids = args[0] if args else []
        if isinstance(ids, int):
            ids = [ids]
        body = kwargs.get("body", "")
        for i in ids:
            self.chatter.setdefault((model, i), []).append(body)
        return 1

    # ---- helpers ---- #
    @staticmethod
    def _project(rec: dict, fields) -> dict:
        if not fields:
            return dict(rec)
        out = {"id": rec.get("id")}
        for f in fields:
            out[f] = rec.get(f, False)
        return out

    @staticmethod
    def _limit(ids: list[int], limit) -> list[int]:
        return ids[:limit] if limit else ids

    @staticmethod
    def _order(table, ids: list[int], order) -> list[int]:
        if not order:
            return sorted(ids)
        field, _, direction = order.partition(" ")
        reverse = direction.strip().lower() == "desc"
        return sorted(ids, key=lambda i: (table[i].get(field) is None, table[i].get(field)), reverse=reverse)


# --------------------------------------------------------------------------- #
# High-level typed client
# --------------------------------------------------------------------------- #
class OdooClient:
    """Convenience API over any ``OdooBackend``.

    Tools call these methods rather than ``execute_kw`` directly, keeping the
    Odoo dialect in one place.
    """

    def __init__(self, backend: OdooBackend):
        self.backend = backend

    # generic ORM passthroughs
    def search_read(self, model, domain=None, fields=None, limit=None, order=None) -> list[dict]:
        return self.backend.execute_kw(
            model, "search_read", [domain or []],
            {"fields": fields, "limit": limit, "order": order},
        )

    def read(self, model, ids, fields=None) -> list[dict]:
        return self.backend.execute_kw(model, "read", [ids], {"fields": fields})

    def create(self, model, vals) -> int:
        return self.backend.execute_kw(model, "create", [vals])

    def write(self, model, ids, vals) -> bool:
        ids = [ids] if isinstance(ids, int) else ids
        return self.backend.execute_kw(model, "write", [ids, vals])

    def count(self, model, domain=None) -> int:
        return self.backend.execute_kw(model, "search_count", [domain or []])

    def log_note(self, model, rec_id, body: str) -> None:
        """Post to the Odoo chatter — the agent's audit trail."""
        self.backend.execute_kw(model, "message_post", [[rec_id]], {"body": body})
