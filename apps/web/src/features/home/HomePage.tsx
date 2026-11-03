/** 学习台:我的书架(大纲进度) + 今日复习 + 继续学 + 下一步学 + 快捷开课 + 想学的/刚冒出的。
 *  P7 后:学习顺序由大纲书原生承载(篇→课→先修链),不再有跨课扁平「学习路线」;
 *  书架进度视图直答「每本书学到哪、下一步读哪」。 */
import { BookOpen, Compass, LibraryBig, Lightbulb, ListTodo, Play, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState, PageError, PageLoading } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useCatalog } from "../../hooks/useCatalog";
import type { components } from "../../types/api.gen";

type ReviewDue = components["schemas"]["ReviewDue"];

interface BookCourse {
  id: string;
  title: string;
  goal?: string;
  course_file_id?: string | null;
}

interface Book {
  topic: string;
  domain: string;
  courses: BookCourse[];
}

/** 读阅读器断点:P6 起进度存 reader-pos-{id} = {top, sec};继续学展示「上次读到第N节」 */
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

export function HomePage() {
  const { cat, err, act } = useCatalog();
  const [topic, setTopic] = useState("");
  const [due, setDue] = useState<ReviewDue | null>(null);
  const [books, setBooks] = useState<Book[] | null>(null);

  // 今日复习清单:进页面拉一次;课堂里重测批改后回来刷新页面即更新
  useEffect(() => {
    void fetch("/api/v1/review/due")
      .then((r) => r.json())
      .then((d: ReviewDue) => setDue(d))
      .catch(() => {});
  }, []);

  // 书架:大纲列表 + 各自详情;ready 状态渲染期从 catalog 合并
  useEffect(() => {
    void (async () => {
      try {
        const list = (await fetch("/api/v1/outlines").then((r) => r.json())) as {
          topic: string;
        }[];
        const ds = await Promise.all(
          list.map((o) =>
            fetch(`/api/v1/outlines/${encodeURIComponent(o.topic)}`)
              .then((r) => r.json())
              .catch(() => null),
          ),
        );
        setBooks(ds.filter((d): d is Book => d !== null));
      } catch {
        setBooks([]);
      }
    })();
  }, []);

  if (err) return <PageError message={`加载失败:${err}`} />;
  if (!cat) return <PageLoading />;

  const learning = cat.learning.map((c) => ({ ...c, prog: progressOf(c.id) }));
  const continuing = learning.filter((c) => c.prog !== null);
  const ready = new Map(learning.map((c) => [c.id, c.ready]));

  // 书架派生:每本书的已学数与书内游标(第一门已出而未学完的课)
  const shelves = (books ?? []).map((b) => {
    const done = b.courses.filter(
      (c) => c.course_file_id && ready.get(c.course_file_id),
    ).length;
    const cursor =
      b.courses.find((c) => c.course_file_id && !ready.get(c.course_file_id)) ?? null;
    const cursorNo = cursor ? b.courses.findIndex((c) => c.id === cursor.id) + 1 : 0;
    return { ...b, done, total: b.courses.length, cursor, cursorNo };
  });
  // 下一步学:第一本没读完的书的游标(书序即优先级)
  const nextBook = shelves.find((b) => b.cursor) ?? null;
  const nextPrev =
    nextBook && nextBook.cursorNo > 1 ? nextBook.courses[nextBook.cursorNo - 2] : null;

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-8">
      <h1 className="text-2xl font-bold">学习台</h1>

      {/* 快捷开课:新主题一句话 → 生成中心接手(出大纲→备样课一条龙) */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = topic.trim();
          if (!t) return;
          setTopic("");
          void act("request_research", t, t);
        }}
        className="flex gap-2"
      >
        <Input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="我想学…(新主题,如 MCP / RAG / 编译原理)"
          className="h-10"
        />
        <Button type="submit" size="lg" disabled={!topic.trim()}>
          开课
        </Button>
      </form>

      {/* 我的书架:每本大纲一行——篇章节里的进度与当前课,直答「学到哪、读哪本」 */}
      <section>
        <SectionHeader
          icon={LibraryBig}
          title="我的书架"
          count={shelves.length}
          hint="每本大纲是一本书;当前课=书里第一门已出而未学完的"
        />
        {shelves === null ? (
          <p className="text-sm text-muted-foreground">书架整理中…</p>
        ) : shelves.length === 0 ? (
          <EmptyState
            icon={LibraryBig}
            title="书架还是空的"
            hint="上面输入新主题开课,或去生成中心看看"
          />
        ) : (
          <div className="space-y-2">
            {shelves.map((b) => {
              const allDone = b.total > 0 && b.done === b.total;
              return (
                <Card key={b.topic} className="p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 text-sm font-medium">
                        <LibraryBig size={13} className="shrink-0 text-primary" />
                        {b.domain && `${b.domain} · `}
                        {b.topic}
                        <span className="font-mono text-xs font-normal text-muted-foreground">
                          已学 {b.done} / {b.total}
                        </span>
                      </p>
                      {b.cursor ? (
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          ▶ 当前课:{b.cursor.title}
                        </p>
                      ) : (
                        <p className="mt-1 text-xs text-success">✓ 全部学完</p>
                      )}
                    </div>
                    {b.cursor && (
                      <Button size="sm" variant="secondary" asChild className="shrink-0">
                        <Link to={`/read/${b.cursor.course_file_id}`} viewTransition>
                          <Play size={13} /> {b.done > 0 ? "继续读" : "开始读"}
                        </Link>
                      </Button>
                    )}
                    {allDone && (
                      <Badge variant="success" className="anim-pop shrink-0">
                        学完
                      </Badge>
                    )}
                  </div>
                  {/* 书内进度线:读完一门课推进一格(width 过渡,CSS 自动补间) */}
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-secondary">
                    <div
                      className="h-full rounded-full bg-primary/70 transition-all duration-500 ease-out"
                      style={{ width: `${b.total ? Math.round((100 * b.done) / b.total) : 0}%` }}
                    />
                  </div>
                </Card>
              );
            })}
            <p className="text-right text-[11px] text-muted-foreground">
              书的全貌在
              <Link to="/courses" className="mx-1 text-primary underline decoration-dotted">
                课程库
              </Link>
              ;书里空白章节点击即出课
            </p>
          </div>
        )}
      </section>

      {due && due.items.length > 0 && (
        <section>
          <SectionHeader
            icon={RotateCcw}
            title="今日复习"
            count={due.items.length}
            hint={`现役复习卡 ${due.total} 张 · 到期重测,批改后自动排下一次`}
          />
          <ul className="space-y-2">
            {due.items.map((r) => (
              <li key={`${r.course_id}/${r.page_id}`}>
                <Link
                  to={`/read/${r.course_id}?section=${r.page_no}`}
                  viewTransition
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2 transition-colors hover:border-primary/40"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm">{r.question}</p>
                    <p className="font-mono text-xs text-muted-foreground">
                      {r.course_title} · {r.page_title}
                      {r.overdue_days > 0 && ` · 逾期 ${r.overdue_days} 天`}
                    </p>
                  </div>
                  <Badge variant={r.mastery >= 0.9 ? "success" : "warning"} className="shrink-0">
                    掌握 {Math.round(r.mastery * 100)}%
                  </Badge>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <SectionHeader icon={Play} title="继续学" count={continuing.length} hint="从上次的断点接着学" />
        {continuing.length ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {continuing.map((c) => (
              <Link key={c.id} to={`/read/${c.id}?section=${c.prog!.sec + 1}`} viewTransition className="group">
                <Card className="h-full p-4 transition-all group-hover:-translate-y-0.5 group-hover:border-primary/40 group-hover:shadow-lg">
                  <p className="mb-1 flex items-center gap-1 font-mono text-xs text-primary">
                    <Play size={11} /> 接着学 · 第 {c.prog!.sec + 1} 节
                  </p>
                  <h3 className="mb-1 font-medium">{c.title}</h3>
                  <p className="font-mono text-xs text-muted-foreground">
                    {c.pages} 页 · {c.checkpoints} 检查点
                  </p>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={BookOpen}
            title="还没有进行中的课"
            hint="书架里挑一本开始读,或上面输入新主题直接开课"
          >
            <Button asChild variant="secondary" size="sm">
              <Link to="/courses">去课程库</Link>
            </Button>
          </EmptyState>
        )}
      </section>

      {nextBook?.cursor && (
        <section>
          <SectionHeader
            icon={Compass}
            title="下一步学"
            hint="书序游标:前置课都已学完,学完它自动轮到下一门"
          />
          <Card className="flex flex-col gap-4 p-5 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="mb-1 flex items-center gap-1.5 font-mono text-xs text-primary">
                <Compass size={12} /> 《{nextBook.topic}》第 {nextBook.cursorNo} / {nextBook.total} 课 · 可以开课
              </p>
              <h3 className="mb-1 text-lg font-medium">{nextBook.cursor.title}</h3>
              <p className="font-mono text-xs text-muted-foreground">
                {nextPrev?.course_file_id && ready.get(nextPrev.course_file_id)
                  ? `承接:你刚学完「${nextPrev.title}」✓`
                  : "这本书的当前课,直接开读"}
              </p>
            </div>
            <Button size="lg" asChild className="shrink-0">
              <Link to={`/read/${nextBook.cursor.course_file_id}`} viewTransition>
                <Play size={15} /> 开始学
              </Link>
            </Button>
          </Card>
        </section>
      )}

      <section>
        <SectionHeader icon={ListTodo} title="想学的" count={cat.todo.length} hint="待探清单,点「调研」自动出课" />
        {cat.todo.length ? (
          <ul className="space-y-2">
            {cat.todo.map((t, i) => (
              <li
                key={`${t.title}::${i}`}
                className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2 transition-colors hover:border-primary/40"
              >
                <div className="min-w-0">
                  <span className="text-sm">{t.title}</span>
                  {t.hint && <span className="ml-2 text-xs text-muted-foreground">{t.hint}</span>}
                  <span className="ml-2 font-mono text-xs text-muted-foreground opacity-60">{t.area}</span>
                </div>
                {t.status === "running" ? (
                  <Badge variant="warning">调研备课中…</Badge>
                ) : t.status === "done" ? (
                  <Badge variant="success">已出课</Badge>
                ) : t.status === "failed" ? (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => void act("request_research", t.title, t.title)}
                  >
                    重试
                  </Button>
                ) : t.requested ? (
                  <Badge variant="secondary">已请求</Badge>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => void act("request_research", t.title, t.title)}>
                    调研
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={ListTodo} title="待探清单还是空的" hint="在课堂里问课件答不了的问题,会自动出现在这里候选" />
        )}
      </section>

      <section>
        <SectionHeader icon={Lightbulb} title="刚冒出的" count={cat.sparks.length} hint="课件答不了的问题 = 衍生候选" />
        {cat.sparks.length === 0 ? (
          <EmptyState icon={Lightbulb} title="还没有衍生问题" hint="上课问到课件覆盖不了的地方时,会自动冒到这里。" />
        ) : (
          <div className="space-y-2">
            {cat.sparks.map((s) => (
              <div key={s.key} className="rounded-lg border border-border bg-card px-4 py-3 transition-colors hover:border-primary/40">
                <p className="mb-1 flex items-start gap-2 text-sm">
                  <Sparkles size={13} className="mt-1 shrink-0 text-primary" />
                  {s.question}
                </p>
                {s.detail && <p className="mb-2 pl-5 font-mono text-xs text-muted-foreground">{s.detail}</p>}
                {s.confirmed ? (
                  <Badge variant="success" className="ml-5">已确认值得学</Badge>
                ) : (
                  <div className="ml-5 flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => void act("confirm_spark", s.key, s.question)}>
                      确认值得学
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void act("dismiss_spark", s.key, s.question)}>
                      忽略
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
