import { ListTodo } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import type { components } from "../../types/api.gen";
import { LearningQuestions } from "../learning-questions/index";
import { studioRequest } from "./studioRequest";
import type { StudioJobFocus } from "./studioRequest";

type Item = components["schemas"]["WishlistItem"];
type Filter = Item["status"];
const FILTERS: { value: Filter; label: string }[] = [
  { value: "pending", label: "待学" }, { value: "started", label: "已发起" }, { value: "removed", label: "已移除" },
];
const SOURCE_LABELS = { manual: "手动记录", vault: "知识库待探", question: "延伸问题" };

export function WishlistPanel({ refreshKey, onFocusJob }: {
  refreshKey: number;
  onFocusJob: (job: StudioJobFocus) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<Filter>("pending");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<components["schemas"]["WishlistResponse"] | null>(null);
  const [loadedFilter, setLoadedFilter] = useState<Filter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const operationPending = useRef(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void studioRequest<components["schemas"]["WishlistResponse"]>(`/api/v1/wishlist?status=${filter}`, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) { setData(result); setLoadedFilter(filter); }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "待学清单加载失败");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filter, refreshKey, revision, open]);

  function refresh() {
    setLoading(true);
    setError("");
    setRevision((value) => value + 1);
  }

  async function operate(item: Item, action: "start" | "remove" | "restore") {
    if (operationPending.current) return;
    operationPending.current = true;
    setBusy(item.id);
    setError("");
    setNotice("");
    try {
      if (action === "start") {
        const result = await studioRequest<components["schemas"]["WishlistStartResult"]>(`/api/v1/wishlist/${encodeURIComponent(item.id)}/start`, { method: "POST" });
        setNotice(result.note || "已发起生成，可在生成任务查看流程。");
        onFocusJob({ kind: result.job.kind, target: result.job.target });
      } else {
        const body: components["schemas"]["WishlistUpdate"] = { status: action === "remove" ? "removed" : "pending" };
        await studioRequest<Item>(`/api/v1/wishlist/${encodeURIComponent(item.id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setNotice(action === "remove" ? "已从待学清单移除，可在已移除中恢复。" : "已恢复到待学清单。");
      }
      refresh();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "操作失败，请重试");
    } finally {
      operationPending.current = false;
      setBusy(null);
    }
  }

  const term = query.trim().toLocaleLowerCase();
  const items = loadedFilter === filter ? data?.items.filter((item) => `${item.title} ${item.sources.map((source) => source.label).join(" ")}`.toLocaleLowerCase().includes(term)) ?? [] : [];
  return <details open={open} onToggle={(event) => {
    if (event.target !== event.currentTarget) return;
    const expanded = event.currentTarget.open;
    if (expanded !== open) { setLoading(true); setError(""); setOpen(expanded); }
  }} className="min-w-0 rounded-xl border border-border bg-card">
    <summary className="min-h-11 cursor-pointer px-4 py-4 sm:px-6">
      <span className="inline-flex flex-wrap items-center gap-2 font-medium"><ListTodo size={18} aria-hidden="true" />待学清单<Badge variant="secondary">{data ? `${data.pending_count} 条待学` : error ? "读取失败" : "待读取"}</Badge></span>
      <span className="mt-1 block text-sm text-muted-foreground">先收集想学的内容，需要时再开始生成。</span>
    </summary>
    <div className="space-y-4 border-t border-border p-4 sm:p-6">
      <div className="flex flex-wrap gap-2" role="group" aria-label="待学清单筛选">
        {FILTERS.map((entry) => <Button key={entry.value} variant={filter === entry.value ? "secondary" : "ghost"} aria-pressed={filter === entry.value} className="min-h-11" onClick={() => { if (filter !== entry.value) { setFilter(entry.value); setLoading(true); setError(""); } }}>{entry.label}</Button>)}
        <Button variant="ghost" className="min-h-11 sm:ml-auto" disabled={loading} onClick={refresh}>刷新清单</Button>
      </div>
      <Input aria-label="搜索待学清单" placeholder="搜索主题或来源" value={query} onChange={(event) => setQuery(event.target.value)} className="min-h-11" />
      {loading && <p role="status" className="text-sm text-muted-foreground">正在读取待学清单…</p>}
      {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="break-words text-sm text-primary">{notice}</p>}
      {!loading && !error && !items.length && <p className="py-3 text-sm text-muted-foreground">{query.trim() ? "没有匹配的条目。" : filter === "pending" ? "还没有待学内容，可以在上方输入主题并先存起来。" : filter === "started" ? "还没有从清单发起的任务。" : "暂无已移除条目。"}</p>}
      <ul className="space-y-3">
        {items.map((item) => <li key={item.id} className="min-w-0 rounded-lg border border-border p-4">
          <p className="break-words font-medium">{item.title}</p>
          <ul className="mt-2 space-y-1 text-sm text-muted-foreground">{item.sources.map((source) => <li key={`${source.kind}:${source.id}`} className="break-words">{SOURCE_LABELS[source.kind]} · {source.label}{source.course_id && <Link className="ml-2 text-primary underline underline-offset-4" to={`/read/${encodeURIComponent(source.course_id)}`}>查看来源课程</Link>}</li>)}</ul>
          <div className="mt-3 flex flex-wrap gap-2">
            {item.status === "pending" && <Button className="min-h-11" disabled={busy !== null} onClick={() => void operate(item, "start")}>{busy === item.id ? "处理中…" : "开始生成"}</Button>}
            {item.status === "started" && (item.job && item.job.status !== "deleted" ? <Button variant="outline" className="min-h-11" onClick={() => { if (item.job) onFocusJob({ kind: item.job.kind, target: item.job.target }); }}>查看任务</Button> : <span className="self-center text-sm text-muted-foreground">原任务已删除或未保留记录</span>)}
            {item.status === "started" && item.job?.status === "done" && item.job.course_id && <Button asChild variant="outline" className="min-h-11"><Link to={`/read/${encodeURIComponent(item.job.course_id)}`}>查看课程</Link></Button>}
            <Button variant="ghost" className="min-h-11" disabled={busy !== null} onClick={() => void operate(item, item.status === "removed" ? "restore" : "remove")}>{item.status === "removed" ? "恢复" : "移除"}</Button>
          </div>
        </li>)}
      </ul>
      <p className="text-sm text-muted-foreground">移除条目只整理清单；任务的停止、继续与删除请在生成任务中操作。</p>
      <LearningQuestions unassigned onSaved={refresh} />
    </div>
  </details>;
}
