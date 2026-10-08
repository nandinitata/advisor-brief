"""The web API for advisor-brief.

  GET  /health    model + index status
  GET  /clients   the pre-loaded demo households (so the UI needs no setup)
  POST /ask        {client_id, question, guardrails} -> brief + email + compliance report

The guardrails flag lets the UI show the same question with the compliance layer
off vs on: same model, same evidence, but one draft is shipped raw and the other
is grounded, cited, and reviewed. That contrast is the whole point.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import agent
import audit
import clients
import llm
from schemas import AuditInfo

app = FastAPI(title="advisor-brief", version="0.1.0")

# CORS: local dev by default; set AB_ALLOW_ORIGINS (comma-separated, or "*") for a
# deployed frontend. Any *.vercel.app preview/prod origin is always allowed so the
# hosted demo works without re-configuring on every Vercel deploy.
_origins_env = os.environ.get("AB_ALLOW_ORIGINS")
_origins = (
    [o.strip() for o in _origins_env.split(",") if o.strip()]
    if _origins_env
    else ["http://localhost:3000", "http://127.0.0.1:3000"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskBody(BaseModel):
    client_id: str
    question: str
    guardrails: bool = True


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "provider": llm.provider(),
        "writer_model": llm.WRITER_MODEL,
        "judge_model": llm.JUDGE_MODEL,
        "tiers": {"small": llm.SMALL_MODEL, "large": llm.LARGE_MODEL},
        "audit": audit.verify_chain(),
    }


@app.get("/clients")
def list_clients() -> dict:
    return {
        "clients": [
            {"id": c["id"], "name": c["name"], "members": c["members"], "goal": c["goal"]}
            for c in clients.CLIENTS.values()
        ]
    }


@app.post("/ask")
def ask(body: AskBody) -> dict:
    q = body.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Ask a question.")
    if clients.get(body.client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client.")
    result = agent.ask(body.client_id, q, enforce=body.guardrails)

    # books-and-records: append this request to the tamper-evident audit chain
    entry = audit.log(
        ts=datetime.now(timezone.utc).isoformat(),
        client_id=body.client_id,
        question=q,
        writer_model=llm.WRITER_MODEL,
        judge_model=llm.JUDGE_MODEL,
        prompt=f"{body.client_id}\n{q}\nguardrails={body.guardrails}",
        output=result.deliverable.meeting_brief + "\n\n" + result.deliverable.client_email,
        passed=result.compliance.passed,
        flags=[f.rule for f in result.compliance.flags],
    )
    result.audit = AuditInfo(**entry)
    return result.model_dump()


@app.get("/audit")
def audit_tail(limit: int = 20) -> dict:
    """Read-only view of the append-only audit chain (newest last)."""
    return {"records": audit.read_tail(limit)}


@app.get("/audit/verify")
def audit_verify() -> dict:
    """Walk the chain and report whether any record has been tampered with."""
    return audit.verify_chain()
