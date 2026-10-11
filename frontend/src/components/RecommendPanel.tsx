import { useEffect, useState } from "react";
import { api, type Recommendation } from "../lib/api";

type Target = { engagement_id: number; contract_date: string; major: string; minor: string };

/** ② 별건 추천: 최근 선임 고객 → 추천 사건유형 상위 5개와 근거 콘텐츠. 발송은 사람이 "등록"만 한다. */
export default function RecommendPanel({ asOf }: { asOf: string }) {
  const [targets, setTargets] = useState<Target[]>([]);
  const [picked, setPicked] = useState<number | null>(null);
  const [rec, setRec] = useState<{ owned: string[]; recommendations: Recommendation[] } | null>(null);
  const [queued, setQueued] = useState<Set<string>>(new Set());

  useEffect(() => {
    let stale = false;
    api.recommendTargets(asOf).then((t) => { if (!stale) { setTargets(t); setPicked(t[0]?.engagement_id ?? null); } });
    return () => { stale = true; };
  }, [asOf]);
  useEffect(() => {
    let stale = false;
    if (picked) api.recommend(picked).then((r) => { if (!stale) setRec(r); });
    return () => { stale = true; };
  }, [picked]);

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
      <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <h2 className="px-1 text-xs font-semibold text-slate-500">최근 선임 고객</h2>
        <ul className="mt-2 max-h-[28rem] space-y-0.5 overflow-y-auto">
          {targets.map((t) => (
            <li key={t.engagement_id}>
              <button onClick={() => setPicked(t.engagement_id)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-xs ${picked === t.engagement_id ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                #{t.engagement_id} · {t.major} {t.minor} <span className="opacity-60">{t.contract_date.slice(5)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        {rec && (
          <>
            <p className="text-xs text-slate-500">보유 사건: {rec.owned.join(", ")}</p>
            {rec.recommendations.length === 0 && <p className="mt-3 text-sm text-slate-400">동시출현 2건 이상인 추천 유형이 없습니다.</p>}
            <ul className="mt-3 space-y-4">
              {rec.recommendations.map((r) => (
                <li key={r.case_type_id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">{r.label}</span>
                    <span className="text-xs text-slate-500">
                      {r.because_of} 선임 고객의 {(r.probability * 100).toFixed(1)}% ({r.pair_count}건)
                    </span>
                    <button disabled={queued.has(r.label)}
                      onClick={() => setQueued(new Set(queued).add(r.label))}
                      className="ml-auto rounded-md bg-indigo-600 px-2 py-1 text-[11px] font-medium text-white disabled:bg-slate-300">
                      {queued.has(r.label) ? "등록됨" : "전송 등록"}
                    </button>
                  </div>
                  <ul className="mt-1.5 space-y-1">
                    {r.contents.map((c) => (
                      <li key={c.content_id} className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{c.kind}</span>
                        {c.url ? <span className="text-indigo-700 underline">{c.title}</span> : <span className="text-slate-700">{c.title} (비공개)</span>}
                        <span className="text-slate-400">유사도 {c.similarity} · 키워드 겹침 {c.keyword_overlap} · {c.match_level}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-[11px] text-slate-400">
              전송 등록은 발송 대기열에만 넣는다. 실제 발송 직전에 마케팅 동의를 다시 조회하고, 조회가 실패하면 그 묶음을 통째로 보류한다.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
