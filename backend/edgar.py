"""A small SEC EDGAR client. Free, no key, but the SEC asks for two things:
a User-Agent that identifies you, and gentle request rates. We honor both.

Two kinds of evidence come out of here:
  - structured XBRL facts (revenue, net income, ...) -> exact numbers to cite
  - 10-K narrative text (risk factors, MD&A) -> context to retrieve against
"""
from __future__ import annotations

import html
import os
import re
import time

import requests

UA = os.environ.get("AB_SEC_UA", "advisor-brief research project (contact: sai.tata@example.com)")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}

# be a good citizen: the SEC asks for <= 10 requests/sec; we go much slower
_MIN_GAP = 0.25
_last_call = 0.0


def _get(url: str) -> requests.Response:
    global _last_call
    gap = time.time() - _last_call
    if gap < _MIN_GAP:
        time.sleep(_MIN_GAP - gap)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    _last_call = time.time()
    resp.raise_for_status()
    return resp


def cik_map() -> dict[str, str]:
    """ticker (upper) -> 10-digit zero-padded CIK, from the SEC's official map."""
    data = _get("https://www.sec.gov/files/company_tickers.json").json()
    out: dict[str, str] = {}
    for row in data.values():
        out[row["ticker"].upper()] = str(row["cik_str"]).zfill(10)
    return out


# each plain label can come from more than one XBRL tag (companies tag revenue
# differently). We gather all candidates and keep the most recent annual value.
_FACTS: dict[str, list[str]] = {
    "Total revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "Net income": ["NetIncomeLoss"],
    "Total assets": ["Assets"],
    "Total liabilities": ["Liabilities"],
    "Shareholders' equity": ["StockholdersEquity"],
    "R&D expense": ["ResearchAndDevelopmentExpense"],
    "Operating income": ["OperatingIncomeLoss"],
}


def latest_annual_facts(cik: str) -> list[dict]:
    """Most recent fiscal-year value for each fact we track, with a citation handle."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        facts = _get(url).json().get("facts", {}).get("us-gaap", {})
    except requests.HTTPError:
        return []
    out: list[dict] = []
    for label, tags in _FACTS.items():
        candidates = []
        for tag in tags:
            if tag not in facts:
                continue
            units = facts[tag].get("units", {}).get("USD", [])
            # full-year figures only (10-K annual: form 10-K, fp FY)
            candidates += [u for u in units if u.get("form") == "10-K" and u.get("fp") == "FY" and "val" in u]
        if not candidates:
            continue
        latest = max(candidates, key=lambda u: u.get("end", ""))
        out.append(
            {
                "label": label,
                "value": latest["val"],
                "fiscal_year": latest.get("fy"),
                "period_end": latest.get("end"),
                "accession": latest.get("accn"),
            }
        )
    return out


def _find_10k(block: dict, cik: str) -> tuple[str, str] | None:
    """Search one filings block (recent or an older page) for a 10-K document."""
    forms = block.get("form", [])
    for i, form in enumerate(forms):
        if form != "10-K":
            continue
        accession = block["accessionNumber"][i].replace("-", "")
        primary = block["primaryDocument"][i]
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{primary}"
        return url, block.get("filingDate", [""] * len(forms))[i]
    return None


def latest_10k_doc(cik: str) -> tuple[str, str] | None:
    """Return (text, source_url) for the most recent 10-K primary document.

    Big filers (XOM, etc.) push a lot of 8-Ks, so their 10-K can fall off the
    'recent' page. If it isn't there, we page into the older submission files.
    """
    sub = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    hit = _find_10k(sub.get("filings", {}).get("recent", {}), cik)
    if hit is None:
        for extra in sub.get("filings", {}).get("files", []):
            block = _get(f"https://data.sec.gov/submissions/{extra['name']}").json()
            hit = _find_10k(block, cik)
            if hit:
                break
    if hit is None:
        return None
    url, _ = hit
    return html_to_text(_get(url).text), url


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def html_to_text(raw: str) -> str:
    """Strip a filing's HTML to readable text without pulling in a parser dep."""
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.I)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", raw, flags=re.I)
    text = _TAG.sub(" ", raw)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()
