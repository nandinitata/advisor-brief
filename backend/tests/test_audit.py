"""The audit log is a hash chain, so tampering is detectable. We point it at a
temp file and prove: a clean chain verifies, and editing any past record breaks it."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audit


def _use_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DATA", tmp_path)
    monkeypatch.setattr(audit, "LOG", tmp_path / "audit.jsonl")


def _entry(i):
    return dict(
        ts=f"2026-01-0{i}T00:00:00+00:00",
        client_id="becker",
        question=f"q{i}",
        writer_model="llama-3.3-70b",
        judge_model="llama-3.1-8b",
        prompt=f"p{i}",
        output=f"o{i}",
        passed=True,
        flags=[],
    )


def test_clean_chain_verifies(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    for i in range(1, 4):
        audit.log(**_entry(i))
    v = audit.verify_chain()
    assert v == {"ok": True, "count": 3, "broken_at": None}


def test_tampering_breaks_the_chain(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    for i in range(1, 4):
        audit.log(**_entry(i))

    lines = audit.LOG.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["question"] = "edited after the fact"  # tamper, keep the old record_hash
    lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    audit.LOG.write_text("\n".join(lines) + "\n")

    v = audit.verify_chain()
    assert v["ok"] is False
    assert v["broken_at"] == 2


def test_index_increments(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    e1 = audit.log(**_entry(1))
    e2 = audit.log(**_entry(2))
    assert e1["index"] == 1 and e2["index"] == 2
    assert e2["record_hash"] != e1["record_hash"]
