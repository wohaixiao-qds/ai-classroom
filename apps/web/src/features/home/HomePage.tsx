/** 学习台(甲方案):学习路线 + 今日复习 + 继续学 + 下一步学 + 快捷开课 + 推荐。
 *  「在学什么」的首页;课程全量在课程库,生成管理在生成中心。
 *  复习/顺序(2026-11-02):批改结果服务端累积成掌握度,到期检查点回这里重测;
 *  先修依赖来自课件 meta.depends_on(人工/备课标注),学完前置课才推荐后继。
 *  路线游标(P6 后):拓扑序里第一个未学完的课=当前步,顶部步骤条直答「按什么顺序学」。 */
import { BookOpen, Compass, Lightbulb, ListTodo, Play, Route, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState, PageError, PageLoading } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useCatalog } from "../../hooks/useCatalog";
import { suggestOrder } from "../../lib/learningPath";
import { cn } from "../../lib/utils";
import type { AnyCourse } from "../../types/csl";
import type { components } from "../../types/api.gen";

type ReviewDue = components["schemas"]["ReviewDue"];

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

  // 今日复习清单:进页面拉一次;课堂里重测批改后回来刷新页面即更新
  useEffect(() => {
    void fetch("/api/v1/review/due")
      .then((r) => r.json())
      .then((d: ReviewDue) => setDue(d))
      .catch(() => {});
  }, []);

  if (err) return <PageError message={`加载失败:${err}`} />;
  if (!cat) return <PageLoading />;

  const learning = cat.learning.map((c) => ({ ...c, prog: progressOf(c.id) }));
  const continuing = learning.filter((c) => c.prog !== null);
  const readyById = new Map(learning.map((c) => [c.id, c.ready]));
  // 学习路线:catalog 的 depends_on 就够排拓扑序(不用拉全量课件 JSON)
  const route = suggestOrder(
    learning.map(
      (c) => ({ id: c.id, title: c.title, meta: { depends_on: c.depends_on } }) as AnyCourse,
    ),
  );
  const steps = route.map((c, i) => ({
    id: c.id,
    title: c.title,
    step: i + 1,
    ready: readyById.get(c.id) ?? false,
  }));
  // 路线游标:第一个未学完的课=当前步(前置已 ready 的天然靠前)
  const cursor = steps.find((s) => !s.ready) ?? null;
  const cursorPrev = cursor && cursor.step > 1 ? steps[cursor.step - 2] : null;

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-8">
      <h1 className="text-2xl font-bold">学习台</h1>

      {/* 快捷开课:新主题一句话 → 生成中心接手(调研+备课+音频一条龙) */}
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

      {/* 学习路线:直答「按什么顺序学」——拓扑序步骤条,当前步即游标 */}
      {steps.length > 0 && (
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium">
            <Route size={14} className="text-primary" /> 学习路线
            {cursor && (
              <span className="ml-1 font-mono text-xs font-normal text-muted-foreground">
                你在第 {cursor.step} / {steps.length} 步
              </span>
            )}
            {!cursor && (
              <span className="ml-1 font-mono text-xs font-normal text-success">
                全部学完 🎉
              </span>
            )}
          </h2>
          <ol className="flex flex-wrap items-center gap-x-2 gap-y-2">
            {steps.map((s, i) => {
              const isCursor = cursor?.id === s.id;
              return (
                <li key={s.id} className="flex items-center gap-2">
                  {i > 0 && <span className="text-muted-foreground">→</span>}
                  <Link
                    to={isCursor ? `/read/${s.id}` : `/courses/${s.id}`}
                    className={cn(
                      "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors",
                      isCursor
                        ? "border-primary bg-primary/10 font-medium text-primary"
                        : s.ready
                          ? "border-success/50 bg-success/10 text-success"
                          : "border-border bg-background text-muted-foreground hover:border-primary/40",
                    )}
                    title={isCursor ? "当前步,点开就读" : s.ready ? "已学完" : "还没轮到,但也能直接点进去"}
                  >
                    <span className="font-mono opacity-70">{i + 1}</span>
                    {s.ready && "✓"}
                    {isCursor && "▶ "}
                    {s.title}
                  </Link>
                </li>
              );
            })}
          </ol>
        </section>
      )}

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
              <Link key={c.id} to={`/read/${c.id}?section=${c.prog!.sec + 1}`} className="group">
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
            hint="去课程库挑一门,或上面输入新主题直接开课"
          >
            <Button asChild variant="secondary" size="sm">
              <Link to="/courses">去课程库</Link>
            </Button>
          </EmptyState>
        )}
      </section>

      {cursor && (
        <section>
          <SectionHeader
            icon={Compass}
            title="下一步学"
            hint="路线上的当前步:前置课都已学完,学完它自动轮到下一门"
          />
          <Card className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="mb-1 flex items-center gap-1.5 font-mono text-xs text-primary">
                <Compass size={12} /> 第 {cursor.step} / {steps.length} 步 · 可以开课
              </p>
              <h3 className="mb-1 text-lg font-medium">{cursor.title}</h3>
              <p className="font-mono text-xs text-muted-foreground">
                {cursorPrev
                  ? `承接:你刚学完「${cursorPrev.title}」✓`
                  : "路线起点,直接开读"}
              </p>
            </div>
            <Button size="lg" asChild className="shrink-0">
              <Link to={`/read/${cursor.id}`}>
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
                className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2"
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
              <div key={s.key} className="rounded-lg border border-border bg-card px-4 py-3">
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
