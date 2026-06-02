"""FastAPI veneer over ``DashboardService`` — JSON API + one HTML page.

FastAPI is imported lazily so the core package stays stdlib-only. Install the
extra and run:

    pip install "aaaas[dashboard]"   # or: pip install fastapi uvicorn
    aaaas-dashboard                  # serves http://127.0.0.1:8000
"""
from __future__ import annotations

from datetime import date

from ..app import build_bookkeeper
from ..config import Settings
from ..odoo.client import InMemoryBackend
from ..seed import seed_demo_data
from .service import DashboardHITL, DashboardService


def build_default_service(today: date | None = None) -> DashboardService:
    """A seeded, in-memory service with a demo batch already run."""
    today = today or date(2026, 6, 2)
    settings = Settings.from_env()
    settings.odoo.in_memory = True
    backend = InMemoryBackend()
    ids = seed_demo_data(backend, today=today)
    bk = build_bookkeeper(settings, backend=backend, hitl=DashboardHITL(), today=today)
    service = DashboardService(bk, demo_ids=ids)
    service.run_demo_batch()
    return service


def create_app(service: DashboardService | None = None):
    """Build the FastAPI app. Imports FastAPI lazily."""
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "The dashboard needs FastAPI: pip install 'aaaas[dashboard]'"
        ) from exc

    app = FastAPI(title="AAAAS Bookkeeping Agent — Admin", version="0.1.0")
    app.state.service = service or build_default_service()

    def svc() -> DashboardService:
        return app.state.service

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/metrics")
    def metrics():
        return svc().metrics()

    @app.get("/api/approvals")
    def approvals():
        return svc().approvals()

    @app.get("/api/activity")
    def activity():
        return svc().recent_activity()

    @app.post("/api/approvals/{pid}/approve")
    def approve(pid: int):
        try:
            result = svc().approve(pid)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"No pending approval #{pid}")
        return {"ok": True, "result": result}

    @app.post("/api/approvals/{pid}/reject")
    def reject(pid: int, note: str = Body("", embed=True)):
        try:
            svc().reject(pid, note)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"No pending approval #{pid}")
        return {"ok": True}

    @app.post("/api/demo/reset")
    def reset():
        app.state.service = build_default_service()
        return JSONResponse({"ok": True})

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:  # pragma: no cover
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Run needs uvicorn: pip install 'aaaas[dashboard]'") from exc
    uvicorn.run(create_app(), host=host, port=port)


INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AAAAS — Bookkeeping Agent</title>
<style>
  :root { --bg:#0f1216; --card:#1a1f27; --line:#2a313c; --fg:#e6e9ef;
          --muted:#8b94a3; --green:#3fb950; --amber:#d29922; --red:#f85149;
          --blue:#58a6ff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:20px 28px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; justify-content:space-between; }
  header h1 { font-size:17px; margin:0; font-weight:650; }
  header .sub { color:var(--muted); font-size:12px; }
  button { background:var(--card); color:var(--fg); border:1px solid var(--line);
           border-radius:7px; padding:6px 12px; cursor:pointer; font-size:13px; }
  button:hover { border-color:var(--blue); }
  button.approve { border-color:#1f6f33; } button.approve:hover { background:#16341f; }
  button.reject { border-color:#6f2a26; } button.reject:hover { background:#341816; }
  main { padding:24px 28px; max-width:1100px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:14px; margin-bottom:26px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:11px;
          padding:16px 18px; }
  .card .k { color:var(--muted); font-size:12px; text-transform:uppercase;
             letter-spacing:.04em; }
  .card .v { font-size:26px; font-weight:680; margin-top:6px; }
  .card .v.green{color:var(--green)} .card .v.amber{color:var(--amber)}
  .card .v.blue{color:var(--blue)}
  h2 { font-size:14px; color:var(--muted); text-transform:uppercase;
       letter-spacing:.05em; margin:22px 0 12px; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line);
          vertical-align:top; }
  th { color:var(--muted); font-weight:600; font-size:12px; }
  .pill { font-size:11px; padding:2px 8px; border-radius:999px;
          border:1px solid var(--line); }
  .pill.auto{color:var(--green);border-color:#1f6f33}
  .pill.auto_flag{color:var(--amber);border-color:#6e5413}
  .pill.draft_hitl{color:var(--blue);border-color:#1d4e7a}
  .pill.pause{color:var(--red);border-color:#6f2a26}
  .muted{color:var(--muted)} .empty{color:var(--muted);padding:14px 10px;}
  .right{text-align:right} .mono{font-variant-numeric:tabular-nums}
</style>
</head>
<body>
<header>
  <div><h1>🤖 AAAAS · Bookkeeping Agent</h1>
       <div class="sub">Autonomous AP/AR on Odoo — human keeps the sign-off</div></div>
  <button onclick="resetDemo()">↻ Reset demo</button>
</header>
<main>
  <div class="cards" id="cards"></div>

  <h2>Approval queue <span class="muted" id="apCount"></span></h2>
  <table id="approvals"><thead><tr>
    <th>#</th><th>Action</th><th>Summary</th><th class="right">Confidence</th><th></th>
  </tr></thead><tbody></tbody></table>

  <h2>Recent activity</h2>
  <table id="activity"><thead><tr>
    <th>Time</th><th>Tool</th><th>Decision</th><th>Result</th>
  </tr></thead><tbody></tbody></table>
</main>

<script>
const $ = s => document.querySelector(s);
async function jget(u){ return (await fetch(u)).json(); }
async function jpost(u,b){ return fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},
  body:b?JSON.stringify(b):null}); }

function card(k,v,cls){ return `<div class="card"><div class="k">${k}</div>
  <div class="v ${cls||''} mono">${v}</div></div>`; }

async function refresh(){
  const m = await jget('/api/metrics');
  $('#cards').innerHTML =
      card('Transactions processed', m.transactions_processed, 'green')
    + card('Hours saved', m.hours_saved, 'blue')
    + card('Pending approval', m.pending_approval, m.pending_approval? 'amber':'')
    + card('Paused (low conf.)', m.paused, m.paused? 'amber':'')
    + card('Automation rate', Math.round(m.automation_rate*100)+'%');

  const ap = await jget('/api/approvals');
  $('#apCount').textContent = ap.length ? `(${ap.length})` : '';
  const ab = $('#approvals tbody');
  ab.innerHTML = ap.length ? ap.map(a => `<tr>
      <td class="mono">${a.id}</td>
      <td><code>${a.action}</code></td>
      <td>${a.summary}</td>
      <td class="right mono">${Math.round(a.confidence*100)}%</td>
      <td class="right">
        <button class="approve" onclick="approve(${a.id})">Approve</button>
        <button class="reject" onclick="reject(${a.id})">Reject</button>
      </td></tr>`).join('')
    : `<tr><td colspan="5" class="empty">Nothing waiting — the agent is clear. ✨</td></tr>`;

  const act = await jget('/api/activity');
  $('#activity tbody').innerHTML = act.length ? act.map(a => `<tr>
      <td class="muted mono">${a.ts}</td>
      <td><code>${a.tool}</code></td>
      <td>${a.decision ? `<span class="pill ${a.decision}">${a.decision}</span>`:'<span class="muted">—</span>'}</td>
      <td class="${a.ok?'':'muted'}">${a.message}</td></tr>`).join('')
    : `<tr><td colspan="4" class="empty">No activity yet.</td></tr>`;
}
async function approve(id){ await jpost(`/api/approvals/${id}/approve`); refresh(); }
async function reject(id){ await jpost(`/api/approvals/${id}/reject`, {note:'rejected from dashboard'}); refresh(); }
async function resetDemo(){ await jpost('/api/demo/reset'); refresh(); }

refresh(); setInterval(refresh, 3000);
</script>
</body>
</html>
"""
