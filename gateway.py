#!/usr/bin/env python3
"""
Shell Gateway — 接收客户端提交的 shell 命令，分发给工作机执行，保存结果供客户端查询。
"""

import sqlite3
import uuid
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = "gateway.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gateway")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS commands (
            reqid       TEXT PRIMARY KEY,
            command     TEXT NOT NULL,
            user        TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
            stdout      TEXT DEFAULT '',
            stderr      TEXT DEFAULT '',
            exit_code   INTEGER DEFAULT NULL,
            created_at  TEXT NOT NULL,
            claimed_at  TEXT DEFAULT NULL,
            updated_at  TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Gateway started")
    yield

app = FastAPI(title="Shell Gateway", lifespan=lifespan)


# ── Pydantic models ──────────────────────────────────────────────

class SubmitRequest(BaseModel):
    command: str
    user: str


class SubmitResponse(BaseModel):
    reqid: str


class ResultRequest(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


class CommandInfo(BaseModel):
    reqid: str
    command: str
    user: str
    status: str
    stdout: str
    stderr: str
    exit_code: int | None


# ── API endpoints ────────────────────────────────────────────────

@app.post("/api/command", response_model=SubmitResponse)
def submit_command(req: SubmitRequest):
    """客户端提交 shell 命令，返回 reqid。"""
    if req.user == "root":
        raise HTTPException(403, "root execution is forbidden")
    reqid = uuid.uuid4().hex[:12]
    ts = now_iso()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO commands (reqid, command, user, status, created_at, updated_at) VALUES (?,?,?,'pending',?,?)",
        (reqid, req.command, req.user, ts, ts),
    )
    conn.commit()
    conn.close()
    logger.info("New command: reqid=%s user=%s cmd=%s", reqid, req.user, req.command)
    return SubmitResponse(reqid=reqid)


@app.get("/api/command/next", response_model=CommandInfo | dict)
def get_next_command():
    """工作机轮询获取下一条待执行命令。返回最早提交的 pending 命令，并标记为 running。"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT reqid, command, user FROM commands WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if row is None:
        conn.close()
        return {}
    reqid, command, user = row
    ts = now_iso()
    conn.execute(
        "UPDATE commands SET status='running', claimed_at=?, updated_at=? WHERE reqid=?",
        (ts, ts, reqid),
    )
    conn.commit()
    conn.close()
    logger.info("Dispatched command: reqid=%s to worker", reqid)
    return CommandInfo(reqid=reqid, command=command, user=user, status="running",
                       stdout="", stderr="", exit_code=None)


@app.post("/api/command/{reqid}/result")
def post_result(reqid: str, result: ResultRequest):
    """工作机提交执行结果。"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT status FROM commands WHERE reqid=?", (reqid,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(404, "reqid not found")
    ts = now_iso()
    conn.execute(
        "UPDATE commands SET status='done', stdout=?, stderr=?, exit_code=?, updated_at=? WHERE reqid=?",
        (result.stdout, result.stderr, result.exit_code, ts, reqid),
    )
    conn.commit()
    conn.close()
    logger.info("Result received: reqid=%s exit_code=%d", reqid, result.exit_code)
    return {"ok": True}


@app.get("/api/command/{reqid}", response_model=CommandInfo)
def query_result(reqid: str):
    """客户端通过 reqid 查询命令状态和结果。"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT reqid, command, user, status, stdout, stderr, exit_code FROM commands WHERE reqid=?",
        (reqid,),
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(404, "reqid not found")
    return CommandInfo(reqid=row[0], command=row[1], user=row[2], status=row[3],
                       stdout=row[4], stderr=row[5], exit_code=row[6])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
