import React, { useEffect, useMemo, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const EXAMPLES = [
  "Prep me for our review meeting.",
  "Rates moved up this week. What should I flag about their tech and bond exposure?",
  "They asked whether they hold too much in tech. How should I frame that?",
  "What did their largest holding say about risk in its latest filing?",
];

const CITE_RE = /\[([A-Za-z0-9][\w&'.]*(?:-[\w&'.]+)+)\]/g;

// render a block of text with **bold** and [source_id] citation pills intact
function renderRich(text, citeMap, onJump) {
  const lines = text.split("\n");
  return lines.map((line, li) => {
    const nodes = [];
    let last = 0;
    const combined = new RegExp(`\\*\\*(.+?)\\*\\*|${CITE_RE.source}`, "g");
    let m;
    let key = 0;
    while ((m = combined.exec(line))) {
      if (m.index > last) nodes.push(line.slice(last, m.index));
      if (m[1] !== undefined) {
        nodes.push(<strong key={key++}>{m[1]}</strong>);
      } else {
        const id = m[2];
        const known = citeMap[id];
        nodes.push(
          <a
            key={key++}
            className="cite"
            href={known?.url || `#src-${id}`}
            target={known?.url ? "_blank" : undefined}
            rel="noreferrer"
            title={known ? known.title : id}
            onClick={(e) => {
              if (!known?.url) {
                e.preventDefault();
                onJump(id);
              }
            }}
          >
            {id}
          </a>
        );
      }
      last = combined.lastIndex;
    }
    if (last < line.length) nodes.push(line.slice(last));
    return (
      <div key={li} style={{ minHeight: line.trim() ? undefined : "0.7em" }}>
        {nodes}
      </div>
    );
  });
}

export default function App() {
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState(null);
  const [question, setQuestion] = useState("");
  const [guardrails, setGuardrails] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const srcRefs = useRef({});

  useEffect(() => {
    fetch(`${API}/clients`)
      .then((r) => r.json())
      .then((d) => {
        setClients(d.clients || []);
        if (d.clients?.length) setClientId(d.clients[0].id);
      })
      .catch(() => setError("Can't reach the backend. Is it running on " + API + "?"));
  }, []);

  const citeMap = useMemo(() => {
    const m = {};
    (result?.deliverable?.citations || []).forEach((c) => (m[c.source_id] = c));
    return m;
  }, [result]);

  async function run() {
    if (!clientId || !question.trim()) return;
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const r = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId, question, guardrails }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "request failed");
      setResult(await r.json());
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  function jumpTo(id) {
    const el = srcRefs.current[id];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.style.background = "var(--pine-soft)";
      setTimeout(() => (el.style.background = ""), 1200);
    }
  }

  const comp = result?.compliance;
  const stampClass = !guardrails ? "off" : comp?.passed ? "cleared" : "hold";
  const stampText = !guardrails ? "Guardrails off" : comp?.passed ? "Cleared" : "Hold — review";

  return (
    <div className="wrap">
      <header className="masthead">
        <div>
          <h1>advisor&#8203;-brief<span className="dot">.</span></h1>
          <div className="sub">Grounded meeting prep for the independent advisor</div>
        </div>
        <div className="colophon">
          Every figure traces to a <b>source</b>. Nothing is a recommendation.
          <br />
          Decision support, with a human in the loop.
        </div>
      </header>
      <div className="ruleline" />

      <section className="setup">
        <div>
          <div className="label">01 — Choose a household</div>
          <div className="clients">
            {clients.map((c) => (
              <button
                key={c.id}
                className={"client-card" + (c.id === clientId ? " active" : "")}
                onClick={() => setClientId(c.id)}
              >
                <div className="cname">{c.name}</div>
                <div className="cmeta">{c.members}</div>
                <div className="cgoal">{c.goal}</div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="label">02 — Ask what you'd ask before a client meeting</div>
          <div className="ask">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Prep me for our review meeting."
            />
            <div className="chips">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="chip" onClick={() => setQuestion(ex)}>
                  {ex}
                </button>
              ))}
            </div>
            <div className="controls">
              <button
                className={"toggle" + (guardrails ? " on" : "")}
                onClick={() => setGuardrails((g) => !g)}
                title="Toggle the compliance layer to see what it catches"
              >
                <span className="track">
                  <span className="knob" />
                </span>
                Compliance layer {guardrails ? "ON" : "OFF"}
              </button>
              <button className="run" onClick={run} disabled={loading || !question.trim()}>
                {loading ? "Working…" : "Prepare brief"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {error && <div className="status" style={{ color: "var(--hold)" }}>{error}</div>}

      {loading && (
        <div className="status">
          <span className="spin" />
          Retrieving filings, drafting, and running the compliance review…
        </div>
      )}

      {result && !loading && (
        <>
          {/* compliance stamp */}
          <div className="sheet">
            <div className="sheet-head">
              <span className="k">Compliance review</span>
              <span className="k">{comp.checked_claims} quantitative claim(s) checked</span>
            </div>
            <div className="doc" style={{ paddingLeft: 40 }}>
              <div className="stamp-row">
                <span className={"stamp " + stampClass}>{stampText}</span>
                <span className="stamp-note">
                  {!guardrails
                    ? "Draft shown as the model wrote it. These are the issues the layer would have caught."
                    : comp.passed
                    ? "Every figure is cited to retrieved evidence; no recommendation or guarantee language."
                    : "Draft needs an advisor's eyes before it goes to the client."}
                </span>
              </div>
              {comp.refused && (
                <p style={{ marginTop: 16 }}>
                  <b>Refused:</b> {comp.refusal_reason}
                </p>
              )}
              {comp.flags?.length > 0 && (
                <div style={{ marginTop: 18 }}>
                  {comp.flags.map((f, i) => (
                    <div className="flag" key={i}>
                      <div className="rule">
                        {f.severity} · {f.rule}
                      </div>
                      <div className="quote">“{f.quote}”</div>
                      <div className="fix">→ {f.suggested_fix}</div>
                    </div>
                  ))}
                </div>
              )}
              {comp.unsupported_claims_removed?.length > 0 && (
                <div className="meter">
                  {comp.unsupported_claims_removed.length} uncited claim(s) pulled before this
                  draft was shown.
                </div>
              )}
              {result.audit && (
                <div className="meter audit-line">
                  Logged to the append-only audit chain — record #{result.audit.index} ·{" "}
                  {result.audit.record_hash.slice(0, 12)}… ·{" "}
                  {result.audit.chain_ok ? "chain verified ✓" : "chain BROKEN ✗"}
                </div>
              )}
            </div>
          </div>

          {/* the deliverable */}
          <div className="sheet">
            <div className="sheet-head">
              <span className="k">Deliverable</span>
              <span className="k">{result.deliverable.citations.length} sources cited</span>
            </div>
            <div className="doc">
              <h2>Meeting brief</h2>
              <div className="body">
                {renderRich(result.deliverable.meeting_brief, citeMap, jumpTo)}
              </div>
            </div>
            {result.deliverable.client_email && (
              <div className="doc">
                <h2>Client email (draft)</h2>
                <div className="body email">
                  {renderRich(result.deliverable.client_email, citeMap, jumpTo)}
                </div>
              </div>
            )}
          </div>

          {/* sources */}
          {result.deliverable.citations.length > 0 && (
            <div className="sheet">
              <div className="sheet-head">
                <span className="k">Sources</span>
                <span className="k">free &amp; public: SEC EDGAR · FRED · market data</span>
              </div>
              <div className="doc" style={{ paddingLeft: 40 }}>
                <ul className="sources">
                  {result.deliverable.citations.map((c) => (
                    <li
                      className="src"
                      key={c.source_id}
                      id={`src-${c.source_id}`}
                      ref={(el) => (srcRefs.current[c.source_id] = el)}
                    >
                      <span className="sid">[{c.source_id}]</span>
                      <div>
                        <div className="stitle">{c.title}</div>
                        <div className="ssnip">{c.snippet}</div>
                        {c.url && (
                          <a className="sl" href={c.url} target="_blank" rel="noreferrer">
                            {c.url}
                          </a>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* FinOps */}
          {result.finops && (
            <div className="sheet">
              <div className="sheet-head">
                <span className="k">Inference FinOps</span>
                <span className="k">
                  {result.finops.cache_hit ? "semantic cache" : "small + large tiers"}
                </span>
              </div>
              <div className="doc" style={{ paddingLeft: 40 }}>
                {result.finops.cache_hit ? (
                  <div className="stamp-row">
                    <span className="stamp cleared">Cache hit</span>
                    <span className="stamp-note">{result.finops.note}</span>
                  </div>
                ) : (
                  <>
                    <div className="finops-grid">
                      <div className="finops-cell">
                        <div className="fv">{(result.finops.tokens_in + result.finops.tokens_out).toLocaleString()}</div>
                        <div className="fk">tokens total</div>
                      </div>
                      <div className="finops-cell">
                        <div className="fv">${result.finops.est_cost_usd.toFixed(5)}</div>
                        <div className="fk">est. cost</div>
                      </div>
                      <div className="finops-cell">
                        <div className="fv">
                          {result.finops.calls.filter((c) => c.tier === "small").length}
                          <span className="fsep">/</span>
                          {result.finops.calls.filter((c) => c.tier === "large").length}
                        </div>
                        <div className="fk">small / large calls</div>
                      </div>
                    </div>
                    <div className="meter">{result.finops.note}</div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* trace */}
          <details className="trace">
            <summary>How it worked — {result.steps.length} steps</summary>
            <ol>
              {result.steps.map((s, i) => (
                <li key={i}>
                  <b>{s.title}.</b> {s.detail}
                </li>
              ))}
            </ol>
          </details>
        </>
      )}

      <footer className="footer">
        <b>advisor-brief</b> — a working prototype. Grounded on SEC EDGAR filings, FRED macro,
        and public market data. Open-weights models only. Not investment advice; a decision-support
        tool that keeps a human in the loop.
      </footer>
    </div>
  );
}
