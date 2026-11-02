/** 学习台(甲方案):今日复习 + 继续学 + 下一步学 + 快捷开课 + 推荐(想学的/刚冒出的)。
 *  「在学什么」的首页;课程全量在课程库,生成管理在生成中心。
 *  复习/顺序(2026-11-02):批改结果服务端累积成掌握度,到期检查点回这里重测;
 *  先修依赖来自课件 meta.depends_on(人工/备课标注),学完前置课才推荐后继。 */
import { BookOpen, Compass, Lightbulb, ListTodo, Play, RotateCcw, Sparkles } from "lucide-react";
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

/** 读本地断点(与播放引擎同 key):学习台展示「上次学到第N页」 */
function progressOf(courseId: string): { p: number } | null {
  try {
    const raw = localStorage.getItem(`classroom-progress-${courseId}`);
    return raw ? (JSON.parse(raw) as { p: number }) : null;
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
  const continuing = learning.filter((c) => c.prog && c.prog.p > 0);
  const readyById = new Map(learning.map((c) => [c.id, c.ready]));
  // 下一步学:没学完、没有断点、先修全部学完的课(顺序来自 meta.depends_on)
  const nextUp = learning.filter(
    (c) =>
      !c.ready &&
      !c.prog &&
      c.depends_on.length > 0 &&
      c.depends_on.every((d) => readyById.get(d.id)),
  );

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
              <Link key={c.id} to={`/read/${c.id}`} className="group">
                <Card className="h-full p-4 transition-all group-hover:-translate-y-0.5 group-hover:border-primary/40 group-hover:shadow-lg">
                  <p className="mb-1 flex items-center gap-1 font-mono text-xs text-primary">
                    <Play size={11} /> 接着学 · 第 {c.prog!.p + 1} 页
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

      {nextUp.length > 0 && (
        <section>
          <SectionHeader
            icon={Compass}
            title="下一步学"
            count={nextUp.length}
            hint="先修课都学完了,按学习顺序轮到这些"
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {nextUp.map((c) => (
              <Link key={c.id} to={`/courses/${c.id}`} className="group">
                <Card className="h-full p-4 transition-all group-hover:-translate-y-0.5 group-hover:border-primary/40 group-hover:shadow-lg">
                  <p className="mb-1 flex items-center gap-1 font-mono text-xs text-primary">
                    <Compass size={11} /> 可以开课
                  </p>
                  <h3 className="mb-1 font-medium">{c.title}</h3>
                  <p className="line-clamp-2 font-mono text-xs text-muted-foreground">
                    {c.depends_on.map((d) => d.reason).filter(Boolean).join(";")}
                  </p>
                </Card>
              </Link>
            ))}
          </div>
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
