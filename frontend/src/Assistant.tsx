import { useEffect, useRef, useState } from "react";
import type { ChatBrain, ChatMsg, ChatView, State } from "./types";

const PHASES: { id: ChatView["phase"]; label: string; hint: string }[] = [
  { id: "pre", label: "✈️ Before the trip", hint: "searching, booking, changes, questions" },
  { id: "during", label: "🏨 During the stay", hint: "problems in the room, requests, billing" },
  { id: "post", label: "⭐ After the stay", hint: "feedback, receipts, lost items, refunds" },
];

const DECISION: Record<string, { label: string; cls: string }> = {
  allow: { label: "Done automatically", cls: "ok" },
  needs_human: { label: "Waiting for a human", cls: "wait" },
  block: { label: "Blocked by guardrails", cls: "bad" },
};

const post = (path: string, body?: object) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) })
    .then((r) => r.json());

export default function Assistant({ s }: { s: State }) {
  const [view, setView] = useState<ChatView | null>(null);
  const [shown, setShown] = useState<ChatMsg[]>([]);
  const [text, setText] = useState("");
  const [typing, setTyping] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);   // which agent message's "brain" to show
  const bottom = useRef<HTMLDivElement>(null);
  const busy = useRef(false);

  const start = (phase: ChatView["phase"]) =>
    post("/api/assistant/new", { phase }).then((v: ChatView) => { setView(v); setShown(v.messages); setFocus(null); });

  useEffect(() => { start("pre"); }, []);

  // Pick up messages that arrive later (e.g. a human approved a refund in the Needs a human queue).
  useEffect(() => {
    if (!view) return;
    const t = setInterval(async () => {
      if (busy.current) return;
      const r = await fetch(`/api/assistant/${view.id}`);
      if (!r.ok) return;
      const v: ChatView = await r.json();
      if (v.messages.length > shown.length) { setView(v); setShown(v.messages); }
    }, 2500);
    return () => clearInterval(t);
  }, [view?.id, shown.length]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [shown.length, typing]);

  const send = async (msg: string) => {
    const m = msg.trim();
    if (!m || !view || busy.current) return;
    busy.current = true;
    setText("");
    setShown((x) => [...x, { id: Date.now(), role: "user", text: m }]);
    setTyping(true);
    const started = Date.now();
    const res = await post(`/api/assistant/${view.id}/message`, { text: m });
    // A short "typing…" pause so the reply feels like a person writing it.
    const wait = Math.max(0, 700 + Math.min(1400, (res.replies?.[0]?.text?.length ?? 60) * 8) - (Date.now() - started));
    setTimeout(() => {
      setTyping(false);
      setView(res);
      setShown(res.messages);
      setFocus(null);
      busy.current = false;
    }, wait);
  };

  const switchPhase = async (phase: ChatView["phase"]) => {
    if (!view) return;
    const v = await post(`/api/assistant/${view.id}/phase`, { phase });
    setView(v); setShown(v.messages); setFocus(null);
  };

  if (!view) return <p className="muted">Starting the assistant…</p>;
  const agentMsgs = shown.filter((m) => m.role === "agent" && m.brain);
  const brainMsg = focus != null ? shown.find((m) => m.id === focus) : agentMsgs[agentMsgs.length - 1];
  const myApprovals = s.approvals.filter((a) => a.conv_id === view.id);

  return (
    <>
      <section className="card intro">
        <h2>Traveler assistant <small>a customer-facing agent (Ava) for before, during and after the stay</small></h2>
        <p className="small">
          You are <b>{view.traveler.full_name}</b> ({view.traveler.user_id}, {view.traveler.tier}) with a trip to{" "}
          <b>{String(view.trip.hotel)}</b>, {String(view.trip.dates)}. Pick a moment in the trip, tap a sample message
          or type your own, and watch Ava reply and act. The right side shows what Ava understood, why she did what she
          did, and which guardrail checked each action.
        </p>
        <div className="phases">
          {PHASES.map((p) => (
            <button key={p.id} className={view.phase === p.id ? "on" : ""} onClick={() => switchPhase(p.id)}>
              {p.label}<small>{p.hint}</small>
            </button>
          ))}
          <button className="ghost" onClick={() => start(view.phase)}>↺ New chat</button>
        </div>
      </section>

      <div className="grid chatgrid">
        <section className="card chat">
          <div className="chathead">
            <span className="avatar">A</span>
            <div><b>Ava</b> <small className="muted">Trip assistant · usually replies instantly</small></div>
          </div>
          <div className="msgs">
            {shown.map((m) => (
              <div key={m.id} className={`msg ${m.role} ${m.id === brainMsg?.id ? "focus" : ""}`}
                onClick={() => m.role === "agent" && m.brain && setFocus(m.id)}>
                <div className="bubble">{m.text}</div>
                {m.cards && m.cards.length > 0 && (
                  <div className="cards">
                    {m.cards.map((c) => (
                      <div key={c.n} className="ccard">
                        <div className="cn">Option {c.n}</div>
                        <b>{c.name}</b>
                        <span className="muted">{c.area}</span>
                        <div className="cprice">${c.price}{c.kind === "hotel" ? <small>/night</small> : null}
                          {c.rating && <span className="crate">★ {c.rating}</span>}</div>
                        <div className="perks">{c.perks.map((p) => <span key={p}>{p}</span>)}</div>
                        <button onClick={(e) => { e.stopPropagation(); send(`Book option ${c.n}`); }}>Book this</button>
                      </div>
                    ))}
                  </div>
                )}
                {m.role === "agent" && m.brain && m.brain.actions.length > 0 && (
                  <div className="actchips">
                    {m.brain.actions.map((a) => (
                      <span key={a.id} className={`act ${DECISION[a.decision]?.cls ?? ""}`}>
                        T{a.tier} · {DECISION[a.decision]?.label ?? a.decision}
                      </span>
                    ))}
                  </div>
                )}
                {m.role === "agent" && m.quick && m.quick.length > 0 && m.id === shown[shown.length - 1]?.id && (
                  <div className="quickr">
                    {m.quick.map((q) => <button key={q} onClick={(e) => { e.stopPropagation(); send(q); }}>{q}</button>)}
                  </div>
                )}
              </div>
            ))}
            {typing && <div className="msg agent"><div className="bubble typing"><i /><i /><i /></div></div>}
            <div ref={bottom} />
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Message Ava…" />
            <button type="submit" disabled={!text.trim()}>Send</button>
          </form>
          <div className="samplemsgs">
            <span className="muted small">Things travelers often ask {PHASES.find((p) => p.id === view.phase)?.label.toLowerCase()}:</span>
            {(view.samples[view.phase] ?? []).map((q) => <button key={q} onClick={() => send(q)}>{q}</button>)}
          </div>
        </section>

        <section className="card brain">
          <h2>Inside Ava's head <small>{focus != null ? "selected message" : "latest reply"} · click any reply to inspect it</small></h2>
          {brainMsg?.brain ? <Brain b={brainMsg.brain} /> : <p className="muted">Send a message to see Ava's reasoning.</p>}
          <h3>Waiting for a human from this chat</h3>
          {myApprovals.length === 0 && <p className="muted small">Nothing waiting. Refunds and credits will appear here and in Live agents → Needs a human.</p>}
          {myApprovals.map((a) => (
            <div key={a.id} className="approval mini">
              <b>{a.title}</b>
              <div className="muted small">{a.reason}</div>
              <div className="abtns">
                <button className="approve" onClick={() => post(`/api/approvals/${a.id}/approve`, { note: "Approved by care team" })}>Approve</button>
                <button className="ghost" onClick={() => post(`/api/approvals/${a.id}/reject`, { note: "Outside goodwill policy" })}>Reject</button>
              </div>
            </div>
          ))}
          <details className="schema">
            <summary>What Ava is allowed to do</summary>
            <table className="regions">
              <tbody>
                <tr><td><span className="tier t1">T1</span></td><td>Inform and notify: tickets to the hotel, alerts, hand-off to a person</td><td>automatic</td></tr>
                <tr><td><span className="tier t2">T2</span></td><td>Safe, reversible, or confirmed by the traveler: hold or book after a "yes", early check-in, housekeeping, room move, invoice, points</td><td>automatic</td></tr>
                <tr><td><span className="tier t3">T3</span></td><td>Moves money outside policy: refunds, credits, price matching</td><td>human approves</td></tr>
                <tr><td><span className="tier t4">T4</span></td><td>Changes prices or rates (e.g. free upgrades)</td><td>never</td></tr>
              </tbody>
            </table>
          </details>
        </section>
      </div>
    </>
  );
}

function Brain({ b }: { b: ChatBrain }) {
  const slots = Object.entries(b.slots).filter(([, v]) => v !== null && v !== undefined && v !== false);
  return (
    <div className="brainbody">
      <div className="brow"><span>Understood as</span><b>{b.intent.replace(/_/g, " ")}</b></div>
      <div className="brow"><span>Confidence</span>
        <div className="confbar"><div style={{ width: `${b.confidence * 100}%` }} /></div><b>{Math.round(b.confidence * 100)}%</b>
      </div>
      {slots.length > 0 && (
        <div className="brow"><span>Details found</span>
          <div className="slots">{slots.map(([k, v]) => <code key={k}>{k.replace(/_/g, " ")}: {String(v)}</code>)}</div>
        </div>
      )}
      <h3>Reasoning</h3>
      <ol className="reasons">{b.reasoning.map((r, i) => <li key={i}>{r}</li>)}</ol>
      <h3>Actions</h3>
      {b.actions.length === 0 && <p className="muted small">No action needed for this reply.</p>}
      <ul className="acts">
        {b.actions.map((a) => (
          <li key={a.id}>
            <span className={`tier t${a.tier}`}>T{a.tier}</span> {a.title}
            <div className={`dec ${DECISION[a.decision]?.cls ?? ""}`}>
              {DECISION[a.decision]?.label ?? a.decision} · <span className="muted">{a.reason}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
