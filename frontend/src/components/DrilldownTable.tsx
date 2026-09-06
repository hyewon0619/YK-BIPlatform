import { useState } from "react";
import { won, type DrilldownRow } from "../lib/api";

const DIMENSIONS = [
  { key: "branch", label: "지점" },
  { key: "region", label: "권역" },
  { key: "channel", label: "유입 채널" },
  { key: "category", label: "상담 유형" },
];

type Props = {
  rows: DrilldownRow[];
  dimension: string;
  onChange: (dimension: string) => void;
};

/** 퍼널이 떨어졌을 때 "어디가" 떨어졌는지 보는 표. */
export default function DrilldownTable({ rows, dimension, onChange }: Props) {
  const [sortKey, setSortKey] = useState<"revenue" | "overall_rate" | "calls">("revenue");
  const sorted = [...rows].sort((a, b) => b[sortKey] - a[sortKey]);
  const best = sorted[0]?.[sortKey] || 1;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">드릴다운</h2>
        <div className="flex gap-1">
          {DIMENSIONS.map((d) => (
            <button
              key={d.key}
              onClick={() => onChange(d.key)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                dimension === d.key
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[540px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs text-slate-500">
              <th className="py-2 text-left font-medium">구분</th>
              {(
                [
                  ["calls", "콜"],
                  ["overall_rate", "전환율"],
                  ["revenue", "매출"],
                ] as const
              ).map(([key, label]) => (
                <th key={key} className="py-2 text-right font-medium">
                  <button
                    onClick={() => setSortKey(key)}
                    className={`hover:text-slate-900 ${sortKey === key ? "text-slate-900 font-semibold" : ""}`}
                  >
                    {label} {sortKey === key && "↓"}
                  </button>
                </th>
              ))}
              <th className="py-2 text-right font-medium">비중</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.name} className="border-b border-slate-50 last:border-0">
                <td className="py-2 font-medium text-slate-800">{r.name}</td>
                <td className="py-2 text-right tabular-nums text-slate-600">
                  {r.calls.toLocaleString()}
                </td>
                <td className="py-2 text-right tabular-nums text-slate-600">{r.overall_rate}%</td>
                <td className="py-2 text-right tabular-nums font-medium text-slate-900">
                  {won(r.revenue)}
                </td>
                <td className="w-24 py-2 pl-3">
                  <div className="h-1.5 rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-indigo-500"
                      style={{ width: `${Math.max((r[sortKey] / best) * 100, 2)}%` }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
