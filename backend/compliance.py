"""The compliance layer. This is the part Vinay Nair would actually read.

Three kinds of check, on purpose:

  1. Deterministic grounding. Every factual/numeric sentence must carry a
     [source_id] that exists in the evidence pack. A citation to something we
     never retrieved, or a number with no citation at all, is treated as
     unsupported and pulled. This is what makes "refuse instead of hallucinate"
     real rather than a slogan, and it is what the eval harness measures.

  2. Deterministic suitability. A draft that steers the client into an asset
     class their profile forbids (high-yield to an income-first 71-year-old, say)
     is blocked by code, not by the model's good intentions. The forbidden
     classes come from a read-only MCP-style bridge (compliance_mcp.py) over the
     client's suitability policy — the hard half of SEC Reg BI / FINRA 2111.

  3. An LLM-as-judge pass for the things rules of thumb miss: language that
     reads as a specific recommendation, a performance guarantee, or a
     prediction. These implicate SEC suitability / fiduciary expectations and an
     advisor's books-and-records duties (Rule 204-2), so the judge flags them
     for a human rather than letting them go out.

Nothing here is legal advice; it is a guardrail that keeps the draft honest and
puts a human in the loop.
"""
from __future__ import annotations

import re

import compliance_mcp
import llm
from schemas import Citation, ComplianceFlag, ComplianceReport

# a citation looks like a source_id: no spaces, at least one hyphen,
# e.g. AAPL-FACT-total, MACRO-DGS10, AAPL-10K-2025-72. This deliberately does
# NOT match prose in brackets like "[No specific figures]" or "[Your Name]".
_CITE = re.compile(r"\[([A-Za-z0-9][\w&'.]*(?:-[\w&'.]+)+)\]")
# split on sentence-ending punctuation followed by whitespace, and on newlines.
# crucially this does NOT split a decimal like "5.28" (no space after the dot)
# or a source_id, so a number stays attached to its citation.
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# a real quantitative claim: a dollar amount, a percentage, or a 2+ digit
# number. A bare list ordinal like "1." is one digit and is NOT matched.
_QUANT = re.compile(r"\$\s?\d|\d(?:[.,]?\d)*\s?%|\b\d{2,}(?:[.,]\d+)*\b|\bpercent\b", re.I)


def referenced_ids(text: str) -> set[str]:
    return {m.strip() for m in _CITE.findall(text)}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text) if s.strip()]


def grounding_flags(text: str, evidence: list[Citation]) -> tuple[list[ComplianceFlag], list[str]]:
    """Deterministic: catch invalid citations and uncited numeric claims.

    Returns (flags, unsupported_sentences)."""
    valid = {c.source_id for c in evidence}
    flags: list[ComplianceFlag] = []
    unsupported: list[str] = []

    # citations that point at evidence we never retrieved = fabricated grounding
    for rid in referenced_ids(text):
        if rid not in valid:
            flags.append(
                ComplianceFlag(
                    severity="block",
                    rule="grounding / no fabricated sources",
                    quote=f"[{rid}]",
                    why="This citation points to a source that is not in the retrieved evidence.",
                    suggested_fix="Remove the claim or cite a real retrieved source.",
                )
            )

    # a sentence that states a real figure but carries no valid citation is unsupported
    for sent in _sentences(text):
        if _QUANT.search(sent) and not _CITE.search(sent):
            unsupported.append(sent)
            flags.append(
                ComplianceFlag(
                    severity="block",
                    rule="grounding / every figure cited",
                    quote=sent[:200],
                    why="States a figure or quantitative claim with no citation to retrieved evidence.",
                    suggested_fix="Attach a [source_id] from the evidence, or remove the figure.",
                )
            )
    return flags, unsupported


# verbs that turn "mentioning X" into "steering the client into X". A prohibited
# asset class only trips suitability when the draft proposes acquiring more of it.
_ACQUIRE = re.compile(
    r"\b(buy|buying|add(?:ing)?|increase|increasing|move|moving|shift(?:ing)?|"
    r"allocate|allocating|overweight|rotate|rotating|put more|load up|pile|boost)\b",
    re.I,
)


def suitability_flags(text: str, client_id: str) -> list[ComplianceFlag]:
    """Deterministic: block language that steers the client into a prohibited asset class.

    Reads the client's suitability policy through the MCP-style bridge and flags any
    sentence that pairs an acquisition verb with a forbidden asset class."""
    policy = compliance_mcp.suitability_for(client_id)
    if policy is None or not policy.prohibited:
        return []
    flags: list[ComplianceFlag] = []
    for sent in _sentences(text):
        low = sent.lower()
        if not _ACQUIRE.search(low):
            continue
        for term in policy.prohibited:
            if term.lower() in low:
                flags.append(
                    ComplianceFlag(
                        severity="block",
                        rule=f"SEC Reg BI / FINRA 2111 suitability ({policy.risk.split('.')[0]})",
                        quote=sent[:200],
                        why=f"Steers this client toward '{term}', which their suitability profile "
                        f"prohibits. {policy.rationale}",
                        suggested_fix="Remove this. If the client raised it, frame it as a question "
                        "to discuss, not a move to make.",
                    )
                )
                break  # one flag per sentence is enough
    return flags


_JUDGE_SYSTEM = (
    "You are a compliance reviewer at a US registered investment adviser. You read a "
    "draft an advisor plans to use with a client and you flag only three things:\n"
    "1. RECOMMENDATION: a specific instruction to buy, sell, add, trim, or move into a "
    "named security or asset (suitability / fiduciary concern).\n"
    "2. GUARANTEE: any promise or prediction about future performance, e.g. 'will "
    "outperform', 'is guaranteed', 'you will make'.\n"
    "3. ADVICE_AS_FACT: an opinion stated as certainty that a client could act on.\n"
    "Framing exposure, asking the client a question, or describing what a filing says is "
    "FINE and should NOT be flagged. Output one line per issue, nothing else:\n"
    "FLAG | <RECOMMENDATION|GUARANTEE|ADVICE_AS_FACT> | <exact sentence from the draft>\n"
    "If there is nothing to flag, output exactly: CLEAN"
)

_RULE_LABEL = {
    "RECOMMENDATION": "SEC suitability / fiduciary (specific recommendation)",
    "GUARANTEE": "No performance guarantees or predictions",
    "ADVICE_AS_FACT": "SEC suitability / fiduciary (opinion stated as fact)",
}


def judge_flags(text: str, meter: list | None = None) -> list[ComplianceFlag]:
    """LLM-as-judge pass for advice / guarantee language. Runs on the small tier."""
    out = llm.generate(_JUDGE_SYSTEM, text, temperature=0.0, tier="small", meter=meter)
    flags: list[ComplianceFlag] = []
    for line in out.splitlines():
        line = line.strip()
        if not line.upper().startswith("FLAG"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        kind = parts[1].upper()
        quote = parts[2].strip().strip('"')
        if not quote:
            continue
        flags.append(
            ComplianceFlag(
                severity="block",
                rule=_RULE_LABEL.get(kind, "SEC suitability / fiduciary"),
                quote=quote[:200],
                why="Reads as advice a client could act on; an advisor must review before it goes out.",
                suggested_fix="Reframe as a discussion point or a question for the client, not an instruction.",
            )
        )
    return flags


def review(
    text: str,
    evidence: list[Citation],
    client_id: str | None = None,
    meter: list | None = None,
) -> ComplianceReport:
    """Full compliance review of a draft: grounding + suitability + LLM judge."""
    g_flags, unsupported = grounding_flags(text, evidence)
    s_flags = suitability_flags(text, client_id) if client_id else []
    j_flags = judge_flags(text, meter=meter)
    flags = g_flags + s_flags + j_flags
    n_claims = len([s for s in _sentences(text) if _QUANT.search(s)])
    return ComplianceReport(
        passed=not any(f.severity == "block" for f in flags),
        flags=flags,
        unsupported_claims_removed=unsupported,
        checked_claims=n_claims,
    )
