"""The compliance grounding checks are deterministic, so we can test them hard
without touching a model. These are the rules the product's credibility rests on."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas import Citation
import compliance


EV = [
    Citation(source_id="MACRO-DGS10", kind="macro", title="10y", snippet="5.28"),
    Citation(source_id="AAPL-FACT-total", kind="financial_fact", title="rev", snippet="$416B"),
    Citation(source_id="AAPL-10K-2025-3", kind="filing_text", title="risk", snippet="..."),
]


def _blocks(text):
    flags, _ = compliance.grounding_flags(text, EV)
    return len(flags)


def test_cited_numeric_claim_passes():
    assert _blocks("The 10-year Treasury yield is 5.28 [MACRO-DGS10].") == 0


def test_decimal_does_not_break_citation():
    # "5.28" must not be split away from its citation
    assert _blocks("Revenue was $416.2B [AAPL-FACT-total].") == 0


def test_uncited_number_blocks():
    assert _blocks("Rates rose to 5% this week.") >= 1


def test_fabricated_source_blocks():
    assert _blocks("Revenue hit $416B [AAPL-FACT-madeup].") >= 1


def test_list_ordinal_is_not_a_claim():
    assert _blocks("1. Discuss tech exposure.\n2. Discuss bonds.") == 0


def test_prose_bracket_is_not_a_citation():
    assert compliance.referenced_ids("[No specific figures or citations]") == set()
    assert _blocks("We should review the plan together.") == 0


def test_referenced_ids_extracts_real_sources():
    ids = compliance.referenced_ids("See [AAPL-FACT-total] and [MACRO-DGS10].")
    assert ids == {"AAPL-FACT-total", "MACRO-DGS10"}


def test_quant_claim_counting():
    # counts quantitative sentences only (no LLM involved)
    text = "Yield is 5.28 [MACRO-DGS10]. We will talk it through."
    claims = [s for s in compliance._sentences(text) if compliance._QUANT.search(s)]
    assert len(claims) == 1
