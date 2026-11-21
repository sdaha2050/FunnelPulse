import { useEffect, useState } from "react";
import type { Action, State } from "./types";
import Regions from "./Regions";
import Monthly from "./Monthly";

// Each agent gets a color so the conversation feed is easy to follow.
const AGENT_COLORS: Record<string, string> = {
  Simulator: "#64748b",
  DataQualityAgent: "#0891b2",
  FunnelMonitorAgent: "#2563eb",
  ReservationIntegrityAgent: "#7c3aed",
  RootCauseAgent: "#c026d3",
  ActionRouterAgent: "#ea580c",
  Guardrails: "#dc2626",
  EvalAgent: "#16a34a",
  "Human agent": "#ca8a04",
};

const INCIDENT_BUTTONS: { type: string; label: string }[] = [
  { type: "payment_decline_spike", label: "Payment declines" },
  { type: "supplier_timeout", label: "Supplier stops confirming" },
  { type: "price_mismatch", label: "Price mismatch (iOS)" },
  { type: "tracking_outage", label: "Broken tracking (bad data)" },
  { type: "state_payment_outage", label: "California payments fail" },
  { type: "country_3ds_failure", label: "UK bank check fails" },
];

type Tab = "live" | "us" | "intl" | "monthly";
const TABS: { id: Tab; label: string }[] = [
  { id: "live", label: "Live agents" },
  { id: "us", label: "US by state" },
  { id: "intl", label: "International" },
  { id: "monthly", label: "Monthly + top issues" },
];

const STEPS = [
  ["Ingest", "Fake traveler journeys stream in every 0.5s (search → itinerary delivered)."],
  ["Check data", "DataQualityAgent makes sure the data is fresh, complete and well-formed."],
  ["Detect", "FunnelMonitor spots conversion drops; ReservationIntegrity finds paid-but-unconfirmed bookings."],
  ["Diagnose", "RootCauseAgent finds the segment behind the drop, with evidence and a confidence score."],
  ["Act safely", "ActionRouter picks a tier. Guardrails check every action. Safe fixes run; sensitive ones go to a human."],
  ["Learn", "EvalAgent scores every step against the truth, so we know the agents can be trusted."],
];

async function post(path: string, body?: unknown) {
  await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);

export default function App() {
  const [s, setS] = useState<State | null>(null);
  const [error, setError] = useState(false);
  const [showHow, setShowHow] = useState(true);
  const [tab, setTab] = useState<Tab>("live");

  // Poll the backend once a second. Simple and good enough for a demo.
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch("/api/state");
        const data = (await r.json()) as State;
        if (alive) {
          setS(data);
          setError(false);
        }
      } catch {
        if (alive) setError(true);
      }
    };
    load();
    const id = setInterval(load, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (!s) return <div className="loading">{error ? "Can't reach the backend…" : "Starting agents…"}</div>;

  const anomalyByTarget = new Map(s.anomalies.map((a) => [a.to_stage, a]));
  const maxCount = Math.max(1, ...s.funnel.map((f) => f.count));
  const killOn = s.guardrails.kill_switch.global;

  return (
    <div className="page">
      <header>
        <div>
          <h1>
            TripSentry <span className="tag">demo</span>
          </h1>
          <p className="sub">
            AI agents watch every booking from search to check-in, catch where travelers drop or
            reservations break, fix the safe things, and ask a human for the rest.
          </p>
        </div>
        <div className="controls">
          <span className="label">Inject a problem:</span>
          {INCIDENT_BUTTONS.map((b) => (
            <button key={b.type} onClick={() => post(`/api/incidents/${b.type}`)}>
              {b.label}
            </button>
          ))}
          <button className="ghost" onClick={() => post("/api/incidents/clear")}>
            Clear
          </button>
          <button
            className={killOn ? "danger" : "ghost"}
            onClick={() => post("/api/killswitch", { global_on: !killOn })}
            title="Stops every automated fix (Tier 2+). Alerts still flow."
          >
            Kill switch: {killOn ? "ON" : "OFF"}
          </button>
        </div>
      </header>

      <div className="status">
        <div className={`pill ${s.incident ? (s.incident.real ? "bad" : "warn") : "ok"}`}>
          {s.incident
            ? `Active problem: ${s.incident.label} (${s.incident.seconds_left}s left)`
            : "No injected problem right now (one is added automatically every ~50s)"}
        </div>
        <div className={`pill ${s.data_quality.reliable ? "ok" : "warn"}`}>
          Data quality: {s.data_quality.reliable ? "reliable" : `UNRELIABLE — ${s.data_quality.reason}`}
        </div>
        {error && <div className="pill bad">Connection lost, retrying…</div>}
      </div>

      <nav className="tabs">
        {TABS.map((t) => {
          const alerts = t.id === "us" || t.id === "intl" ? s.regions[t.id].alerts : 0;
          return (
            <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
              {t.label}
              {alerts > 0 && <span className="dot">{alerts}</span>}
            </button>
          );
        })}
      </nav>

      {(tab === "us" || tab === "intl") && <Regions kind={tab} data={s.regions[tab]} />}
      {tab === "monthly" && <Monthly />}

      {tab === "live" && (<>

      <section className="card how">
        <button className="link" onClick={() => setShowHow(!showHow)}>
          {showHow ? "▾" : "▸"} How it works
        </button>
        {showHow && (
          <ol className="steps">
            {STEPS.map(([t, d], i) => (
              <li key={t}>
                <b>
                  {i + 1}. {t}
                </b>
                <span>{d}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <div className="grid two">
        <section className="card">
          <h2>Live booking funnel <small>last 10 seconds</small></h2>
          <div className="funnel">
            {s.funnel.map((f) => {
              const anomaly = anomalyByTarget.get(f.stage);
              return (
                <div key={f.stage}>
                  <div className={`frow ${anomaly ? "hot" : ""}`}>
                    <span className="fname">{f.label}</span>
                    <div className="fbar">
                      <div style={{ width: `${Math.max(2, (f.count / maxCount) * 100)}%` }} />
                    </div>
                    <span className="fcount">{f.count.toLocaleString()}</span>
                  </div>
                  {anomaly && (
                    <div className="alertline">
                      ⚠ Drop: {anomaly.label} at {pct(anomaly.rate)} vs {pct(anomaly.baseline)} normal
                      (−{anomaly.drop_pct}%)
                    </div>
                  )}
                  {f.next_rate != null && !anomalyByTarget.has(s.funnel[s.funnel.indexOf(f) + 1]?.stage) && (
                    <div className="conv">↓ {pct(f.next_rate)} continue</div>
                  )}
                </div>
              );
            })}
          </div>
          {s.diagnoses[0] && (
            <div className="diag">
              <b>Root cause ({s.diagnoses[0].label}):</b> {s.diagnoses[0].llm_summary || s.diagnoses[0].summary}
            </div>
          )}
        </section>

        <section className="card">
          <h2>Data coming in <small>fake ingestion</small></h2>
          <ul className="events">
            {s.events.map((e) => (
              <li key={e.id} className={!e.schema_ok ? "broken" : e.booked ? "booked" : ""}>
                <code>{e.id}</code> {e.brand} · {e.market} · {e.device} →{" "}
                {e.schema_ok ? (e.booked ? "booked ✓" : `left at ${e.stage}`) : "missing fields ✗"}
              </li>
            ))}
          </ul>
          <h3>Paid but not confirmed</h3>
          {s.stuck_orders.length === 0 ? (
            <p className="muted">None. All paid bookings are confirmed by suppliers.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Order</th><th>Supplier</th><th>Check-in</th><th>Retries</th><th>Status</th></tr>
              </thead>
              <tbody>
                {s.stuck_orders.slice(0, 5).map((o) => (
                  <tr key={o.id}>
                    <td>{o.id}</td><td>{o.supplier}</td><td>{o.checkin_hours}h</td>
                    <td>{o.retries}/3</td><td>{o.status.replace("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <div className="grid two">
        <section className="card">
          <h2>Agents talking to each other</h2>
          <ul className="chat">
            {s.messages.slice(0, 30).map((m) => (
              <li key={m.id}>
                <span className="who" style={{ color: AGENT_COLORS[m.sender] || "#334155" }}>
                  {m.sender}
                </span>
                <span className="to">→ {m.to}</span>
                <span className="txt">{m.text}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card human">
          <h2>
            Needs a human <small>Tier 3: money, trips, or traveler contact</small>
          </h2>
          {s.approvals.length === 0 && <p className="muted">Nothing waiting. Inject a problem to see one.</p>}
          {s.approvals.map((a) => (
            <ApprovalCard key={a.id} a={a} />
          ))}
          {s.waiting_for_human > 0 && (
            <p className="muted">+{s.waiting_for_human} more bookings queued behind these.</p>
          )}
          {s.decided.length > 0 && (
            <>
              <h3>Recent human decisions</h3>
              <ul className="small">
                {s.decided.slice(0, 4).map((a) => (
                  <li key={a.id}>
                    <b className={a.status === "approved" ? "okc" : "badc"}>{a.status}</b> {a.title}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

      <div className="grid three">
        <section className="card">
          <h2>Handled by agents <small>Tier 1–2</small></h2>
          <ul className="small">
            {s.auto_actions.slice(0, 10).map((a) => (
              <li key={a.id}>
                <span className={`tier t${a.tier}`}>T{a.tier}</span> {a.title}
                <div className="muted">{a.result?.detail}</div>
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <h2>Guardrails <small>{s.guardrails.mishaps_total} mishaps prevented</small></h2>
          {s.guardrails.mishaps.length === 0 && <p className="muted">No risky actions attempted yet.</p>}
          <ul className="small">
            {s.guardrails.mishaps.map((m) => (
              <li key={m.rule}>
                <b>{m.count}×</b> {m.label}
                <div className="muted">e.g. “{m.example}”</div>
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <h2>Evals <small>agents graded against the truth</small></h2>
          <table className="scores">
            <tbody>
              {s.evals.scores.map((sc) => (
                <tr key={sc.name} title={sc.help}>
                  <td>{sc.name}</td>
                  <td className="num">{sc.value == null ? "–" : `${sc.value}${sc.unit}`}</td>
                  <td className="muted">{sc.target}</td>
                  <td>{sc.pass == null ? "" : sc.pass ? "✅" : "❌"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Incidents</h3>
          <ul className="small">
            {s.evals.incidents.map((c, i) => (
              <li key={i}>
                {c.active ? "🔴" : "⚪"} {c.label}
                <div className="muted">
                  {c.outcome}
                  {c.ttd != null && ` in ${c.ttd}s`}
                  {c.rca_correct != null && ` · root cause ${c.rca_correct ? "correct" : "wrong"}`}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
      </>)}
      <footer>Fake data only. No real Expedia systems or traveler data are used.</footer>
    </div>
  );
}

function ApprovalCard({ a }: { a: Action }) {
  const [busy, setBusy] = useState(false);
  const decide = async (ok: boolean) => {
    setBusy(true);
    await post(`/api/approvals/${a.id}/${ok ? "approve" : "reject"}`, { note: ok ? "Approved in demo" : "Rejected in demo" });
  };
  return (
    <div className="approval">
      <div className="ahead">
        <span className={`sev ${a.severity === "Sev 1" ? "s1" : ""}`}>{a.severity}</span>
        <b>{a.title}</b>
      </div>
      <div className="muted">{a.reason}</div>
      {a.impact && <div>Impact: {a.impact}</div>}
      <ul className="evidence">
        {a.evidence.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
      <div className="abuttons">
        <button disabled={busy} className="approve" onClick={() => decide(true)}>Approve</button>
        <button disabled={busy} className="ghost" onClick={() => decide(false)}>Reject</button>
      </div>
    </div>
  );
}
