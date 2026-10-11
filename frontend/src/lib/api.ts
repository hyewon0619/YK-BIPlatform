/** 백엔드 API 래퍼. vite proxy 가 /api 를 :8000 으로 넘긴다. */

export type Funnel = {
  date: string;
  calls: number;
  reservations: number;
  visits: number;
  contracts: number;
  revenue: number;
  success_fee: number;
  reservation_rate: number;
  visit_rate: number;
  contract_rate: number;
  overall_rate: number;
  value_per_contract: number;
  revenue_per_call: number;
};

export type SnapshotResponse = {
  current: Funnel;
  history: Funnel[];
  baseline: Record<string, number>;
  delta_pct: Record<string, number>;
  weeks: number;
};

export type DrilldownRow = {
  name: string;
  calls: number;
  reservations: number;
  visits: number;
  contracts: number;
  revenue: number;
  overall_rate: number;
  revenue_share: number;
  revenue_per_call: number;
};

export type Grain = "daily" | "weekly" | "monthly";

export type Scored = {
  metric: string;
  label: string;
  kind: "count" | "amount" | "rate";
  value: number;
  baseline_mean: number;
  z: number;
  delta: number;
  unit: string;
  direction: string;
  score: number;
  candidate: boolean;
};

export type Highlights = {
  grain: Grain;
  period: [string, string];
  baseline_periods: number;
  official: boolean;
  values: Record<string, number>;
  highlights: Scored[];
  all: Scored[];
};

export type WhyItem = {
  value: string;
  contribution: number;
  mix_effect?: number;
  conversion_effect?: number;
};

export type Why = {
  metric: string;
  label: string;
  dimension: string;
  dimension_label: string;
  parent: string | null;
  now: number;
  baseline: number;
  card_baseline: number;
  difference: number;
  sum_of_contributions: number;
  effects: { amount_effect: number; count_effect: number } | null;
  explained_top3_pct: number;
  no_clear_cause: boolean;
  official: boolean;
  items: WhyItem[];
  message?: string;
};

export type Forecast = {
  view: "current";
  month: string;
  elapsed_days: number;
  total_days: number;
  confirmed: { same_day: number; collected: number; refund: number; total: number };
  scheduled: {
    principal: number;
    expected: number;
    uncollected_expected: number;
    buckets: { bucket: string; principal: number; expected: number }[];
  };
  new_inflow: { expected_contracts: number; avg_amount: number; pay_ratio: number; value: number };
  forecast: number;
  target: number | null;
  achievement: number | null;
  color: "green" | "orange" | "red" | null;
  formula: string;
  history: { month: string; confirmed: number }[];
};

export type PreviousMonth = {
  view: "previous";
  month: string;
  confirmed: { same_day: number; collected: number; refund: number; total: number };
};

export type SuccessFee = {
  pending_count: number;
  pending_max: number;
  expected: number;
  by_major: Record<string, number>;
  levels_used: Record<string, number>;
};

export type Recommendation = {
  case_type_id: number;
  label: string;
  because_of: string;
  pair_count: number;
  probability: number;
  contents: {
    content_id: number;
    kind: string;
    title: string;
    similarity: number;
    keyword_overlap: number;
    match_level: string;
    url: string | null;
  }[];
};

export type Meta = {
  start: string;
  end: string;
  total_consultations: number;
  dimensions: string[];
  decompose_dimensions: Record<string, string>;
  metrics: Record<string, string>;
};

let currentUser = "admin";
export function setUser(user: string) {
  currentUser = user;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { "X-User": currentUser } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>("/api/meta"),
  menus: () => get<{ user: string; menus: string[] }>("/api/me/menus"),
  highlights: (target: string, grain: Grain, exclude: boolean) =>
    get<Highlights>(`/api/monitoring/highlights?target=${target}&grain=${grain}&exclude=${exclude}`),
  why: (target: string, grain: Grain, exclude: boolean, metric: string, dimension: string, parent?: string) =>
    get<Why>(
      `/api/monitoring/why?target=${target}&grain=${grain}&exclude=${exclude}&metric=${metric}` +
        `&dimension=${dimension}${parent ? `&parent=${encodeURIComponent(parent)}` : ""}`
    ),
  snapshot: (target: string, weeks = 12) =>
    get<SnapshotResponse>(`/api/funnel/snapshot?target=${target}&weeks=${weeks}`),
  drilldown: (dimension: string, start: string, end: string) =>
    get<{ label: string; rows: DrilldownRow[] }>(`/api/drilldown?dimension=${dimension}&start=${start}&end=${end}`),
  forecast: (asOf: string) => get<Forecast>(`/api/forecast/revenue?as_of=${asOf}`),
  previousMonth: (asOf: string) => get<PreviousMonth>(`/api/forecast/revenue?as_of=${asOf}&view=previous`),
  successFee: () => get<SuccessFee>("/api/forecast/success-fee"),
  recommendTargets: (asOf: string) =>
    get<{ engagement_id: number; contract_date: string; major: string; minor: string }[]>(
      `/api/recommend/targets?as_of=${asOf}`
    ),
  recommend: (id: number) =>
    get<{ engagement_id: number; owned: string[]; recommendations: Recommendation[] }>(`/api/recommend/${id}`),
};

/** 원 단위를 억/만 단위 한글로 줄여 표기한다. */
export function won(value: number): string {
  const sign = value < 0 ? "−" : "";
  const v = Math.abs(value);
  if (v >= 100_000_000) return `${sign}${(v / 100_000_000).toFixed(1)}억`;
  if (v >= 10_000) return `${sign}${Math.round(v / 10_000).toLocaleString()}만`;
  return `${sign}${Math.round(v).toLocaleString()}`;
}

export function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}
