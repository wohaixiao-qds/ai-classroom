/** 新手可直接操作的本地人工原文审查页。 */
import { ArrowLeft, BookOpenCheck, ChevronLeft, ChevronRight, ExternalLink, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { PageError, PageLoading } from "../../components/PageState";
import { SectionHeader } from "../../components/SectionHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import type { components } from "../../types/api.gen";

type Schemas = components["schemas"];
type CourseSummary = Schemas["EvidenceReviewCourse"];
type ReviewDetail = Schemas["EvidenceReviewDetail"];
type ReviewBlock = Schemas["EvidenceReviewBlock"];
type ReviewVerdict = Schemas["EvidenceReviewSave"]["verdict"];
type EvidenceTranslation = Schemas["EvidenceReviewTranslation"];
type ReviewDraft = { verdict: ReviewVerdict | ""; reason: string };

const PAGE_SIZE = 10;
const LABELS: Record<ReviewVerdict, string> = {
  supported: "有依据",
  unsupported: "没依据",
  uncertain: "看不出来",
};
const draftKey = (courseId: string, blockId: string) => `${courseId}:${blockId}`;
const evidenceKey = (courseId: string, blockId: string, evidenceId: string) =>
  `${courseId}:${blockId}:${evidenceId}`;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function draftFor(block: ReviewBlock): ReviewDraft {
  return block.verdict === "unreviewed"
    ? { verdict: "", reason: "" }
    : { verdict: block.verdict, reason: block.reason };
}

export function EvidenceReviewPage() {
  const [courses, setCourses] = useState<CourseSummary[] | null>(null);
  const [courseId, setCourseId] = useState("");
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [offset, setOffset] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, ReviewDraft>>({});
  const [translations, setTranslations] = useState<Record<string, EvidenceTranslation>>({});
  const [visibleTranslations, setVisibleTranslations] = useState<Record<string, boolean>>({});
  const [translationErrors, setTranslationErrors] = useState<Record<string, string>>({});
  const [reviewer, setReviewer] = useState(() => {
    try { return localStorage.getItem("evidence-reviewer") || "我"; } catch { return "我"; }
  });
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [translatingKey, setTranslatingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const totalPages = useMemo(
    () => detail ? Math.max(1, Math.ceil(detail.total_blocks / PAGE_SIZE)) : 1,
    [detail],
  );

  useEffect(() => {
    const controller = new AbortController();
    void request<Schemas["EvidenceReviewCourses"]>("/api/v1/evidence-review/courses", {
      signal: controller.signal,
    }).then((result) => {
      if (controller.signal.aborted) return;
      setCourses(result.courses);
      setCourseId((current) => current || result.courses[0]?.course_id || "");
      if (result.courses.length === 0) setLoading(false);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "课程列表加载失败");
        setLoading(false);
      }
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!courseId) return;
    const controller = new AbortController();
    void request<ReviewDetail>(
      `/api/v1/evidence-review/${encodeURIComponent(courseId)}?offset=${offset}&limit=${PAGE_SIZE}`,
      { signal: controller.signal },
    ).then((result) => {
      if (controller.signal.aborted) return;
      setDetail(result);
      setDrafts((current) => {
        const next = { ...current };
        result.blocks.forEach((block) => {
          const key = draftKey(courseId, block.id);
          if (!next[key]) next[key] = draftFor(block);
          else if (block.stale) next[key] = { verdict: "", reason: "" };
        });
        return next;
      });
      setLoading(false);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "课程内容加载失败");
        setLoading(false);
      }
    });
    return () => controller.abort();
  }, [courseId, offset]);

  function updateDraft(blockId: string, change: Partial<ReviewDraft>) {
    const key = draftKey(courseId, blockId);
    setDrafts((current) => ({
      ...current,
      [key]: { ...(current[key] ?? { verdict: "", reason: "" }), ...change },
    }));
  }

  async function translate(block: ReviewBlock, evidenceId: string) {
    const key = evidenceKey(courseId, block.id, `${evidenceId}:${block.input_hash}`);
    const existing = translations[key];
    if (existing) {
      setVisibleTranslations((current) => ({ ...current, [key]: !current[key] }));
      return;
    }
    setTranslationErrors((current) => ({ ...current, [key]: "" }));
    setTranslatingKey(key);
    try {
      const result = await request<EvidenceTranslation>(
        `/api/v1/evidence-review/${encodeURIComponent(courseId)}/translate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            block_id: block.id,
            evidence_id: evidenceId,
            input_hash: block.input_hash,
          }),
        },
      );
      setTranslations((current) => ({ ...current, [key]: result }));
      setVisibleTranslations((current) => ({ ...current, [key]: true }));
    } catch (cause: unknown) {
      setTranslationErrors((current) => ({
        ...current,
        [key]: cause instanceof Error ? cause.message : "翻译失败，请重试",
      }));
    } finally {
      setTranslatingKey(null);
    }
  }

  async function save(block: ReviewBlock) {
    const draft = drafts[draftKey(courseId, block.id)];
    if (!draft?.verdict || !draft.reason.trim() || !reviewer.trim()) return;
    setSavingId(block.id);
    setError(null);
    setNotice(null);
    try {
      const saved = await request<Schemas["EvidenceReviewSaved"]>(
        `/api/v1/evidence-review/${encodeURIComponent(courseId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            block_id: block.id,
            reviewer: reviewer.trim(),
            input_hash: block.input_hash,
            verdict: draft.verdict,
            reason: draft.reason.trim(),
          }),
        },
      );
      try { localStorage.setItem("evidence-reviewer", reviewer.trim()); } catch { /* 可选偏好 */ }
      setDetail((current) => current && ({
        ...current,
        reviewed_blocks: saved.reviewed_blocks,
        supported: current.supported + Number(saved.verdict === "supported") - Number(block.verdict === "supported"),
        unsupported: current.unsupported + Number(saved.verdict === "unsupported") - Number(block.verdict === "unsupported"),
        uncertain: current.uncertain + Number(saved.verdict === "uncertain") - Number(block.verdict === "uncertain"),
        blocks: current.blocks.map((item) => item.id === block.id
          ? { ...item, verdict: saved.verdict, reason: saved.reason, reviewer: saved.reviewer, stale: false }
          : item),
      }));
      setNotice(`已保存「${LABELS[saved.verdict]}」。你的判断只记在本地审查记录中。`);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "保存失败，请重试");
    } finally {
      setSavingId(null);
    }
  }

  if (loading && courses === null) return <PageLoading label="正在准备审查页面…" />;
  if (error && courses === null) return <PageError message={error} />;

  const detailLoading = loading || (
    Boolean(courseId) && !error && (detail?.course_id !== courseId || detail?.offset !== offset)
  );
  return (
    <div className="workspace-page max-w-5xl space-y-6">
      <header className="workspace-header flex-col items-start gap-3 sm:flex-row sm:items-center">
        <div>
          <Link to="/eval" className="mb-2 inline-flex min-h-11 items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft size={15} aria-hidden="true" /> 返回观测
          </Link>
          <h1 className="workspace-title">人工抽查课件</h1>
          <p className="workspace-description">逐条对照原文，看看课程内容是否真的有依据。</p>
        </div>
      </header>

      <Card className="space-y-4 rounded-2xl p-4 sm:p-6">
        <SectionHeader icon={BookOpenCheck} title="怎么判断" hint="只判断课件里的事实是否被所列原文支持，不用评价写得好不好。" />
        <div className="grid gap-2 text-sm leading-relaxed sm:grid-cols-3">
          <p className="rounded-lg border border-success/30 bg-success/5 p-3"><strong>有依据：</strong>重要事实都能在原文中找到，没有额外夸大的结论。</p>
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3"><strong>没依据：</strong>主要事实在原文里找不到，或与原文矛盾。</p>
          <p className="rounded-lg border border-warning/30 bg-warning/5 p-3"><strong>看不出来：</strong>原文不够、看不懂，或暂时无法判断。可以先跳过。</p>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          第一轮每次展示 10 条。请先读课件内容，再展开“查看原文”对照。没有把握就选“看不出来”，不要猜。保存只会新增本地审查记录，不改课程或笔记。
        </p>
      </Card>

      <section className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,16rem)] sm:items-end">
        <label className="space-y-2 text-sm font-medium" htmlFor="review-course">
          选择课程
          <select id="review-course" value={courseId} onChange={(event) => {
            setOffset(0);
            setDetail(null);
            setError(null);
            setNotice(null);
            setCourseId(event.target.value);
          }} disabled={!courses?.length}
            className="flex h-11 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/30 disabled:opacity-60">
            {courses?.map((course) => (
              <option key={course.course_id} value={course.course_id}>
                {course.title} · 已审 {course.reviewed_blocks}/{course.total_blocks}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-2 text-sm font-medium" htmlFor="reviewer-name">
          你的名字或称呼
          <Input id="reviewer-name" value={reviewer} maxLength={80} onChange={(event) => setReviewer(event.target.value)} className="h-11" />
        </label>
      </section>

      {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm text-success">{notice}</p>}
      {detailLoading ? <PageLoading label="正在载入课程内容…" /> : error && !detail ? (
        <PageError message={error} />
      ) : !courses?.length ? (
        <Card className="rounded-2xl p-6 text-sm leading-relaxed text-muted-foreground">
          目前没有可抽查的课程。页面只列出已发布、并且有原文依据关联的书页课程。
        </Card>
      ) : detail?.course_id === courseId && detail.offset === offset ? <>
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
          <div>
            <h2 className="font-semibold">{detail.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">已审 {detail.reviewed_blocks}/{detail.total_blocks} 条 · 有依据 {detail.supported} · 没依据 {detail.unsupported} · 看不出来 {detail.uncertain}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" className="min-h-11" disabled={offset === 0} onClick={() => {
              setDetail(null);
              setOffset(Math.max(0, offset - PAGE_SIZE));
            }}>
              <ChevronLeft size={16} aria-hidden="true" /> 上 10 条
            </Button>
            <span className="min-w-16 text-center text-xs text-muted-foreground">{Math.floor(offset / PAGE_SIZE) + 1} / {totalPages}</span>
            <Button variant="outline" className="min-h-11" disabled={offset + PAGE_SIZE >= detail.total_blocks} onClick={() => {
              setDetail(null);
              setOffset(offset + PAGE_SIZE);
            }}>
              下 10 条 <ChevronRight size={16} aria-hidden="true" />
            </Button>
          </div>
        </section>

        {(detail.evidence_errors ?? []).length > 0 && (
          <Card className="rounded-xl border-warning/40 bg-warning/5 p-4 text-sm text-warning">
            这门课有部分来源编号或证据结构问题；本页仍允许对可显示的原文逐条判断。{(detail.evidence_errors ?? []).slice(0, 2).join("；")}
          </Card>
        )}

        <div className="space-y-4">
          {detail.blocks.map((block, index) => {
            const draft = drafts[draftKey(courseId, block.id)] ?? draftFor(block);
            const ordinal = offset + index + 1;
            return (
              <Card key={block.id} className="space-y-4 rounded-2xl p-4 shadow-(--shadow-1) sm:p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={block.verdict === "supported" ? "success" : block.verdict === "unsupported" ? "destructive" : block.verdict === "uncertain" ? "warning" : "secondary"}>
                    {block.verdict === "unreviewed" ? "待判断" : LABELS[block.verdict]}
                  </Badge>
                  {block.stale && <Badge variant="warning">课件已变化，请重新判断</Badge>}
                  <span className="text-xs text-muted-foreground">第 {ordinal} 条 · {block.section}</span>
                </div>

                <div className="rounded-xl border border-border bg-background p-4">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">课件内容</p>
                  <p className="whitespace-pre-wrap break-words text-sm leading-7">{block.text}</p>
                </div>

                <div className="space-y-3">
                  <p className="text-sm font-medium">对应原文</p>
                  {block.evidence.map((item) => {
                    const source = block.sources.find((entry) => entry.id === item.source_id);
                    const key = evidenceKey(courseId, block.id, `${item.id}:${block.input_hash}`);
                    const translation = translations[key];
                    const isTranslating = translatingKey === key;
                    return (
                      <div key={item.id} className="rounded-xl border border-border p-4">
                        <p className="text-xs leading-relaxed text-muted-foreground">资料要点：{item.point}</p>
                        <blockquote className="mt-3 border-l-2 border-primary/50 pl-3 text-sm leading-7 [overflow-wrap:anywhere]">
                          {item.quote || "没有保存原文摘录。"}
                        </blockquote>
                        <div className="mt-3 flex flex-wrap items-center gap-3">
                          <Button type="button" variant="outline" className="min-h-11"
                            disabled={isTranslating || (!item.quote && !item.context)}
                            onClick={() => void translate(block, item.id)}>
                            {isTranslating ? <><LoaderCircle size={15} className="animate-spin" aria-hidden="true" /> 翻译中…</> : translation ? (visibleTranslations[key] ? "隐藏中文" : "显示中文") : "翻译成中文"}
                          </Button>
                          <span className="text-xs text-muted-foreground">点击后会调用当前配置的模型翻译这条原文；结果只暂存在本页。翻译仅供理解，判断时仍可对照英文原文和来源。</span>
                        </div>
                        {translationErrors[key] && <p role="alert" className="mt-2 text-sm text-destructive">{translationErrors[key]}</p>}
                        {translation && visibleTranslations[key] && translation.quote_translation && (
                          <div className="mt-3 rounded-lg bg-muted/50 p-3 text-sm leading-7">
                            <p className="mb-1 text-xs font-medium text-muted-foreground">中文翻译（原文摘录）</p>
                            <p className="whitespace-pre-wrap break-words">{translation.quote_translation}</p>
                          </div>
                        )}
                        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
                          <span className="text-muted-foreground">{item.quote_status === "matched" ? "摘录在抓取正文中找到" : "摘录位置未确认"}</span>
                          {source && <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1 text-primary underline underline-offset-2 [overflow-wrap:anywhere]">
                            打开来源：{source.title} <ExternalLink size={13} aria-hidden="true" />
                          </a>}
                        </div>
                        {item.context && <details className="mt-2 text-xs text-muted-foreground">
                          <summary className="flex min-h-11 cursor-pointer items-center">查看前后文</summary>
                          <p className="whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 leading-relaxed">{item.context}</p>
                          {translation?.context_translation && visibleTranslations[key] && (
                            <div className="mt-2 rounded-md bg-muted/50 p-3 leading-relaxed">
                              <p className="mb-1 font-medium">中文翻译（前后文）</p>
                              <p className="whitespace-pre-wrap break-words">{translation.context_translation}</p>
                            </div>
                          )}
                        </details>}
                      </div>
                    );
                  })}
                </div>

                <fieldset className="space-y-3">
                  <legend className="text-sm font-medium">你的判断</legend>
                  <div className="flex flex-wrap gap-2">
                    {(["supported", "unsupported", "uncertain"] as const).map((verdict) => (
                      <Button key={verdict} type="button" variant={draft.verdict === verdict ? "default" : "outline"}
                        aria-pressed={draft.verdict === verdict} className="min-h-11"
                        onClick={() => updateDraft(block.id, { verdict })}>
                        {LABELS[verdict]}
                      </Button>
                    ))}
                  </div>
                  <label htmlFor={`reason-${block.id}`} className="block space-y-2 text-sm">
                    简单说说为什么
                    <Textarea id={`reason-${block.id}`} value={draft.reason} maxLength={2000} rows={3}
                      placeholder="例如：原文只说系统支持重试，没有提到成功率提高到 95%。"
                      onChange={(event) => updateDraft(block.id, { reason: event.target.value })} />
                  </label>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button className="min-h-11" disabled={!draft.verdict || !draft.reason.trim() || !reviewer.trim() || savingId !== null}
                      onClick={() => void save(block)}>
                      {savingId === block.id ? <><LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> 保存中…</> : block.verdict === "unreviewed" ? "保存判断" : "更新判断"}
                    </Button>
                    {block.reviewer && <span className="text-xs text-muted-foreground">上次由 {block.reviewer} 审查；再次保存会更新这条判断。</span>}
                  </div>
                </fieldset>
              </Card>
            );
          })}
        </div>
      </> : null}
    </div>
  );
}
