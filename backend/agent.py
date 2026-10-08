r"""The advisor copilot, as a small LangGraph state machine so every step is visible:

    retrieve -> plan -> draft -> review --(blocked, 1st time)--> revise -> review
                                   \--(clean or out of tries)--> assemble -> END

retrieve  gathers grounded evidence (filings, facts, macro, prices)
plan      decides what the brief should cover for this client + question
draft     writes the meeting brief + client email, citing [source_id] for every fact
review    runs the compliance layer (grounding + LLM-as-judge)
revise    rewrites once to clear blocking flags
assemble  packages the deliverable + compliance report

The point of the shape: decision support, with a human-in-the-loop guardrail that
refuses to ship an uncited number or an unreviewed recommendation.
"""
from __future__ import annotations

import re
from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

import clients
import compliance
import llm
import retrieve
import router
from schemas import AskResult, Citation, ComplianceReport, Deliverable, DraftContract, FinOps

MAX_REVISIONS = 1


class State(TypedDict, total=False):
    client_id: str
    question: str
    client_summary: str
    evidence: list[Citation]
    plan: str
    brief: str
    email: str
    report: ComplianceReport
    revisions: int
    enforce: bool
    steps: list[dict]
    meter: list[dict]


def _step(state: State, title: str, detail: str, **extra) -> None:
    state.setdefault("steps", []).append({"title": title, "detail": detail, **extra})


def _evidence_block(evidence: list[Citation]) -> str:
    return "\n".join(f"[{c.source_id}] {c.title} — {c.snippet}" for c in evidence)


def _split_draft(text: str) -> tuple[str, str]:
    brief, email = text, ""
    m = re.search(r"===\s*EMAIL\s*===", text, re.I)
    if m:
        brief = re.sub(r"===\s*BRIEF\s*===", "", text[: m.start()], flags=re.I).strip()
        email = text[m.end() :].strip()
    return brief.strip(), email.strip()


_CONTRACT_REMINDER = (
    "\n\nYour previous output was rejected because it did not contain both a non-empty "
    "=== BRIEF === section and a non-empty === EMAIL === section. Produce both now, in "
    "that exact structure, using only the evidence provided."
)


def _draft_with_contract(system: str, user: str, state: State, label: str) -> tuple[str, str]:
    """Generate a brief+email and enforce the §7.1 DraftContract at the node boundary.

    If the split output fails to validate (empty brief or missing email), do one
    localized, inexpensive retry before letting the state advance — the doc's
    "ValidationError -> localized retry" pattern, scoped to this node."""
    meter = state.get("meter")
    text = llm.generate(system, user, temperature=0.2, tier="large", meter=meter)
    brief, email = _split_draft(text)
    try:
        DraftContract(meeting_brief=brief, client_email=email)
    except ValidationError:
        _step(state, f"{label}: state-contract retry",
              "Draft failed its state contract (missing brief or email); retried once.")
        text = llm.generate(system, user + _CONTRACT_REMINDER, temperature=0.1,
                            tier="large", meter=meter)
        brief, email = _split_draft(text)
    return brief, email


# ---- nodes ----

def retrieve_node(state: State) -> State:
    evidence = retrieve.evidence_pack(state["client_id"], state["question"])
    _step(state, "Retrieve evidence",
          f"Fanned out in parallel: 10-K text from semantic memory (vector) + XBRL facts, "
          f"macro, and prices as structured tool calls. {len(evidence)} grounded items.",
          sources=[c.source_id for c in evidence])
    return {"evidence": evidence, "revisions": 0}


def plan_node(state: State) -> State:
    system = (
        "You are a financial advisor's assistant. Given a client and a question, "
        "write a SHORT plan (2-4 bullet points) for what the meeting brief should "
        "cover. No advice, just what to address."
    )
    user = f"Client: {state['client_summary']}\n\nQuestion: {state['question']}"
    plan = llm.generate(system, user, temperature=0.1, tier="small", meter=state.get("meter"))
    _step(state, "Plan the brief", plan)
    return {"plan": plan}


_WRITER_SYSTEM = (
    "You are a financial advisor's assistant preparing material the advisor will "
    "review before any client sees it.\n"
    "Write TWO things, separated exactly like this:\n"
    "=== BRIEF ===\n(a meeting-prep brief for the advisor, plain and skimmable)\n"
    "=== EMAIL ===\n(a short, warm client email the advisor can adapt)\n\n"
    "Hard rules:\n"
    "- Use ONLY the evidence provided. Do not add facts, numbers, or company details "
    "from your own knowledge.\n"
    "- Every factual or numeric statement MUST end with a citation in square brackets "
    "whose text is a source_id copied EXACTLY from the evidence list, e.g.:\n"
    "    The 10-year Treasury yield is 5.28 [MACRO-DGS10].\n"
    "    Apple's FY2025 revenue was $416.2B [AAPL-FACT-total].\n"
    "- Use only source_ids that appear in the evidence. Never invent a source_id and "
    "never write a placeholder like [citation needed] or [Your Name].\n"
    "- If you don't have evidence for a point, leave the point out. Do not guess.\n"
    "- Do NOT tell the client to buy, sell, add, or trim anything. Do NOT predict or "
    "guarantee performance. Frame choices as discussion points and questions.\n"
    "- Write like a person: short sentences, no hype, no jargon for its own sake."
)


def draft_node(state: State) -> State:
    user = (
        f"Client: {state['client_summary']}\n\n"
        f"Question: {state['question']}\n\n"
        f"Plan: {state['plan']}\n\n"
        f"Evidence you may use (cite by [source_id]):\n{_evidence_block(state['evidence'])}"
    )
    brief, email = _draft_with_contract(_WRITER_SYSTEM, user, state, "Draft brief + email")
    _step(state, "Draft brief + email", brief[:600] + ("..." if len(brief) > 600 else ""))
    return {"brief": brief, "email": email}


def review_node(state: State) -> State:
    combined = state["brief"] + "\n\n" + state["email"]
    report = compliance.review(combined, state["evidence"],
                               client_id=state.get("client_id"), meter=state.get("meter"))
    blocks = [f for f in report.flags if f.severity == "block"]
    detail = "Clean — no blocking issues." if report.passed else \
        f"{len(blocks)} blocking issue(s): " + "; ".join(f.rule for f in blocks[:4])
    _step(state, "Compliance review", detail,
          passed=report.passed, flags=[f.model_dump() for f in report.flags])
    return {"report": report}


def _route(state: State) -> str:
    # unguarded mode: run the review so we can show what it WOULD catch, but
    # never revise — ship the raw draft alongside the flags
    if not state.get("enforce", True):
        return "clean"
    if state["report"].passed:
        return "clean"
    if state.get("revisions", 0) >= MAX_REVISIONS:
        return "giveup"
    return "revise"


_REVISE_SYSTEM = (
    "Revise the advisor's draft to clear the compliance flags below. Remove or reframe "
    "the exact sentences flagged: pull any figure that has no citation, delete citations "
    "to sources that don't exist, and turn any recommendation or performance promise into "
    "a neutral discussion point or a question for the client. Keep the rest intact and keep "
    "the same === BRIEF === / === EMAIL === structure. Use only the evidence provided."
)


def revise_node(state: State) -> State:
    flags = "\n".join(f"- [{f.severity}] {f.rule}: \"{f.quote}\" -> {f.suggested_fix}"
                      for f in state["report"].flags)
    user = (
        f"Flags to clear:\n{flags}\n\n"
        f"Evidence you may use:\n{_evidence_block(state['evidence'])}\n\n"
        f"Current draft:\n=== BRIEF ===\n{state['brief']}\n=== EMAIL ===\n{state['email']}"
    )
    brief, email = _draft_with_contract(_REVISE_SYSTEM, user, state, "Revise to clear flags")
    _step(state, "Revise to clear flags", "Rewrote flagged lines and re-checked.")
    return {"brief": brief, "email": email, "revisions": state.get("revisions", 0) + 1}


def assemble_node(state: State) -> State:
    # attach only the evidence the final draft actually leans on
    used_ids = compliance.referenced_ids(state["brief"] + " " + state["email"])
    cited = [c for c in state["evidence"] if c.source_id in used_ids]
    _step(state, "Assemble deliverable",
          f"{len(cited)} sources cited; compliance {'passed' if state['report'].passed else 'flagged for review'}.")
    return {"evidence": cited}  # narrow evidence to what was cited for the response


def build_graph():
    g = StateGraph(State)
    for name, fn in [
        ("retrieve", retrieve_node), ("plan", plan_node), ("draft", draft_node),
        ("review", review_node), ("revise", revise_node), ("assemble", assemble_node),
    ]:
        g.add_node(name, fn)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "plan")
    g.add_edge("plan", "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", _route,
                            {"revise": "revise", "clean": "assemble", "giveup": "assemble"})
    g.add_edge("revise", "review")
    g.add_edge("assemble", END)
    return g.compile()


_graph = None


def _finops_from_meter(meter: list[dict], cache_hit: bool = False) -> FinOps:
    if cache_hit:
        return FinOps(cache_hit=True, note="Served from the semantic cache — zero tokens, sub-ms.")
    return FinOps(
        cache_hit=False,
        tokens_in=sum(c.get("in", 0) for c in meter),
        tokens_out=sum(c.get("out", 0) for c in meter),
        est_cost_usd=router.estimate_cost(meter),
        calls=meter,
    )


def ask(client_id: str, question: str, enforce: bool = True, use_cache: bool = True) -> AskResult:
    global _graph
    if _graph is None:
        _graph = build_graph()

    client = clients.get(client_id)
    if client is None:
        raise ValueError(f"unknown client: {client_id}")

    # §7.4: serve a semantically-matching prior answer before spending any tokens
    if use_cache:
        cached = router.cache_get(client_id, question, enforce)
        if cached is not None:
            result = AskResult.model_validate(cached)
            result.finops = _finops_from_meter([], cache_hit=True)
            return result

    meter: list[dict] = []
    final = _graph.invoke(
        {
            "client_id": client_id,
            "question": question,
            "client_summary": clients.summary(client),
            "enforce": enforce,
            "steps": [],
            "meter": meter,
        },
        {"recursion_limit": 25},
    )

    report: ComplianceReport = final["report"]
    # if nothing grounded came back, be honest rather than creative
    if not final.get("evidence") and not report.flags:
        report.refused = True
        report.refusal_reason = "No grounded evidence was found for this client and question."

    # read the meter back from final state: LangGraph may hand nodes a copy of
    # the initial state, so the list the nodes actually appended to lives there.
    meter = final.get("meter", meter) or meter
    finops = _finops_from_meter(meter)
    _step(final, "FinOps",
          f"{finops.tokens_in + finops.tokens_out} tokens across {len(meter)} call(s); "
          f"~${finops.est_cost_usd:.5f} (illustrative).")

    result = AskResult(
        client_id=client_id,
        question=question,
        deliverable=Deliverable(
            meeting_brief=final.get("brief", ""),
            client_email=final.get("email", ""),
            citations=final.get("evidence", []),
        ),
        compliance=report,
        steps=final.get("steps", []),
        finops=finops,
    )
    if use_cache:
        router.cache_put(client_id, question, enforce, result.model_dump())
    return result
