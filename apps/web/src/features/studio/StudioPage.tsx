/** 生成中心(甲方案):「造课」的所有入口与状态集中一页。
 *  我想学(新主题)/ 能学的(笔记→备课)/ 任务动态(备课中/完成/失败)。
 *  框架审阅流(双源框架→挑子题)为下一步,先把生成管理归位。 */
import { Check, CircleX, History, LoaderCircle, SquarePen, Sprout } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState, PageError, PageLoading } from "../../components/PageState";
import { JobFeed } from "../../components/JobFeed";
import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useCatalog } from "../../hooks/useCatalog";
import { OutlinePanel } from "./OutlinePanel";

interface OutlineJob {
  target: string;
  title: string;
  status: string;
}

export function StudioPage() {
  const { cat, err, act } = useCatalog();
  const [topic, setTopic] = useState("");
  const [outlineJobs, setOutlineJobs] = useState<OutlineJob[]>([]);
  useEffect(() => {
    void fetch("/api/v1/outline-jobs")
      .then((r) => r.json())
      .then(setOutlineJobs)
      .catch(() => {});
  }, []);

  if (err) return <PageError message={`加载失败:${err}`} />;
  if (!cat) return <PageLoading />;

  // 任务动态:所有发起过生成的目标(notes + todo 含新主题 + 大纲点单),按状态分拣。
  // apiKind/target 用于拉取该任务的处理消息(/api/v1/jobs/log)
  const jobs = [
    ...cat.todo.map((t) => ({
      title: t.title, area: t.area, status: t.status, kind: "调研+备课",
      apiKind: "request_research" as const, target: t.title,
    })),
    ...cat.notes
      .filter((n) => n.requested)
      .map((n) => ({
        title: n.title, area: n.area, status: n.status, kind: "笔记备课",
        apiKind: "request_prep" as const, target: n.path,
      })),
    ...outlineJobs.map((j) => ({
      title: j.title, area: "大纲点单", status: j.status, kind: "大纲点单备课",
      apiKind: "outline_prep" as const, target: j.target,
    })),
  ];
  const running = jobs.filter((j) => j.status === "running");
  const finished = jobs.filter((j) => j.status !== "running");

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

      <OutlinePanel />

      {running.length > 0 && (
        <section>
          <SectionHeader icon={LoaderCircle} title="正在造" count={running.length} hint="分钟级后台任务,下方实时亮出它在干什么" />
          <ul className="space-y-2">
            {running.map((j) => (
              <li
                key={`${j.apiKind}-${j.target}`}
                className="overflow-hidden rounded-lg border border-primary/40 bg-primary/5 text-sm"
              >
                <div className="flex items-center gap-3 px-4 py-2">
                  <LoaderCircle size={13} className="shrink-0 animate-spin text-primary" />
                  <span className="flex-1 truncate">{j.title}</span>
                  <span className="font-mono text-xs text-muted-foreground">{j.kind}</span>
                </div>
                {/* 不确定进度线:分钟级等待的「活着」信号 */}
                <div className="anim-progress h-0.5" />
                <JobFeed kind={j.apiKind} target={j.target} active className="mx-3 mb-2" />
              </li>
            ))}
          </ul>
        </section>
      )}

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

      {finished.length > 0 && (
        <section>
          <SectionHeader icon={History} title="任务记录" count={finished.length} hint="近期发起过的生成" />
          <ul className="space-y-1.5">
            {finished.map((j) => (
              <li
                key={`${j.apiKind}-${j.target}`}
                className="rounded-lg border border-border bg-card px-4 py-2 text-sm"
              >
                <div className="flex items-center gap-3">
                  {j.status === "done" ? (
                    <Check size={13} className="shrink-0 text-success" />
                  ) : j.status === "failed" ? (
                    <CircleX size={13} className="shrink-0 text-destructive" />
                  ) : (
                    <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
                  )}
                  <span className="flex-1 truncate">{j.title}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {j.status === "done" ? "已出课" : j.status === "failed" ? "失败" : "已请求"} · {j.kind}
                  </span>
                </div>
                {/* 失败的任务直接亮出原因,不用去翻日志文件 */}
                {j.status === "failed" && (
                  <JobFeed kind={j.apiKind} target={j.target} active={false} className="mt-2" />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
