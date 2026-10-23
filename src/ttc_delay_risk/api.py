"""Read-only prediction API with explicit demo/degraded status and bounded queries."""

import os
from datetime import date as Date, datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, HTMLResponse
from .store import Store


def create_app(url=None):
    app = FastAPI(title="TTC Delay Risk", version="0.2.0")
    store = Store(url or os.getenv("DATABASE_URL", "sqlite:///data/predictions.db"))
    app.state.store = store

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse(
            status_code=503, content={"detail": "Service dependency unavailable"}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        today = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
        rows = store.predictions(today)
        usable = bool(rows) and all(
            r["status"] == "ok" and r["mode"] == "real_data" for r in rows
        )
        return JSONResponse(
            status_code=200 if usable else 503,
            content={
                "ready": usable,
                "date": today,
                "reason": None if usable else "No current production predictions",
            },
        )

    @app.get("/predictions")
    def predictions(
        date: Date,
        route: str = Query(default=None, max_length=16),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        rows = store.predictions(date.isoformat())
        if route:
            rows = [r for r in rows if r["route_id"] == route]
        return {"total": len(rows), "items": rows[offset : offset + limit]}

    @app.get("/risk-ranking")
    def ranking(date: Date, top_k: int = Query(10, ge=1, le=100)):
        rows = store.predictions(date.isoformat())
        return {
            "items": sorted(
                rows, key=lambda r: (-r["probability"], r["route_id"], r["start"])
            )[:top_k]
        }

    @app.get("/model-info")
    def model_info(date: Date):
        rows = store.predictions(date.isoformat())
        return {
            "versions": sorted({r["model_version"] for r in rows}),
            "modes": sorted({r["mode"] for r in rows}),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>TTC Delay Risk</title>
<style>body{font:16px system-ui;background:#f4f6fa;color:#142336;max-width:1050px;margin:50px auto;padding:24px}h1{font-size:40px}table{width:100%;border-collapse:collapse;background:white}td,th{text-align:left;padding:14px;border-bottom:1px solid #ddd}button{background:#154c79;color:white;border:0;padding:12px}input{padding:10px}.note{padding:20px;background:#fff2cf;margin:20px 0}</style>
<h1>TTC Delay Risk</h1><p>Recorded-event risk by route and hour</p><div class="note">Research prototype. Synthetic demo results are not TTC forecasts. An absent event record does not establish on-time service.</div>
<label>Operating date <input id="day" type="date" value="2025-07-01"></label> <button id="load">View ranking</button><p id="status" role="status"></p><table><thead><tr><th>Route</th><th>Window (UTC)</th><th>Probability</th><th>Risk</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table>
<script>document.getElementById('load').onclick=async()=>{const body=document.getElementById('rows');body.replaceChildren();try{const res=await fetch('/risk-ranking?date='+document.getElementById('day').value);if(!res.ok)throw Error();const data=await res.json();document.getElementById('status').textContent=data.items.length?'Top recorded-event risk windows':'No published batch for this date';for(const x of data.items){const tr=document.createElement('tr');for(const v of [x.route_id,x.start,(100*x.probability).toFixed(1)+'%',x.risk_level,x.mode+' / '+x.status]){const td=document.createElement('td');td.textContent=v;tr.append(td)}body.append(tr)}}catch(e){document.getElementById('status').textContent='Service unavailable'}};</script></html>"""

    return app
