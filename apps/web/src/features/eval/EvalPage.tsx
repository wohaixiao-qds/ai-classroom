/** Eval 观测页 —— 只管 agent 质量（学习进度归课表页）。
 *  三块：防假性完成指标 / 同问题历史(轻量抓回归) / 衍生候选。 */
import { useEffect, useState } from "react";

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

const GAP_LABEL = {
  searched: { icon: "🔍", text: "课件未覆盖（联网查了）" },
  repeated: { icon: "🔁", text: "反复问（课件讲不清）" },
  checkpoint_fail: { icon: "❌", text: "检查点未通过" },
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

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-bold">Eval 观测</h1>
          <p className="muted mt-1 text-sm">只看 agent 质量：答得有据吗、改了有没有变差、该补什么课</p>
        </div>
        <label className="muted flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={includeTest}
            onChange={(e) => setIncludeTest(e.target.checked)}
          />
          含调试调用
        </label>
      </header>

      {/* 防假性完成 */}
      <Section title={`防假性完成 · 共 ${sum?.asks ?? 0} 问`}>
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
            label="批改结果"
            value={
              sum && Object.keys(sum.verdict_counts).length
                ? Object.entries(sum.verdict_counts)
                    .map(([k, v]) => `${{ pass: "✅", warn: "⚠️", fail: "❌" }[k] ?? k}${v}`)
                    .join(" ")
                : "—"
            }
          />
        </div>
        <p className="muted mt-3 font-mono text-xs">
          均 {c?.avg_elapsed_s ?? "—"}s · 最慢 {c?.slowest_s ?? "—"}s · in{" "}
          {c?.in_tokens ?? 0}/out {c?.out_tokens ?? 0} tokens
          {c?.cache_hit_rounds ? ` · 缓存命中 ${c.cache_hit_rounds} 轮` : " · 缓存未命中(智谱不支持)"}
        </p>
      </Section>

      {/* 同问题历史 = 轻量抓回归 */}
      <Section title={`同问题历史 · 抓回归（${repeats.length} 组）`}>
        {repeats.length ? (
          <ul className="space-y-2">
            {repeats.map((r, i) => (
              <li key={i} className="rounded-lg border border-(--line) bg-(--surface)">
                <button
                  onClick={() => setOpenRepeat(openRepeat === i ? null : i)}
                  className="flex w-full items-baseline gap-3 px-4 py-3 text-left text-sm"
                >
                  <span className="accent shrink-0 font-mono text-xs">×{r.count}</span>
                  <span className="min-w-0 flex-1 truncate">{r.question}</span>
                  <span className="muted shrink-0 text-xs">对比答案演变 →</span>
                </button>
                {openRepeat === i && (
                  <div className="space-y-3 border-t border-(--line) px-4 py-3">
                    {r.history.map((h, j) => (
                      <div key={j} className="text-sm">
                        <p className="muted mb-1 font-mono text-xs">
                          {h.ts?.slice(5, 16)} · {h.answer_len ?? "?"}字 ·{" "}
                          {h.grounded ? "有据" : "无据"} · {h.elapsed_s}s
                          {h.cited_pages.length > 0 && ` · 引第${h.cited_pages.join(",")}页`}
                        </p>
                        <p className="leading-relaxed whitespace-pre-wrap">{h.answer}</p>
                      </div>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>同一问题问过两次以上才会出现——用于对比改动前后答案变好还是变差</Empty>
        )}
      </Section>

      {/* 衍生候选 */}
      <Section title={`衍生候选 · 该补什么课（${gaps.length}）`}>
        {gaps.length ? (
          <ul className="space-y-2">
            {gaps.map((g, i) => {
              const l = GAP_LABEL[g.kind];
              return (
                <li key={i} className="rounded-lg border border-(--line) bg-(--surface) p-3 text-sm">
                  <p>
                    <span className="mr-2">{l?.icon}</span>
                    {g.question}
                  </p>
                  <p className="muted mt-1 font-mono text-xs">
                    {l?.text} · {g.detail}
                    {g.ts && ` · ${g.ts.slice(5, 16)}`}
                  </p>
                </li>
              );
            })}
          </ul>
        ) : (
          <Empty>三个信号来源：联网查过的问题 / 反复问的问题 / 检查点未通过的页</Empty>
        )}
      </Section>

      {/* 问答轨迹 */}
      <Section title="问答轨迹">
        {tutor.length ? (
          <ul className="space-y-2">
            {tutor.map((t, i) => (
              <li key={i} className="rounded-lg border border-(--line) bg-(--surface)">
                <button
                  onClick={() => setOpenTrace(openTrace === i ? null : i)}
                  className="flex w-full items-baseline gap-3 px-4 py-3 text-left text-sm"
                >
                  <span className="muted shrink-0 font-mono text-xs">{t.ts?.slice(11, 16)}</span>
                  <span className="min-w-0 flex-1 truncate">{t.question}</span>
                  <span className="muted shrink-0 font-mono text-xs">
                    {!t.grounded && "⚠️ "}
                    {t.searched && "🔍 "}
                    {t.cited_pages.length > 0 && `第${t.cited_pages.join(",")}页 · `}
                    {t.elapsed_s}s
                  </span>
                </button>
                {openTrace === i && (
                  <div className="border-t border-(--line) px-4 py-3 text-sm">
                    {t.tool_calls.length > 0 && (
                      <div className="muted mb-2 space-y-0.5 font-mono text-xs">
                        {t.tool_calls.map((tc, j) => (
                          <p key={j}>
                            {tc.error ? "❌" : "🔍"} {tc.name}({String(Object.values(tc.args)[0])}){" "}
                            {tc.ms}ms {tc.error && `— ${tc.error}`}
                          </p>
                        ))}
                      </div>
                    )}
                    <p className="leading-relaxed whitespace-pre-wrap">{t.answer}</p>
                    <p className="muted mt-2 font-mono text-xs">
                      {t.usage.input_tokens
                        ? `in ${t.usage.input_tokens}/out ${t.usage.output_tokens ?? 0} tokens`
                        : "（旧记录无 token 数据）"}
                      {t.soft_landed && " · 软着陆"}
                      {t.truncated && " · 被截断"}
                    </p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>还没有问答记录</Empty>
        )}
      </Section>
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
  value: string | number;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <div
      className="rounded-xl border bg-(--surface) px-4 py-3"
      style={{ borderColor: warn ? "var(--accent)" : "var(--line)" }}
      title={hint}
    >
      <p className="muted text-xs">{label}</p>
      <p className={`mt-1 font-mono text-lg font-bold ${warn ? "accent" : ""}`}>{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-sm font-medium tracking-wide">{title}</h2>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="muted text-sm leading-relaxed">{children}</p>;
}
