/** 书页(P7 两层导航新增):一本书的目录——篇(part)→大纲课,挂接课件平铺真实标题。
 *  课程库是书架(封面卡),点书进这里,点课件行去阅读——解决「目录行名≠课件标题,
 *  挂接课折叠在手风琴里找不到」的问题:这一层全部平铺,名字用课件真名。 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  BookOpen,
  CircleCheck,
  FileText,
  LoaderCircle,
  Play,
} from "lucide-react";

import { PageError, PageLoading } from "../../components/PageState";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";
import { fetchAllCourses } from "../../lib/learningPath";
import type { components } from "../../types/api.gen";

type OutlineCourse = components["schemas"]["OutlineCourse"];
type OutlineDetail = components["schemas"]["OutlineDetail"];

export function BookPage() {
  const { topic = "" } = useParams();
  const [detail, setDetail] = useState<OutlineDetail | null>(null);
  const [readyById, setReadyById] = useState<Map<string, boolean>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const [d, r] = await Promise.all([
        fetch(`/api/v1/outlines/${encodeURIComponent(topic)}`).then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json() as Promise<OutlineDetail>;
        }),
        fetchAllCourses().then(({ readyById }) => readyById),
      ]);
      setDetail(d);
      setReadyById(r);
    } catch (e: unknown) {
      setError(String(e));
    }
  }, [topic]);

  useEffect(() => {
    setDetail(null);
    setError(null);
    void load();
  }, [load]);

  // 任一门在排队/备课中 → 8s 轮询,状态自动跟走(同旧 OutlineToc)
  const cooking = detail?.courses.some(
    (c) => c.prep_status === "queued" || c.prep_status === "running",
  );
  useEffect(() => {
    if (!cooking) return;
    const t = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(t);
  }, [cooking, load]);

  const prep = async (title: string) => {
    setMsg("");
    const r = await fetch(`/api/v1/outlines/${encodeURIComponent(topic)}/prep`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!r.ok) {
      const d = (await r.json().catch(() => ({}))) as { detail?: string };
      setMsg(d.detail ?? `HTTP ${r.status}`);
      return;
    }
    setMsg(`「${title}」已排队,正在备课…`);
    await load();
  };

  if (error) return <PageError message={`书目录加载失败:${error}`} />;
  if (!detail) return <PageLoading />;

  // 行级语义(2026-11-17 拍板 A·行内推进):多挂行=互补型,全片读完才算✓;
  // 游标在行内逐片推进(第一门含未读片的行→行内第一个未读附件),读完自动前进,
  // 不再「读任一片整行✓跳行」——那会把互补的兄弟片孤儿化(实测踩过:05 行读 state
  // 侧信道后整行✓,自我学习闭环无人推荐)
  const rowComplete = (c: OutlineCourse) =>
    (c.course_file_ids ?? []).length > 0 &&
    (c.course_file_ids ?? []).every((r) => readyById.get(r));
  const rowReadCount = (c: OutlineCourse) =>
    (c.course_file_ids ?? []).filter((r) => readyById.get(r)).length;
  // 游标行:第一门已出而未全读完;游标文件:该行第一个未读附件
  const cursor = detail.courses.find(
    (c) => (c.course_file_ids ?? []).length > 0 && !rowComplete(c),
  );
  const cursorFile = cursor?.course_file_ids?.find((r) => !readyById.get(r)) ?? null;
  const doneCount = detail.courses.filter(rowComplete).length;

  // 按篇分组(保序);无 part 归「正文」
  const groups: { part: string; items: { c: OutlineCourse; i: number }[] }[] = [];
  detail.courses.forEach((c, i) => {
    const part = c.part?.trim() || "正文";
    const last = groups[groups.length - 1];
    if (last && last.part === part) last.items.push({ c, i });
    else groups.push({ part, items: [{ c, i }] });
  });

  return (
    <div className="workspace-page workspace-page--detail">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
        <Link to="/courses" viewTransition>
          ← 书架
        </Link>
      </Button>

      <header className="mt-4 mb-8 border-b border-border pb-5">
        <p className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <BookOpen size={12} className="text-primary" />
          {detail.domain && `${detail.domain} · `}书 · {detail.courses.length} 课
        </p>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <h1 className="workspace-title min-w-0">{detail.topic}</h1>
          {cursorFile && (
            <Button size="sm" asChild className="shrink-0">
              <Link to={`/read/${cursorFile}`} viewTransition>
                <Play size={13} /> 继续读
              </Link>
            </Button>
          )}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <div className="h-1.5 w-44 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${detail.courses.length ? Math.round((100 * doneCount) / detail.courses.length) : 0}%` }}
            />
          </div>
          <span className="font-mono text-xs text-muted-foreground">
            已学 {doneCount} / {detail.courses.length}
            {doneCount === detail.courses.length && detail.courses.length > 0 && " · 全书读完"}
          </span>
        </div>
      </header>

      {msg && (
        <p
          key={msg}
          className="anim-drop mb-6 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-xs text-primary"
        >
          {msg}
        </p>
      )}

      {detail.source_status === "historical_unrecorded" ? (
        <p className="mb-5 text-xs text-muted-foreground">
          这本旧大纲没有保存调研来源记录。
        </p>
      ) : detail.source_evidence?.length ? (
        <section className="mb-6 rounded-xl border border-border bg-card/70 p-4">
          <h2 className="mb-2 text-xs font-medium text-foreground">大纲调研来源</h2>
          <ul className="flex flex-wrap gap-x-4 gap-y-2 text-xs">
            {detail.source_evidence.map((source) => (
              <li key={source.id}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  title={`网页快照指纹 ${source.snapshot_sha256 ?? "未提供"}`}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-muted-foreground">
            来源记录用于追溯课程设计依据，不代表已验证先修关系或内容质量。
          </p>
        </section>
      ) : null}

      {groups.map((g) => (
        <section key={g.part} className="mb-8">
          {g.part !== "正文" && (
            <h2 className="mb-3 border-b border-border pb-1.5 font-mono text-[11px] tracking-widest text-primary">
              ◆ {g.part}
            </h2>
          )}
          <div className="space-y-3">
            {g.items.map(({ c, i }) => {
              const refs = c.course_file_ids ?? [];
              const complete = rowComplete(c);
              const readCount = rowReadCount(c);
              const isCursor = c.id === cursor?.id;
              const busy = c.prep_status === "queued" || c.prep_status === "running";
              return (
                <div
                  key={c.id}
                  className={cn(
                    "rounded-xl border bg-card p-4 transition-colors",
                    isCursor ? "border-primary/40" : "border-border",
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="font-mono text-xs text-muted-foreground">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    {complete ? (
                      <CircleCheck size={14} className="anim-pop shrink-0 text-success" />
                    ) : busy ? (
                      <span className="anim-pop inline-flex shrink-0">
                        <LoaderCircle size={14} className="animate-spin text-warning" />
                      </span>
                    ) : isCursor ? (
                      <Play size={14} className="anim-pop shrink-0 text-primary" />
                    ) : (
                      <span className="w-[14px] shrink-0" />
                    )}
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate text-[15px]",
                        complete ? "text-muted-foreground" : isCursor ? "font-medium text-primary" : "",
                      )}
                      title={c.goal}
                    >
                      {c.title}
                    </span>
                    {/* 多挂章的部分读状态:诚实亮出「还差几片」,不再读一片就整章✓ */}
                    {refs.length > 1 && readCount < refs.length && (
                      <span
                        className={cn(
                          "shrink-0 font-mono text-[10px]",
                          readCount > 0 ? "text-warning" : "text-muted-foreground/60",
                        )}
                        title={`${readCount}/${refs.length} 片已读`}
                      >
                        {readCount > 0 ? `已学 ${readCount}/${refs.length} 片` : `${refs.length} 片`}
                      </span>
                    )}
                    {busy && (
                      <span className="shrink-0 text-xs text-warning">
                        {c.prep_status === "running" ? "备课中…" : "排队中…"}
                      </span>
                    )}
                  </div>
                  {c.goal && (
                    <p className="mt-1 pl-[26px] text-xs leading-relaxed text-muted-foreground">
                      {c.goal}
                    </p>
                  )}
                  {c.why && (
                    <p
                      className="mt-0.5 pl-[26px] text-xs leading-relaxed text-primary/70"
                      title="学习动机:这门课解决什么理解障碍或实际问题"
                    >
                      学习动机：{c.why}
                    </p>
                  )}
                  {c.source_ids?.length ? (
                    <p className="mt-1 pl-[26px] text-[11px] text-muted-foreground">
                      调研依据:{" "}
                      {c.source_ids.map((id, index) => {
                        const source = detail.source_evidence?.find((item) => item.id === id);
                        if (!source) return null;
                        return (
                          <span key={id}>
                            {index > 0 ? " · " : ""}
                            <a
                              href={source.url}
                              target="_blank"
                              rel="noreferrer"
                              title={`抓取时间 ${source.fetched_at ?? "未知"} · 指纹 ${source.snapshot_sha256 ?? "未知"}`}
                              className="text-primary underline-offset-2 hover:underline"
                            >
                              {source.title}
                            </a>
                          </span>
                        );
                      })}
                    </p>
                  ) : null}
                  {/* 挂接课件平铺:真实课件标题,一门大纲课可能收编多门旧课 */}
                  {refs.length > 0 && (
                    <ul className="mt-2 space-y-0.5 pl-[26px]">
                      {refs.map((fid, k) => {
                        const isCursorFile = fid === cursorFile;
                        return (
                          <li key={fid}>
                            <Link
                              to={`/read/${fid}`}
                              viewTransition
                              className={cn(
                                "flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm transition-colors outline-none hover:bg-secondary focus-visible:ring-[3px] focus-visible:ring-ring/40",
                                isCursorFile ? "text-primary" : "text-muted-foreground hover:text-foreground",
                              )}
                            >
                              <FileText size={12} className="shrink-0" />
                              <span className="min-w-0 flex-1 truncate">
                                {c.course_file_titles?.[k] ?? fid}
                              </span>
                              {readyById.get(fid) && (
                                <CircleCheck size={12} className="shrink-0 text-success" />
                              )}
                              {isCursorFile && (
                                <span className="shrink-0 font-mono text-[10px] text-primary">
                                  ▶ 从这读
                                </span>
                              )}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {refs.length === 0 && !busy && (
                    <div className="mt-2 pl-[26px]">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void prep(c.title)}
                        title={`点击开始备课:${c.title}`}
                      >
                        点单备课
                      </Button>
                    </div>
                  )}
                  {busy && <div className="anim-progress mt-2 ml-[26px] mr-2 h-1 rounded-full" />}
                </div>
              );
            })}
          </div>
        </section>
      ))}

      <p className="text-[11px] text-muted-foreground">
        已出课点课件行去读;空白课点「点单备课」即开始(原料调研→写课→发布,自动挂进本书),分钟级。
      </p>
    </div>
  );
}
