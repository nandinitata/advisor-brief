"""Macro and price data, both free and key-free.

FRED is read through its public fredgraph CSV endpoint (no API key needed).
Prices come from yfinance. Both are pulled once at ingest time and cached to
disk, so the live app never waits on them.
"""
from __future__ import annotations

import csv
import io

import requests

from universe import MACRO_SERIES

_FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"


def macro_snapshot() -> dict[str, dict]:
    """Latest reading per series, plus the prior reading so we can say which way
    it moved. Shape: {series_id: {label, latest, latest_date, prior, prior_date}}."""
    out: dict[str, dict] = {}
    for series_id, label in MACRO_SERIES.items():
        try:
            resp = requests.get(_FRED.format(series_id), timeout=30)
            resp.raise_for_status()
            rows = list(csv.reader(io.StringIO(resp.text)))
        except Exception:
            continue
        # rows[0] is the header; values of "." mean "no reading that day"
        points = [(r[0], r[1]) for r in rows[1:] if len(r) == 2 and r[1] not in ("", ".")]
        if not points:
            continue
        latest_date, latest = points[-1]
        prior_date, prior = points[-2] if len(points) > 1 else (None, None)
        out[series_id] = {
            "label": label,
            "latest": float(latest),
            "latest_date": latest_date,
            "prior": float(prior) if prior is not None else None,
            "prior_date": prior_date,
        }
    return out


def price_snapshot(tickers: list[str]) -> dict[str, dict]:
    """Last close and trailing-1y return per ticker, via yfinance."""
    import yfinance as yf

    out: dict[str, dict] = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
            if hist.empty:
                continue
            last = float(hist["Close"].iloc[-1])
            first = float(hist["Close"].iloc[0])
            ret_1y = (last / first - 1.0) if first else None
            out[ticker] = {
                "last_close": round(last, 2),
                "return_1y": round(ret_1y, 4) if ret_1y is not None else None,
                "as_of": str(hist.index[-1].date()),
            }
        except Exception:
            continue
    return out
