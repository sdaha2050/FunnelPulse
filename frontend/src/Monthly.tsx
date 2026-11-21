import { useEffect, useMemo, useState } from "react";
import type { MonthlyData, MonthRow } from "./types";

const fmt = (n: number) => n.toLocaleString();
const short = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n);
const usd = (n: number) => `$${short(n)}`;
const pct = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`;

export default function Monthly() {
  const [d, setD] = useState<MonthlyData | null>(null);
  const [sel, setSel] = useState<string>("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/monthly")
      .then((r) => r.json())
      .then((data: MonthlyData) => {
        setD(data);
        setSel(data.months[data.months.length - 2].month); // last full month
      });
  }, []);

  const view = useMemo(() => {
    if (!d || !sel) return null;
    const i = d.months.findIndex((m) => m.month === sel);
    const m = d.months[i];
    const prev = i > 0 ? d.months[i - 1] : null;
    const totalLost = Math.max(1, m.lost_bookings);
    const issues = d.issues
      .map((it) => {
        const lost = m.lost_by_issue[it.id];
        const before = prev ? prev.lost_by_issue[it.id] : 0;
        return { ...it, lost, share: lost / totalLost, change: before ? (lost - before) / before : null };
      })
      .sort((a, b) => b.lost - a.lost);
    return { i, m, prev, issues };
  }, [d, sel]);

  if (!d || !view) return <p className="muted">Loading monthly data…</p>;
  const { m, prev, issues } = view;

  // Lost bookings grouped by funnel stage (where travelers drop).
  const byStage = new Map<string, number>();
  issues.forEach((it) => byStage.set(it.stage, (byStage.get(it.stage) ?? 0) + it.lost));
  const stageRows = d.stage_labels.slice(1).map((s) => ({ stage: s, lost: byStage.get(s) ?? 0 }));
  const maxStage = Math.max(1, ...stageRows.map((r) => r.lost));
  const top = issues[0];

  return (
    <>
      <div className="monthbar">
        <label>
          Month:{" "}
          <select value={sel} onChange={(e) => setSel(e.target.value)}>
            {d.months.map((x) => (
              <option key={x.month} value={x.month}>{x.label}</option>
            ))}
          </select>
        </label>
        <span className="muted">{d.note} Lost value uses an average booking of ${d.avg_booking_usd}.</span>
      </div>

      <div className="kpis">
        <Kpi label="Searches" value={short(m.searches)} cur={m.searches} prev={prev?.searches} />
        <Kpi label="Bookings" value={short(m.bookings)} cur={m.bookings} prev={prev?.bookings} />
        <Kpi label="Search → booking" value={pct(m.conversion, 2)} cur={m.conversion} prev={prev?.conversion} />
        <Kpi label="Booking value" value={usd(m.revenue_usd)} cur={m.revenue_usd} prev={prev?.revenue_usd} />
        <Kpi label="Bookings lost to top issues" value={short(m.lost_bookings)} cur={m.lost_bookings}
          prev={prev?.lost_bookings} badIsUp />
        <Kpi label="Value lost" value={usd(m.lost_bookings * d.avg_booking_usd)} cur={m.lost_bookings}
          prev={prev?.lost_bookings} badIsUp />
      </div>
      {m.partial && <p className="muted">This month is not over yet, so totals are month to date.</p>}

      <div className="pill bad regionalert">
        Biggest issue in {m.label}: <b>{top.title}</b>, about {fmt(top.lost)} lost bookings
        ({pct(top.share, 0)} of all losses). Root cause: {top.root_cause}
      </div>

      <div className="grid two">
        <section className="card">
          <h2>Bookings and conversion, last 12 months <small>bars = bookings, line = search → booking</small></h2>
          <TrendChart months={d.months} selected={sel} onPick={setSel} />
        </section>
        <section className="card">
          <h2>Where bookings are lost <small>{m.label}, by funnel stage</small></h2>
          <div className="mini">
            {stageRows.map((r) => (
              <div key={r.stage} className="mrow wide">
                <span>{r.stage}</span>
                <div className="mbar">
                  <div className="val worse" style={{ width: `${(r.lost / maxStage) * 100}%` }} />
                </div>
                <b>{short(r.lost)}</b>
              </div>
            ))}
          </div>
          <p className="muted small">
            Each bar is bookings lost to known issues at that stage. Travelers lost early are counted only as the share
            who would normally have gone on to book.
          </p>
        </section>
      </div>

      <section className="card">
        <h2>Top {issues.length} issues causing the drop <small>{m.label}, ranked by lost bookings · click a row for the root cause</small></h2>
        <table className="regions issues">
          <thead>
            <tr>
              <th>#</th><th>Issue</th><th>Stage</th><th className="num">Lost bookings</th>
              <th className="num">Lost value</th><th>Share of loss</th><th className="num">vs last month</th>
              <th>12-month trend</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {issues.map((it, idx) => (
              <IssueRow key={it.id} it={it} rank={idx + 1} avg={d.avg_booking_usd} sel={view.i}
                open={open === it.id} onToggle={() => setOpen(open === it.id ? null : it.id)} />
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function Kpi({ label, value, cur, prev, badIsUp }: {
  label: string; value: string; cur: number; prev?: number; badIsUp?: boolean;
}) {
  const ch = prev ? (cur - prev) / prev : null;
  const bad = ch != null && (badIsUp ? ch > 0 : ch < 0);
  return (
    <div className="kpi">
      <span>{label}</span>
      <b>{value}</b>
      {ch != null && (
        <em className={bad ? "down" : "up"}>
          {ch >= 0 ? "▲" : "▼"} {Math.abs(ch * 100).toFixed(1)}% vs prior month
        </em>
      )}
    </div>
  );
}

type IssueView = MonthlyData["issues"][number] & { lost: number; share: number; change: number | null };

function IssueRow({ it, rank, avg, sel, open, onToggle }: {
  it: IssueView; rank: number; avg: number; sel: number; open: boolean; onToggle: () => void;
}) {
  return (
    <>
      <tr className={open ? "sel" : ""} onClick={onToggle}>
        <td><b>{rank}</b></td>
        <td><b>{it.title}</b></td>
        <td><span className="stage">{it.stage}</span></td>
        <td className="num">{fmt(it.lost)}</td>
        <td className="num">{usd(it.lost * avg)}</td>
        <td>
          <div className="share"><div style={{ width: `${it.share * 100}%` }} /></div>
          <small>{pct(it.share, 0)}</small>
        </td>
        <td className={`num ${it.change != null && it.change > 0 ? "badc" : "okc"}`}>
          {it.change == null ? "–" : `${it.change > 0 ? "▲" : "▼"} ${Math.abs(it.change * 100).toFixed(0)}%`}
        </td>
        <td><Spark values={it.trend} mark={sel} /></td>
        <td><span className="status">{it.status}</span></td>
      </tr>
      {open && (
        <tr className="detail">
          <td />
          <td colSpan={8}>
            <div className="rc">
              <div><span>Root cause</span>{it.root_cause}</div>
              <div><span>Evidence</span>{it.evidence}</div>
              <div><span>Found by</span>{it.found_by}</div>
              <div><span>Fix</span>{it.fix}</div>
              <div><span>Owner</span>{it.owner}</div>
              <div><span>Lost value, 12 months</span>{usd(it.year_lost_revenue_usd)}</div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Spark({ values, mark }: { values: number[]; mark: number }) {
  const w = 110, h = 26, max = Math.max(1, ...values);
  const x = (i: number) => (i / (values.length - 1)) * (w - 4) + 2;
  const y = (v: number) => h - 3 - (v / max) * (h - 6);
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <svg width={w} height={h} role="img" aria-label="12-month trend">
      <polyline points={pts} fill="none" stroke="#dc2626" strokeWidth="1.5" />
      <circle cx={x(mark)} cy={y(values[mark])} r="3" fill="#0f172a" />
    </svg>
  );
}

function TrendChart({ months, selected, onPick }: { months: MonthRow[]; selected: string; onPick: (m: string) => void }) {
  const W = 640, H = 240, L = 44, R = 44, T = 16, B = 34;
  const iw = W - L - R, ih = H - T - B;
  const maxB = Math.max(...months.map((m) => m.bookings)) * 1.1;
  const convs = months.map((m) => m.conversion);
  const cMin = Math.min(...convs) * 0.9, cMax = Math.max(...convs) * 1.05;
  const bw = iw / months.length;
  const yB = (v: number) => T + ih - (v / maxB) * ih;
  const yC = (v: number) => T + ih - ((v - cMin) / (cMax - cMin)) * ih;
  const line = months.map((m, i) => `${L + bw * i + bw / 2},${yC(m.conversion)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="trend" role="img" aria-label="Bookings and conversion by month">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={L} x2={W - R} y1={T + ih * (1 - f)} y2={T + ih * (1 - f)} stroke="#e2e8f0" />
          <text x={L - 6} y={T + ih * (1 - f) + 4} textAnchor="end" fontSize="11" fill="#64748b">{short(maxB * f)}</text>
          <text x={W - R + 6} y={T + ih * (1 - f) + 4} fontSize="11" fill="#64748b">
            {pct(cMin + (cMax - cMin) * f, 1)}
          </text>
        </g>
      ))}
      {months.map((m, i) => (
        <g key={m.month} onClick={() => onPick(m.month)} style={{ cursor: "pointer" }}>
          <rect x={L + bw * i + bw * 0.18} y={yB(m.bookings)} width={bw * 0.64} height={T + ih - yB(m.bookings)}
            rx="3" fill={m.month === selected ? "#1d4ed8" : "#93c5fd"} opacity={m.partial ? 0.55 : 1} />
          <text x={L + bw * i + bw / 2} y={H - 14} textAnchor="middle" fontSize="11"
            fill={m.month === selected ? "#0f172a" : "#64748b"} fontWeight={m.month === selected ? 700 : 400}>
            {m.label.slice(0, 3)}
          </text>
        </g>
      ))}
      <polyline points={line} fill="none" stroke="#dc2626" strokeWidth="2" />
      {months.map((m, i) => (
        <circle key={m.month} cx={L + bw * i + bw / 2} cy={yC(m.conversion)} r="3" fill="#dc2626" />
      ))}
    </svg>
  );
}
