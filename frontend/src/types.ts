// Shapes returned by GET /api/state

export interface FunnelStage {
  stage: string;
  label: string;
  count: number;
  next_rate: number | null;
  baseline: number | null;
}

export interface Anomaly {
  key: string;
  from_stage: string;
  to_stage: string;
  label: string;
  rate: number;
  baseline: number;
  drop_pct: number;
}

export interface Action {
  id: string;
  type: string;
  tier: number;
  title: string;
  owner: string;
  evidence: string[];
  severity: string;
  reason: string;
  impact: string;
  status?: string;
  ts: number;
  result?: { ok: boolean; detail: string };
  note?: string;
  decision?: { decision: string; rule: string | null; reason: string };
}

export interface Message {
  id: number;
  ts: number;
  sender: string;
  to: string;
  topic: string;
  text: string;
}

export interface Score {
  name: string;
  value: number | null;
  target: string;
  unit: string;
  help: string;
  pass: boolean | null;
}

export interface Mishap {
  rule: string;
  label: string;
  count: number;
  example: string;
}

export interface State {
  now: number;
  incident: { type: string; label: string; real: boolean; seconds_left: number } | null;
  incident_types: Record<string, string>;
  data_quality: { reliable: boolean; reason: string; checks: Record<string, boolean> };
  funnel: FunnelStage[];
  anomalies: Anomaly[];
  events: { ts: number; id: string; brand: string; market: string; device: string; stage: string; schema_ok: boolean; booked: boolean }[];
  messages: Message[];
  stuck_orders: { id: string; supplier: string; checkin_hours: number; retries: number; status: string; waiting_s: number }[];
  auto_actions: Action[];
  approvals: Action[];
  waiting_for_human: number;
  decided: Action[];
  blocked: Action[];
  guardrails: {
    kill_switch: { global: boolean; types: string[] };
    data_reliable: boolean;
    mishaps: Mishap[];
    mishaps_total: number;
  };
  evals: {
    scores: Score[];
    incidents: { label: string; real: boolean; active: boolean; ttd: number | null; rca_correct: boolean | null; outcome: string }[];
    bad_data_suppressed: number;
  };
  diagnoses: { summary: string; label: string; llm_summary?: string }[];
  regions: { us: RegionRollup; intl: RegionRollup };
}

export interface RegionRow {
  code: string;
  searches: number;
  bookings: number;
  conversion: number;
  vs_others: number;
  z: number;
  payment_success: number | null;
  stages: number[];
  revenue_usd: number;
  stuck_orders: number;
  status: "ok" | "watch" | "alert";
  agent_flag: string | null;
}

export interface RegionRollup {
  searches: number;
  bookings: number;
  conversion: number;
  revenue_usd: number;
  stuck_orders: number;
  stage_labels: string[];
  stages: number[];
  alerts: number;
  rows: RegionRow[];
}
