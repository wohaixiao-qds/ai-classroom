/** Eval 观测页 —— 只管 agent 质量（学习进度归课表页）。
 *  三块：防假性完成指标 / 同问题历史(轻量抓回归) / 衍生候选。 */
import { ChevronDown, Compass, FlaskConical, History, MessageSquareText, Repeat, Search, CircleX } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { EmptyState } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Collapse } from "../../components/Collapse";
import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { useCountUp } from "../../hooks/useCountUp";
import { cn } from "../../lib/utils";

interface Summary {
  asks: number;
  quality: {
    grounded_rate: number;
    cited_rate: number;
    searched: number;
    unsourced_long: number;
    tool_error: number;
    soft_landed: number;
    truncated: number;
    self_eval_checked: number;
    self_eval_fabricated: number;
    self_eval_partial: number;
  };
  cost: {
    avg_elapsed_s: number;
    slowest_s: number;
    in_tokens: number;
    out_tokens: number;
    cache_hit_rounds: number;
  };
  verdict_counts: Record<string, number>;
}

interface TutorTrace {
  ts: string;
  question: string;
  answer: string;
  answer_len: number | null;
  cited_pages: number[];
  tool_calls: { name: string; args: Record<string, unknown>; ms: number; error: string | null }[];
  searched: boolean;
  grounded: boolean;
  tool_error: boolean;
  soft_landed: boolean;
  truncated: boolean;
  elapsed_s: number;
  usage: { input_tokens?: number; output_tokens?: number; cache_read?: number };
}

interface RepeatGroup {
  question: string;
  count: number;
  history: {
    ts: string;
    answer: string;
    answer_len: number | null;
    cited_pages: number[];
    grounded: boolean;
    elapsed_s: number;
  }[];
}

interface Gap {
  kind: "searched" | "repeated" | "checkpoint_fail";
  ts?: string;
  question: string;
  detail: string;
}

const GAP_META = {
  searched: { icon: Search, text: "课件未覆盖（联网查了）" },
  repeated: { icon: Repeat, text: "反复问（课件讲不清）" },
  checkpoint_fail: { icon: CircleX, text: "检查点未通过" },
} as const;

export function EvalPage() {
  const [sum, setSum] = useState<Summary | null>(null);
  const [tutor, setTutor] = useState<TutorTrace[]>([]);
  const [repeats, setRepeats] = useState<RepeatGroup[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [openTrace, setOpenTrace] = useState<number | null>(null);
  const [openRepeat, setOpenRepeat] = useState<number | null>(null);
  const [includeTest, setIncludeTest] = useState(false);

  useEffect(() => {
    const q = `?include_test=${includeTest}`;
    void fetch(`/api/v1/eval/summary${q}`).then((r) => r.json()).then(setSum);
    void fetch(`/api/v1/eval/traces${q}&limit=50`)
      .then((r) => r.json())
      .then((d: { tutor: TutorTrace[] }) => setTutor(d.tutor ?? []));
    void fetch(`/api/v1/eval/repeats${q}`)
      .then((r) => r.json())
      .then((d: { repeats: RepeatGroup[] }) => setRepeats(d.repeats ?? []));
    void fetch(`/api/v1/eval/gaps${q}`)
      .then((r) => r.json())
      .then((d: { gaps: Gap[] }) => setGaps(d.gaps ?? []));
  }, [includeTest]);

  const q = sum?.quality;
  const c = sum?.cost;
  const vc = sum?.verdict_counts;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-bold">Eval 观测</h1>
          <p className="mt-1 text-sm text-muted-foreground">只看 agent 质量：答得有据吗、改了有没有变差、该补什么课</p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeTest}
            onChange={(e) => setIncludeTest(e.target.checked)}
            className="accent-primary"
          />
          含调试调用
        </label>
      </header>

      {/* 防假性完成 */}
      <section className="mb-8">
        <SectionHeader icon={FlaskConical} title="防假性完成" count={sum?.asks ?? 0} hint="共 N 问的口径见各项" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="有据率" value={q ? `${q.grounded_rate}%` : "—"} hint="引了课件或联网查过" />
          <Metric label="引用课件率" value={q ? `${q.cited_rate}%` : "—"} />
          <Metric
            label="无据长答"
            value={q?.unsourced_long ?? "—"}
            warn={(q?.unsourced_long ?? 0) > 0}
            hint="没引课件没联网还长篇 → 可疑瞎编"
          />
          <Metric label="工具报错" value={q?.tool_error ?? "—"} warn={(q?.tool_error ?? 0) > 0} />
          <Metric label="软着陆" value={q?.soft_landed ?? "—"} hint="撞查询上限硬答" />
          <Metric label="被截断" value={q?.truncated ?? "—"} warn={(q?.truncated ?? 0) > 0} />
          <Metric label="联网次数" value={q?.searched ?? "—"} />
          <Metric
            label="自评瞎编"
            value={q?.self_eval_fabricated ?? "—"}
            warn={(q?.self_eval_fabricated ?? 0) > 0}
            hint={`可疑答案自评判「编造」数(下限);已评 ${q?.self_eval_checked ?? 0} · 存疑 ${q?.self_eval_partial ?? 0}`}
          />
          <Metric
            label="批改结果"
            value={
              vc && Object.keys(vc).length
                ? [
                    ["pass", "通过", "success"],
                    ["warn", "存疑", "warning"],
                    ["fail", "不过", "destructive"],
                  ]
                    .filter(([k]) => vc[k])
                    .map(([k, label, variant]) => (
                      <Badge key={k} variant={variant as "success" | "warning" | "destructive"}>
                        {label} {vc[k]}
                      </Badge>
                    ))
                : "—"
            }
          />
        </div>
        <p className="mt-3 font-mono text-xs text-muted-foreground">
          均 {c?.avg_elapsed_s ?? "—"}s · 最慢 {c?.slowest_s ?? "—"}s · in{" "}
          {c?.in_tokens ?? 0}/out {c?.out_tokens ?? 0} tokens
          {c?.cache_hit_rounds ? ` · 缓存命中 ${c.cache_hit_rounds} 轮` : " · 缓存未命中(智谱不支持)"}
        </p>
      </section>

      {/* 同问题历史 = 轻量抓回归 */}
      <section className="mb-8">
        <SectionHeader icon={Repeat} title="同问题历史" count={repeats.length} hint="抓回归:对比改动前后答案变好还是变差" />
        {repeats.length ? (
          <ul className="space-y-2">
            {repeats.map((r, i) => (
              <li key={i}>
                <Card className="overflow-hidden">
                  <button
                    onClick={() => setOpenRepeat(openRepeat === i ? null : i)}
                    className="flex w-full items-baseline gap-3 px-4 py-3 text-left text-sm outline-none hover:bg-accent/50"
                  >
                    <Badge variant="default" className="font-mono">×{r.count}</Badge>
                    <span className="min-w-0 flex-1 truncate">{r.question}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">对比答案演变</span>
                    <ChevronDown
                      size={14}
                      className={cn("shrink-0 text-muted-foreground transition-transform", openRepeat === i && "rotate-180")}
                    />
                  </button>
                  <Collapse open={openRepeat === i}>
                    <div className="space-y-3 border-t border-border px-4 py-3">
                      {r.history.map((h, j) => (
                        <div key={j} className="text-sm">
                          <p className="mb-1 font-mono text-xs text-muted-foreground">
                            {h.ts?.slice(5, 16)} · {h.answer_len ?? "?"}字 · {h.grounded ? "有据" : "无据"} · {h.elapsed_s}s
                            {h.cited_pages.length > 0 && ` · 引第${h.cited_pages.join(",")}页`}
                          </p>
                          <p className="leading-relaxed whitespace-pre-wrap">{h.answer}</p>
                        </div>
                      ))}
                    </div>
                  </Collapse>
                </Card>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={Repeat} title="还没有重复提问" hint="同一问题问过两次以上才会出现——用于对比改动前后答案变好还是变差" />
        )}
      </section>

      {/* 衍生候选 */}
      <section className="mb-8">
        <SectionHeader icon={Compass} title="衍生候选" count={gaps.length} hint="该补什么课" />
        {gaps.length ? (
          <ul className="space-y-2">
            {gaps.map((g, i) => {
              const m = GAP_META[g.kind];
              const GIcon = m?.icon ?? Compass;
              return (
                <li key={i} className="rounded-lg border border-border bg-card p-3 text-sm">
                  <p className="flex items-start gap-2">
                    <GIcon size={14} className="mt-0.5 shrink-0 text-primary" />
                    {g.question}
                  </p>
                  <p className="mt-1 pl-6 font-mono text-xs text-muted-foreground">
                    {m?.text} · {g.detail}
                    {g.ts && ` · ${g.ts.slice(5, 16)}`}
                  </p>
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState icon={Compass} title="没有待补的口子" hint="三个信号来源：联网查过的问题 / 反复问的问题 / 检查点未通过的页" />
        )}
      </section>

      {/* 问答轨迹 */}
      <section className="mb-8">
        <SectionHeader icon={History} title="问答轨迹" count={tutor.length} hint="最近 50 条答疑记录" />
        {tutor.length ? (
          <ul className="space-y-2">
            {tutor.map((t, i) => (
              <li key={i}>
                <Card className="overflow-hidden">
                  <button
                    onClick={() => setOpenTrace(openTrace === i ? null : i)}
                    className="flex w-full items-baseline gap-3 px-4 py-3 text-left text-sm outline-none hover:bg-accent/50"
                  >
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{t.ts?.slice(11, 16)}</span>
                    <span className="min-w-0 flex-1 truncate">{t.question}</span>
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">
                      {!t.grounded && <span className="text-warning">⚠ 无据 </span>}
                      {t.searched && <Search size={11} className="inline align-[-1px]" />}
                      {t.cited_pages.length > 0 && ` 第${t.cited_pages.join(",")}页 · `}
                      {t.elapsed_s}s
                    </span>
                    <ChevronDown
                      size={14}
                      className={cn("shrink-0 text-muted-foreground transition-transform", openTrace === i && "rotate-180")}
                    />
                  </button>
                  <Collapse open={openTrace === i}>
                    <div className="border-t border-border px-4 py-3 text-sm">
                      {t.tool_calls.length > 0 && (
                        <div className="mb-2 space-y-0.5 font-mono text-xs text-muted-foreground">
                          {t.tool_calls.map((tc, j) => (
                            <p key={j} className={tc.error ? "text-destructive" : undefined}>
                              {tc.error ? "❌" : "🔍"} {tc.name}({String(Object.values(tc.args)[0])}) {tc.ms}ms
                              {tc.error && `— ${tc.error}`}
                            </p>
                          ))}
                        </div>
                      )}
                      <p className="leading-relaxed whitespace-pre-wrap">{t.answer}</p>
                      <p className="mt-2 font-mono text-xs text-muted-foreground">
                        {t.usage.input_tokens
                          ? `in ${t.usage.input_tokens}/out ${t.usage.output_tokens ?? 0} tokens`
                          : "（旧记录无 token 数据）"}
                        {t.soft_landed && " · 软着陆"}
                        {t.truncated && " · 被截断"}
                      </p>
                    </div>
                  </Collapse>
                </Card>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={MessageSquareText} title="还没有问答记录" hint="去课堂页向 AI 老师提问,轨迹会落在这里" />
        )}
      </section>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  warn,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  warn?: boolean;
}) {
  // 纯数字(可带 %)才参与滚动;Badge 组/「—」等原样渲染
  const m =
    typeof value === "number" || typeof value === "string"
      ? String(value).match(/^(\d+(?:\.\d+)?)(%)?$/)
      : null;
  const shown = useCountUp(m ? Number(m[1]) : null);
  return (
    <Card
      className={cn("px-4 py-3", warn && "border-warning/40 bg-warning/5")}
      title={hint}
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 font-mono text-lg font-bold", warn ? "text-warning" : undefined)}>
        {m ? `${Math.round((shown ?? 0) * 10) / 10}${m[2] ?? ""}` : value}
      </p>
    </Card>
  );
}
