"""Build everything the live app reads, once, from free sources.

    python ingest.py            # full demo universe
    python ingest.py --limit 2  # just the first couple tickers, for a quick check

Outputs under backend/data/:
  chroma/        vector store of 10-K narrative chunks (embedded with nomic via Ollama)
  facts.json     latest annual XBRL figures per company, each with a citation handle
  macro.json     latest FRED readings
  prices.json    last close + 1y return per ticker
  ontology.json  the knowledge graph (see ontology.py)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import chromadb

import edgar
import market
import ontology
from universe import UNIVERSE, tickers

DATA = Path(__file__).parent / "data"
CHROMA_DIR = DATA / "chroma"
COLLECTION = "filings"

MAX_CHARS = 140_000      # cap narrative per filing so ingest stays quick
CHUNK = 1200
OVERLAP = 150

# rough section markers in a 10-K; chunk gets labeled by the last one seen
_SECTIONS = [
    (re.compile(r"item\s*1a[.\s]", re.I), "Risk Factors"),
    (re.compile(r"item\s*7[.\s]", re.I), "MD&A"),
    (re.compile(r"item\s*1[.\s]", re.I), "Business"),
]

_WORDS = re.compile(r"[A-Za-z]{3,}")


def _looks_like_prose(text: str) -> bool:
    """Skip XBRL header noise and number soup: keep chunks that read as sentences."""
    words = _WORDS.findall(text)
    return len(words) >= 60


def _section_at(text: str, pos: int) -> str:
    label = "general"
    best = -1
    for pat, name in _SECTIONS:
        for m in pat.finditer(text[:pos]):
            if m.start() > best:
                best, label = m.start(), name
    return label


def chunk_filing(text: str) -> list[tuple[str, str]]:
    """Return (chunk_text, section_label), skipping non-prose chunks."""
    text = text[:MAX_CHARS]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        piece = text[i : i + CHUNK]
        if _looks_like_prose(piece):
            out.append((piece.strip(), _section_at(text, i)))
        i += CHUNK - OVERLAP
    return out


def run(limit: int | None = None) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    universe = tickers()[: limit] if limit else tickers()

    print("resolving CIKs...")
    cik = edgar.cik_map()

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    # no embedding_function passed: Chroma uses its built-in on-device model
    # (MiniLM via onnxruntime). No API key, no Ollama, deploys anywhere.
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    facts: dict[str, list[dict]] = {}

    for ticker in universe:
        name = UNIVERSE[ticker][0]
        if ticker not in cik:
            print(f"  ! no CIK for {ticker}, skipping")
            continue
        print(f"ingesting {ticker} ({name})...")

        facts[ticker] = edgar.latest_annual_facts(cik[ticker])

        doc = edgar.latest_10k_doc(cik[ticker])
        if not doc:
            print(f"  ! no 10-K for {ticker}")
            continue
        text, url = doc
        chunks = chunk_filing(text)
        if not chunks:
            continue

        fiscal = facts[ticker][0]["fiscal_year"] if facts.get(ticker) else "recent"
        docs, ids, metas = [], [], []
        for n, (chunk_text, section) in enumerate(chunks):
            docs.append(chunk_text)
            ids.append(f"{ticker}-10K-{n}")
            metas.append(
                {
                    "ticker": ticker,
                    "company": name,
                    "section": section,
                    "fiscal_year": str(fiscal),
                    "source_id": f"{ticker}-10K-{fiscal}-{n}",
                    "url": url,
                }
            )
        print(f"  embedding {len(docs)} chunks...")
        col.add(ids=ids, documents=docs, metadatas=metas)

    print("facts.json...")
    (DATA / "facts.json").write_text(json.dumps(facts, indent=2))

    print("macro.json...")
    (DATA / "macro.json").write_text(json.dumps(market.macro_snapshot(), indent=2))

    print("prices.json...")
    (DATA / "prices.json").write_text(json.dumps(market.price_snapshot(universe), indent=2))

    print("ontology.json...")
    ontology.save(ontology.build())

    print(f"done. {col.count()} filing chunks indexed across {len(universe)} tickers.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    run(args.limit)
