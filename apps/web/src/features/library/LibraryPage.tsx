/** 课程库(P7 两层导航)= 书架:每本大纲一本书(封面卡),点书进 /books/:topic
 *  看目录(篇→课,挂接课件平铺真实标题),从目录继续学习。
 *  旧「一页平铺所有大纲卡」换成了真实书架隐喻——目录细节下沉到书页层。 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowUpRight, BookOpen, CircleCheck, LibraryBig, LoaderCircle, Play, RotateCcw, Route, SquarePen } from "lucide-react";

import { KindIcon } from "../../components/KindIcon";
import { PageError, PageLoading } from "../../components/PageState";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { cn } from "../../lib/utils";
import { fetchAllCourses } from "../../lib/learningPath";
import { useCatalog } from "../../hooks/useCatalog";
import type { components } from "../../types/api.gen";
import { courseUnits, isV2, type AnyCourse } from "../../types/csl";

type CompletionState = components["schemas"]["CompletionState"];
type NoteDraft = components["schemas"]["NoteDraft"];
type ApplyResult = components["schemas"]["ApplyResult"];
type ReviewDue = components["schemas"]["ReviewDue"];

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

/** 读阅读器断点:reader-pos-{id} = {top, sec}(原学习台逻辑随页面退役迁此) */
function progressOf(courseId: string): { sec: number } | null {
  try {
    const raw = localStorage.getItem(`reader-pos-${courseId}`);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { sec?: number };
    return Number.isInteger(saved.sec) ? { sec: saved.sec as number } : null;
  } catch {
    return null;
  }
}

interface ShelfBook {
  topic: string;
  domain: string;
  courses: {
    id: string;
    title: string;
    part?: string;
    course_file_ids?: string[];
    prep_status?: string | null;
  }[];
}

/** 封面色板(低饱和,与三主题和谐):按书名哈希取,同书恒色 */
const COVERS = [
  "from-primary/25 via-card to-secondary",
  "from-blue-500/20 via-card to-secondary",
  "from-amber-500/15 via-card to-secondary",
  "from-emerald-500/15 via-card to-secondary",
];

export function LibraryPage() {
  const { cat } = useCatalog();
  const [books, setBooks] = useState<ShelfBook[] | null>(null);
  const [readyById, setReadyById] = useState<Map<string, boolean>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [due, setDue] = useState<ReviewDue | null>(null);

  const load = useCallback(async () => {
    try {
      const list = (await fetch("/api/v1/outlines").then((r) => r.json())) as {
        topic: string;
      }[];
      const [ds, r] = await Promise.all([
        Promise.all(
          list.map((o) =>
            fetch(`/api/v1/outlines/${encodeURIComponent(o.topic)}`)
              .then((res) => res.json() as Promise<ShelfBook>)
              .catch(() => null),
          ),
        ),
        fetchAllCourses().then(({ readyById }) => readyById),
      ]);
      setBooks(ds.filter((d): d is ShelfBook => d !== null));
      setReadyById(r);
    } catch (e: unknown) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 任一本书有课在备课中 → 8s 轮询,封面状态自动跟走
  const cooking = books?.some((b) =>
    b.courses.some((c) => c.prep_status === "queued" || c.prep_status === "running"),
  );
  useEffect(() => {
    if (!cooking) return;
    const t = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(t);
  }, [cooking, load]);

  // 今日横条:到期复习卡(学习台退役后其独有职责收编至此)
  useEffect(() => {
    void fetch("/api/v1/review/due")
      .then((r) => r.json())
      .then((d: ReviewDue) => setDue(d))
      .catch(() => {});
  }, []);

  if (error) return <PageError message={`加载失败:${error}`} />;
  if (!books) return <PageLoading />;

  // 今日两件事(学习台退役后收编):断点继续学 + 到期复习。都没有则横条不渲染
  const continuing = (cat?.learning ?? [])
    .map((c) => ({ ...c, prog: progressOf(c.id) }))
    .filter((c) => c.prog !== null);

  return (
    <div className="workspace-page">
      <header className="workspace-header">
        <div>
          <h1 className="workspace-title">学习</h1>
          <p className="workspace-description">继续上次的课程，复习到期内容，或从书架选一本书。</p>
        </div>
      </header>

      {/* 今日横条:断点继续学 + 到期复习(原学习台独有职责,合一后置顶常驻) */}
      {(continuing.length > 0 || (due && due.items.length > 0)) && (
        <section aria-label="今日学习" className="mb-8 grid grid-cols-1 gap-3 sm:grid-flow-col sm:auto-cols-fr sm:grid-cols-none">
          {continuing.length > 0 &&
            (() => {
              const c = continuing[0];
              return (
                <div className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
                  <div className="min-w-0">
                    <p className="mb-0.5 flex items-center gap-1 font-mono text-xs text-primary">
                      <Play size={11} />
                      继续学{continuing.length > 1 ? ` · ${continuing.length} 门进行中` : ""}
                    </p>
                    <p className="truncate text-sm font-medium">{c.title}</p>
                    <p className="font-mono text-xs text-muted-foreground">
                      上次读到第 {(c.prog!.sec ?? 0) + 1} 节
                    </p>
                  </div>
                  <Button size="sm" asChild className="shrink-0">
                    <Link to={`/read/${c.id}?section=${(c.prog!.sec ?? 0) + 1}`} viewTransition>
                      继续读
                    </Link>
                  </Button>
                </div>
              );
            })()}
          {due && due.items.length > 0 && (
            <div className="min-w-0 rounded-xl border border-border bg-card p-4">
              <p className="mb-2 flex items-center gap-1 font-mono text-xs text-primary">
                <RotateCcw size={11} /> 今日复习 · {due.items.length} 张到期
              </p>
              {/* 到期多时限高滚动(滚动条占宽,右侧留呼吸位),别把书架顶出屏 */}
              <ul className="max-h-56 space-y-1 overflow-y-auto pr-2">
                {due.items.map((r) => (
                  <li key={`${r.course_id}/${r.page_id}`}>
                    <Link
                      to={`/read/${r.course_id}?section=${r.page_no}`}
                      viewTransition
                      className="flex items-center justify-between gap-2 rounded-lg px-2 py-1 text-sm transition-colors hover:bg-secondary"
                    >
                      <span className="min-w-0 truncate text-muted-foreground">
                        {r.course_title} · {r.page_title}
                        {r.overdue_days > 0 && ` · 逾期 ${r.overdue_days} 天`}
                      </span>
                      <Badge
                        variant={r.mastery >= 0.9 ? "success" : "warning"}
                        className="shrink-0 font-mono text-[10px]"
                      >
                        {Math.round(r.mastery * 100)}%
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
      <section aria-labelledby="bookshelf-title">
        <h2 id="bookshelf-title" className="mb-4 flex items-baseline gap-2 text-xl font-semibold">
          书架 <span className="text-sm font-normal tabular-nums text-muted-foreground">{books.length} 本</span>
        </h2>
        {books.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-6 sm:p-8">
            <p className="mb-3 text-sm text-muted-foreground">生成第一门课后，就可以在书架上打开它。</p>
            <Button asChild size="sm"><Link to="/studio">去生成中心</Link></Button>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 xl:grid-cols-4">
            {books.map((b, idx) => {
              // 行级语义同书页(2026-11-17 拍板 A):全片读完才算行✓;游标=行内第一个未读片
              const rowComplete = (c: ShelfBook["courses"][number]) =>
                (c.course_file_ids ?? []).length > 0 &&
                (c.course_file_ids ?? []).every((r) => readyById.get(r));
              const done = b.courses.filter(rowComplete).length;
              const cursor = b.courses.find(
                (c) => (c.course_file_ids ?? []).length > 0 && !rowComplete(c),
              );
              const cursorFile =
                cursor?.course_file_ids?.find((r) => !readyById.get(r)) ??
                (cursor?.course_file_ids ?? [])[0];
              const parts = new Set(b.courses.map((c) => c.part?.trim() || "正文"));
              const busy = b.courses.some(
                (c) => c.prep_status === "queued" || c.prep_status === "running",
              );
              const allDone = b.courses.length > 0 && done === b.courses.length;
              return (
                <div
                  key={b.topic}
                  className="library-book-card desktop-book-enter relative min-h-48 sm:aspect-[3/4]"
                  style={{ animationDelay: `${Math.min(idx, 6) * 35}ms` }}
                >
                  <div
                    className={cn(
                      "library-book-card__surface relative flex min-h-48 flex-col overflow-hidden rounded-xl border border-border bg-gradient-to-br sm:aspect-[3/4]",
                      "hover:border-primary/55 focus-within:border-primary/60",
                      COVERS[Math.abs(b.topic.length * 7 + idx) % COVERS.length],
                    )}
                  >
                    {/* 书名区:整块可点,进书页目录 */}
                    <Link
                      to={`/books/${encodeURIComponent(b.topic)}`}
                      viewTransition
                      className="group/cover flex min-h-0 flex-1 flex-col outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70 focus-visible:ring-inset"
                      title={`打开《${b.topic}》目录`}
                    >
                      <span className="flex items-center gap-1 px-3 pt-3 font-mono text-[10px] tracking-widest text-muted-foreground">
                        <BookOpen size={10} className="text-primary" />
                        {b.domain || "书"}
                        <ArrowUpRight
                          aria-hidden="true"
                          size={14}
                          className="ml-auto hidden shrink-0 text-primary opacity-0 transition-[opacity,translate] duration-(--dur-fast) ease-out group-hover/cover:opacity-100 group-focus-visible/cover:opacity-100 motion-safe:-translate-x-1 motion-safe:group-hover/cover:translate-x-0 motion-safe:group-focus-visible/cover:translate-x-0 lg:block"
                        />
                      </span>
                      <span className="mt-2 mb-3 line-clamp-3 px-3 break-words text-[15px] font-semibold leading-snug">
                        {b.topic}
                      </span>
                      <span className="mt-auto px-3 pb-1">
                        <span className="block font-mono text-[10px] text-muted-foreground">
                          {parts.size} 篇 · {b.courses.length} 课
                          {busy && (
                            <span className="ml-1 inline-flex translate-y-0.5 align-middle text-warning">
                              <LoaderCircle size={10} className="animate-spin" />
                            </span>
                          )}
                        </span>
                        <span className="mb-2 mt-1.5 block h-1 overflow-hidden rounded-full bg-foreground/10">
                          <span
                            className="block h-full rounded-full bg-primary transition-all"
                            style={{
                              width: `${b.courses.length ? Math.round((100 * done) / b.courses.length) : 0}%`,
                            }}
                          />
                        </span>
                      </span>
                    </Link>
                    {/* 底条:当前课 + 继续读直达(书架一步进阅读器,不必先进书页) */}
                    <span className="flex items-center justify-between gap-2 px-3 pb-3">
                      <span className="min-w-0 truncate text-[11px]">
                        {allDone ? (
                          <span className="text-success">✓ 全书读完</span>
                        ) : cursor ? (
                          <span className="text-muted-foreground">▶ {cursor.title}</span>
                        ) : (
                          <span className="text-muted-foreground/70">未开课</span>
                        )}
                      </span>
                      {cursor && cursorFile && (
                        <Link
                          to={`/read/${cursorFile}`}
                          viewTransition
                          className="flex min-h-8 shrink-0 items-center rounded-md bg-primary/15 px-2 text-xs font-medium text-primary transition-colors hover:bg-primary/25"
                          title={`继续读《${cursor.title}》`}
                        >
                          继续读
                        </Link>
                      )}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
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
  const [refine, setRefine] = useState(""); // 重蒸要求:对上一版草稿的修改意见,随「重新生成」带上
  const [draftErr, setDraftErr] = useState<string | null>(null);
  const [written, setWritten] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [draftDialogOpen, setDraftDialogOpen] = useState(false);
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
    // 生成中/已有草稿 → 仅重开弹窗接上(进度/草稿都还在);都没有 → 启动蒸馏
    if (draftBusy || draft) {
      setDraftDialogOpen(true);
      return;
    }
    setDraftErr(null);
    setWritten(null);
    setDraftDialogOpen(true);
    startDraftSSE();
  }

  function startDraftSSE(refine?: string) {
    setDraft(null);
    setDraftBusy(true);
    setDraftStage("connect");
    setDistillChars(0);
    setDraftElapsed(0);
    const started = Date.now();
    const ac = new AbortController();
    draftAbortRef.current = ac;
    // 重蒸反馈(2026-11-19):意见直达蒸馏 prompt,重新生成不再纯重掷
    const qs = refine?.trim() ? `?feedback=${encodeURIComponent(refine.trim().slice(0, 200))}` : "";
    // 计时器:弹层上实时走「已等待 N 秒」
    const timer = window.setInterval(
      () => setDraftElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );

    void (async () => {
      try {
        const resp = await fetch(`/api/v1/notes/draft-stream/${courseId}${qs}`, {
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
    setApplying(true); // 正常应是缓存命中秒回;409=缓存失效,红字提示重新生成
    void fetch(`/api/v1/notes/apply/${courseId}`, { method: "POST" })
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json() as Promise<ApplyResult>;
      })
      .then((r) => {
        setWritten(r.note_path);
        setDraft(null);
      })
      .catch((e: unknown) => setDraftErr(String(e)))
      .finally(() => setApplying(false));
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
  function closeDraftDialog() {
    // 只关弹层:蒸馏继续跑,重开弹窗能接上进度/草稿(P7)
    setDraftDialogOpen(false);
  }

  function finishWritten() {
    // 写回已成功,没有可续的流:全重置+关闭,不留空壳弹窗
    setWritten(null);
    setDraft(null);
    setDraftErr(null);
    setDraftDialogOpen(false);
  }

  function cancelDraftGen() {
    draftAbortRef.current?.abort();
    setDraftBusy(false);
    setDraftStage(null);
    setDraftDialogOpen(false);
    setDraftErr("已取消生成");
  }

  function regenerateDraft() {
    setDraft(null);
    setDraftErr(null);
    startDraftSSE(refine);
  }

  return (
    <div className="workspace-page workspace-page--detail">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link to="/courses">← 课程库</Link>
      </Button>
      {course.meta.topic && (
        <p className="mt-4 flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <LibraryBig size={12} /> {course.meta.topic}
        </p>
      )}
      <div className="workspace-header mt-3">
        <div className="min-w-0">
          <h1 className="workspace-title">{course.title}</h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {course.scenario} · {isV2(course) ? `${units.length} 节` : `${units.length} 页 · ${sumSentences(course)} 句`} · {cps.length} 检查点
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link to={`/read/${course.id}`} viewTransition>
              <Play size={15} aria-hidden="true" /> 阅读课程
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
      <Dialog open={draftDialogOpen} onOpenChange={(o) => !o && (written ? finishWritten() : closeDraftDialog())}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-2xl">
          {written ? (
            <div className="p-8 text-center">
              <CircleCheck size={36} className="anim-pop mx-auto mb-3 text-success" />
              <p className="mb-1 font-medium">已写回知识库</p>
              <p className="mb-4 font-mono text-xs break-all text-muted-foreground">{written}</p>
              <p className="text-xs text-muted-foreground">巩固区已留空——去 Obsidian 亲手填完它。</p>
              <Button className="mt-5" onClick={finishWritten}>
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
                          {pct}% · 已等待 {draftElapsed} 秒 · 预计还需几分钟
                        </p>
                        <Button variant="ghost" size="sm" onClick={cancelDraftGen}>
                          取消生成
                        </Button>
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
                <DialogFooter className="flex-col gap-2 border-t border-border px-6 py-4 sm:flex-col">
                  {/* 重蒸要求:填了再点「重新生成」,意见直达蒸馏 prompt(留空=原样重掷) */}
                  <Input
                    value={refine}
                    onChange={(e) => setRefine(e.target.value)}
                    placeholder="重蒸要求(可选):如 更精简 / 多给代码示例 / 巩固题只留两道…"
                    className="h-8 text-xs"
                    disabled={applying}
                  />
                  <div className="flex w-full justify-end gap-2">
                    <Button variant="ghost" disabled={applying} onClick={() => setDraft(null)}>
                      取消
                    </Button>
                    <Button variant="outline" disabled={applying} onClick={regenerateDraft}>
                      ↺ 重新生成{refine.trim() ? "(带要求)" : ""}
                    </Button>
                    <Button onClick={confirmWrite} disabled={applying}>
                      {applying ? "写入中…" : "确认写回"}
                    </Button>
                  </div>
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
