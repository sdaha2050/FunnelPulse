import { useEffect, useState } from "react";
import type { State, TraceView } from "./types";
import Pipeline from "./Pipeline";

type Sample = { id: string; name: string; story: string; expect: string; events: object[] };

const ICON: Record<string, string> = { done: "✓", warn: "!", active: "•", pending: "", skipped: "–" };

const QUICK = [
  { type: "payment_decline_spike", label: "Amex declines" },
  { type: "supplier_timeout", label: "Supplier stops confirming" },
  { type: "price_mismatch", label: "iOS price mismatch" },
  { type: "tracking_outage", label: "Broken tracking" },
  { type: "state_payment_outage", label: "California payments" },
  { type: "country_3ds_failure", label: "UK bank check" },
];

const post = (path: string, body?: object) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

export default function SendEvents({ s, onOpenUser }: { s: State; onOpenUser: (u: string) => void }) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [sel, setSel] = useState<Sample | null>(null);
  const [text, setText] = useState("");
  const [skip, setSkip] = useState(false);
  const [err, setErr] = useState<string[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceView | null>(null);
  const [history, setHistory] = useState<{ id: string; name: string; count: number; sent_ago: number }[]>([]);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    fetch("/api/events/samples").then((r) => r.json()).then((d: Sample[]) => {
      setSamples(d);
      pick(d[2] ?? d[0]);
    });
  }, []);

  // Follow the trace live.
  useEffect(() => {
    if (!traceId) return;
    const load = async () => {
      const r = await fetch(`/api/traces/${traceId}`);
      if (r.ok) setTrace(await r.json());
      const h = await fetch("/api/traces");
      if (h.ok) setHistory(await h.json());
    };
    load();
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [traceId]);

  const pick = (x: Sample) => {
    setSel(x);
    setText(JSON.stringify({ events: x.events }, null, 2));
    setErr([]);
  };

  const send = async () => {
    setErr([]);
    let body: { events?: object[] };
    try {
      body = JSON.parse(text);
    } catch {
      setErr(["That isn't valid JSON. Check for a missing comma or quote."]);
      return;
    }
    setSending(true);
    const r = await post("/api/events", { name: sel?.name ?? "Custom events", events: body.events ?? [], skip_delay: skip });
    setSending(false);
    const d = await r.json();
    if (!r.ok) {
      setErr(d.detail?.errors ?? [String(d.detail)]);
      return;
    }
    setTrace(null);
    setTraceId(d.trace_id);
  };

  const autoOn = s.settings.auto_incidents;

  return (
    <>
      <section className="card intro">
        <h2>Send events <small>you play the traveler apps: send events, then watch every agent handle them</small></h2>
        <ol className="howto">
          <li><b>Pick a sample</b> on the left (or edit the JSON: change the card, the count, the stage…).</li>
          <li><b>Press Send.</b> Your events join the live stream of ~120 background events per second.</li>
          <li><b>Follow the 8 steps</b> on the right. Each one shows what the agent did and <i>why</i>.</li>
        </ol>
        <div className="toggles">
          <label className="switch">
            <input type="checkbox" checked={autoOn} onChange={(e) => post("/api/settings", { auto_incidents: e.target.checked })} />
            Random demo problems {autoOn ? "ON" : "OFF"}
          </label>
          {autoOn && <span className="muted small">Tip: turn this off so only your events cause problems.</span>}
        </div>
      </section>

      <div className="grid sendgrid">
        <section className="card">
          <h2>1. Choose events</h2>
          <ul className="samples">
            {samples.map((x) => (
              <li key={x.id} className={sel?.id === x.id ? "on" : ""} onClick={() => pick(x)}>
                <b>{x.name}</b>
                <span>{x.story}</span>
              </li>
            ))}
          </ul>
          {sel && (
            <div className="expect">
              <b>What should happen:</b> {sel.expect}
            </div>
          )}
          <label className="small muted">Event JSON (editable)</label>
          <textarea className="json" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          <label className="switch small">
            <input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} />
            Skip the 10–20s ingestion delay (faster demo)
          </label>
          {err.length > 0 && <div className="errbox">{err.map((x) => <div key={x}>✗ {x}</div>)}</div>}
          <button className="send" disabled={sending} onClick={send}>{sending ? "Sending…" : "Send events ▶"}</button>
          <details className="schema">
            <summary>Event fields</summary>
            <ul className="small">
              <li><code>type</code>: always <code>traveler_session</code> (one traveler's visit)</li>
              <li><code>furthest_stage</code>: search · detail · checkout · payment · booked</li>
              <li><code>brand</code>, <code>market</code> (country code), <code>state</code> (US), <code>device</code>,
                <code>payment_method</code>, <code>supplier</code>, <code>user_id</code></li>
              <li><code>supplier_confirms</code>: false = the hotel never confirms (booked only)</li>
              <li><code>session_id</code>: null = broken tracking</li>
              <li><code>count</code>: how many travelers like this (1–200)</li>
            </ul>
          </details>
        </section>

        <section className="card">
          <h2>2. Follow them through the agents {trace && <small>{trace.name} · sent {trace.sent_ago}s ago · trace {trace.id}</small>}</h2>
          {!trace && <p className="muted">Send events to see their journey here.</p>}
          {trace && (
            <ol className="trace">
              {trace.steps.map((st) => (
                <li key={st.key} className={st.status}>
                  <span className="ic">{ICON[st.status]}</span>
                  <div>
                    <b>{st.title}</b>
                    <p>{st.text}</p>
                    {st.why && <p className="why"><span>Why:</span> {st.why}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
          {trace && trace.orders.length > 0 && (
            <>
              <h3>Bookings created</h3>
              <ul className="small">
                {trace.orders.map((o) => (
                  <li key={o.id}>
                    <code>{o.id}</code> <span className={`otag ${o.tone}`}>{o.label}</span>{" "}
                    {o.user_id && <a className="lnk" onClick={() => onOpenUser(o.user_id!)}>journey of {o.user_id}</a>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {history.length > 1 && (
            <div className="chips">Earlier sends: {history.slice(0, 8).map((h) => (
              <button key={h.id} onClick={() => setTraceId(h.id)} className={h.id === traceId ? "on" : ""}>
                {h.id} · {h.name} ({h.sent_ago}s ago)
              </button>
            ))}</div>
          )}
        </section>
      </div>

      <Pipeline s={s} />

      <section className="card">
        <h2>Or inject a ready-made problem <small>the agents' view of a real outage, for 35 seconds</small></h2>
        <div className="quick">
          {QUICK.map((q) => <button key={q.type} onClick={() => post(`/api/incidents/${q.type}`)}>{q.label}</button>)}
          <button className="ghost" onClick={() => post("/api/incidents/clear")}>Clear</button>
        </div>
      </section>
    </>
  );
}
