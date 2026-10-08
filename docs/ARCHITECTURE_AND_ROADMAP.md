# advisor-brief — architecture, pain points, and a roadmap for TIFIN

This project is a small, working advisor copilot. It exists to be a **concrete
conversation starter**, not a finished product. The research note in this folder
(*TIFIN Boulder Culture Analysis & AI Optimization Pitch Strategy*) ends with four
architectural pitches for a Senior/Staff AI Engineering role. This document tracks
each one against what `advisor-brief` actually does today, where the honest gaps
are, and how I'd take it to production inside TIFIN's stack.

A deliberate constraint runs through everything: `advisor-brief` uses **only free,
keyless, open-weights infrastructure** (Chroma + Llama via Groq/Ollama, SEC EDGAR /
FRED / yfinance). So I adapted the doc's *patterns* rather than its literal paid
stack (PGVector + GPT-4o/Claude). Where that trade-off matters, I call it out.

> TL;DR of what's built vs. discussed:
> | § | Pattern | In this repo | Depth |
> |---|---|---|---|
> | 7.1 | Dual-engine orchestrator (state contracts) | `agent.py`, `schemas.py` | **built** |
> | 7.2 | Deterministic compliance guardrail + WORM audit | `compliance.py`, `compliance_mcp.py`, `audit.py` | **built** |
> | 7.3 | Tool-calling agentic RAG | `retrieve.py` | **built (demo-scale)** |
> | 7.4 | Inference FinOps semantic router | `router.py`, `llm.py` | **built (demo-scale)** |

---

## §7.1 — Dual-Engine Sovereign Orchestrator (state degradation)

**The pain point.** Multi-agent workflows degrade across long horizons: one node's
small hallucination becomes the next node's trusted input, and LangGraph passes node
output straight to the next node by default, so the error propagates silently. The
doc's fix: keep LangGraph as a *deterministic* state machine and validate every
hand-off against a rigid Pydantic "state contract," retrying locally on a
`ValidationError` instead of letting bad state advance.

**What advisor-brief does today.** The agent is a real LangGraph `StateGraph`
(`agent.py:build_graph`) with deterministic, Python-governed edges — the only branch
is `_route()`, plain conditional logic, never the LLM deciding its own next hop. The
writer and reviser nodes now enforce a `DraftContract` (`schemas.py`) at the node
boundary: if the generated draft doesn't parse (empty brief, missing email), the node
does **one localized retry** with a corrective instruction before the state is allowed
to advance (`agent.py:_draft_with_contract`). Every state value is a typed Pydantic
model, so nothing crosses an edge as a loose string.

**The gap / why not full production.**
- It's a **single-agent** graph, not true multi-agent delegation. There are no
  independent agents handing off across constituencies (advisor-support → entity →
  client), which is where state degradation actually bites at TIFIN scale.
- The contract checks *shape*, not *semantics* — it can't yet assert "liquidity
  horizon is a positive integer consistent with the client's profile."
- No durable checkpointing / resume; a crashed run restarts.

**How I'd productionize it at TIFIN.**
- Promote each node to a Pydantic-AI agent with its own typed input/output contract,
  and make the contract carry **permissions and ethical walls as fields**, so an agent
  structurally cannot read state it isn't entitled to.
- Add LangGraph durable checkpoints (Postgres saver) for resumable long-horizon runs
  and human-in-the-loop interrupts at compliance gates.
- Escalate the retry: localized re-prompt → model-tier bump → human interrupt, with the
  retry budget itself a typed, audited field.

---

## §7.2 — Deterministic Compliance Guardrail (SEC/FINRA liability)

**The pain point.** LLMs are probabilistic; SEC Reg BI and FINRA 2111/3110 demand
deterministic, *documented* accuracy. Prompt-engineering a model to "act as a
fiduciary" is legally insufficient. The doc's fix: a terminal guardrail node that
(a) classifies non-compliant language with a false-negative-averse model, (b)
programmatically blocks output that violates a client's hardcoded suitability
thresholds pulled over a read-only MCP bridge, and (c) writes a tamper-proof WORM
audit record (prompt, output, model version, timestamp).

**What advisor-brief does today.** This is the project's centerpiece — three layers in
`compliance.py`:
1. **Deterministic grounding.** Every quantitative sentence must carry a `[source_id]`
   that exists in the retrieved evidence; an uncited figure or a fabricated citation is
   blocked by regex, not judgment (`grounding_flags`). This is measured by the eval.
2. **Deterministic suitability.** `suitability_flags` reads each client's machine-
   readable policy (max equity %, max single position %, prohibited asset classes)
   through an **MCP-style read-only bridge** (`compliance_mcp.py`) and blocks any draft
   that steers the client *into* a prohibited class — e.g. a high-yield bond fund for
   an income-first 71-year-old. The same sentence passes for an aggressive young client:
   suitability is per-profile, by code.
3. **LLM-as-judge.** A small-model pass flags recommendation / guarantee / advice-as-
   fact language the rules miss (`judge_flags`).
Every `/ask` then appends a record to a **hash-chained, append-only audit log**
(`audit.py`): timestamp, client, model versions, and SHA-256 hashes of the prompt and
output, each linked to the previous record's hash. Edit, reorder, or delete any past
line and `GET /audit/verify` reports exactly where the chain breaks. It's WORM in
spirit without a database.

**The gap / why not full production.**
- The MCP bridge is an **in-process module**, not a real hosted MCP server; it reads a
  dict in `clients.py`, not a firm's compliance system of record.
- Suitability matching is keyword+verb based, so it catches "add a high-yield fund" but
  not an obfuscated paraphrase; the LLM judge is the backstop, but it's not the
  inverse-class-weighted classifier the doc describes.
- The audit log is a local JSONL file, not WORM Postgres / S3 Object Lock, and isn't
  written from a telemetry span.

**How I'd productionize it at TIFIN.**
- Stand up a genuine **read-only MCP compliance server** over the firm's suitability
  DB (the Truthifi / FINTRX pattern). The guardrail code upstream wouldn't change —
  `compliance_mcp.suitability_for()` already is the contract.
- Replace the keyword rule with a **fine-tuned small classifier using inverse class
  weighting** (per TIFIN India's claim-verification work) so false negatives on
  violations are punished hardest, and pair it with structured threshold checks against
  the client's live portfolio.
- Move the audit chain into **WORM Postgres (or S3 Object Lock)** written from an
  **OpenTelemetry** span, preserving the hash-chain property for defensible
  recordkeeping under Rule 204-2.

---

## §7.3 — Tool-Calling Agentic RAG (high-velocity data)

**The pain point.** Vector RAG is great for static narrative text and wrong for
high-velocity tabular data: by the time a tick is embedded and indexed, the price is
stale, and models get "lost in the middle" of numeric context. The doc's fix: split
the agent's memory — semantic (vector) for narrative, deterministic **tool calls** for
real-time numbers — and fan out / join in parallel.

**What advisor-brief does today.** `retrieve.py` makes the split explicit. **Semantic
memory** (Chroma vector search) serves only 10-K narrative chunks. **Structured /
real-time tool calls** serve XBRL facts, FRED macro, and prices as direct lookups that
never touch an embedding. The four sources **fan out in parallel** (`ThreadPoolExecutor`)
and join. Setting `AB_LIVE_DATA=1` switches macro/prices to a **request-time live fetch**
via `market.py`, with automatic fallback to the cached snapshot — the "bypass the vector
store for live tabular data" path, made real and offline-safe.

**The gap / why not full production.**
- The default demo reads **cached snapshots**, not a live market feed; live mode uses
  free endpoints (FRED CSV, yfinance), not an institutional feed.
- The parallel fan-out is in-process threads, not LangGraph parallel branches with a
  real join node.
- The universe is ~11 large-cap names so filings are rich and recognizable.

**How I'd productionize it at TIFIN.**
- Make real-time data genuine Pydantic-AI **tool calls** against Morningstar / FactSet,
  invoked from LangGraph parallel branches with a typed join node.
- Keep PGVector for the semantic half (the doc's choice) and treat tabular data as
  tools, never embeddings — exactly the bifurcation above, at firm scale.
- Add a freshness contract: real-time tool results carry an `as_of` field the guardrail
  can reject if stale.

---

## §7.4 — Inference FinOps Semantic Router (token economics)

**The pain point.** Routing every query through a frontier model — even "what's this
stock's price" — burns tokens and latency and compresses margin as a free-tier user
base grows. The doc's fix: a semantic cache for repeats, a small/local model for simple
tasks, and frontier models only for genuinely hard reasoning.

**What advisor-brief does today.** `router.py` + `llm.py` implement both halves,
adapted to open weights. **Tiered routing**: planning and the compliance judge run on a
small model (`llama-3.1-8b-instant`); drafting and revising run on the large one
(`llama-3.3-70b-versatile`) — `tier_for(task)` is the policy, and `llm.generate(tier=…)`
picks the model. **Semantic cache**: a Chroma collection embeds `(client, question)`
with the same on-device MiniLM model, and a sufficiently similar prior question for the
same client + guardrail setting returns the stored answer at zero token cost. Every run
reports a **FinOps summary** (tokens in/out, illustrative cost, small/large call mix,
cache hit) surfaced in the UI, the API response, and the eval.

**The gap / why not full production.**
- The "frontier" tier is still open-weights (70B), not GPT-4o/Claude; there's no third
  escalation tier for the hardest reasoning.
- Cost figures use **illustrative** per-token rates, clearly labeled — they prove cost
  is *measurable*, not that they're TIFIN's real numbers.
- The semantic cache has no TTL / invalidation when underlying data changes; fine for a
  demo, unsafe for live prices.

**How I'd productionize it at TIFIN.**
- Three tiers: semantic cache → **FinBloom-7B** (the doc's domain model) for routine
  financial tasks → frontier model for complex multi-step reasoning (tax-loss
  harvesting, portfolio optimization).
- A fine-tuned Stella-400M router embedding for the cache + intent classification, with
  **cache invalidation keyed to the freshness of the evidence** a cached answer relied
  on.
- Per-tenant FinOps dashboards from the same meter, so margin is observable as the
  free-advisor data-lake strategy scales.

---

## Open questions I'd want to discuss with TIFIN

1. **State hand-offs:** where does multi-agent state degradation actually hurt most in
   AXIS today — onboarding, ACAT transfers, meeting prep? That's where typed state
   contracts pay off first.
2. **Compliance surface:** is the deterministic guardrail better placed as a terminal
   node (as here) or as a sidecar every node consults? How is the suitability system of
   record exposed — is an internal MCP server already the plan?
3. **Recordkeeping:** what's the current answer to "reconstruct exactly what the model
   saw and produced" for an SEC exam? Hash-chained WORM vs. append-only Postgres vs.
   a vendor?
4. **FinOps:** is FinBloom-7B serving in production yet, and what share of traffic could
   a semantic cache realistically absorb for repeat advisor questions?
5. **Data velocity:** which real-time feeds are in scope, and where's the line between
   "embed it" and "call it as a tool"?

## Known limitations (same as the README, restated honestly)

Synthetic clients; no auth / custody / real PII; ~11-name universe; 10-K numerics come
from exact XBRL facts, not from reading HTML tables (the genuinely hard open problem);
open-weights models only. This is decision-support scaffolding to argue from, not
investment advice.
