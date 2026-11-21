import { useState } from "react";
import type { RegionRollup, RegionRow } from "./types";

// Simple tile-grid map of the US: one square per state at [row, col].
const US_TILES: Record<string, [number, number]> = {
  AK: [0, 0], ME: [0, 11],
  VT: [1, 10], NH: [1, 11],
  WA: [2, 1], ID: [2, 2], MT: [2, 3], ND: [2, 4], MN: [2, 5], IL: [2, 6], WI: [2, 7], MI: [2, 8], NY: [2, 9], RI: [2, 10], MA: [2, 11],
  OR: [3, 1], NV: [3, 2], WY: [3, 3], SD: [3, 4], IA: [3, 5], IN: [3, 6], OH: [3, 7], PA: [3, 8], NJ: [3, 9], CT: [3, 10],
  CA: [4, 1], UT: [4, 2], CO: [4, 3], NE: [4, 4], MO: [4, 5], KY: [4, 6], WV: [4, 7], VA: [4, 8], MD: [4, 9], DE: [4, 10],
  AZ: [5, 2], NM: [5, 3], KS: [5, 4], AR: [5, 5], TN: [5, 6], NC: [5, 7], SC: [5, 8], DC: [5, 9],
  OK: [6, 4], LA: [6, 5], MS: [6, 6], AL: [6, 7], GA: [6, 8],
  HI: [7, 0], TX: [7, 4], FL: [7, 9],
};

const STATE_NAMES: Record<string, string> = {
  CA: "California", TX: "Texas", FL: "Florida", NY: "New York", WA: "Washington", IL: "Illinois",
  NV: "Nevada", GA: "Georgia", MA: "Massachusetts", NC: "North Carolina", CO: "Colorado", AZ: "Arizona", HI: "Hawaii",
};

const COUNTRY_NAMES: Record<string, string> = {
  GB: "United Kingdom", DE: "Germany", FR: "France", CA: "Canada", MX: "Mexico",
  JP: "Japan", AU: "Australia", ES: "Spain", IN: "India",
};

const STATUS_TEXT = { ok: "Normal", watch: "Watch", alert: "Problem" } as const;

const pct = (v: number | null | undefined, digits = 1) => (v == null ? "–" : `${(v * 100).toFixed(digits)}%`);
const usd = (v: number) => `$${v.toLocaleString()}`;

export default function Regions({ kind, data }: { kind: "us" | "intl"; data: RegionRollup }) {
  const names = kind === "us" ? STATE_NAMES : COUNTRY_NAMES;
  const [picked, setPicked] = useState<string | null>(null);
  const alertRow = data.rows.find((r) => r.status === "alert");
  const sel = data.rows.find((r) => r.code === picked) ?? alertRow ?? data.rows[0];
  const title = kind === "us" ? "United States, by state" : "International, by country";

  return (
    <>
      <div className="kpis">
        <Kpi label="Searches (last 20s)" value={data.searches.toLocaleString()} />
        <Kpi label="Bookings" value={data.bookings.toLocaleString()} />
        <Kpi label="Search → booking" value={pct(data.conversion)} />
        <Kpi label="Booking value" value={usd(data.revenue_usd)} />
        <Kpi label="Stuck bookings" value={String(data.stuck_orders)} warn={data.stuck_orders > 0} />
        <Kpi label={kind === "us" ? "States with a problem" : "Countries with a problem"}
          value={String(data.alerts)} warn={data.alerts > 0} />
      </div>

      {alertRow && (
        <div className="pill bad regionalert">
          ⚠ {names[alertRow.code] ?? alertRow.code}: only {pct(alertRow.conversion)} of searches end in a booking,{" "}
          {Math.round(alertRow.vs_others * 100)}% of the rate in other {kind === "us" ? "states" : "countries"}.
          {alertRow.agent_flag ? ` ${alertRow.agent_flag}.` : ""}
        </div>
      )}

      <div className="grid two">
        <section className="card">
          <h2>{title} <small>click a {kind === "us" ? "state" : "country"} to see its funnel</small></h2>
          {kind === "us" ? (
            <UsMap rows={data.rows} selected={sel?.code} onPick={setPicked} />
          ) : (
            <CountryBars rows={data.rows} names={names} selected={sel?.code} onPick={setPicked} />
          )}
          <Legend />
        </section>
        <section className="card">
          {sel ? (
            <>
              <h2>
                {names[sel.code] ?? sel.code} <small>{STATUS_TEXT[sel.status]}</small>
              </h2>
              <MiniFunnel labels={data.stage_labels} counts={sel.stages} compare={data.stages} />
              <div className="facts">
                <div><span>Payment success</span><b>{pct(sel.payment_success, 0)}</b></div>
                <div><span>Booking value</span><b>{usd(sel.revenue_usd)}</b></div>
                <div><span>Stuck bookings</span><b>{sel.stuck_orders}</b></div>
                <div><span>Conversion vs others</span><b>{Math.round(sel.vs_others * 100)}%</b></div>
              </div>
              {sel.agent_flag && <div className="diag">{sel.agent_flag}</div>}
              <p className="muted small">
                Grey bars show the {kind === "us" ? "US" : "international"} average funnel, scaled to the same number
                of searches, so you can see where this {kind === "us" ? "state" : "country"} loses travelers.
              </p>
            </>
          ) : (
            <p className="muted">No data yet.</p>
          )}
        </section>
      </div>

      <section className="card">
        <h2>All {kind === "us" ? "states" : "countries"}</h2>
        <table className="regions">
          <thead>
            <tr>
              <th>{kind === "us" ? "State" : "Country"}</th><th>Status</th><th className="num">Searches</th>
              <th className="num">Bookings</th><th className="num">Search → booking</th>
              <th className="num">Payment success</th><th className="num">Value</th><th className="num">Stuck</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.code} className={r.code === sel?.code ? "sel" : ""} onClick={() => setPicked(r.code)}>
                <td><b>{r.code}</b> {names[r.code] ?? ""}</td>
                <td><span className={`st ${r.status}`}>{STATUS_TEXT[r.status]}</span></td>
                <td className="num">{r.searches.toLocaleString()}</td>
                <td className="num">{r.bookings}</td>
                <td className="num">{pct(r.conversion)}</td>
                <td className="num">{pct(r.payment_success, 0)}</td>
                <td className="num">{usd(r.revenue_usd)}</td>
                <td className="num">{r.stuck_orders}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">
          "Problem" means conversion is far below the other {kind === "us" ? "states" : "countries"} and the gap is
          too big to be random noise. It is computed from the data only.
        </p>
      </section>
    </>
  );
}

function Kpi({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className={`kpi ${warn ? "warn" : ""}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      <span><i className="st ok" /> Normal</span>
      <span><i className="st watch" /> Watch</span>
      <span><i className="st alert" /> Problem</span>
      <span><i className="st none" /> No traffic in demo</span>
    </div>
  );
}

function UsMap({ rows, selected, onPick }: { rows: RegionRow[]; selected?: string; onPick: (c: string) => void }) {
  const byCode = new Map(rows.map((r) => [r.code, r]));
  return (
    <div className="usmap">
      {Object.entries(US_TILES).map(([code, [row, col]]) => {
        const r = byCode.get(code);
        return (
          <button
            key={code}
            className={`tile ${r ? r.status : "none"} ${code === selected ? "picked" : ""}`}
            style={{ gridRow: row + 1, gridColumn: col + 1 }}
            disabled={!r}
            onClick={() => onPick(code)}
            title={r ? `${code}: ${r.searches} searches, ${pct(r.conversion)} book` : `${code}: no demo traffic`}
          >
            <b>{code}</b>
            {r && <small>{pct(r.conversion, 0)}</small>}
          </button>
        );
      })}
    </div>
  );
}

function CountryBars({ rows, names, selected, onPick }: {
  rows: RegionRow[]; names: Record<string, string>; selected?: string; onPick: (c: string) => void;
}) {
  const max = Math.max(1, ...rows.map((r) => r.searches));
  return (
    <ul className="cbars">
      {rows.map((r) => (
        <li key={r.code} className={r.code === selected ? "picked" : ""} onClick={() => onPick(r.code)}>
          <span className="cname"><b>{r.code}</b> {names[r.code] ?? ""}</span>
          <div className="cbar"><div className={r.status} style={{ width: `${(r.searches / max) * 100}%` }} /></div>
          <span className="cnum">{pct(r.conversion)}</span>
        </li>
      ))}
    </ul>
  );
}

function MiniFunnel({ labels, counts, compare }: { labels: string[]; counts: number[]; compare: number[] }) {
  const base = counts[0] || 1;
  const scale = compare[0] ? counts[0] / compare[0] : 0;
  return (
    <div className="mini">
      {labels.map((l, i) => {
        const avg = compare[i] * scale;
        const worse = i > 0 && counts[i] < avg * 0.7;
        return (
          <div key={l} className="mrow">
            <span>{l}</span>
            <div className="mbar">
              <div className="avg" style={{ width: `${(avg / base) * 100}%` }} />
              <div className={`val ${worse ? "worse" : ""}`} style={{ width: `${(counts[i] / base) * 100}%` }} />
            </div>
            <b>{counts[i].toLocaleString()}</b>
          </div>
        );
      })}
    </div>
  );
}
