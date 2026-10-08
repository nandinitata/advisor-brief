"""A read-only MCP-style compliance bridge.

TIFIN's architecture talks about interacting with a firm's compliance and
custodial systems through the Model Context Protocol (MCP) — a hosted, read-only
bridge an AI agent can query for the facts it needs (a client's suitability
profile, their risk tolerance, their ethical walls) without being handed write
access to the system of record.

This module is the local, in-process stand-in for that bridge. It serves one
thing: the hardcoded suitability policy for a given client, pulled from
`clients.py`. The compliance layer calls `suitability_for(client_id)` and uses
the returned, typed policy to deterministically block drafts that would steer a
client into something their profile forbids.

In production this would be a genuine MCP server over the firm's compliance
database (the doc's Truthifi / FINTRX pattern): same contract, same read-only
posture, same typed response — just backed by the real system instead of a dict.
The guardrail code upstream would not change.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

import clients


class SuitabilityPolicy(BaseModel):
    """The machine-readable constraints a draft must not violate for this client."""

    client_id: str
    risk: str = Field(..., description="the client's stated risk posture, verbatim")
    max_equity_pct: int = Field(..., description="ceiling on total equity exposure")
    max_single_position_pct: int = Field(..., description="ceiling on any one position")
    prohibited: list[str] = Field(
        default_factory=list,
        description="asset-class keywords this client may not be steered into",
    )
    rationale: str = ""


_DEFAULT = {
    "max_equity_pct": 100,
    "max_single_position_pct": 100,
    "prohibited": [],
    "rationale": "No suitability profile on file; nothing is programmatically blocked.",
}


def suitability_for(client_id: str) -> SuitabilityPolicy | None:
    """Read-only lookup of a client's suitability policy. None if the client is unknown."""
    client = clients.get(client_id)
    if client is None:
        return None
    s = {**_DEFAULT, **client.get("suitability", {})}
    return SuitabilityPolicy(
        client_id=client_id,
        risk=client.get("risk", ""),
        max_equity_pct=s["max_equity_pct"],
        max_single_position_pct=s["max_single_position_pct"],
        prohibited=s["prohibited"],
        rationale=s["rationale"],
    )
