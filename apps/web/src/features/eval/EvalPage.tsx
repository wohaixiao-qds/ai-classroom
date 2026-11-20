/** Eval 观测:行为、规则与证据评价分别展示,所有 API 类型来自生成契约。 */
import {
  ChevronDown,
  Compass,
  FlaskConical,
  History,
  ListChecks,
  Repeat,
  Search,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { Collapse } from "../../components/Collapse";
import { EmptyState, PageError, PageLoading } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Textarea } from "../../components/ui/textarea";
import { cn } from "../../lib/utils";
import type { components } from "../../types/api.gen";

type Schemas = components["schemas"];
type Trace = Schemas["TraceRecord"];
type Lesson = Schemas["Lesson"];
type Data = {
  summary: Schemas["EvalSummary"];
  traces: Schemas["EvalTraces"];
  repeats: Schemas["EvalRepeats"];
  gaps: Schemas["EvalGaps"];
  lessons: Schemas["EvalLessons"];
};

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
  return response.json() as Promise<T>;
}

const STAGES = { tutor: "答疑", grade: "批改", research: "调研", prep: "备课" } as const;
const STATUS: Record<string, string> = {
  running: "执行中", succeeded: "已完成", failed: "失败", cancelled: "已取消",
  interrupted: "异常中断", unknown: "旧记录·状态未知",
};
const VERDICT: Record<string, string> = {
  supported: "证据支持", partial: "部分缺证据", unsupported: "缺少证据支持",
  uncertain: "无法判断", unreviewed: "待审查", skipped: "未评", grounded: "旧版有据信号",
  fabricated: "旧版疑似编造",
};
const SKIP: Record<string, string> = {
  not_sampled: "未命中抽样", judge_error: "裁判调用失败", invalid_judge_output: "裁判输出无效",
  incomplete_execution: "执行未完成", legacy_or_missing: "旧版或缺少评价",
  pending: "等待补评", assessment_error: "补评异常", no_assessment: "缺少裁判结果",
};
const percent = (value: number | null | undefined) => value == null ? "—" : `${value}%`;
const countText = (counts: Record<string, number>, names: Record<string, string>) =>
  Object.entries(counts).map(([key, n]) => `${names[key] ?? key} ${n}`).join(" · ");

export function EvalPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [includeTest, setIncludeTest] = useState(false);
  const [revision, setRevision] = useState(0);
  const [stage, setStage] = useState<keyof typeof STAGES>("tutor");
  const [busyLesson, setBusyLesson] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [reviewError, setReviewError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const q = `?include_test=${includeTest}`;
    const init = { signal: controller.signal };
    void Promise.all([
      read<Data["summary"]>(`/api/v1/eval/summary${q}`, init),
      read<Data["traces"]>(`/api/v1/eval/traces${q}&limit=50`, init),
      read<Data["repeats"]>(`/api/v1/eval/repeats${q}`, init),
      read<Data["gaps"]>(`/api/v1/eval/gaps${q}`, init),
      read<Data["lessons"]>("/api/v1/eval/lessons", init),
    ]).then(([summary, traces, repeats, gaps, lessons]) => {
      if (!controller.signal.aborted) setData({ summary, traces, repeats, gaps, lessons });
    }).catch((e: unknown) => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "加载失败");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [includeTest, revision]);

  function refresh() {
    setLoading(true);
    setError(null);
    setRevision((n) => n + 1);
  }

  async function review(lesson: Lesson, status: "approved" | "rejected") {
    setBusyLesson(lesson.id);
    setReviewError(null);
    try {
      const updated = await read<Lesson>(`/api/v1/eval/lessons/${encodeURIComponent(lesson.id)}/review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, ...(status === "approved" ? {
          text: (drafts[lesson.id] ?? lesson.text).trim(),
        } : {}) }),
      });
      setData((current) => current && ({ ...current, lessons: {
        lessons: current.lessons.lessons.map((item) => item.id === updated.id ? updated : item),
      } }));
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : "审核失败");
    } finally {
      setBusyLesson(null);
    }
  }

  const q = data?.summary.quality;
  const c = data?.summary.cost;
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
      <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">Eval 观测</h1>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            看执行是否完成、规则是否遵守、证据是否支撑回答。模型审查结果需结合原文复核。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={includeTest} onChange={(e) => {
              setLoading(true);
              setError(null);
              setIncludeTest(e.target.checked);
            }} />
            含调试调用
          </label>
          <Button variant="secondary" className="min-h-11" onClick={refresh}>刷新</Button>
        </div>
      </header>
      {loading ? <PageLoading label="读取执行与评价记录…" /> : error ? (
        <PageError message={error} onRetry={refresh} />
      ) : data && q && c ? <>
        <section className="mb-8">
          <SectionHeader icon={FlaskConical} title="答疑评价" count={data.summary.asks} hint={`每类最近 ${data.summary.window} 次执行`} />
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="语义审查覆盖率" value={percent(q.coverage_pct)} hint={`已评 ${q.checked} / 已作答 ${q.answers}`} />
            <Metric label="已评答案证据支持率" value={percent(q.support_rate_pct)} hint="仅含新规则下能判断的已评答案;未知不计通过" />
            <Metric label="引用存在性合格率" value={percent(q.valid_citation_pct)} hint={`已查 ${q.citation_checks} 条;旧引用未核验 ${q.citation_unknown} 条`} />
            <Metric label="引用规则违规" value={q.guard_violations} warn={q.guard_violations > 0} hint="章节或来源编号不存在;与语义支撑分开" />
            <Metric label="工具使用 / 报错" value={`${q.tool_used} / ${q.tool_error}`} hint="使用工具本身不能证明回答有据" />
            <Metric label="疑似重复教学" value={q.reteach} hint="规则命中,需结合学员提问人工复核" />
            <Metric label="预算收尾 / 截断" value={`${q.soft_landed} / ${q.truncated}`} />
            <Metric label="缺证据 / 部分缺证据" value={`${q.assessment_counts.unsupported ?? 0} / ${q.assessment_counts.partial ?? 0}`} hint="证据不足不能直接判定事实编造" />
          </div>
          <div className="mt-3 space-y-1 text-sm leading-relaxed text-muted-foreground">
            <p>未评原因：{countText(q.skip_reasons, SKIP) || "无"}。高风险全评，其余固定 20% 抽样。</p>
            <p>执行均耗时 {c.avg_elapsed_s}s · 已知用量 in {c.in_tokens} / out {c.out_tokens} tokens · {c.unknown_usage} 次缺用量。</p>
            <p>裁判另计 in {c.judge_in_tokens} / out {c.judge_out_tokens} tokens · 累计 {c.judge_elapsed_s}s。答疑与裁判共用模型，结果有同源偏差。</p>
            <p>批改结果：{countText(data.summary.verdict_counts, { pass: "通过", warn: "存疑", fail: "未过" }) || "暂无"}；其中辅导保底 {data.summary.tutored_grades} 次。此分布反映学员表现，不代表批改准确率。</p>
          </div>
        </section>

        <ResearchSection traces={data.traces.research} />

        <section className="mb-8">
          <SectionHeader icon={History} title="执行轨迹" hint="每类最近 50 次,旧记录的执行状态保持未知" />
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="执行类型">
            {Object.entries(STAGES).map(([key, name]) => {
              const metrics = data.summary.stages[key];
              return <Button key={key} variant={stage === key ? "default" : "outline"}
                className="h-auto min-h-11 flex-col items-start gap-1 whitespace-normal p-3 text-left"
                aria-pressed={stage === key} onClick={() => setStage(key as keyof typeof STAGES)}>
                <span>{name} · {metrics?.total ?? 0}</span>
                <span className="text-xs font-normal leading-relaxed">{countText(metrics?.statuses ?? {}, STATUS) || "暂无执行"}</span>
              </Button>;
            })}
          </div>
          <div key={stage} className="desktop-state-arrive space-y-2">
            {data.traces[stage].length ? data.traces[stage].map((t, i) => (
              <TraceRow key={t.run_id ?? `${stage}-${i}`} trace={t} />
            )) : <EmptyState icon={History} title="暂无此类轨迹" hint="运行后会显示成功、失败与取消记录" />}
          </div>
        </section>

        <section className="mb-8">
          <SectionHeader icon={ListChecks} title="教训审核" count={data.lessons.lessons.filter((l) => l.status === "pending").length} hint="自动候选经人工确认后,从下一问开始生效" />
          {reviewError && <p className="mb-3 text-sm text-destructive" role="alert">{reviewError}</p>}
          <div className="space-y-3">
            {data.lessons.lessons.length ? data.lessons.lessons.map((lesson) => (
              <Card key={lesson.id} className="space-y-3 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={lesson.status === "approved" ? "success" : "secondary"}>
                    {{ pending: "待审核·未生效", approved: "已确认·已生效", rejected: "已拒绝·未生效" }[lesson.status]}
                  </Badge>
                  <span className="min-w-0 break-all font-mono text-xs text-muted-foreground">{lesson.run_id ?? "旧账本导入"}</span>
                </div>
                {lesson.status === "pending" ? (
                  <Textarea aria-label="待审核教训" value={drafts[lesson.id] ?? lesson.text}
                    maxLength={1000} className="min-h-24"
                    onChange={(e) => setDrafts((prev) => ({ ...prev, [lesson.id]: e.target.value }))} />
                ) : <p className="text-sm leading-relaxed whitespace-pre-wrap">{lesson.text}</p>}
                <details className="text-sm text-muted-foreground">
                  <summary className="flex min-h-11 cursor-pointer items-center">查看候选依据</summary>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(lesson.evidence, null, 2)}</pre>
                </details>
                <div className="flex flex-wrap gap-2">
                  {lesson.status !== "approved" && <Button className="min-h-11" disabled={busyLesson !== null || !(drafts[lesson.id] ?? lesson.text).trim()}
                    onClick={() => void review(lesson, "approved")}>{busyLesson === lesson.id ? "提交中…" : "确认并生效"}</Button>}
                  {lesson.status !== "rejected" && <Button variant="outline" className="min-h-11" disabled={busyLesson !== null}
                    onClick={() => void review(lesson, "rejected")}>{lesson.status === "approved" ? "撤销生效" : "拒绝候选"}</Button>}
                </div>
              </Card>
            )) : <EmptyState icon={ListChecks} title="暂无教训候选" hint="证据审查发现问题后会提出候选,候选不会自动进入答疑上下文" />}
          </div>
        </section>

        <section className="mb-8">
          <SectionHeader icon={Repeat} title="同问题历史" count={data.repeats.count} hint="按课程和当前节分组;上下文变化时仅供浏览" />
          <div className="space-y-2">
            {data.repeats.repeats.length ? data.repeats.repeats.map((group, i) => (
              <details key={i} className="rounded-lg border border-border bg-card p-4">
                <summary className="min-h-11 cursor-pointer text-sm leading-relaxed">
                  {group.question} · {group.course_id} · {group.count} 次
                  <span className="mt-1 block text-muted-foreground">{group.comparable ? "初始上下文与模型一致,仍需人工判断质量变化" : "上下文或版本不同/缺失,不能直接据此判定回归"}</span>
                </summary>
                <div className="mt-3 space-y-2">{group.history.map((t, j) => <TraceRow key={j} trace={t} />)}</div>
              </details>
            )) : <EmptyState icon={Repeat} title="暂无同课同节的重复提问" />}
          </div>
        </section>

        <section>
          <SectionHeader icon={Compass} title="待复核线索" count={data.gaps.count} hint="查询、重复或未通过都只是线索,不自动判定为课程缺口" />
          <ul className="space-y-2">{data.gaps.gaps.slice(0, 50).map((g, i) => (
            <li key={i} className="rounded-lg border border-border bg-card p-4 text-sm">
              <p className="break-words">{g.question}</p>
              <p className="mt-1 leading-relaxed text-muted-foreground">{g.course_id} · {g.detail}</p>
            </li>
          ))}</ul>
          {!data.gaps.count && <EmptyState icon={Compass} title="暂无线索" />}
          {data.gaps.count > 50 && <p className="mt-2 text-sm text-muted-foreground">展示最近窗口内前 50 条线索。</p>}
        </section>
      </> : null}
    </div>
  );
}

function TraceRow({ trace: t }: { trace: Trace }) {
  const [open, setOpen] = useState(false);
  return <Card className="overflow-hidden">
    <button className="flex min-h-11 w-full items-start gap-3 p-4 text-left text-sm hover:bg-accent/50"
      aria-expanded={open} onClick={() => setOpen((v) => !v)}>
      <span className="min-w-0 flex-1">
        <span className="block break-words">{t.question || t.subtopic || t.topic || `${t.course_id} · ${t.page_id ?? ""}`}</span>
        <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{t.ts} · {STATUS[t.status ?? "unknown"] ?? t.status} · {t.elapsed_s}s · 循环 {t.turns ?? "未知"} 次</span>
      </span>
      <ChevronDown size={16} className={cn("mt-1 shrink-0 transition-transform", open && "rotate-180")} />
    </button>
    <Collapse open={open}>
      <div className="space-y-3 border-t border-border p-4 text-sm">
        {t.error && <p className="break-words text-destructive">{t.error}</p>}
        {!!t.validation_errors?.length && <p className="break-words text-destructive">交付校验：{t.validation_errors.join("；")}</p>}
        {!!t.guard_violations?.length && <p className="text-destructive">引用违规：{t.guard_violations.join("；")}</p>}
        {!!t.reteach?.length && <p className="text-warning">重复教学信号：{t.reteach.join("；")}</p>}
        <p className="text-muted-foreground">评价：{VERDICT[t.self_eval?.verdict ?? "skipped"] ?? "旧版/未知"}
          {t.self_eval?.skip_reason && ` · ${SKIP[t.self_eval.skip_reason] ?? t.self_eval.skip_reason}`}
          {t.self_eval?.reason && ` · ${t.self_eval.reason}`}</p>
        {!!t.tool_calls?.length && <ul className="space-y-2">{t.tool_calls.map((tool, i) => (
          <li key={i} className={cn("break-words text-xs", tool.error ? "text-destructive" : "text-muted-foreground")}>
            {tool.name}{tool.args?.url ? ` · ${String(tool.args.url)}` : ""} · {tool.ms}ms
            {tool.reused_from_call != null ? ` · 复用第 ${tool.reused_from_call + 1} 次抓取` : ""}
            {tool.error ? ` · ${tool.error}` : " · 调用完成(不等于答案有据)"}
          </li>
        ))}</ul>}
        {t.verdict && <p>批改：{t.verdict} · 原始分 {t.raw_score ?? "未知"} / 应用分 {t.score ?? "未知"}{t.tutored && " · 辅导保底"}</p>}
        {t.research_outline && <p>大纲：{t.research_outline.sourced_courses} / {t.research_outline.courses} 门课有来源 · {t.research_outline.sources} 个来源</p>}
        {t.research_evidence && <p>原料证据：{t.research_evidence.matched} / {t.research_evidence.total} 条引用命中正文 · 已审 {t.research_evidence.reviewed} 条 · {countText(t.research_evidence.verdicts, VERDICT)}{t.research_evidence.review_error && ` · 审查错误: ${t.research_evidence.review_error}`}</p>}
        {t.research_cost && <p>调研成本：模型 {t.research_cost.generation_s}s · 工具 {t.research_cost.tool_s}s · 审查 {t.research_cost.review_s}s · in {t.research_cost.total_usage.input_tokens ?? 0} / out {t.research_cost.total_usage.output_tokens ?? 0} tokens</p>}
        {!!t.answer && <p className="break-words leading-relaxed whitespace-pre-wrap">{t.answer}</p>}
        <p className="break-all font-mono text-xs text-muted-foreground">run {t.run_id ?? "旧记录"} · 模型 {t.versions?.model ?? "未知"} · 规则 {t.versions?.eval ?? "未知"}<br />prompt {t.versions?.prompt_hash?.slice(0, 12) ?? "未知"} · context {t.versions?.context_hash?.slice(0, 12) ?? "未知"} · source {t.source}</p>
      </div>
    </Collapse>
  </Card>;
}

function ResearchSection({ traces }: { traces: Trace[] }) {
  const evidence = traces.flatMap((trace) => trace.research_evidence ? [trace.research_evidence] : []);
  const costs = traces.flatMap((trace) => trace.research_cost ? [trace.research_cost] : []);
  const outlines = traces.flatMap((trace) => trace.research_outline ? [trace.research_outline] : []);
  const verdicts = evidence.reduce<Record<string, number>>((all, item) => {
    Object.entries(item.verdicts).forEach(([key, value]) => { all[key] = (all[key] ?? 0) + value; });
    return all;
  }, {});
  const matched = evidence.reduce((sum, item) => sum + item.matched, 0);
  const total = evidence.reduce((sum, item) => sum + item.total, 0);
  const reviewed = evidence.reduce((sum, item) => sum + item.reviewed, 0);
  const reviewErrors = evidence.filter((item) => item.review_error).length;
  const sourcedCourses = outlines.reduce((sum, item) => sum + item.sourced_courses, 0);
  const outlineCourses = outlines.reduce((sum, item) => sum + item.courses, 0);
  const sourceCount = outlines.reduce((sum, item) => sum + item.sources, 0);
  const generationS = costs.reduce((sum, item) => sum + item.generation_s, 0);
  const toolS = costs.reduce((sum, item) => sum + item.tool_s, 0);
  const reviewS = costs.reduce((sum, item) => sum + item.review_s, 0);
  const inputTokens = costs.reduce((sum, item) => sum + (item.total_usage.input_tokens ?? 0), 0);
  const outputTokens = costs.reduce((sum, item) => sum + (item.total_usage.output_tokens ?? 0), 0);
  const toolCalls = traces.flatMap((trace) => trace.tool_calls ?? []);
  const fetchCalls = toolCalls.filter((tool) => tool.name === "fetch_page");
  const reusedFetches = fetchCalls.filter((tool) => tool.reused_from_call != null).length;
  const failedFetches = fetchCalls.filter((tool) => tool.error).length;

  return (
    <section className="mb-8">
      <SectionHeader icon={Search} title="Research 调研评价" count={traces.length} hint="大纲与课程原料分开观察；证据命中和模型审查都不替代人工事实核验" />
      {!traces.length ? <EmptyState icon={Search} title="暂无调研轨迹" hint="运行领域大纲或课程调研后会显示来源、证据审查和成本" /> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="大纲来源覆盖" value={outlineCourses ? `${sourcedCourses} / ${outlineCourses}` : "—"} hint="有实际抓取来源的课程数" warn={outlineCourses > 0 && sourcedCourses < outlineCourses} />
            <Metric label="原文引用命中" value={total ? `${matched} / ${total}` : "—"} hint="引用片段在 fetch_page 正文快照中找到" warn={total > 0 && matched < total} />
            <Metric label="语义审查完成" value={total ? `${reviewed} / ${total}` : "—"} hint={reviewErrors ? `${reviewErrors} 次审查有错误` : "只统计已落盘原料"} warn={reviewErrors > 0} />
            <Metric label="审查结论" value={countText(verdicts, VERDICT) || "—"} hint="supported 仍需人工抽查，不等于事实已证实" />
            <Metric label="抓取复用 / 失败" value={`${reusedFetches} / ${failedFetches}`} hint={`${fetchCalls.length} 次 fetch_page；同轮重复 URL 会复用快照`} />
            <Metric label="来源快照" value={sourceCount || "—"} hint="大纲阶段记录的 URL 与正文 SHA-256" />
            <Metric label="总模型用量" value={`${inputTokens} / ${outputTokens}`} hint="Research generation + evidence review · in / out tokens" />
            <Metric label="耗时拆分" value={`${generationS.toFixed(1)}s`} hint={`模型 ${generationS.toFixed(1)}s · 工具 ${toolS.toFixed(1)}s · 审查 ${reviewS.toFixed(1)}s`} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1"><ShieldCheck size={14} /> 证据审查是发布前质量门，不会自动替代作者确认</span>
            <span className="inline-flex items-center gap-1"><Timer size={14} /> 已记录 {costs.length} 次调研成本</span>
          </div>
        </>
      )}
    </section>
  );
}

function Metric({ label, value, hint, warn }: { label: string; value: ReactNode; hint?: string; warn?: boolean }) {
  return <Card className={cn("min-w-0 p-4", warn && "border-warning/40 bg-warning/5")}>
    <p className="text-sm text-muted-foreground">{label}</p>
    <p className={cn("mt-1 break-words font-mono text-xl font-bold", warn && "text-warning")}>{value}</p>
    {hint && <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{hint}</p>}
  </Card>;
}
