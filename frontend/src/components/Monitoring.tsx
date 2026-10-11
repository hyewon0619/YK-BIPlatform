import { useEffect, useState } from "react";
import { api, won, type Grain, type Highlights, type Scored, type Why } from "../lib/api";

const GRAINS: { key: Grain; label: string; base: string }[] = [
  { key: "daily", label: "일간", base: "같은 요일 12주" },
  { key: "weekly", label: "주간", base: "직전 12주" },
  { key: "monthly", label: "월간", base: "직전 3개월" },
];

function fmt(kind: Scored["kind"], v: number): string {
  if (kind === "rate") return `${v.toFixed(1)}%`;
  if (kind === "amount") return `${won(v)}원`;
  return `${Math.round(v).toLocaleString()}건`;
}

type Props = { target: string; dimensions: Record<string, string> };

/** ④ 경영 모니터링: 평소와 다른 지표 상위 3개 + 지표 카드 + "왜?" 원인 분해. */
export default function Monitoring({ target, dimensions }: Props) {
  const [grain, setGrain] = useState<Grain>("daily");
  const [exclude, setExclude] = useState(false);
  const [data, setData] = useState<Highlights | null>(null);
  const [why, setWhy] = useState<{ metric: string; dimension: string; parent?: string } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target) return;
    let stale = false;
    api.highlights(target, grain, exclude)
      .then((d) => { if (!stale) setData(d); })
      .catch((e) => { if (!stale) setError(String(e)); });
    return () => { stale = true; };
  }, [target, grain, exclude]);

  if (error) return <p className="text-xs text-rose-600">{error}</p>;
  if (!data) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  const baseLabel = GRAINS.find((g) => g.key === grain)!.base;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {GRAINS.map((g) => (
          <button key={g.key} onClick={() => setGrain(g.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${grain === g.key ? "bg-slate-900 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}>
            {g.label}
          </button>
        ))}
        <span className="text-xs text-slate-500">{data.period[0]}{data.period[0] !== data.period[1] && ` ~ ${data.period[1]}`} · 기준 {baseLabel}</span>
        <label className="ml-auto flex items-center gap-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} />
          자문·저액 선임 제외
          {!data.official && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800">공식 수치와 다름</span>}
        </label>
      </div>

      <section className={`rounded-xl border px-4 py-3 ${data.highlights.length ? "border-rose-200 bg-rose-50" : "border-emerald-200 bg-emerald-50"}`}>
        <div className={`text-sm font-semibold ${data.highlights.length ? "text-rose-800" : "text-emerald-800"}`}>
          {data.highlights.length ? "눈에 띄는 수치" : "평소 범위 안"}
        </div>
        {data.highlights.length === 0 && (
          <p className="mt-0.5 text-xs text-emerald-700">지표 {data.all.length}개 모두 {baseLabel} 기준 안에 있습니다.</p>
        )}
        <ul className="mt-1.5 space-y-1">
          {data.highlights.map((h) => (
            <li key={h.metric} className="flex flex-wrap items-center gap-2 text-xs text-rose-900">
              <span className="font-semibold">{h.label}</span>
              <span>{h.direction} {h.delta}{h.unit}</span>
              <span className="text-rose-700">({fmt(h.kind, h.value)} · 평소 {fmt(h.kind, h.baseline_mean)} · z {h.z})</span>
              <button onClick={() => setWhy({ metric: h.metric, dimension: "case_major" })}
                className="rounded bg-white px-1.5 py-0.5 text-[11px] font-medium text-rose-700 ring-1 ring-rose-200">왜?</button>
            </li>
          ))}
        </ul>
      </section>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {data.all.map((m) => {
          const diff = m.baseline_mean ? ((m.value - m.baseline_mean) / m.baseline_mean) * 100 : 0;
          return (
            <div key={m.metric} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                {m.label}
                <button onClick={() => setWhy({ metric: m.metric, dimension: "case_major" })}
                  className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200">왜?</button>
              </div>
              <div className="mt-1 text-xl font-bold tabular-nums text-slate-900">{fmt(m.kind, m.value)}</div>
              <div className={`mt-1 text-xs ${Math.abs(diff) < 0.05 ? "text-slate-400" : diff > 0 ? "text-emerald-600" : "text-rose-600"}`}>
                {diff > 0 ? "▲" : diff < 0 ? "▼" : ""} {Math.abs(diff).toFixed(1)}% <span className="text-slate-400">(평소 {fmt(m.kind, m.baseline_mean)})</span>
              </div>
            </div>
          );
        })}
      </section>

      {why && (
        <WhyPanel target={target} grain={grain} exclude={exclude} dimensions={dimensions}
          metric={why.metric} dimension={why.dimension} parent={why.parent}
          onChange={(dimension, parent) => setWhy({ metric: why.metric, dimension, parent })}
          onClose={() => setWhy(null)} />
      )}
    </div>
  );
}

type WhyProps = {
  target: string; grain: Grain; exclude: boolean; dimensions: Record<string, string>;
  metric: string; dimension: string; parent?: string;
  onChange: (dimension: string, parent?: string) => void; onClose: () => void;
};

function WhyPanel({ target, grain, exclude, dimensions, metric, dimension, parent, onChange, onClose }: WhyProps) {
  const [data, setData] = useState<Why | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let stale = false;
    setError("");
    api.why(target, grain, exclude, metric, dimension, parent)
      .then((d) => { if (!stale) setData(d); })
      .catch((e) => { if (!stale) setError(String(e)); });
    return () => { stale = true; };
  }, [target, grain, exclude, metric, dimension, parent]);

  const isRate = metric === "contract_rate";
  const isAmount = metric === "revenue" || metric === "value_per_contract";
  const level = (v: number) => (isRate ? `${v.toFixed(1)}%` : isAmount ? `${won(v)}원` : `${v.toLocaleString()}건`);
  const unit = (v: number) => (isRate ? `${v > 0 ? "+" : ""}${v.toFixed(2)}%p` : metric === "revenue" || metric === "value_per_contract" ? `${v > 0 ? "+" : ""}${won(v)}원` : `${v > 0 ? "+" : ""}${v.toFixed(1)}건`);
  const max = Math.max(1e-9, ...(data?.items ?? []).map((i) => Math.abs(i.contribution)));

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">
          왜? — {data?.label ?? metric}{parent && ` · ${parent}`}
        </h2>
        <button onClick={onClose} className="text-xs text-slate-500">닫기</button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {Object.entries(dimensions).filter(([k]) => !(isRate && (k === "retain_type" || k === "amount_bucket"))).map(([k, label]) => (
          <button key={k} onClick={() => onChange(k)}
            className={`rounded-md px-2 py-1 text-[11px] font-medium ${dimension === k ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {error && <p className="mt-3 text-xs text-rose-600">{error}</p>}
      {data && data.message && <p className="mt-3 text-xs text-slate-500">{data.message}</p>}
      {data && !data.message && (
        <>
          <p className="mt-3 text-xs text-slate-600">
            이번 {level(data.now)} · 기준 {level(data.baseline)}
            {" "}→ 차이 <b>{unit(data.difference)}</b> · 기여도 합 {unit(data.sum_of_contributions)}
            {" "}· 상위 3개 설명력 {data.explained_top3_pct}%
            {data.no_clear_cause && <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5">특별한 원인 없음</span>}
          </p>
          {data.effects && (
            <p className="mt-1 text-xs text-slate-500">
              금액 효과 {unit(data.effects.amount_effect)} + 건수 효과 {unit(data.effects.count_effect)}
            </p>
          )}
          <ul className="mt-3 space-y-1.5">
            {data.items.slice(0, 10).map((it) => (
              <li key={it.value} className="grid grid-cols-[8rem_1fr_6.5rem] items-center gap-2 text-xs">
                <button disabled={dimension !== "case_major"} onClick={() => onChange("case_minor", it.value)}
                  className={`truncate text-left ${dimension === "case_major" ? "text-indigo-700 underline" : "text-slate-700"}`}>
                  {it.value}
                </button>
                <div className="relative h-3 rounded bg-slate-50">
                  <div className={`absolute top-0 h-3 rounded ${it.contribution < 0 ? "right-1/2 bg-rose-400" : "left-1/2 bg-emerald-400"}`}
                    style={{ width: `${(Math.abs(it.contribution) / max) * 50}%` }} />
                </div>
                <span className="text-right tabular-nums text-slate-700">{unit(it.contribution)}</span>
              </li>
            ))}
          </ul>
          {isRate && <p className="mt-2 text-[11px] text-slate-400">각 행 = 구성 효과(평균 대비 어떤 고객이 왔나) + 전환 효과(같은 고객을 더 잘 잡았나)</p>}
          {Math.abs(data.baseline - data.card_baseline) > 0.005 && (
            <p className="mt-1 text-[11px] text-slate-400">카드 기준값(기간별 단순 평균) {level(data.card_baseline)} · 분해 기준값(기간 합산) {level(data.baseline)}</p>
          )}
        </>
      )}
    </section>
  );
}
