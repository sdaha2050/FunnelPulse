"""FastAPI app: the API for the UI, plus the built frontend as static files."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.engine import TICK_SECONDS, Engine

engine = Engine(auto_incidents=os.environ.get("AUTO_INCIDENTS", "1") == "1")


async def _run_loop():
    while True:
        engine.tick()
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_run_loop())
    yield
    task.cancel()


app = FastAPI(title="TripSentry", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Decision(BaseModel):
    note: str = ""


class KillSwitch(BaseModel):
    global_on: bool | None = None
    action_type: str | None = None
    on: bool | None = None


@app.get("/api/health")
async def health():
    return {"ok": True, "ticks": engine.ticks}


@app.get("/api/state")
async def state():
    return engine.state()


@app.post("/api/incidents/clear")
async def clear_incident():
    engine.clear_incident()
    return {"ok": True}


@app.post("/api/incidents/{kind}")
async def start_incident(kind: str):
    try:
        inc = engine.start_incident(kind)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "incident": inc["label"]}


@app.get("/api/approvals")
async def approvals():
    return engine.state()["approvals"]


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: str, body: Decision | None = None):
    try:
        return {"ok": True, "status": engine.decide(approval_id, True, (body or Decision()).note)["status"]}
    except KeyError:
        raise HTTPException(404, "No pending approval with that id")


@app.post("/api/approvals/{approval_id}/reject")
async def reject(approval_id: str, body: Decision | None = None):
    try:
        return {"ok": True, "status": engine.decide(approval_id, False, (body or Decision()).note)["status"]}
    except KeyError:
        raise HTTPException(404, "No pending approval with that id")


@app.post("/api/killswitch")
async def killswitch(body: KillSwitch):
    return engine.set_kill_switch(body.global_on, body.action_type, body.on)


# ---------- serve the built React app ----------
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        file = STATIC_DIR / path
        return FileResponse(file if path and file.is_file() else STATIC_DIR / "index.html")
