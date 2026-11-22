import { useEffect, useState } from "react";
import type { OrderView, UserView, SessionView } from "./types";

async function getJson<T>(path: string): Promise<T | null> {
  const r = await fetch(path);
  return r.ok ? ((await r.json()) as T) : null;
}

function useSamples() {
  const [s, setS] = useState<{ users: string[]; orders: string[] }>({ users: [], orders: [] });
  useEffect(() => {
    const load = () => getJson<{ users: string[]; orders: string[] }>("/api/lookup/samples").then((d) => d && setS(d));
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);
  return s;
}

// ---------- Search by order ID (inside "Needs a human") ----------
export function OrderSearch({ onOpenUser }: { onOpenUser: (uid: string) => void }) {
  const samples = useSamples();
  const [q, setQ] = useState("");
  const [id, setId] = useState<string | null>(null);
  const [view, setView] = useState<OrderView | null>(null);
  const [missing, setMissing] = useState(false);

  // Keep the result live: the status changes as agents retry and humans decide.
  useEffect(() => {
    if (!id) return;
    const load = () =>
      getJson<OrderView>(`/api/orders/${encodeURIComponent(id)}`).then((v) => {
        setView(v);
        setMissing(!v);
      });
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [id]);

  const go = (v: string) => {
    const x = v.trim().toUpperCase();
    if (!x) return;
    setQ(x);
    setId(x);
  };

  const decide = async (ok: boolean) => {
    if (!view?.pending_approval_id) return;
    await fetch(`/api/approvals/${view.pending_approval_id}/${ok ? "approve" : "reject"}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: ok ? "Approved from order search" : "Rejected from order search" }),
    });
  };

  return (
    <div className="lookup">
      <form onSubmit={(e) => { e.preventDefault(); go(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by order ID, e.g. ORD-102701" />
        <button type="submit">Find order</button>
        {id && <button type="button" className="ghost" onClick={() => { setId(null); setView(null); setQ(""); }}>Close</button>}
      </form>
      {!id && samples.orders.length > 0 && (
        <div className="chips">Try: {samples.orders.slice(0, 4).map((o) => (
          <button key={o} type="button" onClick={() => go(o)}>{o}</button>
        ))}</div>
      )}
      {missing && <p className="muted">No order {id} in the demo's recent data (orders are kept for a few minutes).</p>}
      {view && (
        <div className={`orderview ${view.tone}`}>
          <div className="ohead">
            <b>{view.id}</b>
            <span className={`otag ${view.tone}`}>{view.label}</span>
          </div>
          <div className="ogrid">
            <div><span>Traveler</span>
              {view.user_id ? <a onClick={() => onOpenUser(view.user_id!)}>{view.user_id} · see journey →</a> : view.traveler}
            </div>
            <div><span>Supplier</span>{view.supplier}</div>
            <div><span>Value</span>${view.value_usd} · {view.payment_method}</div>
            <div><span>Check-in</span>in {view.checkin_hours}h</div>
            <div><span>Where</span>{view.brand} · {view.device} · {view.state ? `${view.state}, ` : ""}{view.market}</div>
            <div><span>Agent retries</span>{view.retries} of 3</div>
          </div>
          <ol className="otime">
            {view.timeline.map((t, i) => (
              <li key={i}><span className="ago">{t.ago}s ago</span><b>{t.who}</b> {t.text}</li>
            ))}
          </ol>
          {view.pending_approval_id && (
            <div className="abtns">
              <button className="approve" onClick={() => decide(true)}>Approve rebooking</button>
              <button className="ghost" onClick={() => decide(false)}>Reject</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------- Traveler journey tab ----------
const ICON: Record<string, string> = { done: "✓", dropped: "✗", waiting: "…", not_reached: "" };

export function Journey({ initial }: { initial: string }) {
  const samples = useSamples();
  const [q, setQ] = useState(initial);
  const [uid, setUid] = useState(initial);
  const [view, setView] = useState<UserView | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => { if (initial) { setQ(initial); setUid(initial); } }, [initial]);

  useEffect(() => {
    if (!uid) return;
    const load = () =>
      getJson<UserView>(`/api/users/${encodeURIComponent(uid)}`).then((v) => {
        setView(v);
        setMissing(!v);
      });
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [uid]);

  const go = (v: string) => {
    const x = v.trim().toUpperCase();
    if (x) { setQ(x); setUid(x); }
  };

  return (
    <>
      <section className="card">
        <h2>Traveler journey <small>enter a user ID to see every recent session, from search to booked</small></h2>
        <div className="lookup">
          <form onSubmit={(e) => { e.preventDefault(); go(q); }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="User ID, e.g. U10720" />
            <button type="submit">Show journey</button>
          </form>
          {samples.users.length > 0 && (
            <div className="chips">Try a recent traveler: {samples.users.map((u) => (
              <button key={u} type="button" onClick={() => go(u)}>{u}</button>
            ))}</div>
          )}
          <p className="muted small">
            Demo travelers are U10000–U14999. Each one shops every ~40 seconds, and the last 6 sessions are kept.
          </p>
        </div>
      </section>

      {missing && <p className="muted">No recent sessions for {uid}. Try one of the suggested travelers.</p>}
      {view && (
        <>
          <div className="kpis three">
            <div className="kpi"><span>Traveler</span><b>{view.user_id}</b></div>
            <div className="kpi"><span>Recent sessions</span><b>{view.total}</b></div>
            <div className="kpi"><span>Booked</span><b>{view.booked}</b></div>
          </div>
          {view.sessions.map((x) => <Session key={x.session_id} x={x} />)}
        </>
      )}
    </>
  );
}

function Session({ x }: { x: SessionView }) {
  const tone = x.outcome === "Booked" ? "ok" : x.outcome.startsWith("Tracking") ? "warn" : "bad";
  return (
    <section className={`card session ${x.in_pipeline ? "flying" : ""}`}>
      <div className="shead">
        <span className={`otag ${tone}`}>{x.outcome}</span>
        <b>{x.session_id}</b>
        <span className="muted">started {x.started_ago}s ago · {x.brand} · {x.device} ·{" "}
          {x.state ? `${x.state}, ` : ""}{x.market} · {x.supplier} · {x.payment_method}</span>
      </div>
      {x.in_pipeline && (
        <div className="pill wait">
          Still in the ingestion pipeline: the agents will see this session in about {x.lands_in}s.
        </div>
      )}
      <ol className="stepper">
        {x.steps.map((st) => (
          <li key={st.name} className={st.state}>
            <span className="ic">{ICON[st.state]}</span>
            <b>{st.name}</b>
            <small>{st.ago != null ? `${st.ago}s ago` : st.state === "dropped" ? "didn't get here" : st.state === "waiting" ? "waiting" : ""}</small>
          </li>
        ))}
      </ol>
      <p className="why">
        {x.why}
        {x.issue && <><br /><span className="badc">Known problem at the time: {x.issue}</span></>}
        {x.order_id && <><br /><span className="muted">Order {x.order_id} (search it under Live agents → Needs a human)</span></>}
        {x.lag != null && x.lag > 0 && <><br /><span className="muted">Reached the agents {Math.round(x.lag)}s after it happened.</span></>}
      </p>
    </section>
  );
}
