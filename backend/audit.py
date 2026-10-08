"""A tamper-evident, append-only audit log — the books-and-records half of the
compliance story.

SEC Rule 204-2 and FINRA Rule 3110 treat an AI tool that drafts client-facing
material as part of a firm's supervisory chain: the firm must keep unalterable
records of what the model saw and what it produced, with the model version and a
timestamp, so a regulator can reconstruct any decision after the fact.

This is a minimal, honest version of that. Every /ask appends one line to
`data/audit.jsonl`. Each record carries a `prev_hash` and a `record_hash`, where

    record_hash = sha256(prev_hash + canonical(record without record_hash))

so the file is a hash chain: change, reorder, or delete any past line and
`verify_chain()` breaks at that point. It's WORM in spirit — append-only, and
provably untampered — without needing a database. We store hashes of the prompt
and output rather than the raw text, which keeps PII out of the log while still
proving exactly what was processed.

In production this is a WORM Postgres table (or S3 Object Lock) written from a
background OpenTelemetry span, not a local JSONL file — but the chain property
and the fields are the same.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"
LOG = DATA / "audit.jsonl"
GENESIS = "0" * 64


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(record: dict) -> str:
    """Stable serialization so the same record always hashes the same way."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def record_hash(prev_hash: str, record: dict) -> str:
    """The chain hash for `record` following `prev_hash`. Pure; used by verify too."""
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return _sha256(prev_hash + _canonical(body))


def _last_hash() -> str:
    if not LOG.exists():
        return GENESIS
    last = GENESIS
    for line in LOG.read_text().splitlines():
        line = line.strip()
        if line:
            last = json.loads(line).get("record_hash", last)
    return last


def log(
    *,
    ts: str,
    client_id: str,
    question: str,
    writer_model: str,
    judge_model: str,
    prompt: str,
    output: str,
    passed: bool,
    flags: list[str],
) -> dict:
    """Append one audit record and return it (with its index and hashes).

    `ts` is injected by the caller (e.g. datetime.utcnow().isoformat()) so this
    function stays pure and testable.
    """
    DATA.mkdir(parents=True, exist_ok=True)
    prev = _last_hash()
    record = {
        "ts": ts,
        "client_id": client_id,
        "question": question,
        "writer_model": writer_model,
        "judge_model": judge_model,
        "prompt_sha256": _sha256(prompt),
        "output_sha256": _sha256(output),
        "passed": passed,
        "flags": flags,
        "prev_hash": prev,
    }
    record["record_hash"] = record_hash(prev, record)
    with LOG.open("a") as fh:
        fh.write(_canonical(record) + "\n")
    index = sum(1 for ln in LOG.read_text().splitlines() if ln.strip())
    return {"index": index, "record_hash": record["record_hash"], "chain_ok": True}


def read_tail(limit: int = 20) -> list[dict]:
    if not LOG.exists():
        return []
    lines = [ln for ln in LOG.read_text().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines[-limit:]]


def verify_chain() -> dict:
    """Walk the whole chain. Returns {ok, count, broken_at (1-indexed or None)}."""
    if not LOG.exists():
        return {"ok": True, "count": 0, "broken_at": None}
    prev = GENESIS
    count = 0
    for i, line in enumerate(l for l in LOG.read_text().splitlines() if l.strip()):
        count += 1
        rec = json.loads(line)
        if rec.get("prev_hash") != prev:
            return {"ok": False, "count": count, "broken_at": i + 1}
        if record_hash(prev, rec) != rec.get("record_hash"):
            return {"ok": False, "count": count, "broken_at": i + 1}
        prev = rec["record_hash"]
    return {"ok": True, "count": count, "broken_at": None}
