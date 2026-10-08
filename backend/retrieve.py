"""Turn a client + question into a pack of evidence the writer is allowed to use.

Grounding happens here and nowhere else. The writer never sees the open web or
its own memory of a company; it only sees what this module hands it, and every
item is a Citation with a snippet the claim can be checked against.

This follows the §7.3 "Tool-Calling Agentic RAG" split: the agent's knowledge is
two different memory systems, and we never ask the vector store to do a job it is
bad at.

  Semantic memory (vector search) — unstructured, narrative, slow-changing:
    1. 10-K narrative chunks, scoped to what the client holds.

  Real-time / structured data (deterministic "tool calls", no embedding) — the
  tabular numbers that a vector index would only make stale:
    2. structured XBRL facts for those holdings
    3. macro readings for the factors those holdings react to
    4. recent price / 1y return for those holdings

The four sources fan out in parallel and join. Price and macro default to cached
snapshots for a deterministic, offline-safe demo; set AB_LIVE_DATA=1 to fetch
them live at request time (with automatic fallback to the cache) — that is the
"bypass the vector store for high-velocity tabular data" path, made real.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import chromadb

import ontology
from schemas import Citation
from universe import UNIVERSE

DATA = Path(__file__).parent / "data"
FRED_PAGE = "https://fred.stlouisfed.org/series/{}"
LIVE_DATA = os.environ.get("AB_LIVE_DATA") == "1"


@lru_cache(maxsize=1)
def _store() -> dict:
    client = chromadb.PersistentClient(path=str(DATA / "chroma"))
    col = client.get_collection("filings")
    return {
        "col": col,
        "facts": json.loads((DATA / "facts.json").read_text()),
        "macro": json.loads((DATA / "macro.json").read_text()),
        "prices": json.loads((DATA / "prices.json").read_text()),
        "graph": ontology.load(),
    }


def _fmt_usd(v: float | int) -> str:
    return f"${v/1e9:.1f}B" if abs(v) >= 1e9 else f"${v/1e6:.1f}M"


def _live_or_cached_macro() -> dict:
    """Live FRED pull when AB_LIVE_DATA=1, else the cached snapshot. Always falls
    back to cache on any failure so a flaky network can't break a request."""
    if LIVE_DATA:
        try:
            import market

            live = market.macro_snapshot()
            if live:
                return live
        except Exception:
            pass
    return _store()["macro"]


def _live_or_cached_prices(held: list[str]) -> dict:
    if LIVE_DATA:
        try:
            import market

            live = market.price_snapshot([t for t in held if t in UNIVERSE])
            if live:
                return live
        except Exception:
            pass
    return _store()["prices"]


def filing_evidence(question: str, held: list[str], k: int = 4) -> list[Citation]:
    store = _store()
    scoped = [t for t in held if t in UNIVERSE]  # BONDS has no filing
    if not scoped:
        return []
    where = {"ticker": {"$in": scoped}} if len(scoped) > 1 else {"ticker": scoped[0]}
    res = store["col"].query(query_texts=[question], n_results=k, where=where)
    out: list[Citation] = []
    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
        snippet = doc.strip().replace("\n", " ")
        out.append(
            Citation(
                source_id=meta["source_id"],
                kind="filing_text",
                ticker=meta["ticker"],
                title=f"{meta['company']} 10-K FY{meta['fiscal_year']}, {meta['section']}",
                snippet=snippet[:400],
                url=meta["url"],
            )
        )
    return out


def fact_evidence(held: list[str]) -> list[Citation]:
    store = _store()
    out: list[Citation] = []
    for ticker in held:
        for f in store["facts"].get(ticker, []):
            out.append(
                Citation(
                    source_id=f"{ticker}-FACT-{f['label'].split()[0].lower()}",
                    kind="financial_fact",
                    ticker=ticker,
                    title=f"{UNIVERSE[ticker][0]} 10-K FY{f['fiscal_year']} (XBRL, {f['accession']})",
                    snippet=f"{f['label']} for FY{f['fiscal_year']}: {_fmt_usd(f['value'])} "
                    f"(exact: {f['value']:,}).",
                    url=None,
                )
            )
    return out


def macro_evidence(factors: list[str]) -> list[Citation]:
    store = _store()
    series = ontology.series_for_factors(store["graph"], factors)
    macro = _live_or_cached_macro()
    out: list[Citation] = []
    for sid in series:
        m = macro.get(sid)
        if not m:
            continue
        move = ""
        if m.get("prior") is not None:
            direction = "up" if m["latest"] > m["prior"] else "down" if m["latest"] < m["prior"] else "flat"
            move = f" ({direction} from {m['prior']} on {m['prior_date']})"
        out.append(
            Citation(
                source_id=f"MACRO-{sid}",
                kind="macro",
                ticker=None,
                title=m["label"],
                snippet=f"{m['label']}: {m['latest']} as of {m['latest_date']}{move}.",
                url=FRED_PAGE.format(sid),
            )
        )
    return out


def price_evidence(held: list[str]) -> list[Citation]:
    prices = _live_or_cached_prices(held)
    out: list[Citation] = []
    for ticker in held:
        p = prices.get(ticker)
        if not p:
            continue
        ret = f"{p['return_1y']*100:+.1f}% over the trailing year" if p.get("return_1y") is not None else "n/a"
        out.append(
            Citation(
                source_id=f"PRICE-{ticker}",
                kind="price",
                ticker=ticker,
                title=f"{UNIVERSE[ticker][0]} price",
                snippet=f"{ticker} last close ${p['last_close']} ({p['as_of']}); {ret}.",
                url=None,
            )
        )
    return out


def evidence_pack(client_id: str, question: str) -> list[Citation]:
    """The full, de-duplicated evidence list for a client question.

    The four sources are independent, so we fan them out in parallel and join —
    the semantic-memory vector query and the structured/real-time tool calls run
    at once rather than one after another."""
    store = _store()
    g = store["graph"]
    held = ontology.tickers_for_client(g, client_id)
    factors = ontology.factors_for_client(g, client_id)

    tasks = [
        lambda: filing_evidence(question, held),  # semantic memory (vector)
        lambda: fact_evidence(held),              # structured tool call
        lambda: macro_evidence(factors),          # real-time / structured tool call
        lambda: price_evidence(held),             # real-time / structured tool call
    ]
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        results = list(pool.map(lambda fn: fn(), tasks))
    cites = [c for group in results for c in group]
    # de-dupe by source_id, keep first
    seen: set[str] = set()
    unique: list[Citation] = []
    for c in cites:
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        unique.append(c)
    return unique
