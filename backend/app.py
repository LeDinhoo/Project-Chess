from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.core import Core, SyncError


class ResultRequest(BaseModel):
    success: bool
    elapsed_ms: int | float


app = FastAPI()
core = Core()


@app.post("/api/sync")
def sync():
    try:
        return core.sync()
    except SyncError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/sessions/today")
def start_today():
    try:
        return core.start_session()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/sessions")
def list_sessions():
    return core.list_sessions()


@app.get("/api/sessions/{date}")
def get_session(date: str):
    try:
        session = core.get_session(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{date}/{position}/result")
def record_result(date: str, position: int, request: ResultRequest):
    try:
        return core.record_result(date, position, request.success, request.elapsed_ms)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
