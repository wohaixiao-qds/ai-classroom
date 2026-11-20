/** 领域大纲面板(P7·M2):看大纲 → 调整(调序/删课) → 按课点单备课。
 *  数据 = /api/v1/outlines(列表)与 /api/v1/outlines/{topic}(详情+备课状态)。
 *  点「备课」= outline_prep 后台任务(原料调研→备课→按大纲钦定先修链→发布)。 */
import { ArrowDown, ArrowUp, BookOpen, ListOrdered, LoaderCircle, Save, X } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { SectionHeader } from "../../components/SectionHeader";
import { JobFeed } from "../../components/JobFeed";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import type { components } from "../../types/api.gen";

interface OutlineItem {
  topic: string;
  domain: string;
  count: number;
  prepared?: number; // 已有课件的课数(列表端点出课判定)
}

type OutlineCourse = components["schemas"]["OutlineCourse"];
type OutlineDetail = components["schemas"]["OutlineDetail"];

export function OutlinePanel() {
  const [outlines, setOutlines] = useState<OutlineItem[] | null>(null);
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  const [detail, setDetail] = useState<OutlineDetail | null>(null);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");

  const loadList = useCallback(() => {
    void fetch("/api/v1/outlines")
      .then((r) => r.json())
      .then(setOutlines)
      .catch(() => setOutlines([]));
  }, []);

  const loadDetail = useCallback(async (topic: string) => {
    const d = (await fetch(`/api/v1/outlines/${encodeURIComponent(topic)}`).then((r) =>
      r.json(),
    )) as OutlineDetail;
    setDetail(d);
    setDirty(false);
    return d;
  }, []);

  useEffect(() => loadList(), [loadList]);

  // 有备课在跑时轮询详情(queued/running → done/failed),按钮状态自动跟走
  useEffect(() => {
    if (!openTopic || !detail?.courses.some((c) => c.prep_status === "queued" || c.prep_status === "running"))
      return;
    const t = window.setInterval(() => void loadDetail(openTopic), 8000);
    return () => window.clearInterval(t);
  }, [openTopic, detail, loadDetail]);

  const open = async (topic: string) => {
    setOpenTopic(topic);
    setMsg("");
    await loadDetail(topic);
  };

  const move = (i: number, delta: number) => {
    if (!detail) return;
    const courses = [...detail.courses];
    const j = i + delta;
    if (j < 0 || j >= courses.length) return;
    [courses[i], courses[j]] = [courses[j], courses[i]];
    setDetail({ ...detail, courses });
    setDirty(true);
  };

  const remove = (i: number) => {
    if (!detail) return;
    setDetail({ ...detail, courses: detail.courses.filter((_, k) => k !== i) });
    setDirty(true);
  };

  const save = async () => {
    if (!detail) return;
    const r = await fetch(`/api/v1/outlines/${encodeURIComponent(detail.topic)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ courses: detail.courses }),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
      setMsg(`保存被校验器打回:${d.detail}`);
      return;
    }
    setMsg("大纲已更新");
    await loadDetail(detail.topic);
  };

  const attribute = async () => {
    if (!detail) return;
    setMsg("归位匹配中(一次 LLM 调用,只配实质相同的)…");
    const r = await fetch("/api/v1/outlines/attribute-all", { method: "POST" });
    const d = (await r.json().catch(() => ({}))) as {
      placements?: { course_id: string; outline_topic: string; outline_course_id: string }[];
      unplaceable?: { course_id: string; reason: string }[];
      detail?: string;
    };
    if (!r.ok) {
      setMsg(`归位失败:${d.detail}`);
      return;
    }
    setMsg(
      d.placements && d.placements.length
        ? `归位 ${d.placements.length} 门:${d.placements.map((m) => `${m.course_id} → ${m.outline_topic}/${m.outline_course_id}`).join(";")}` +
            (d.unplaceable?.length ? `;出圈 ${d.unplaceable.length} 门` : "")
        : "没有待归位的课件",
    );
    await loadDetail(detail.topic);
  };

  const cancelJob = async (title: string) => {
    if (!detail) return;
    const r = await fetch(
      `/api/v1/jobs/cancel?kind=outline_prep&target=${encodeURIComponent(
        `${detail.topic}::${title}`,
      )}`,
      { method: "POST" },
    );
    if (!r.ok) {
      const d2 = (await r.json().catch(() => ({}))) as { detail?: string };
      setMsg(`取消失败:${d2.detail}`);
      return;
    }
    setMsg(`「${title}」已取消(0 节骨架课会自动清理)`);
    await loadDetail(detail.topic);
  };

  const prep = async (title: string) => {
    if (!openTopic) return;
    setMsg("");
    const r = await fetch(`/api/v1/outlines/${encodeURIComponent(openTopic)}/prep`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const d = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
    if (!r.ok) {
      setMsg(`打回:${d.detail}`);
      return;
    }
    setMsg(`「${title}」已排队备课(原料调研→写课→发布),下方状态会自动刷新`);
    await loadDetail(openTopic);
  };

  return (
    <section>
      <SectionHeader
        icon={ListOrdered}
        title="领域大纲"
        count={outlines?.length ?? 0}
        hint="调研产出的大纲:调整顺序、逐课点单备课,出炉自动挂进学习路线"
      />
      {outlines === null ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : outlines.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          还没有大纲——在上方输入新主题开课,调研完就会出现在这里
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {outlines.map((o) => (
              <button
                key={o.topic}
                type="button"
                onClick={() => void open(o.topic)}
                className={`relative rounded-full border px-3 py-1.5 text-xs transition-colors ${
                  openTopic === o.topic
                    ? "border-primary font-medium text-primary"
                    : "border-border bg-background hover:border-primary/40"
                }`}
              >
                {/* 选中底色滑动:motion layoutId,切大纲时平滑迁移 */}
                {openTopic === o.topic && (
                  <motion.span
                    layoutId="outline-chip"
                    className="absolute inset-0 rounded-full bg-primary/10"
                    transition={{ duration: 0.25, ease: [0.22, 0.9, 0.3, 1] }}
                  />
                )}
                <span className="relative">
                  {o.domain ? `${o.domain} · ` : ""}
                  {o.topic}({o.count})
                  {/* 已出课件标记:一眼看出这本大纲备到哪了 */}
                  {o.prepared ? (
                    <span className="ml-1 text-success">已出 {o.prepared}</span>
                  ) : null}
                </span>
              </button>
            ))}
          </div>

          {detail && (
            <Card className="p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-sm font-medium">
                  {detail.domain && `${detail.domain} · `}
                  {detail.topic}
                  <span className="ml-2 font-mono text-xs text-muted-foreground">
                    {detail.courses.length} 门
                  </span>
                </p>
                <div className="flex items-center gap-2">
                  {dirty && (
                    <Button size="sm" onClick={() => void save()}>
                      <Save size={13} /> 保存调整
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => void attribute()}>
                    归位旧课
                  </Button>
                </div>
              </div>
              {detail.source_status === "historical_unrecorded" && (
                <p className="mb-3 text-xs text-muted-foreground">
                  历史大纲缺少调研来源记录。
                </p>
              )}
              {detail.source_evidence?.length > 0 && (
                <details className="mb-3 text-xs text-muted-foreground">
                  <summary className="cursor-pointer">调研原文摘录</summary>
                  {detail.source_evidence.map((source) => (
                    <blockquote key={source.id} className="my-2 break-words border-l border-border pl-3">
                      <a href={source.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                        {source.title}
                      </a>
                      <p className="mt-1 whitespace-pre-wrap">{source.excerpt}</p>
                    </blockquote>
                  ))}
                </details>
              )}
              {(() => {
                const groups: { part: string; items: { c: OutlineCourse; i: number }[] }[] = [];
                for (let i = 0; i < detail.courses.length; i++) {
                  const part = detail.courses[i].part?.trim() ?? "";
                  const last = groups[groups.length - 1];
                  if (last && last.part === part) last.items.push({ c: detail.courses[i], i });
                  else groups.push({ part, items: [{ c: detail.courses[i], i }] });
                }
                return groups.map((g) => (
                  <div key={g.part || "__none"} className="mb-3">
                    {g.part && (
                      <p className="mb-1.5 border-b border-border pb-1 font-mono text-[11px] tracking-widest text-primary">
                        ◆ {g.part}
                      </p>
                    )}
                    <ol className="space-y-2">
                      {g.items.map(({ c, i }) => {
                  const busy = c.prep_status === "queued" || c.prep_status === "running";
                  return (
                    // motion layout:↑↓ 换序时 FLIP 平滑滑到位,不再硬跳
                    <motion.li
                      layout
                      key={c.id}
                      transition={{ duration: 0.3, ease: [0.22, 0.9, 0.3, 1] }}
                      className="flex flex-col gap-1.5 rounded-lg border border-border bg-background/50 px-3 py-2"
                    >
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 font-mono text-xs text-muted-foreground">{i + 1}</span>
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                          {c.title}
                          {c.course_file_id ? (
                            <Badge variant="success" className="anim-pop">已出课</Badge>
                          ) : busy ? (
                            <Badge variant="warning" className="anim-pop">
                              <LoaderCircle size={10} className="mr-0.5 inline animate-spin" />
                              {c.prep_status === "running" ? "备课中" : "排队中"}
                            </Badge>
                          ) : c.prep_status === "failed" ? (
                            <Badge variant="destructive" className="anim-pop">上次失败,可重试</Badge>
                          ) : null}
                        </p>
                        {c.goal && (
                          <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-muted-foreground">
                            {c.goal}
                          </p>
                        )}
                        {c.scope && (
                          <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
                            范围:{c.scope}
                          </p>
                        )}
                        {c.source_ids && c.source_ids.length > 0 && (
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                            <span>依据:</span>
                            {c.source_ids.map((sourceId) => {
                              const source = detail.source_evidence?.find((item) => item.id === sourceId);
                              return source ? (
                                <a
                                  key={sourceId}
                                  href={source.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  title={`抓取于 ${source.fetched_at} · SHA-256 ${source.snapshot_sha256}`}
                                  className="max-w-48 truncate text-primary underline-offset-2 hover:underline"
                                >
                                  {source.title}
                                </a>
                              ) : null;
                            })}
                          </div>
                        )}
                        {c.prereq_titles && c.prereq_titles.length > 0 && (
                          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                            ⛓ 先修:{c.prereq_titles.join("、")}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        {busy && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => void cancelJob(c.title)}
                          >
                            取消
                          </Button>
                        )}
                        {c.course_file_id ? (
                          <Button size="sm" variant="secondary" asChild>
                            <a href={`/read/${c.course_file_id}`}>
                              <BookOpen size={13} /> 去读
                            </a>
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busy}
                            onClick={() => void prep(c.title)}
                          >
                            备课
                          </Button>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7"
                          onClick={() => move(i, -1)}
                          disabled={i === 0}
                          title="上移"
                        >
                          <ArrowUp size={13} />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7"
                          onClick={() => move(i, 1)}
                          disabled={i === detail.courses.length - 1}
                          title="下移"
                        >
                          <ArrowDown size={13} />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7"
                          onClick={() => remove(i)}
                          title="从大纲移除"
                        >
                          <X size={13} />
                        </Button>
                      </div>
                      </div>
                      {/* 备课进行时:实时输出(进度光条已内置于 JobFeed 盒顶);失败行直接亮出原因 */}
                      {(busy || c.prep_status === "failed") && (
                        <JobFeed
                          kind="outline_prep"
                          target={`${openTopic ?? ""}::${c.title}`}
                          active={Boolean(busy)}
                        />
                      )}
                    </motion.li>
                  );
                      })}
                    </ol>
                  </div>
                ));
              })()}
              {msg && <p key={msg} className="anim-drop mt-3 text-xs text-muted-foreground">{msg}</p>}
              <p className="mt-3 text-[11px] text-muted-foreground">
                备课 = 原料调研 → 写课 → 发布,出炉自动按大纲先修链挂进学习路线; minutes 级任务
              </p>
            </Card>
          )}
        </div>
      )}
    </section>
  );
}
