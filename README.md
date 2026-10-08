# advisor-brief

**Grounded meeting prep for the independent financial advisor — decision support with a human in the loop.**

An advisor picks a client, asks what they'd ask before a review meeting ("prep me for the Patels", "rates moved up, what do I flag about their bond sleeve?"), and gets back two things they can actually use: a **meeting brief** and a **client email draft**. Every figure is cited to a real source. Nothing is a recommendation. A compliance layer refuses to ship an uncited number or an unreviewed piece of advice.

It runs on free, public data (SEC EDGAR, FRED, market prices) and open-weights models only.

---

## Why this exists

Large language models hallucinate on a large share of finance questions, and the wealth industry can't put that in front of a client. The 2025–2026 SEC exam priorities ask firms to **explain how an AI reached a decision**; an AI-written note that contains an investment recommendation is a regulated record. So the hard part of AI in wealth isn't generating text, it's generating text an advisor can defend: grounded, cited, and free of language that crosses into advice.

Most "AI copilots" skip that part. `advisor-brief` is built entirely around it.

---

## What it does

```
            client household + the advisor's question
                              │
         ┌────────────────────▼─────────────────────┐
         │  LangGraph agent (a small ReAct-style loop)│
         │                                           │
         │  retrieve → plan → draft → review → revise │
         │                                           │
         │  retrieve : 10-K text (vector search) +    │
         │             XBRL facts + FRED macro +      │
         │             prices, chosen by walking a    │
         │             holdings→sector→factor graph   │
         │  draft    : meeting brief + client email,  │
         │             every fact cited [source_id]   │
         │  review   : compliance layer (below)       │
         │  revise   : one pass to clear blocking flags│
         └────────────────────┬─────────────────────┘
                              │
          brief + email + citations + compliance report
```

### The compliance layer (the point)

Three checks run on every draft:

1. **Deterministic grounding.** Every quantitative sentence must carry a `[source_id]` that exists in the retrieved evidence. A number with no citation, or a citation to something we never retrieved, is pulled. This is what makes "refuse instead of hallucinate" real and measurable rather than a slogan.
2. **Deterministic suitability.** A draft that steers the client *into* an asset class their profile forbids (high-yield to an income-first 71-year-old, say) is blocked by code. The forbidden classes come from each client's machine-readable suitability policy, read through a read-only **MCP-style bridge** (`compliance_mcp.py`) — the hard half of SEC Reg BI / FINRA 2111.
3. **LLM-as-judge.** A second model pass flags language that reads as a specific recommendation, a performance guarantee, or an opinion stated as fact — the things that implicate SEC suitability / fiduciary expectations and an advisor's books-and-records duties (Rule 204-2). Flagged lines go back for one revision, then to a human.

Every request is then written to a **hash-chained, append-only audit log** (`audit.py`): timestamp, client, model versions, and SHA-256 hashes of the prompt and output, each linked to the previous record. Tamper with any past line and `GET /audit/verify` reports where the chain breaks — WORM recordkeeping in spirit (Rule 204-2) without a database.

Flip the **compliance layer off** in the UI to see the same model, same evidence, produce a draft the layer would have caught. That contrast is the demo.

> **Where this is going:** the four architectures this project embodies — and the honest gaps between the demo and a production build at TIFIN — are written up in [`docs/ARCHITECTURE_AND_ROADMAP.md`](docs/ARCHITECTURE_AND_ROADMAP.md). That's the conversation this repo is meant to start.

---

## Does the layer actually change the output?

`python backend/eval/evaluate.py` drafts a fixed set of advisor questions twice — guardrails off vs on — and scores both.

<!-- EVAL:START (filled by eval/evaluate.py) -->
| guardrails | grounding rate | ungrounded claims | advice/guarantee flags |
|---|---|---|---|
| OFF | _run eval_ | _run eval_ | _run eval_ |
| ON  | _run eval_ | _run eval_ | _run eval_ |
<!-- EVAL:END -->

"Grounding rate" is the share of quantitative claims that carry a valid citation. "Ungrounded claims" are figures with no citation or citations to sources that were never retrieved. The run also prints a **FinOps** line — total tokens and illustrative cost for the guarded runs, with planning/judging on the small model tier and drafting/revising on the large one.

---

## Mapped to TIFIN

This was built to mirror how TIFIN talks about AI for wealth, and to exercise the skills in their AI Engineering role.

| What TIFIN / Vinay Nair emphasizes | Where it shows up here |
|---|---|
| "Decision support, not autonomous advice" | The judge blocks/flags advice language; output is advisor-facing, never auto-sent |
| "Actionable intelligence," not just analysis | Output is a ready meeting brief + client email |
| The underserved sub-$100M advisor "no one has cracked" | The whole product is aimed there; free to run |
| Verticalized / ontology-driven finance AI | A holdings→sector→macro-factor knowledge graph drives retrieval |
| "Productionizing AI" | A deployed, working app with an eval number attached |
| Multi-agent / ReAct / RAG + knowledge graph | The LangGraph loop |
| LLM-as-judge eval pipelines | The compliance layer + `eval/evaluate.py` |
| Governance / guardrails / human-in-the-loop | Citations, calibrated refusal, compliance flags |
| Deterministic compliance + MCP (§7.2) | Suitability blocking via an MCP-style bridge + a WORM audit chain |
| State contracts across agent hand-offs (§7.1) | Pydantic `DraftContract` validated at each node, with a localized retry |
| Tool-calling RAG for high-velocity data (§7.3) | Vector "semantic memory" split from real-time tool calls, fanned out in parallel |
| Inference FinOps (§7.4) | Semantic cache + small/large model tiering + per-request token/cost metering |

---

## Stack

- **Data (free, no keys):** SEC EDGAR (10-K text + XBRL facts), FRED macro (public CSV endpoint), market prices via yfinance.
- **Retrieval:** Chroma vector store with an on-device embedding model (no API key, deploys anywhere) + a `networkx` ontology graph. Vector "semantic memory" (10-K text) is split from real-time structured tool calls (facts/macro/prices), fanned out in parallel; `AB_LIVE_DATA=1` fetches macro/prices live with cached fallback.
- **Agent:** LangGraph state machine, Pydantic-typed state contracts with a localized retry at each draft hand-off.
- **Compliance:** deterministic grounding + suitability (via an MCP-style bridge) + an LLM judge, with a hash-chained append-only audit log.
- **Models (open-weights only):** two tiers for Inference FinOps — a small Llama (`llama-3.1-8b-instant`) for planning/judging, a large one (`llama-3.3-70b-versatile`) for drafting — plus a semantic cache for repeat questions. Local Llama 3 via Ollama for dev; Groq for the deployed demo. Swappable with env vars.
- **Backend:** FastAPI. **Frontend:** React + Vite.

---

## Run it locally

```bash
# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python ingest.py                 # pulls filings/facts/macro/prices (one time, ~8 min)

# generation: either local Ollama...
ollama pull llama3
# ...or Groq (faster, better): put GROQ_API_KEY in backend/.env
uvicorn main:app --reload --port 8000

# 2. frontend (another terminal)
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

## Deploy

The live demo is two pieces: the **FastAPI backend on [Render](https://render.com)**
and the **React frontend on [Vercel](https://vercel.com)**.

- **Backend (Render):** New + → *Blueprint* → pick this repo; Render reads `render.yaml`.
  Add a free `GROQ_API_KEY` ([console.groq.com/keys](https://console.groq.com/keys)) when
  prompted. The Chroma store is committed, so there's no ingest step. Health check: `/health`.
- **Frontend (Vercel):** import the repo, set **Root Directory** to `frontend`, and add an
  env var `VITE_API_URL` = your Render URL. Vercel auto-detects Vite (`npm run build` → `dist/`).

The backend is a stateful container (Chroma + on-device embeddings), so it runs on Render, not
Vercel's serverless functions. CORS allows any `*.vercel.app` origin out of the box.

## Tests

```bash
cd backend && python -m pytest tests/ -q
```

The tests cover the deterministic pieces the product's trust depends on: the grounding checks, the ontology graph, and filing-text extraction. They don't call a model.

---

## Honest limitations

- The demo universe is ~11 large, well-known holdings so the filings are rich and recognizable. It is not all of EDGAR.
- Client portfolios are synthetic. No real client data, auth, or custody integration.
- 10-K table/numeric reasoning is handled by pulling exact XBRL facts, not by reading tables out of the HTML — that's a deliberate scope choice, and the hardest open problem in the space.
- This is a prototype and decision-support tool. It is not investment advice.
