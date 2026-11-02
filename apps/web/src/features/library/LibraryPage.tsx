/** 课程库(甲方案):左侧主题树(领域→主题→层)筛选 + 课程卡 → 详情页 → 课堂。
 *  树从 topic 串自动生长("Agent / harness / Runtime"),与 vault 目录心智一致,零手工维护。
 *  topic 真源是后端 catalog 的实时推导(老课件文件里没有);此处拉取时合并进课程数据。 */
import { BookOpen, ChevronDown, ChevronRight, Folder, LibraryBig, Play, CircleCheck, SquarePen, Route } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { KindIcon } from "../../components/KindIcon";
import { PageError, PageLoading } from "../../components/PageState";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { fetchAllCourses, suggestOrder } from "../../lib/learningPath";
import { cn } from "../../lib/utils";
import type { components } from "../../types/api.gen";
import { courseUnits, isV2, type AnyCourse } from "../../types/csl";

type CompletionState = components["schemas"]["CompletionState"];
type NoteDraft = components["schemas"]["NoteDraft"];
type ApplyResult = components["schemas"]["ApplyResult"];

// ---------- 主题树 ----------

interface TreeNode {
  name: string;
  path: string[]; // 从根到本节点的路径(筛选键)
  children: TreeNode[];
  courses: AnyCourse[]; // 恰好挂在本节点的课(叶子层)
}

/** 主题串 → 树层级段。单段主题若以已知领域开头(「Agent 解析层」)提为两层。 */
function topicSegs(topic: string | null | undefined, domains: Set<string>): string[] {
  const t = topic ?? "未分组";
  const segs = t.split(" / ");
  if (segs.length === 1) {
    const i = segs[0].indexOf(" ");
    if (i > 0 && domains.has(segs[0].slice(0, i))) {
      return [segs[0].slice(0, i), segs[0].slice(i + 1)];
    }
  }
  return segs;
}

function deriveDomains(courses: AnyCourse[]): Set<string> {
  const domains = new Set<string>();
  for (const c of courses) {
    const segs = (topicOf(c) ?? "").split(" / ");
    if (segs.length > 1) domains.add(segs[0]);
  }
  return domains;
}

/** topic 真源:合并进 meta.topic 的 catalog 推导值(见拉取处) */
function topicOf(c: AnyCourse): string | null {
  return c.meta.topic ?? null;
}

function buildTree(courses: AnyCourse[], domains: Set<string>): TreeNode {
  const root: TreeNode = { name: "", path: [], children: [], courses: [] };
  for (const c of courses) {
    let node = root;
    for (const seg of topicSegs(topicOf(c), domains)) {
      let child = node.children.find((x) => x.name === seg);
      if (!child) {
        child = { name: seg, path: [...node.path, seg], children: [], courses: [] };
        node.children.push(child);
      }
      node = child;
    }
    node.courses.push(c);
  }
  return root;
}

function countCourses(n: TreeNode): number {
  return n.courses.length + n.children.reduce((s, x) => s + countCourses(x), 0);
}

function TreeView({
  node,
  sel,
  onSelect,
  depth = 0,
}: {
  node: TreeNode;
  sel: string[] | null;
  onSelect: (path: string[] | null) => void;
  depth?: number;
}) {
  return (
    <ul>
      {node.children.map((ch) => {
        const active = sel && sel.join("/") === ch.path.join("/");
        const expanded = sel ? sel.join("/").startsWith(ch.path.join("/")) : false;
        return (
          <li key={ch.path.join("/")}>
            <button
              onClick={() => onSelect(active ? null : ch.path)}
              className={cn(
                "flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                active
                  ? "bg-primary/15 font-medium text-foreground ring-1 ring-primary/40"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
              style={{ paddingLeft: 8 + depth * 14 }}
            >
              {ch.children.length > 0 ? (
                expanded ? (
                  <ChevronDown size={12} className="shrink-0" />
                ) : (
                  <ChevronRight size={12} className="shrink-0" />
                )
              ) : (
                <Folder size={12} className="shrink-0" />
              )}
              <span className="min-w-0 flex-1 truncate">{ch.name}</span>
              <span className="shrink-0 font-mono opacity-60">{countCourses(ch)}</span>
            </button>
            {expanded && ch.children.length > 0 && (
              <TreeView node={ch} sel={sel} onSelect={onSelect} depth={depth + 1} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** sel 命中:课程层级段在选中路径之下(选中 Agent,则 Agent/harness/Runtime 的课都算) */
function inSelection(c: AnyCourse, sel: string[] | null, domains: Set<string>): boolean {
  if (!sel) return true;
  const segs = topicSegs(topicOf(c), domains);
  return sel.every((s, i) => segs[i] === s);
}

export function LibraryPage() {
  const [courses, setCourses] = useState<AnyCourse[] | null>(null);
  const [readyById, setReadyById] = useState<Map<string, boolean>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string[] | null>(null);
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

  const domains = deriveDomains(courses);
  const tree = buildTree(courses, domains);
  const shown = sel ? courses.filter((c) => inSelection(c, sel, domains)) : courses;
  const titleById = new Map(courses.map((c) => [c.id, c.title]));
  // 学习路线:按先修依赖拓扑排序,给卡片标步数、给顶部路线条供排序
  const path = suggestOrder(courses);
  const stepOf = new Map(path.map((c, i) => [c.id, i + 1]));

  // 选中节点时右侧仍按主题分节;「全部」时同
  const groups: { topic: string; courses: AnyCourse[] }[] = [];
  for (const c of shown) {
    const t = c.meta.topic ?? "未分组";
    const g = groups[groups.length - 1];
    if (g && g.topic === t) g.courses.push(c);
    else groups.push({ topic: t, courses: [c] });
  }

  return (
    <div className="flex h-full">
      {/* 左:主题树(领域→主题→层,点选过滤) */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-secondary/50">
        <div className="flex items-center justify-between px-3 py-2">
          <span className="text-xs font-medium text-muted-foreground">知识版图</span>
          {sel && (
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setSel(null)}>
              全部
            </Button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          <button
            onClick={() => setSel(null)}
            className={cn(
              "mb-1 flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
              sel
                ? "text-muted-foreground hover:bg-accent hover:text-foreground"
                : "bg-primary/15 font-medium text-foreground ring-1 ring-primary/40",
            )}
          >
            <LibraryBig size={12} className="shrink-0" />
            全部课程
            <span className="ml-auto font-mono opacity-60">{courses.length}</span>
          </button>
          <TreeView node={tree} sel={sel} onSelect={setSel} />
        </div>
      </aside>

      {/* 右:课程卡(按主题分节) */}
      <div className="min-w-0 flex-1 overflow-y-auto px-6 py-8">
        <h1 className="mb-6 text-2xl font-bold">
          {sel ? sel.join(" / ") : "课程库"}
          <span className="ml-2 font-mono text-sm font-normal text-muted-foreground">{shown.length} 门</span>
        </h1>
        {/* 学习路线:按先修依赖排出 1→N,直接回答「从哪门开始看起」 */}
        {path.length > 1 && (
          <section className="mb-8 rounded-xl border border-border bg-card p-4">
            <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium">
              <Route size={14} className="text-primary" /> 学习路线 · 从这里开始
              <span className="ml-1 font-mono text-xs font-normal text-muted-foreground">
                按先修依赖自动排出
              </span>
            </h2>
            <ol className="flex flex-wrap items-center gap-x-2 gap-y-2">
              {path.map((c, i) => {
                const done = readyById.get(c.id) ?? false;
                return (
                  <li key={c.id} className="flex items-center gap-2">
                    {i > 0 && <ChevronRight size={13} className="shrink-0 text-muted-foreground" />}
                    <Link
                      to={`/courses/${c.id}`}
                      className={cn(
                        "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors",
                        done
                          ? "border-success/50 bg-success/10 text-success"
                          : "border-border bg-background hover:border-primary/40",
                      )}
                    >
                      <span className="font-mono opacity-70">{i + 1}</span>
                      {c.title}
                      {done && <CircleCheck size={12} />}
                    </Link>
                  </li>
                );
              })}
            </ol>
          </section>
        )}
        {groups.map((g) => (
          <section key={g.topic} className="mb-8">
            <h2 className="mb-3 font-mono text-xs tracking-wider text-muted-foreground">
              {g.topic} · {g.courses.length} 门
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {g.courses.map((c) => {
                const us = courseUnits(c);
                const cp = us.filter((u) => u.hasCheckpoint).length;
                return (
                  <Link key={c.id} to={`/courses/${c.id}`} className="group">
                    <Card className="h-full p-5 transition-all group-hover:-translate-y-0.5 group-hover:border-primary/40 group-hover:shadow-lg">
                      <div className="mb-2 flex items-center gap-1.5">
                        <Badge variant="success">可上课</Badge>
                        <Badge variant="secondary">路线第 {stepOf.get(c.id)} 步</Badge>
                      </div>
                      <h3 className="mb-2 text-lg font-medium">{c.title}</h3>
                      <p className="font-mono text-xs text-muted-foreground">
                        {us.length} 节 · {cp} 检查点 · {c.meta.duration_min ?? "—"} 分钟
                      </p>
                      {(c.meta.depends_on?.length ?? 0) > 0 && (
                        <p className="mt-1 font-mono text-xs text-muted-foreground">
                          ⛓ 先修:
                          {c.meta.depends_on!.map((d) => titleById.get(d.id) ?? d.id).join("、")}
                        </p>
                      )}
                      <p className="mt-2 truncate text-xs text-muted-foreground">{us[0]?.title ?? ""}</p>
                    </Card>
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

/** 课程详情页:大纲 + 来源(有据可查) + 关联笔记 + 进课堂 + 沉淀为笔记(学完解锁) */
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
  const [depTitles, setDepTitles] = useState<Record<string, string>>({});
  const [path, setPath] = useState<AnyCourse[] | null>(null);

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

  // 学习路线(本课在整条路径里的位置 + 上一课/下一课)
  useEffect(() => {
    void fetchAllCourses()
      .then(({ courses }) => setPath(suggestOrder(courses)))
      .catch(() => {});
  }, []);

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
    void fetch(`/api/v1/notes/draft/${courseId}`, { method: "POST" })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        return r.json() as Promise<NoteDraft>;
      })
      .then(setDraft)
      .catch((e: unknown) => setDraftErr(String(e)))
      .finally(() => setDraftBusy(false));
  }

  function closeDraft() {
    setDraft(null);
    setDraftBusy(false);
    setDraftErr(null);
    setWritten(null);
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
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
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
  const stepIdx = path ? path.findIndex((c) => c.id === courseId) : -1;
  const prevCourse = path && stepIdx > 0 ? path[stepIdx - 1] : null;
  const nextCourse =
    path && stepIdx >= 0 && stepIdx + 1 < path.length ? path[stepIdx + 1] : null;
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
            <Link to={`/read/${course.id}`}>
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

      {/* 路线位置:循序渐进的「你在这里」+ 前后课导航 */}
      {path && stepIdx >= 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 font-mono">
            <Route size={12} className="text-primary" /> 路线第 {stepIdx + 1} / {path.length} 步
          </span>
          {prevCourse && (
            <span>
              ← 上一课:
              <Link to={`/courses/${prevCourse.id}`} className="text-primary hover:underline">
                {prevCourse.title}
              </Link>
            </span>
          )}
          {nextCourse && (
            <span>
              下一课:
              <Link to={`/courses/${nextCourse.id}`} className="text-primary hover:underline">
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
              <CircleCheck size={36} className="mx-auto mb-3 text-success" />
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
                {draftBusy && (
                  <DialogDescription className="text-xs">三源蒸馏中(LLM)…</DialogDescription>
                )}
                {draftErr && (
                  <DialogDescription className="text-destructive">{draftErr}</DialogDescription>
                )}
              </DialogHeader>
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
