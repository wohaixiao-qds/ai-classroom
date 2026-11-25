import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import type { components } from "../../types/api.gen";
import type { NoteItem } from "../../types/catalog";
import { studioRequest } from "./studioRequest";
import type { StudioJobFocus } from "./studioRequest";

type Job = components["schemas"]["JobSummary"];

export function NotePicker({ open, onOpenChange, notes, onFocusJob, returnFocus }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  notes: NoteItem[];
  onFocusJob: (job: StudioJobFocus) => void;
  returnFocus: () => void;
}) {
  const [query, setQuery] = useState("");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const operationPending = useRef(false);
  const navigating = useRef(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void studioRequest<Job[]>("/api/v1/jobs", { signal: controller.signal })
      .then((items) => { if (!controller.signal.aborted) setJobs(items); })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "任务加载失败");
      });
    return () => controller.abort();
  }, [open]);

  function focus(job: StudioJobFocus) {
    navigating.current = true;
    onOpenChange(false);
    onFocusJob({ kind: job.kind, target: job.target });
  }

  async function start(note: NoteItem, previous?: Job) {
    if (operationPending.current) return;
    operationPending.current = true;
    setBusy(note.path);
    setError("");
    try {
      if (previous) {
        const params = new URLSearchParams({ kind: previous.kind, target: previous.target });
        await studioRequest<components["schemas"]["JobOperation"]>(`/api/v1/jobs/resume?${params}`, { method: "POST" });
      } else {
        const body: components["schemas"]["CatalogAction"] = { kind: "request_prep", target: note.path, label: note.title };
        await studioRequest<components["schemas"]["ActionResult"]>("/api/v1/catalog/action", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
      }
      focus({ kind: "request_prep", target: note.path });
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "提交失败，请重试");
    } finally {
      operationPending.current = false;
      setBusy(null);
    }
  }

  const term = query.trim().toLocaleLowerCase();
  const filtered = notes.filter((note) => `${note.title} ${note.area} ${note.path}`.toLocaleLowerCase().includes(term));
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="sm:max-w-2xl" onCloseAutoFocus={(event) => {
      event.preventDefault();
      if (!navigating.current) returnFocus();
    }}>
      <DialogHeader>
        <DialogTitle>从已有笔记生成</DialogTitle>
        <DialogDescription className="text-sm">选择一篇笔记作为备课输入。仅在点击生成时启动任务，笔记库保持只读。</DialogDescription>
      </DialogHeader>
      <Input aria-label="搜索笔记" placeholder="搜索标题、目录或路径" value={query} onChange={(event) => setQuery(event.target.value)} className="min-h-11" />
      {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
      {jobs === null && !error && <p role="status" className="text-sm text-muted-foreground">正在核对已有生成任务…</p>}
      {!filtered.length && <p className="py-4 text-sm text-muted-foreground">{notes.length ? "没有匹配的笔记。" : "暂无可生成课程的笔记。"}</p>}
      <ul className="space-y-3">
        {filtered.map((note) => {
          const job = jobs?.find((item) => item.kind === "request_prep" && item.target === note.path);
          const resumable = !!job && job.can_resume;
          return <li key={note.path} className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-4">
            <div className="min-w-0 flex-[1_1_14rem]">
              <p className="break-words font-medium">{note.title}</p>
              <p className="mt-1 break-all text-sm text-muted-foreground">{note.path}</p>
            </div>
            {job?.status === "done" && job.course_id ? <Button asChild variant="outline" className="min-h-11"><Link onClick={() => onOpenChange(false)} to={`/read/${encodeURIComponent(job.course_id)}`}>查看课程</Link></Button>
              : job && !resumable ? <Button variant="outline" className="min-h-11" onClick={() => focus(job)}>查看任务</Button>
                : <Button variant="outline" className="min-h-11" disabled={jobs === null || busy !== null} onClick={() => void start(note, job)}>{busy === note.path ? "提交中…" : resumable ? "继续任务" : "开始生成"}</Button>}
          </li>;
        })}
      </ul>
    </DialogContent>
  </Dialog>;
}
