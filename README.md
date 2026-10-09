# advisor-brief

**Meeting prep for independent financial advisors. It helps them get ready, and a person always stays in the loop.**

An advisor picks a client and asks what they'd ask before a review meeting ("prep me for the Patels", "rates moved up, what should I flag about their bonds?"). They get back two things they can actually use: a **meeting brief** and a **draft email to the client**. Every number is linked to a real source. Nothing is phrased as a recommendation. A compliance layer refuses to send out an uncited number or any advice that hasn't been reviewed.

It runs on free, public data (SEC EDGAR, FRED, market prices) and open-weights models only.

---

## How this came about

I found the AI Engineer opening at TIFIN and liked it enough to dig into the company before I applied.

I went through what was online: Vinay Nair's posts and talks, the product pages, and the job description. A few things stuck with me. TIFIN wants AI to help the advisor, not take over from them, so the AI does the prep work and the advisor still makes the decisions. They also build for smaller advisors, the ones under $100M who most tools skip. And the job itself is about hard engineering work like multi-agent systems, retrieval, keeping the models compliant, and keeping costs down.

Then it clicked for me where the real difficulty is. Getting a model to write text is easy. The hard part is writing something an advisor can actually use and defend. Every number has to come from a real source. It can't cross into giving advice. And you need a record of how the answer was made. Most AI copilots I looked at don't really handle this.

So rather than send in one more application and hope, I built a small version of what the job asks for. advisor-brief takes a question about a client and writes meeting prep the advisor could use. On top of that sits a compliance layer that won't let an uncited number or a piece of advice go out. It's small on purpose, but it works, and it's built around the things I think TIFIN cares about most.

---

## Why this exists

Large language models get a lot of finance questions wrong, and the wealth industry can't put that in front of a client. The SEC exam priorities for 2025 to 2026 ask firms to **explain how an AI reached a decision**, and an AI-written note that gives an investment recommendation counts as a regulated record. Getting a model to produce text is easy. The hard part is producing text an advisor can stand behind, where every figure is grounded and cited and nothing crosses into advice.

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

1. **Grounding.** Every sentence with a number has to point to a real source we actually pulled. If a number has no source, or points to a source we never retrieved, we take it out. This is how "refuse instead of making things up" becomes something you can actually measure.
2. **Suitability.** If a draft tries to push a client toward something their profile says no to (say, a high-yield fund for a 71-year-old who needs steady income), the code blocks it. Each client has a simple, machine-readable list of what they can and can't hold. The guardrail reads that list through a small read-only bridge (`compliance_mcp.py`). This is the hard part of SEC Reg BI and FINRA 2111.
3. **A second model as a judge.** It flags wording that reads like a specific recommendation, a promise about future performance, or an opinion stated as fact. Those are the things that raise SEC suitability and recordkeeping concerns (Rule 204-2). Anything it flags goes back for one rewrite, then to a person.

Every request is then written to an append-only log (`audit.py`). Each entry has a timestamp, the client, the model versions, and SHA-256 hashes of the prompt and the output. Each entry is linked to the one before it with a hash. If anyone edits a past line, `GET /audit/verify` shows exactly where the chain breaks. It's write-once recordkeeping in spirit (Rule 204-2), without needing a database.

Turn the **compliance layer off** in the UI to watch the same model, with the same evidence, write a draft the layer would have caught. That side-by-side is the demo.

> **Where this is going:** the four designs this project is built around, and an honest look at the gaps between this demo and a real production build at TIFIN, are written up in [`docs/ARCHITECTURE_AND_ROADMAP.md`](docs/ARCHITECTURE_AND_ROADMAP.md). That's the conversation this repo is meant to start.

---

## Does the layer actually change the output?

Run `python backend/eval/evaluate.py`. It drafts the same set of advisor questions twice, once with the guardrails off and once on, and scores both.

<!-- EVAL:START (filled by eval/evaluate.py) -->
| guardrails | grounding rate | ungrounded claims | advice/guarantee flags |
|---|---|---|---|
| OFF | _run eval_ | _run eval_ | _run eval_ |
| ON  | _run eval_ | _run eval_ | _run eval_ |
<!-- EVAL:END -->

"Grounding rate" is the share of number claims that carry a valid citation. "Ungrounded claims" are figures with no citation, or citations to sources that were never pulled. The run also prints a **FinOps** line: total tokens and a rough cost for the guarded runs, with planning and judging on the small model and drafting and revising on the large one.

---

## Mapped to TIFIN

This was built to mirror how TIFIN talks about AI for wealth, and to exercise the skills in their AI Engineering role.

| What TIFIN / Vinay Nair emphasizes | Where it shows up here |
|---|---|
| "Decision support, not autonomous advice" | The judge blocks and flags advice language; output is for the advisor, never auto-sent |
| "Actionable intelligence," not just analysis | Output is a ready meeting brief and client email |
| The underserved sub-$100M advisor "no one has cracked" | The whole product is aimed there, and it's free to run |
| Verticalized, ontology-driven finance AI | A holdings→sector→macro-factor knowledge graph drives retrieval |
| "Productionizing AI" | A deployed, working app with an eval number attached |
| Multi-agent / ReAct / RAG + knowledge graph | The LangGraph loop |
| LLM-as-judge eval pipelines | The compliance layer plus `eval/evaluate.py` |
| Governance, guardrails, human in the loop | Citations, calibrated refusal, compliance flags |
| Deterministic compliance + MCP (§7.2) | Suitability blocking through an MCP-style bridge, plus a write-once audit chain |
| State contracts across agent hand-offs (§7.1) | A Pydantic `DraftContract` checked at each step, with a quick retry |
| Tool-calling RAG for fast-moving data (§7.3) | Vector "semantic memory" kept separate from real-time tool calls, run in parallel |
| Inference FinOps (§7.4) | A semantic cache, small and large model tiers, and per-request token and cost tracking |

---

## Stack

- **Data (free, no keys):** SEC EDGAR (10-K text and XBRL facts), FRED macro (public CSV endpoint), market prices via yfinance.
- **Retrieval:** a Chroma vector store with an on-device embedding model (no API key, deploys anywhere), plus a `networkx` ontology graph. The vector "semantic memory" (10-K text) is kept separate from the real-time structured lookups (facts, macro, prices), and the sources run in parallel. Set `AB_LIVE_DATA=1` to fetch macro and prices live, with the cached copy as a fallback.
- **Agent:** a LangGraph state machine, with Pydantic-typed state contracts and a quick retry at each draft hand-off.
- **Compliance:** grounding, suitability (through an MCP-style bridge), and a second model as a judge, backed by an append-only, hash-linked audit log.
- **Models (open-weights only):** two tiers for Inference FinOps. A small Llama (`llama-3.1-8b-instant`) handles planning and judging, and a large one (`llama-3.3-70b-versatile`) handles drafting. There's also a semantic cache for repeat questions. Local Llama 3 via Ollama for dev, Groq for the deployed demo. You can swap models with env vars.
- **Backend:** FastAPI. **Frontend:** React and Vite.

---

## Run it locally

```bash
# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python ingest.py                 # pulls filings/facts/macro/prices (one time, about 8 min)

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

The live demo has two pieces: the **FastAPI backend on [Render](https://render.com)** and the **React frontend on [Vercel](https://vercel.com)**.

- **Backend (Render):** click New +, then Blueprint, then pick this repo. Render reads `render.yaml`. Add a free `GROQ_API_KEY` ([console.groq.com/keys](https://console.groq.com/keys)) when prompted. The Chroma store is committed, so there's no ingest step. Health check: `/health`.
- **Frontend (Vercel):** import the repo, set the **Root Directory** to `frontend`, and add an env var `VITE_API_URL` set to your Render URL. Vercel detects Vite on its own (`npm run build` produces `dist/`).

The backend keeps state (Chroma plus on-device embeddings), so it runs on Render, not on Vercel's serverless functions. CORS allows any `*.vercel.app` origin out of the box.

## Tests

```bash
cd backend && python -m pytest tests/ -q
```

The tests cover the deterministic pieces the product's trust depends on: the grounding checks, the ontology graph, and filing-text extraction. They don't call a model.

---

## Honest limitations

- The demo universe is about 11 large, well-known holdings, so the filings are rich and easy to recognize. It is not all of EDGAR.
- Client portfolios are made up. There's no real client data, no auth, and no custody integration.
- Numbers from 10-K filings come from pulling exact XBRL facts, not from reading tables out of the HTML. That's a deliberate choice, and it's the hardest open problem in this space.
- This is a prototype and a decision-support tool. It is not investment advice.
