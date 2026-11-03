/** 领域大纲·书籍目录(P7·M3):篇归类 + 课进度 + 点单备课。
 *  行为:已出课→点击去读;未出课→点击直接开始备课(行内状态自动跟走)。 */
import { BookOpen, CircleCheck, LoaderCircle, Play } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Card } from "../../components/ui/card";
import { cn } from "../../lib/utils";

interface OutlineCourse {
  id: string;
  title: string;
  goal: string;
  part?: string;
  prereq_titles?: string[];
  course_file_id?: string | null;
  course_file_ids?: string[];
  course_file_titles?: string[];
  prep_status?: string | null;
}

interface OutlineDetail {
  topic: string;
  domain: string;
  courses: OutlineCourse[];
}

export function OutlineToc({ readyById }: { readyById: Map<string, boolean> }) {
  const [details, setDetails] = useState<OutlineDetail[] | null>(null);
  const [msg, setMsg] = useState("");

  const loadAll = useCallback(async () => {
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
      setDetails(ds.filter((d): d is OutlineDetail => d !== null));
    } catch {
      setDetails([]);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // 任一门在排队/备课中 → 8s 轮询,状态自动跟走
  const cooking = details?.some((d) =>
    d.courses.some((c) => c.prep_status === "queued" || c.prep_status === "running"),
  );
  useEffect(() => {
    if (!cooking) return;
    const t = window.setInterval(() => void loadAll(), 8000);
    return () => window.clearInterval(t);
  }, [cooking, loadAll]);

  const prep = async (topic: string, title: string) => {
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
    await loadAll();
  };

  if (details === null) return null;
  if (details.length === 0) return null;

  return (
    <section className="mb-8 space-y-3">
      {msg && (
        <p
          key={msg}
          className="anim-drop rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-xs text-primary"
        >
          {msg}
        </p>
      )}
      {details.map((d) => {
        // 按篇分组(保序);无 part 归「正文」
        const groups: { part: string; items: { c: OutlineCourse; i: number }[] }[] = [];
        d.courses.forEach((c, i) => {
          const part = c.part?.trim() || "正文";
          const last = groups[groups.length - 1];
          if (last && last.part === part) last.items.push({ c, i });
          else groups.push({ part, items: [{ c, i }] });
        });
        const doneCount = d.courses.filter((c) =>
          (c.course_file_ids ?? []).some((r) => readyById.get(r)),
        ).length;
        // 已出课件数:与「已学」区分——出了课 ≠ 学了
        const preparedCount = d.courses.filter((c) => (c.course_file_ids ?? []).length > 0).length;
        // 书内游标:第一门已出而未学完的课
        const bookCursorId = d.courses.find(
          (c) =>
            (c.course_file_ids ?? []).length > 0 &&
            !(c.course_file_ids ?? []).every((r) => readyById.get(r)),
        )?.id;
        return (
          <Card key={d.topic} className="p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <h3 className="flex items-center gap-2 text-sm font-medium">
                <BookOpen size={14} className="text-primary" />
                {d.domain && `${d.domain} · `}
                {d.topic}
                <span className="font-mono text-xs font-normal text-muted-foreground">
                  目录 · {d.courses.length} 课
                </span>
              </h3>
              <span className="font-mono text-xs text-muted-foreground">
                已出<span className={cn("ml-0.5", preparedCount > 0 && "text-success")}>{preparedCount}</span>
                <span className="mx-1.5 opacity-40">·</span>
                已学 {doneCount} / {d.courses.length}
              </span>
            </div>
            <div className="space-y-3">
              {groups.map((g) => (
                <div key={g.part}>
                  {g.part !== "正文" && (
                    <p className="mb-1 border-b border-border pb-1 font-mono text-[11px] tracking-widest text-primary">
                      ◆ {g.part}
                    </p>
                  )}
                  <ol className="space-y-1">
                    {g.items.map(({ c, i }) => {
                      const refs = c.course_file_ids ?? [];
                      const done = refs.some((r) => readyById.get(r));
                      const isCursor = c.id === bookCursorId;
                      const busy =
                        c.prep_status === "queued" || c.prep_status === "running";
                      const inner = (
                        <>
                          <span className="font-mono text-xs text-muted-foreground">
                            {String(i + 1).padStart(2, "0")}
                          </span>
                          {/* 状态图标轮换 pop(spin 是循环动画,外包一层避免互斥) */}
                          {done ? (
                            <CircleCheck size={13} className="anim-pop shrink-0 text-success" />
                          ) : busy ? (
                            <span className="anim-pop inline-flex shrink-0">
                              <LoaderCircle size={13} className="animate-spin text-warning" />
                            </span>
                          ) : isCursor ? (
                            <Play size={13} className="anim-pop shrink-0 text-primary" />
                          ) : (
                            <span className="w-[13px] shrink-0" />
                          )}
                          <span
                            className={`min-w-0 flex-1 truncate ${
                              done
                                ? "text-muted-foreground"
                                : isCursor
                                  ? "font-medium text-primary"
                                  : ""
                            }`}
                          >
                            {c.title}
                          </span>
                          {refs.length > 1 && (
                            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                              已挂 {refs.length} 门
                            </span>
                          )}
                          {busy && (
                            <span className="shrink-0 text-xs text-warning">
                              {c.prep_status === "running" ? "备课中…" : "排队中…"}
                            </span>
                          )}
                          {!busy && refs.length === 0 && (
                            <span className="shrink-0 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                              点击开始备课
                            </span>
                          )}
                          <span className="hidden truncate text-xs text-muted-foreground sm:block sm:max-w-[35%]">
                            {c.goal}
                          </span>
                        </>
                      );
                      return (
                        <li key={c.id} className="group">
                          {refs.length > 0 ? (
                            <>
                              <Link
                                to={`/read/${refs[0]}`}
                                viewTransition
                                className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-secondary"
                                title={c.goal}
                              >
                                {inner}
                              </Link>
                              {refs.length > 1 && (
                                <div className="mb-1 ml-8 flex flex-wrap gap-1.5">
                                  {refs.map((fid, k) => (
                                    <Link
                                      key={fid}
                                      to={`/read/${fid}`}
                                      viewTransition
                                      className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                                    >
                                      {c.course_file_titles?.[k] ?? `旧课${k + 1}`}
                                    </Link>
                                  ))}
                                </div>
                              )}
                            </>
                          ) : (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void prep(d.topic, c.title)}
                              className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-secondary disabled:cursor-wait"
                              title={busy ? "正在备课" : `点击开始备课:${c.title}`}
                            >
                              {inner}
                            </button>
                          )}
                          {/* 备课进行时:不确定进度线(详细输出在生成中心的大纲面板) */}
                          {busy && <div className="anim-progress ml-8 mr-2 h-0.5 rounded-full" />}
                        </li>
                      );
                    })}
                  </ol>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              已出课点击去读;未出课点击即开始备课(原料调研→写课→发布,自动挂进学习路线),分钟级
            </p>
          </Card>
        );
      })}
    </section>
  );
}
