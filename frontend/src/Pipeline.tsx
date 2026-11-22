import { useEffect, useRef, useState } from "react";
import type { Message, State } from "./types";

// Colors per agent: the same color is used for its box, its message dots and its chat lines.
export const AGENT_COLORS: Record<string, string> = {
  Simulator: "#64748b",
  DataQualityAgent: "#0891b2",
  FunnelMonitorAgent: "#2563eb",
  ReservationIntegrityAgent: "#7c3aed",
  RootCauseAgent: "#c026d3",
  ActionRouterAgent: "#ea580c",
  Guardrails: "#dc2626",
  EvalAgent: "#16a34a",
  "Human agent": "#ca8a04",
  TravelAssistantAgent: "#db2777",
  "Traveler apps": "#0f766e",
};

type NodeId = "apps" | "stream" | "dq" | "funnel" | "rca" | "db" | "integrity" | "router" | "guard" | "auto" | "human" | "evals";

// Box positions in the 1100 x 410 drawing.
const W = 130, H = 64;
const NODES: Record<NodeId, { x: number; y: number; w?: number; agent?: string }> = {
  apps: { x: 16, y: 40 },
  stream: { x: 172, y: 40, w: 300, agent: "Simulator" },
  dq: { x: 508, y: 40, agent: "DataQualityAgent" },
  funnel: { x: 674, y: 40, w: 140, agent: "FunnelMonitorAgent" },
  rca: { x: 850, y: 40, w: 140, agent: "RootCauseAgent" },
  db: { x: 16, y: 170 },
  integrity: { x: 172, y: 170, w: 150, agent: "ReservationIntegrityAgent" },
  router: { x: 850, y: 170, w: 140, agent: "ActionRouterAgent" },
  human: { x: 508, y: 300, agent: "Human agent" },
  auto: { x: 674, y: 300, w: 140 },
  guard: { x: 850, y: 300, w: 140, agent: "Guardrails" },
  evals: { x: 172, y: 300, w: 150, agent: "EvalAgent" },
};

// Arrows. A message from A to B travels along the matching path.
const EDGES: Record<string, { d: string; data?: boolean; dashed?: boolean; label?: string; lx?: number; ly?: number; start?: boolean }> = {
  "apps>stream": { d: "M146 72 H172", data: true },
  "stream>dq": { d: "M472 72 H508", data: true },
  "dq>funnel": { d: "M638 72 H674", data: true },
  "funnel>rca": { d: "M814 72 H850", label: "drop found", lx: 832, ly: 30 },
  "rca>router": { d: "M920 104 V170", label: "root cause", lx: 928, ly: 130, start: true },
  "db>integrity": { d: "M146 202 H172", data: true },
  "integrity>router": { d: "M322 202 H850", label: "stuck bookings", lx: 586, ly: 194 },
  "router>guard": { d: "M920 234 V300", label: "proposed action", lx: 928, ly: 270, start: true },
  "guard>auto": { d: "M850 332 H814", label: "safe", lx: 832, ly: 324 },
  "guard>human": { d: "M920 364 V392 H573 V364", label: "needs approval", lx: 746, ly: 404 },
  "dq>guard": { d: "M573 104 V150 H1060 V332 H990", dashed: true, label: "data reliable?", lx: 1066, ly: 250, start: true },
  // routes that pass THROUGH the guardrails box (every action is checked there)
  "router>human": { d: "M920 234 V392 H573 V364" },
  "router>auto": { d: "M920 234 V332 H814" },
};

const NODE_OF: Record<string, NodeId> = {
  Simulator: "stream", DataQualityAgent: "dq", FunnelMonitorAgent: "funnel", RootCauseAgent: "rca",
  ReservationIntegrityAgent: "integrity", ActionRouterAgent: "router", Guardrails: "guard",
  "Human agent": "human", EvalAgent: "evals",
};

function route(m: Message): { d: string; reverse: boolean } | null {
  const from = NODE_OF[m.sender];
  if (!from) return null;
  let to: NodeId | undefined = NODE_OF[m.to];
  if (!to && (from === "router" || from === "guard")) to = "auto";   // e.g. alert to "Payments team"
  if (!to || to === from) return null;
  if (EDGES[`${from}>${to}`]) return { d: EDGES[`${from}>${to}`].d, reverse: false };
  if (EDGES[`${to}>${from}`]) return { d: EDGES[`${to}>${from}`].d, reverse: true };
  return null;
}

type Pulse = { id: number; d: string; reverse: boolean; color: string };

export default function Pipeline({ s }: { s: State }) {
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const lastSeen = useRef<number>(0);
  const [recent, setRecent] = useState<Record<string, number>>({}); // agent -> time it last spoke

  // Turn new bus messages into dots that travel along the arrows.
  useEffect(() => {
    const fresh = s.messages.filter((m) => m.id > lastSeen.current).reverse();
    if (!fresh.length) return;
    const first = lastSeen.current === 0;
    lastSeen.current = Math.max(...s.messages.map((m) => m.id));
    if (first) return;                                   // don't replay history on page load
    const now = Date.now();
    setRecent((r) => ({ ...r, ...Object.fromEntries(fresh.map((m) => [m.sender, now])) }));
    const add: Pulse[] = [];
    fresh.forEach((m) => {
      const r = route(m);
      if (r) add.push({ id: m.id, ...r, color: AGENT_COLORS[m.sender] ?? "#334155" });
    });
    if (!add.length) return;
    setPulses((p) => [...p, ...add].slice(-14));
    const ids = new Set(add.map((a) => a.id));
    setTimeout(() => setPulses((p) => p.filter((x) => !ids.has(x.id))), 1700);
  }, [s.messages]);

  const p = s.pipeline;
  const lagRange = `${p.delay_range[0]}–${p.delay_range[1]}s`;
  const anomaly = s.anomalies[0];
  const top = s.diagnoses[0]?.top;
  const metScores = s.evals.scores.filter((x) => x.pass).length;
  const scored = s.evals.scores.filter((x) => x.pass != null).length;
  const speaking = (agent?: string) => !!agent && Date.now() - (recent[agent] ?? 0) < 2200;

  const status: Record<NodeId, { name: string; line: string; bad?: boolean }> = {
    apps: { name: "Traveler apps", line: "120 events / sec" },
    stream: { name: "Event stream (Kafka)", line: "" },
    dq: { name: "Data quality", line: s.data_quality.reliable ? "Reliable ✓" : "UNRELIABLE", bad: !s.data_quality.reliable },
    funnel: { name: "Funnel monitor", line: anomaly ? `Drop at ${anomaly.label.split(/→|->/)[0].trim()}` : "No drops", bad: !!anomaly },
    rca: { name: "Root cause", line: top ? `${top.value} · ${Math.round(top.confidence * 100)}%` : "Waiting", bad: !!top },
    db: { name: "Bookings DB", line: "real-time, no delay" },
    integrity: { name: "Reservation check", line: `${s.stuck_orders.length} stuck`, bad: s.stuck_orders.length > 0 },
    router: { name: "Action router", line: `${s.auto_actions.length + s.approvals.length} recent actions` },
    guard: {
      name: "Guardrails",
      line: s.guardrails.kill_switch.global ? "KILL SWITCH ON" : `${s.guardrails.mishaps_total} blocked`,
      bad: s.guardrails.kill_switch.global,
    },
    auto: { name: "Agents act (auto)", line: `${s.auto_actions.length} done` },
    human: { name: "Human approval", line: `${s.approvals.length + s.waiting_for_human} waiting`, bad: s.approvals.length > 0 },
    evals: { name: "EvalAgent", line: scored ? `${metScores}/${scored} targets met` : "Scoring…" },
  };

  return (
    <section className="card pipeline">
      <h2>
        Live pipeline <small>dots = events and agent messages moving in real time · each color is one agent</small>
      </h2>
      <div className="pipewrap">
        <svg viewBox="0 0 1160 420" role="img" aria-label="Live agent pipeline">
          <defs>
            <marker id="pa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0 0L10 5L0 10z" fill="#94a3b8" />
            </marker>
          </defs>

          {/* arrows */}
          {Object.entries(EDGES).filter(([k]) => !k.startsWith("router>h") && !k.startsWith("router>a")).map(([k, e]) => (
            <g key={k}>
              <path d={e.d} fill="none" stroke="#94a3b8" strokeWidth="1.25" strokeDasharray={e.dashed ? "4 4" : undefined}
                markerEnd="url(#pa)" />
              {e.label && <text x={e.lx} y={e.ly} fontSize="11" fill="#64748b" textAnchor={e.start ? "start" : "middle"}>{e.label}</text>}
            </g>
          ))}
          <path d="M322 332 H508" fill="none" stroke="#94a3b8" strokeDasharray="4 4" />
          <text x="415" y="324" fontSize="11" fill="#64748b" textAnchor="middle">grades every step</text>

          {/* steady flow of raw events on the data arrows */}
          {Object.entries(EDGES).filter(([, e]) => e.data).map(([k, e]) =>
            [0, 0.33, 0.66].map((off) => (
              <circle key={k + off} r="3" fill="#94a3b8">
                <animateMotion dur="1s" begin={`${off}s`} repeatCount="indefinite" path={e.d} />
              </circle>
            )),
          )}

          {/* boxes */}
          {(Object.keys(NODES) as NodeId[]).map((id) => {
            const n = NODES[id];
            const st = status[id];
            const w = n.w ?? W;
            const color = n.agent ? AGENT_COLORS[n.agent] : "#94a3b8";
            const hot = speaking(n.agent);
            return (
              <g key={id}>
                <rect x={n.x} y={n.y} width={w} height={H} rx="8"
                  fill={hot ? color : st.bad ? "#fef2f2" : "#fff"} fillOpacity={hot ? 0.12 : 1}
                  stroke={st.bad ? "#dc2626" : color} strokeWidth={hot || st.bad ? 2.5 : 1.25}
                  style={{ transition: "all .3s" }} />
                <text x={n.x + w / 2} y={n.y + (id === "stream" ? 18 : 27)} textAnchor="middle" fontSize="13"
                  fontWeight="600" fill="#0f172a">{st.name}</text>
                {id !== "stream" && (
                  <text x={n.x + w / 2} y={n.y + 46} textAnchor="middle" fontSize="11.5"
                    fill={st.bad ? "#dc2626" : "#64748b"} fontWeight={st.bad ? 600 : 400}>{st.line}</text>
                )}
              </g>
            );
          })}

          {/* the conveyor: batches travel through the stream for 10-20s before agents see them */}
          <line x1="184" x2="460" y1="70" y2="70" stroke="#e2e8f0" strokeWidth="18" strokeLinecap="round" />
          {p.in_flight.map((b) => {
            const prog = Math.min(1, Math.max(0, (s.now - b.event_ts) / Math.max(0.1, b.land_at - b.event_ts)));
            return (
              <rect key={b.event_ts} x={184} y={62} width="6" height="16" rx="2" fill="#2563eb" opacity="0.75"
                style={{ transform: `translateX(${prog * 270}px)`, transition: "transform 1s linear" }} />
            );
          })}
          <text x="322" y="96" textAnchor="middle" fontSize="11.5" fill="#64748b">
            {p.delay_range[1] > 0
              ? `${p.in_flight_events.toLocaleString()} events in flight · delay now ${p.lag}s (range ${lagRange})`
              : "no ingestion delay"}
          </text>

          {/* agent messages travelling between boxes */}
          {pulses.map((pl) => <PulseDot key={pl.id} p={pl} />)}
        </svg>

        <div className="pchat">
          <h3>Agents talking</h3>
          <ul>
            {s.messages.slice(0, 14).map((m, i) => (
              <li key={m.id} className={i < 3 ? "new" : ""}>
                <span className="dot" style={{ background: AGENT_COLORS[m.sender] ?? "#334155" }} />
                <b style={{ color: AGENT_COLORS[m.sender] ?? "#334155" }}>{m.sender}</b>
                <span className="to"> → {m.to}</span>
                <div>{m.text}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="muted small">
        Clickstream events (searches, checkouts, payments) reach the agents {lagRange} after they happen, like a real
        Kafka pipeline, so a new problem shows up on the funnel only after that delay. Bookings come straight from the
        bookings database in real time, so stuck bookings are caught without the delay.
      </p>
    </section>
  );
}

// One message: a colored dot that travels along its arrow once, then disappears.
function PulseDot({ p }: { p: Pulse }) {
  const ref = useRef<SVGAnimateMotionElement>(null);
  useEffect(() => {
    ref.current?.beginElement();
  }, []);
  return (
    <circle r="6.5" fill={p.color} stroke="#fff" strokeWidth="1.5">
      <animateMotion ref={ref} dur="1.4s" begin="indefinite" fill="freeze" path={p.d}
        keyPoints={p.reverse ? "1;0" : "0;1"} keyTimes="0;1" calcMode="linear" />
    </circle>
  );
}
