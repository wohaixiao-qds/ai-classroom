import { BookOpen, ChevronDown, ChevronUp, CircleCheck, CircleDashed, CircleX, ListChecks, LoaderCircle, Pause, Play, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import type { components } from "../../types/api.gen";

type Job = components["schemas"]["JobSummary"];
type Detail = components["schemas"]["JobDetail"];
type Trust = components["schemas"]["JobTrustReport"];
const STAGES = [
  ["scope", "需求与范围"], ["research", "调研参考体系"], ["outline", "形成课程大纲"],
  ["material", "准备课程材料"], ["plan", "规划章节"], ["write", "逐节写作"],
  ["review", "验收与审查"], ["revision", "定点修订"], ["publish", "发布课程"],
] as const;
const STATUS: Record<string, string> = { queued: "排队中", running: "执行中", stopping: "正在停止", cancelled: "已停止", failed: "执行中断", done: "已完成", deleted: "已删除" };
const VERDICT: Record<string, string> = { supported: "有证据支持", partial: "部分支持", unsupported: "缺少支持", uncertain: "存疑", unreviewed: "未完成审查", not_applicable: "非事实性内容" };
const reviewStatus: Record<string, string> = { model_reviewed: "自动审查通过", blocked: "未通过", unreviewed: "未完成", complete: "已完成", completed: "已完成", stale: "旧报告已失效" };
const keyOf = (job: Job) => `${job.kind}:${job.target}`;
const paramsOf = (job: Job) => new URLSearchParams({ kind: job.kind, target: job.target });

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `请求失败（HTTP ${response.status}）`);
  return data as T;
}

function TrustEvidence({ report }: { report: Trust }) {
  const { checks = [], sources = [], mappings = [], reviews = [], limitations = [] } = report;
  return (
    <div className="space-y-5 rounded-lg border border-border bg-background/50 p-4">
      <div>
        <h4 className="flex items-center gap-2 font-medium"><ShieldCheck size={16} />可核查依据</h4>
        <p className="mt-1 text-sm text-muted-foreground">不提供可信度总分。程序检查与模型意见分别展示；未记录人工审核。</p>
      </div>
      <div>
        <h5 className="mb-2 text-sm font-medium">程序检查</h5>
        <ul className="space-y-2">
          {checks.map((check) => (
            <li key={check.id} className="text-sm">
              <div className="flex flex-wrap items-center gap-2"><Badge variant={check.status === "passed" ? "success" : check.status === "failed" ? "destructive" : "secondary"}>{check.status === "passed" ? "通过" : check.status === "failed" ? "未通过" : "未知"}</Badge><span>{check.label}</span><span className="text-xs text-muted-foreground">程序核验</span></div>
              <p className="mt-1 break-words text-muted-foreground">{check.detail}</p>
            </li>
          ))}
        </ul>
      </div>
      <details>
        <summary className="cursor-pointer text-sm font-medium">来源与原文记录（{sources.length}）</summary>
        <ul className="mt-3 space-y-3">
          {sources.map((source) => (
            <li key={`${source.stage}:${source.id}:${source.url}`} className="min-w-0 border-l-2 border-border pl-3 text-sm">
              {/^(https?):\/\//i.test(source.url) ? <a href={source.url} target="_blank" rel="noreferrer" className="break-words text-primary underline underline-offset-4">{source.title || source.url}</a> : <span className="break-words">{source.title}</span>}
              <p className="mt-1 text-xs text-muted-foreground">{source.stage === "outline" ? "大纲来源" : "材料来源"} #{source.id} · 发布主体身份未核实 · {source.fetched_at ? `抓取于 ${source.fetched_at}` : "抓取时间未记录"}</p>
              {source.excerpt && <blockquote className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">{source.excerpt}</blockquote>}
              {source.sha256 && <p className="mt-2 break-all font-mono text-xs text-muted-foreground">SHA-256: {source.sha256}</p>}
            </li>
          ))}
          {!sources.length && <li className="text-sm text-muted-foreground">尚无可展示的来源记录，不能视为已核验。</li>}
        </ul>
      </details>
      {mappings.length > 0 && <details>
        <summary className="cursor-pointer text-sm font-medium">大纲参考映射（{mappings.length} 门课）</summary>
        <p className="mt-2 text-xs text-muted-foreground">由模型建立的参考关联，未经人工确认；有来源关联不等于领域完整性已验证。</p>
        <ul className="mt-3 space-y-3">{mappings.map((mapping) => <li key={mapping.course_id} className="text-sm"><p className="font-medium">{mapping.title}</p><p className="mt-1 text-muted-foreground">目标：{mapping.goal || "未记录"}</p><p className="text-muted-foreground">范围：{mapping.scope || "未记录"}</p><p className="text-xs text-muted-foreground">关联大纲来源：{mapping.source_ids?.length ? mapping.source_ids.join("、") : "未记录"}</p></li>)}</ul>
      </details>}
      <div>
        <h5 className="mb-2 text-sm font-medium">模型语义审查意见</h5>
        {!reviews.length && <p className="text-sm text-muted-foreground">尚无模型审查记录。</p>}
        {reviews.map((review) => <details key={review.stage} className="mt-2 rounded-lg border border-border p-3 text-sm">
          <summary className="cursor-pointer">{review.stage === "material" ? "课程材料" : "最终课件"} · {reviewStatus[review.status] || review.status}</summary>
          {review.status === "stale" && <p className="mt-2 font-medium text-warning">以下为失效历史意见，不能用于当前版本验收。</p>}
          <p className="mt-2 break-words text-muted-foreground">审查者：{review.reviewer}。这是自动审查意见，可能误判，不代表人工认证。</p>
          {review.reviewed_at && <p className="text-xs text-muted-foreground">审查时间：{review.reviewed_at}</p>}
          <ul className="mt-3 max-h-80 space-y-3 overflow-y-auto">{(review.items || []).map((item) => <li key={item.id}><span className="font-mono text-xs">{item.id}</span><Badge className="ml-2" variant={review.status === "stale" ? "secondary" : item.verdict === "supported" ? "success" : item.verdict === "not_applicable" ? "secondary" : "warning"}>{VERDICT[item.verdict] || item.verdict}</Badge><p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">{item.reason}</p></li>)}</ul>
        </details>)}
      </div>
      <div className="text-sm"><p className="font-medium">发布门禁：{report.publication_status === "allowed" ? "当前版本满足发布规则" : report.publication_status === "blocked" ? "当前版本未满足发布规则" : "尚无可用发布结论"}</p><p className="mt-1 text-muted-foreground">程序执行验收规则；通过不等于事实绝对正确。</p></div>
      {limitations.length > 0 && <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted-foreground">{limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>}
    </div>
  );
}

function JobProgress({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [trust, setTrust] = useState<Trust | null>(null);
  const [error, setError] = useState("");
  const [trustError, setTrustError] = useState("");
  const [busy, setBusy] = useState<"cancel" | "resume" | "delete" | null>(null);
  const [notice, setNotice] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const { kind, target } = job;
  const load = useCallback(async (signal?: AbortSignal) => {
    const query = new URLSearchParams({ kind, target });
    const [progress, evidence] = await Promise.allSettled([
      request<Detail>(`/api/v1/jobs/detail?${query}`, { signal }),
      request<Trust>(`/api/v1/jobs/trust?${query}`, { signal }),
    ]);
    if (signal?.aborted) return;
    if (progress.status === "fulfilled") { setDetail(progress.value); setError(""); }
    else setError(progress.reason instanceof Error ? progress.reason.message : "任务详情加载失败");
    if (evidence.status === "fulfilled") { setTrust(evidence.value); setTrustError(""); }
    else { setTrust(null); setTrustError(evidence.reason instanceof Error ? evidence.reason.message : "依据报告加载失败"); }
  }, [kind, target]);
  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => { if (!controller.signal.aborted) void load(controller.signal); });
    const timer = window.setInterval(() => void load(controller.signal), 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load]);
  const perform = async (operation: "cancel" | "resume" | "delete") => {
    setBusy(operation); setError(""); setNotice("");
    try {
      const query = paramsOf(job);
      const response = await request<components["schemas"]["JobOperation"]>(operation === "delete" ? `/api/v1/jobs?${query}` : `/api/v1/jobs/${operation}?${query}`, { method: operation === "delete" ? "DELETE" : "POST" });
      // cancel is retained as a legacy endpoint; its note is also shown rather
      // than assuming a signal request means the process has already stopped.
      setNotice(response.note || "操作已提交");
      setDeleteOpen(false);
      onChanged();
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败，请重试"); }
    finally { setBusy(null); }
  };
  const currentJob = detail?.job || job;
  const running = ["running", "queued", "stopping"].includes(currentJob.status);
  return <div className="space-y-4 border-t border-border p-4 sm:p-5">
    <div className="flex flex-wrap gap-2">
      {running && <Button variant="outline" size="sm" disabled={busy !== null || currentJob.status === "stopping"} onClick={() => void perform("cancel")}><Pause size={14} />{busy === "cancel" || currentJob.status === "stopping" ? "正在停止…" : "停止"}</Button>}
      {currentJob.can_resume && <Button size="sm" disabled={busy !== null} onClick={() => void perform("resume")}><Play size={14} />{busy === "resume" ? "正在恢复…" : "继续"}</Button>}
      {currentJob.status === "done" && currentJob.course_id && <Button asChild size="sm"><Link to={`/read/${encodeURIComponent(currentJob.course_id)}`}><BookOpen size={14} />开始学习</Link></Button>}
      <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => setDeleteOpen(true)}><Trash2 size={14} />删除{currentJob.status === "done" ? "记录" : "任务"}</Button>
      <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => void load()}><RefreshCw size={14} />刷新</Button>
    </div>
    {notice && <p role="status" className="text-sm text-primary">{notice}</p>}
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
    {!detail && !error && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle size={14} className="motion-safe:animate-spin" />正在读取流程记录…</p>}
    {detail && <>
      <p className="text-xs text-muted-foreground">执行尝试 {detail.attempts} 次 · {detail.history_recorded ? "以下节点来自已保存的执行事件" : "历史任务未记录完整流程，不补造进度"}</p>
      {currentJob.detail && <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{currentJob.detail}</p>}
      <ol className="ml-2 border-l border-border">
        {STAGES.map(([stage, label]) => {
          const events = detail.events.filter((event) => event.stage === stage);
          const latest = events.at(-1);
          const state = latest?.status;
          const activelyRunning = state === "running" && ["running", "queued"].includes(currentJob.status);
          const Icon = state === "completed" ? CircleCheck : state === "failed" ? CircleX : state === "running" ? LoaderCircle : CircleDashed;
          return <li key={stage} className="relative pb-5 pl-6 last:pb-0">
            <Icon aria-hidden="true" size={17} className={`absolute -left-[9px] top-0.5 bg-card ${state === "completed" ? "text-success" : state === "failed" ? "text-destructive" : activelyRunning ? "text-primary motion-safe:animate-spin" : "text-muted-foreground"}`} />
            <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{label}</span><span className="text-xs text-muted-foreground">{state === "completed" ? "完成" : state === "failed" ? "需要处理" : state === "running" ? activelyRunning ? "进行中" : currentJob.status === "stopping" ? "正在停止，保留进度" : "已中断，保留进度" : state === "skipped" ? "不适用" : detail.history_recorded ? "尚无执行记录" : "历史未记录"}</span>{latest?.total != null && latest.current != null && <span className="font-mono text-xs text-muted-foreground">{latest.current}/{latest.total}</span>}</div>
            {latest && <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted-foreground">{latest.detail}</p>}
            {events.length > 1 && <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">查看本节点 {events.length} 条记录</summary><ul className="mt-2 space-y-2">{events.map((event) => <li key={event.id} className="break-words"><time>{event.created_at}</time> · 执行记录 #{event.action_id}<br />{event.detail}</li>)}</ul></details>}
          </li>;
        })}
      </ol>
    </>}
    {trustError && <p role="alert" className="text-sm text-destructive">依据报告暂不可用：{trustError}</p>}
    {trust && <TrustEvidence report={trust} />}
    <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
      <DialogContent>
        <DialogHeader><DialogTitle>删除这项生成任务？</DialogTitle><DialogDescription className="text-sm leading-relaxed">将移除“{job.label || job.target}”的任务记录及专属未发布草稿。运行中的任务会先停止；已经发布的课程和学习记录保留。</DialogDescription></DialogHeader>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter><Button variant="outline" disabled={busy !== null} onClick={() => setDeleteOpen(false)}>保留任务</Button><Button variant="destructive" disabled={busy !== null} onClick={() => void perform("delete")}>{busy === "delete" ? "正在删除…" : "确认删除"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}

export function GenerationTasks({ refreshKey }: { refreshKey?: string }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await request<Job[]>("/api/v1/jobs", { signal });
      if (signal?.aborted) return;
      setJobs(data); setError("");
      setSelected((old) => {
        if (old !== undefined) return old && data.some((job) => keyOf(job) === old) ? old : old === null ? null : undefined;
        const active = data.find((job) => ["running", "queued"].includes(job.status));
        return active ? keyOf(active) : undefined;
      });
    } catch (reason) { if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "任务加载失败"); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => { if (!controller.signal.aborted) void load(controller.signal); });
    const timer = window.setInterval(() => void load(controller.signal), 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load, refreshKey]);
  return <section aria-label="生成流程" className="space-y-3">
    <SectionHeader icon={ListChecks} title="生成流程" count={jobs.length} hint="逐节点查看产物、验收依据与问题；随时停止或继续。" />
    {error && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">{error}<Button variant="outline" size="sm" onClick={() => void load()}>重新加载</Button></div>}
    {loading && <p role="status" className="text-sm text-muted-foreground">正在读取任务…</p>}
    {!loading && !error && !jobs.length && <p className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">输入想学的主题后，调研、大纲、备课和验收进展会逐步出现在这里。</p>}
    {jobs.map((job) => {
      const key = keyOf(job); const open = selected === key;
      return <article key={key} className={`overflow-hidden rounded-xl border bg-card ${["running", "queued"].includes(job.status) ? "border-primary/40" : "border-border"}`}>
        <button type="button" aria-expanded={open} aria-controls={`generation-${job.id}`} onClick={() => setSelected(open ? null : key)} className="flex w-full items-start gap-3 p-4 text-left sm:p-5">
          <div className="min-w-0 flex-1"><p className="break-words font-medium">{job.label || job.target}</p><p className="mt-1 text-xs text-muted-foreground">{job.kind === "request_research" ? "主题调研与首课" : job.kind === "outline_prep" ? "大纲逐课备课" : "笔记备课"} · {job.created_at}</p></div>
          <Badge variant={job.status === "done" ? "success" : job.status === "failed" ? "destructive" : ["running", "queued", "stopping"].includes(job.status) ? "warning" : "secondary"}>{STATUS[job.status] || job.status}</Badge>
          {open ? <ChevronUp size={16} className="mt-1 shrink-0" /> : <ChevronDown size={16} className="mt-1 shrink-0" />}
        </button>
        {open && <div id={`generation-${job.id}`}><JobProgress job={job} onChanged={() => void load()} /></div>}
      </article>;
    })}
  </section>;
}
