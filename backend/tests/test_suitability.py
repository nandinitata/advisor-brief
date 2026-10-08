"""Suitability is deterministic — the MCP-style policy plus a keyword/verb rule —
so we can test it hard without a model. These are the Reg BI / FINRA 2111 blocks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compliance
import compliance_mcp


def _blocks(text, client_id):
    return len(compliance.suitability_flags(text, client_id))


def test_prohibited_asset_acquisition_blocks_for_becker():
    # high-yield to a capital-preservation, income-first 71-year-old = the classic Reg BI flag
    assert _blocks("We could look at adding a high-yield bond fund for extra income.", "becker") >= 1


def test_same_language_passes_for_aggressive_gomez():
    # high-yield is not on Maria's prohibited list; her profile allows it
    assert _blocks("We could look at adding a high-yield bond fund.", "gomez") == 0


def test_mentioning_without_acquiring_does_not_block():
    # describing / discussing is fine; only steering INTO a prohibited class trips it
    assert _blocks("You asked about high-yield bonds last time.", "becker") == 0


def test_leveraged_products_blocked_everywhere():
    assert _blocks("Consider moving into a leveraged ETF to amplify returns.", "patel") >= 1
    assert _blocks("Consider moving into a leveraged ETF to amplify returns.", "gomez") >= 1


def test_policy_bridge_returns_typed_policy():
    pol = compliance_mcp.suitability_for("becker")
    assert pol is not None
    assert pol.max_equity_pct == 55
    assert "high-yield" in pol.prohibited
    assert compliance_mcp.suitability_for("nobody") is None
