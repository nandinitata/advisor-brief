"""The ontology graph is pure data, so walk it directly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ontology
import clients


def test_client_holdings_match_profile():
    g = ontology.build()
    held = ontology.tickers_for_client(g, "patel")
    profile = [h["ticker"] for h in clients.CLIENTS["patel"]["holdings"]]
    assert sorted(held) == sorted(profile)


def test_factors_reach_series():
    g = ontology.build()
    factors = ontology.factors_for_client(g, "patel")
    assert "rates" in factors
    series = ontology.series_for_factors(g, factors)
    assert "DGS10" in series  # rates is measured by the 10-year yield


def test_bond_sleeve_is_rate_sensitive():
    g = ontology.build()
    factors = ontology.factors_for_client(g, "becker")  # holds BONDS
    assert "rates" in factors and "inflation" in factors


def test_tickers_for_factor_scopes_to_holdings():
    g = ontology.build()
    held = ontology.tickers_for_client(g, "gomez")
    hits = ontology.tickers_for_factor(g, "ai_capex", held)
    assert "NVDA" in hits  # Maria holds NVIDIA, which is ai_capex-sensitive
