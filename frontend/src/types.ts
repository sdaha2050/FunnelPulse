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
  data_quality: { reliable: boolean; reason: string; checks: Record<string, boolean>; lag_seconds: number };
  settings: { auto_incidents: boolean };
  pipeline: {
    delay_range: number[];
    lag: number;
    in_flight_events: number;
    in_flight: { event_ts: number; land_at: number; count: number; bookings: number }[];
    landed_events: number;
  };
  funnel: FunnelStage[];
  anomalies: Anomaly[];
  events: { ts: number; event_ts: number; lag: number; id: string; brand: string; market: string; device: string; stage: string; schema_ok: boolean; booked: boolean }[];
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
    incidents: { label: string; real: boolean; active: boolean; ttd: number | null; rca_correct: boolean | null; outcome: string; lag: number }[];
    bad_data_suppressed: number;
  };
  diagnoses: {
    summary: string; label: string; llm_summary?: string;
    top: { dimension: string; value: string; confidence: number } | null;
  }[];
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

export interface MonthRow {
  month: string;
  label: string;
  partial: boolean;
  searches: number;
  bookings: number;
  conversion: number;
  revenue_usd: number;
  stages: number[];
  lost_by_issue: Record<string, number>;
  lost_bookings: number;
}

export interface MonthlyIssue {
  id: string;
  rank: number;
  title: string;
  stage: string;
  root_cause: string;
  evidence: string;
  found_by: string;
  owner: string;
  fix: string;
  status: string;
  lost_bookings: number;
  lost_revenue_usd: number;
  share_of_loss: number;
  change_vs_prev: number | null;
  trend: number[];
  year_lost_revenue_usd: number;
}

export interface MonthlyData {
  note: string;
  stage_labels: string[];
  avg_booking_usd: number;
  months: MonthRow[];
  ranked_on: string;
  issues: MonthlyIssue[];
}

export interface OrderView {
  id: string; status: string; label: string; tone: "ok" | "bad" | "wait";
  user_id: string | null; supplier: string; brand: string; market: string; state: string | null; device: string;
  payment_method: string; value_usd: number; checkin_hours: number; retries: number;
  traveler: string; email: string; age_seconds: number; pending_approval_id: string | null;
  timeline: { ts: number; ago: number; who: string; text: string }[];
}

export interface SessionView {
  session_id: string; outcome: string; why: string; issue: string | null;
  brand: string; market: string; state: string | null; device: string; supplier: string; payment_method: string;
  started_ago: number; order_id: string | null; in_pipeline: boolean; lands_in: number | null; lag: number | null;
  steps: { name: string; state: "done" | "dropped" | "waiting" | "not_reached"; ago: number | null }[];
}

export interface UserView { user_id: string; sessions: SessionView[]; booked: number; total: number }

export interface TraceView {
  id: string; name: string; sent_ago: number; count: number; events: object[]; done: boolean;
  steps: { key: string; title: string; status: "done" | "warn" | "active" | "pending" | "skipped"; text: string; why: string }[];
  orders: { id: string; label: string; tone: "ok" | "bad" | "wait"; user_id: string | null }[];
}
