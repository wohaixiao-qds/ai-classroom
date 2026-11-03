/** 课程库(甲方案):左侧主题树(领域→主题→层)筛选 + 课程卡 → 详情页 → 课堂。
 *  树从 topic 串自动生长("Agent / harness / Runtime"),与 vault 目录心智一致,零手工维护。
 *  topic 真源是后端 catalog 的实时推导(老课件文件里没有);此处拉取时合并进课程数据。 */
import { BookOpen, LibraryBig, Play, CircleCheck, SquarePen, Route } from "lucide-react";
import { OutlineToc } from "./OutlineToc";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { KindIcon } from "../../components/KindIcon";
import { PageError, PageLoading } from "../../components/PageState";
import { Button } from "../../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { fetchAllCourses } from "../../lib/learningPath";
import type { components } from "../../types/api.gen";
import { courseUnits, isV2, type AnyCourse } from "../../types/csl";

type CompletionState = components["schemas"]["CompletionState"];
type NoteDraft = components["schemas"]["NoteDraft"];
type ApplyResult = components["schemas"]["ApplyResult"];

/** 错误响应解析:HTTPException 的 JSON 取 detail;网关/裸 500 的纯文本直接用原文。 */
async function errText(r: Response): Promise<string> {
  const raw = await r.text();
  try {
    const detail = (JSON.parse(raw) as { detail?: string }).detail;
    if (detail) return detail;
  } catch {
    /* 非 JSON 响应体,原文透出 */
  }
  return raw || `HTTP ${r.status}`;
}

/** 课程库(P7)= 大纲书架:每本大纲是一本书(篇→课→进度),所有课(新旧)
 *  一律挂在大纲目录的对应位置;不再展示零散课程卡。详情页直达:/courses/:id。 */
export function LibraryPage() {
  const [courses, setCourses] = useState<AnyCourse[] | null>(null);
  const [readyById, setReadyById] = useState<Map<string, boolean>>(new Map());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setCourses(null);
    setError(null);
    fetchAllCourses()
      .then(({ courses, readyById }) => {
        setCourses(courses);
        setReadyById(readyById);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <PageError message={`加载失败:${error}`} />;
  if (!courses) return <PageLoading />;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="mb-1 text-2xl font-bold">课程库</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        每本大纲是一本书:篇→课→你的进度。已出的课点开即读;空白章节点击即出课。
      </p>
      <OutlineToc readyById={readyById} />
    </div>
  );
}

export function CourseDetailPage() {
  const { courseId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [course, setCourse] = useState<AnyCourse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prog, setProg] = useState<CompletionState | null>(null);
  const [draft, setDraft] = useState<NoteDraft | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftErr, setDraftErr] = useState<string | null>(null);
  const [written, setWritten] = useState<string | null>(null);
  // 蒸馏进度(P7):后端 SSE 真实阶段 + 已产出字数 + 已等待秒数
  const [draftStage, setDraftStage] = useState<"connect" | "collect" | "distill" | null>(null);
  const [distillChars, setDistillChars] = useState(0);
  const [draftElapsed, setDraftElapsed] = useState(0);
  const draftAbortRef = useRef<AbortController | null>(null);
  const [depTitles, setDepTitles] = useState<Record<string, string>>({});
  // 书内相邻(P7):本课所在大纲书里的上一课/下一课(取代全局拓扑路线)
  const [neighbors, setNeighbors] = useState<{
    book: string;
    step: number;
    total: number;
    prev: { title: string; file: string } | null;
    next: { title: string; file: string } | null;
  } | null>(null);

  // 先修课标题(详情页展示用;拉不到就用 id 兜底)
  useEffect(() => {
    if (!course) return;
    for (const d of course.meta.depends_on ?? []) {
      void fetch(`/courses/${d.id}.csl.json`)
        .then((r) => r.json() as Promise<AnyCourse>)
        .then((c) => setDepTitles((prev) => ({ ...prev, [c.id]: c.title })))
        .catch(() => {});
    }
  }, [course]);

  useEffect(() => {
    void (async () => {
      try {
        const list = (await fetch("/api/v1/outlines").then((r) => r.json())) as {
          topic: string;
        }[];
        for (const o of list) {
          const d = (await fetch(`/api/v1/outlines/${encodeURIComponent(o.topic)}`)
            .then((r) => r.json())) as {
            topic: string;
            courses: { id: string; title: string; course_file_id?: string | null; course_file_ids?: string[] }[];
          };
          const idx = d.courses.findIndex(
            (c) =>
              c.course_file_id === courseId ||
              (c.course_file_ids ?? []).includes(courseId),
          );
          if (idx < 0) continue;
          const at = (i: number) => {
            const c = d.courses[i];
            const file = c.course_file_id ?? (c.course_file_ids ?? [])[0];
            return file ? { title: c.title, file } : null;
          };
          setNeighbors({
            book: d.topic,
            step: idx + 1,
            total: d.courses.length,
            prev: idx > 0 ? at(idx - 1) : null,
            next: idx < d.courses.length - 1 ? at(idx + 1) : null,
          });
          return;
        }
        setNeighbors(null);
      } catch {
        setNeighbors(null);
      }
    })();
  }, [courseId]);

  useEffect(() => {
    setCourse(null);
    setError(null);
    fetch(`/courses/${courseId}.csl.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<AnyCourse>;
      })
      .then(setCourse)
      .catch((e: unknown) => setError(String(e)));
    void fetch(`/api/v1/progress/${courseId}`)
      .then((r) => r.json())
      .then(setProg)
      .catch(() => {});
  }, [courseId]);

  function openDraft() {
    setDraftErr(null);
    setDraft(null);
    setWritten(null);
    setDraftBusy(true);
    setDraftStage("connect");
    setDistillChars(0);
    setDraftElapsed(0);
    const started = Date.now();
    const ac = new AbortController();
    draftAbortRef.current = ac;
    // 计时器:弹层上实时走「已等待 N 秒」
    const timer = window.setInterval(
      () => setDraftElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );

    void (async () => {
      try {
        const resp = await fetch(`/api/v1/notes/draft-stream/${courseId}`, {
          method: "GET",
          signal: ac.signal,
        });
        if (!resp.ok || !resp.body) {
          const detail = await resp.text().catch(() => "");
          throw new Error(detail.slice(-200) || `HTTP ${resp.status}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const blocks = buf.split("\n\n");
          buf = blocks.pop() ?? "";
          for (const block of blocks) {
            let stage = "";
            let dataRaw = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event: ")) stage = line.slice(7).trim();
              else if (line.startsWith("data: ")) dataRaw = line.slice(6);
            }
            if (!dataRaw) continue;
            const data = JSON.parse(dataRaw) as Record<string, unknown>;
            if (stage === "collect") setDraftStage("collect");
            else if (stage === "distill") {
              setDraftStage("distill");
              setDistillChars(Number(data.chars ?? 0));
            } else if (stage === "done") {
              window.clearInterval(timer);
              setDraftBusy(false);
              setDraftStage(null);
              setDraft(data.draft as NoteDraft);
              return;
            } else if (stage === "error") {
              window.clearInterval(timer);
              setDraftBusy(false);
              setDraftStage(null);
              setDraftErr(String(data.message ?? "蒸馏失败"));
              return;
            }
          }
        }
        throw new Error("流意外结束");
      } catch (e: unknown) {
        window.clearInterval(timer);
        setDraftBusy(false);
        setDraftStage(null);
        setDraftErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }

  function closeDraft() {
    draftAbortRef.current?.abort();
    setDraft(null);
    setDraftBusy(false);
    setDraftErr(null);
    setWritten(null);
    setDraftStage(null);
    setDistillChars(0);
  }

  // 课堂学完邀请跳来(?sink=1)→ 自动开草稿
  useEffect(() => {
    if (searchParams.get("sink") === "1" && prog?.ready) {
      searchParams.delete("sink");
      setSearchParams(searchParams, { replace: true });
      openDraft();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 邀请只应触发一次
  }, [prog?.ready]);

  function confirmWrite() {
    void fetch(`/api/v1/notes/apply/${courseId}`, { method: "POST" })
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json() as Promise<ApplyResult>;
      })
      .then((r) => {
        setWritten(r.note_path);
        setDraft(null);
      })
      .catch((e: unknown) => setDraftErr(String(e)));
  }

  if (error) return <PageError message={`课件加载失败:${error}`} back={<Button asChild variant="secondary" size="sm"><Link to="/courses">← 课程库</Link></Button>} />;
  if (!course) return <PageLoading />;

  const units = courseUnits(course);
  const cps = units.filter((u) => u.hasCheckpoint);
  // 本课在路线中的位置(拉不到全量课时不显示)
  const stepIdx = neighbors ? neighbors.step - 1 : -1;
  const prevCourse = neighbors?.prev ?? null;
  const nextCourse = neighbors?.next ?? null;
  const sinkTip = !prog?.ready
    ? `学完解锁(还差:${[
        !prog?.done ? "播放到最后一页" : "",
        prog && prog.checkpoints_passed < prog.checkpoints_total
          ? `检查点 ${prog.checkpoints_passed}/${prog.checkpoints_total}`
          : "",
      ]
        .filter(Boolean)
        .join(";")})`
    : "生成笔记草稿,预览确认后写入知识库";
  const draftOpen = Boolean(draft || draftBusy || draftErr || written);

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link to="/courses">← 课程库</Link>
      </Button>
      {course.meta.topic && (
        <p className="mt-4 flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <LibraryBig size={12} /> {course.meta.topic}
        </p>
      )}
      <div className="mt-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">{course.title}</h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {course.scenario} · {isV2(course) ? `${units.length} 节` : `${units.length} 页 · ${sumSentences(course)} 句`} · {cps.length} 检查点
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Button size="lg" asChild>
            <Link to={`/read/${course.id}`} viewTransition>
              <Play size={15} /> 进阅读器
            </Link>
          </Button>
          <Button
            variant="outline"
            onClick={openDraft}
            disabled={!prog?.ready || draftBusy}
            title={sinkTip}
          >
            <SquarePen size={14} /> 沉淀为笔记
          </Button>
        </div>
      </div>

      {/* 学习进度:检查点通过度(有进度数据才显示) */}
      {prog && prog.checkpoints_total > 0 && (
        <div className="mt-4 flex items-center gap-3">
          <div className="h-1.5 w-44 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.round((100 * prog.checkpoints_passed) / prog.checkpoints_total)}%` }}
            />
          </div>
          <span className="font-mono text-xs text-muted-foreground">
            检查点 {prog.checkpoints_passed}/{prog.checkpoints_total}
            {prog.ready && " · 学完可沉淀"}
          </span>
        </div>
      )}

      {/* 书内位置:循序渐进的「你在这里」+ 前后课导航(直达阅读) */}
      {neighbors && stepIdx >= 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 font-mono">
            <Route size={12} className="text-primary" /> 《{neighbors.book}》第 {stepIdx + 1} / {neighbors.total} 课
          </span>
          {prevCourse && (
            <span>
              ← 上一课:
              <Link to={`/read/${prevCourse.file}`} className="text-primary hover:underline">
                {prevCourse.title}
              </Link>
            </span>
          )}
          {nextCourse && (
            <span>
              下一课:
              <Link to={`/read/${nextCourse.file}`} className="text-primary hover:underline">
                {nextCourse.title}
              </Link>
              →
            </span>
          )}
        </div>
      )}

      {/* 学习顺序:先修依赖(来自 meta.depends_on,人工/备课标注) */}
      {(course.meta.depends_on?.length ?? 0) > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium tracking-wide text-muted-foreground">建议先学</h2>
          <ul className="space-y-1.5">
            {course.meta.depends_on!.map((d) => (
              <li key={d.id} className="rounded-lg border border-border bg-card px-4 py-2 text-sm">
                <Link to={`/courses/${d.id}`} className="text-primary hover:underline">
                  {depTitles[d.id] ?? d.id}
                </Link>
                {d.reason && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{d.reason}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted-foreground">本课大纲</h2>
        <ul className="space-y-1.5">
          {units.map((u, i) => (
            <li
              key={u.id}
              className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-2 text-sm transition-colors hover:border-primary/30"
            >
              <span className="font-mono text-xs text-muted-foreground">{i + 1}</span>
              <span className="text-muted-foreground">
                {u.kind ? <KindIcon kind={u.kind} /> : <BookOpen size={13} />}
              </span>
              <span className="flex-1 truncate">{u.title}</span>
              {u.hasCheckpoint && (
                <span title="有复述检查点" className="flex text-primary">
                  <CircleCheck size={13} />
                </span>
              )}
              {u.sentences > 0 && (
                <span className="font-mono text-xs text-muted-foreground opacity-60">{u.sentences} 句</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {course.meta.sources?.length ? (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium tracking-wide text-muted-foreground">来源(有据可查)</h2>
          <ul className="space-y-1">
            {course.meta.sources.map((s, i) => (
              <li key={i} className="text-xs">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary hover:underline"
                >
                  [{i + 1}] {s.title || s.url}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {course.meta.source_notes.length ? (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium tracking-wide text-muted-foreground">关联材料</h2>
          <ul className="space-y-1 font-mono text-xs text-muted-foreground">
            {course.meta.source_notes.map((n) => (
              <li key={n} title={n}>
                · {n.split("/").slice(-1)[0]}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* 写回确认闸:预览(路径+待探勾选+全文)→ 人确认 → 才落盘 vault */}
      <Dialog open={draftOpen} onOpenChange={(o) => !o && closeDraft()}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-2xl">
          {written ? (
            <div className="p-8 text-center">
              <CircleCheck size={36} className="anim-pop mx-auto mb-3 text-success" />
              <p className="mb-1 font-medium">已写回知识库</p>
              <p className="mb-4 font-mono text-xs break-all text-muted-foreground">{written}</p>
              <p className="text-xs text-muted-foreground">巩固区已留空——去 Obsidian 亲手填完它。</p>
              <Button className="mt-5" onClick={() => setWritten(null)}>
                完成
              </Button>
            </div>
          ) : (
            <>
              <DialogHeader className="border-b border-border px-6 py-4">
                <DialogTitle>写回草稿预览</DialogTitle>
                {draft && (
                  <DialogDescription>
                    {draft.mode === "append" ? "追加到" : "新建"}:{draft.note_path}
                  </DialogDescription>
                )}
                {draftErr && (
                  <DialogDescription className="text-destructive">{draftErr}</DialogDescription>
                )}
              </DialogHeader>
              {draftBusy && (
                <div className="flex flex-col items-center gap-3 px-6 py-12">
                  {/* 确定性进度条(同上传/下载):蒸馏字数 / 估算总量,上限 95% 留给收尾 */}
                  {(() => {
                    const pct =
                      draftStage === "collect"
                        ? 5
                        : Math.min(95, Math.round((distillChars / 3200) * 100));
                    return (
                      <>
                        <div className="h-1.5 w-72 overflow-hidden rounded-full bg-secondary">
                          <div
                            className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <p className="text-sm font-medium">
                          {draftStage === "collect"
                            ? "汇总三源材料(课件 / 批改纠偏 / 答疑对话)…"
                            : `AI 蒸馏中 · 已产出 ${distillChars} 字`}
                        </p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {pct}% · 已等待 {draftElapsed} 秒 · 预计还需几分钟,请勿关闭
                        </p>
                      </>
                    );
                  })()}
                </div>
              )}
              {draft && (
                <div className="flex-1 overflow-y-auto px-6 py-4">
                  {draft.todo_edit && (
                    <div className="mb-4 rounded-lg border border-border bg-background p-3 font-mono text-xs">
                      <p className="mb-1 text-muted-foreground">待探勾选({draft.todo_edit.file}):</p>
                      <p className="text-muted-foreground/60">- {draft.todo_edit.old_line.trim()}</p>
                      <p className="text-success">+ {draft.todo_edit.new_line.trim()}</p>
                    </div>
                  )}
                  <pre className="whitespace-pre-wrap text-xs leading-relaxed">{draft.content}</pre>
                </div>
              )}
              {draft && (
                <DialogFooter className="border-t border-border px-6 py-4">
                  <Button variant="ghost" onClick={() => setDraft(null)}>
                    取消
                  </Button>
                  <Button onClick={confirmWrite}>确认写回</Button>
                </DialogFooter>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function sumSentences(c: AnyCourse): number {
  return isV2(c) ? 0 : c.pages.reduce((n, p) => n + p.script.length, 0);
}
