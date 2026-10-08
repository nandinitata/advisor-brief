"""Three synthetic client households, pre-loaded so anyone can try the demo in
ten seconds without typing in a portfolio.

Nothing here is real. The names are ordinary on purpose. Each household has a
goal and a risk posture so the brief has something human to anchor to, plus
holdings drawn from universe.py.

Each household also carries a `suitability` block: the hardcoded, machine-readable
investment constraints that flow from its risk posture (max equity, max single
position, prohibited asset classes). The compliance layer reads these through the
MCP-style bridge in `compliance_mcp.py` and blocks any draft that would steer the
client into something their profile forbids — the deterministic half of SEC Reg BI
/ FINRA 2111 suitability. See `compliance.suitability_flags`.
"""
from __future__ import annotations

CLIENTS: dict[str, dict] = {
    "patel": {
        "id": "patel",
        "name": "The Patel household",
        "members": "Anil (58) and Rekha (56)",
        "goal": "Retire in about seven years and not worry about market dips near the date.",
        "risk": "Moderate. They felt 2022 in their stomach and don't want a repeat close to retirement.",
        "notes": "Rekha asked last time whether they hold too much in tech.",
        "holdings": [
            {"ticker": "AAPL", "weight": 0.18},
            {"ticker": "MSFT", "weight": 0.17},
            {"ticker": "JPM", "weight": 0.12},
            {"ticker": "JNJ", "weight": 0.13},
            {"ticker": "KO", "weight": 0.10},
            {"ticker": "BONDS", "weight": 0.30},
        ],
        "suitability": {
            "max_equity_pct": 75,
            "max_single_position_pct": 25,
            "prohibited": ["leveraged", "inverse etf", "crypto", "options", "speculative", "meme"],
            "rationale": "Moderate risk, ~7 years to retirement: growth is fine but no leverage, "
            "derivatives, or speculative concentration this close to the date.",
        },
    },
    "gomez": {
        "id": "gomez",
        "name": "Maria Gomez",
        "members": "Maria (31), single",
        "goal": "Grow aggressively for the next couple of decades; a house down payment in ~5 years.",
        "risk": "High. Comfortable with swings, wants growth.",
        "notes": "Keeps asking if she should hold more NVIDIA.",
        "holdings": [
            {"ticker": "NVDA", "weight": 0.25},
            {"ticker": "AMZN", "weight": 0.20},
            {"ticker": "TSLA", "weight": 0.15},
            {"ticker": "GOOGL", "weight": 0.20},
            {"ticker": "MSFT", "weight": 0.20},
        ],
        "suitability": {
            "max_equity_pct": 100,
            "max_single_position_pct": 40,
            "prohibited": ["leveraged", "inverse etf", "illiquid private", "options"],
            "rationale": "High risk tolerance, decades-long horizon: broad equity concentration is "
            "acceptable; still no leverage or illiquid private placements for a single investor.",
        },
    },
    "becker": {
        "id": "becker",
        "name": "Tom Becker",
        "members": "Tom (71), widower",
        "goal": "Steady income and capital preservation. Takes regular withdrawals.",
        "risk": "Low. Income first, growth second.",
        "notes": "Worried about inflation eating his fixed income.",
        "holdings": [
            {"ticker": "KO", "weight": 0.18},
            {"ticker": "PG", "weight": 0.18},
            {"ticker": "JNJ", "weight": 0.16},
            {"ticker": "CVX", "weight": 0.13},
            {"ticker": "BONDS", "weight": 0.35},
        ],
        "suitability": {
            "max_equity_pct": 55,
            "max_single_position_pct": 20,
            "prohibited": [
                "high-yield", "high yield", "junk bond", "leveraged", "inverse etf",
                "illiquid", "private credit", "alternatives", "options", "crypto", "speculative",
            ],
            "rationale": "Capital-preservation profile taking withdrawals at 71: no high-yield/junk, "
            "illiquid alternatives, leverage, or derivatives — the classic Reg BI red flags for an "
            "elderly, income-first client.",
        },
    },
}


def get(client_id: str) -> dict | None:
    return CLIENTS.get(client_id)


def summary(client: dict) -> str:
    """A compact paragraph the writer node can read as context."""
    held = ", ".join(f"{h['ticker']} {int(h['weight'] * 100)}%" for h in client["holdings"])
    return (
        f"{client['name']} ({client['members']}). "
        f"Goal: {client['goal']} Risk posture: {client['risk']} "
        f"Open note from last time: {client['notes']} "
        f"Current holdings: {held}."
    )
