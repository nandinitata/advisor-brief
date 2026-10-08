"""Typed contracts for everything that flows through the agent.

Keeping these in one place means the retriever, the writer, the compliance
judge, and the API all speak the same language. A citation is never a loose
string; a compliance flag always names the rule it tripped.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """One piece of evidence the brief is allowed to lean on."""

    source_id: str = Field(..., description="short tag shown inline, e.g. AAPL-10K-2024-R3")
    kind: Literal["filing_text", "financial_fact", "price", "macro"]
    ticker: str | None = None
    title: str = Field(..., description="human label, e.g. 'Apple 10-K FY2024, Risk Factors'")
    snippet: str = Field(..., description="the exact text or number the claim rests on")
    url: str | None = None


class ComplianceFlag(BaseModel):
    """Something the compliance judge wants a human to look at before this goes out."""

    severity: Literal["block", "warn"]
    rule: str = Field(..., description="the standard it implicates, e.g. 'SEC suitability / fiduciary'")
    quote: str = Field(..., description="the exact sentence from the draft that tripped it")
    why: str
    suggested_fix: str


class ComplianceReport(BaseModel):
    passed: bool
    flags: list[ComplianceFlag] = []
    refused: bool = False
    refusal_reason: str | None = None
    unsupported_claims_removed: list[str] = []
    checked_claims: int = 0


class Deliverable(BaseModel):
    """What the advisor actually walks away with."""

    meeting_brief: str
    client_email: str
    citations: list[Citation] = []


class DraftContract(BaseModel):
    """The state-contract a draft must satisfy before it may advance to review.

    This is the §7.1 "State Contract Schema": the writer node's output has to
    parse into this, or the node does one localized retry before the graph moves
    on. A draft with an empty brief or a missing email is a malformed hand-off,
    not something to pass downstream.
    """

    meeting_brief: str
    client_email: str

    @field_validator("meeting_brief", "client_email")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("draft section is empty")
        return v


class FinOps(BaseModel):
    """What this answer cost, for Inference FinOps (see router.py)."""

    cache_hit: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_usd: float = 0.0
    calls: list[dict] = Field(default_factory=list, description="per-call {task,tier,model,in,out}")
    note: str = "Illustrative open-weights rates; cost is measured, not billed."


class AuditInfo(BaseModel):
    """Pointer to this request's record in the append-only audit chain."""

    index: int
    record_hash: str
    chain_ok: bool


class AskResult(BaseModel):
    client_id: str
    question: str
    deliverable: Deliverable
    compliance: ComplianceReport
    steps: list[dict] = Field(default_factory=list, description="node-by-node trace for the UI")
    finops: FinOps | None = None
    audit: AuditInfo | None = None
