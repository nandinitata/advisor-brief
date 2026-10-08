"""The small, fixed set of holdings the demo clients own.

Deliberately tiny and recognizable so the filings are rich and a person trying
the demo sees names they know. Each holding carries the two things the ontology
graph hangs off of: a sector and the macro factors it reacts to. That lets the
retriever hop from "a client holds this" to "so these macro readings matter."

CIKs are resolved at ingest time from the SEC's official ticker map, so there is
nothing to hand-maintain here.
"""
from __future__ import annotations

# ticker -> (company name, sector, [macro factors it is sensitive to])
UNIVERSE: dict[str, tuple[str, str, list[str]]] = {
    "AAPL": ("Apple", "Technology", ["rates", "consumer_demand", "fx"]),
    "MSFT": ("Microsoft", "Technology", ["rates", "enterprise_it"]),
    "GOOGL": ("Alphabet", "Communication Services", ["rates", "ad_spend"]),
    "AMZN": ("Amazon", "Consumer Discretionary", ["rates", "consumer_demand", "wages"]),
    "NVDA": ("NVIDIA", "Technology", ["rates", "ai_capex", "fx"]),
    "TSLA": ("Tesla", "Consumer Discretionary", ["rates", "consumer_demand", "commodities"]),
    "JPM": ("JPMorgan Chase", "Financials", ["rates", "credit", "yield_curve"]),
    "JNJ": ("Johnson & Johnson", "Health Care", ["rates", "defensive"]),
    "KO": ("Coca-Cola", "Consumer Staples", ["rates", "defensive", "fx"]),
    "PG": ("Procter & Gamble", "Consumer Staples", ["rates", "defensive", "commodities"]),
    "CVX": ("Chevron", "Energy", ["commodities", "inflation"]),
}

# the macro series we pull (FRED series id -> plain label). No API key needed:
# we read the public fredgraph CSV endpoint.
MACRO_SERIES: dict[str, str] = {
    "DGS10": "10-year Treasury yield",
    "DGS2": "2-year Treasury yield",
    "FEDFUNDS": "Federal funds rate",
    "CPIAUCSL": "CPI (headline inflation index)",
    "UNRATE": "Unemployment rate",
}

# which macro factor each series speaks to, for the ontology edges
SERIES_TO_FACTOR: dict[str, str] = {
    "DGS10": "rates",
    "DGS2": "rates",
    "FEDFUNDS": "rates",
    "CPIAUCSL": "inflation",
    "UNRATE": "wages",
}


def tickers() -> list[str]:
    return list(UNIVERSE.keys())
