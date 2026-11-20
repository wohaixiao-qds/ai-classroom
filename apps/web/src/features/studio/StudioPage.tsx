/** 生成中心(甲方案):「造课」的所有入口与状态集中一页。
 *  我想学(新主题)/ 能学的(笔记→备课)/ 任务动态(备课中/完成/失败)。
 *  框架审阅流(双源框架→挑子题)为下一步,先把生成管理归位。 */
import { Lightbulb, ListTodo, Sparkles, SquarePen, Sprout } from "lucide-react";
import { useState } from "react";

import { EmptyState, PageError, PageLoading } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useCatalog } from "../../hooks/useCatalog";
import { OutlinePanel } from "./OutlinePanel";
import { GenerationTasks } from "./GenerationTasks";

export function StudioPage() {
  const { cat, err, act } = useCatalog();
  const [topic, setTopic] = useState("");
  if (err) return <PageError message={`加载失败:${err}`} />;
  if (!cat) return <PageLoading />;

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-8">
      <h1 className="text-2xl font-bold">生成中心</h1>

      <section>
        <SectionHeader icon={Sprout} title="我想学" count={0} hint="一句话开课:调研→备课→音频全自动,出炉进课程库" />
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
            placeholder="新主题,如 MCP / RAG / 编译原理"
            className="h-10"
          />
          <Button type="submit" size="lg" disabled={!topic.trim()}>
            开课
          </Button>
        </form>
      </section>

      <GenerationTasks />

      <OutlinePanel />

      {/* 想学的/刚冒出的(学习台退役迁入):待探清单与衍生问题候选——「造什么」的策展归生成中心 */}
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

      <section>
        <SectionHeader icon={SquarePen} title="能学的" count={cat.notes.length} hint="有笔记未出课,点击请老师备课" />
        {cat.notes.length ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {cat.notes.map((n) => (
              <button
                key={n.path}
                type="button"
                disabled={n.requested && n.status !== "failed"}
                onClick={() => void act("request_prep", n.path, n.title)}
                className="group text-left disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Card className="h-full p-4 transition-all group-hover:-translate-y-0.5 group-hover:border-primary/40 group-hover:shadow-lg">
                  <p className="mb-1 font-mono text-xs text-muted-foreground">{n.area}</p>
                  <p className="mb-2 font-medium">{n.title}</p>
                  {n.status === "running" ? (
                    <Badge variant="warning">老师正在备课…</Badge>
                  ) : n.status === "done" ? (
                    <Badge variant="success">已出课</Badge>
                  ) : n.status === "failed" ? (
                    <Badge variant="destructive">失败,点此重试</Badge>
                  ) : n.requested ? (
                    <Badge variant="secondary">已请求备课</Badge>
                  ) : (
                    <Badge>请老师备课</Badge>
                  )}
                </Card>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState icon={SquarePen} title="没有可备战的笔记" hint="在 Obsidian 里写好学习笔记后,这里会出现可一键备课的卡片" />
        )}
      </section>

    </div>
  );
}
