import { useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import type { components } from "../../types/api.gen";

type LearningQuestion = components["schemas"]["LearningQuestion"];
type WishlistItem = components["schemas"]["WishlistItem"];

type LearningQuestionsProps = {
  courseId?: string;
  unassigned?: boolean;
  onSaved?: () => void;
  sections?: readonly { id: string; heading: string }[];
};

/** 搜索只产生延伸线索；保留、忽略由学员选择，不自动触发备课。 */
export function LearningQuestions({
  courseId,
  unassigned = false,
  onSaved,
  sections,
}: LearningQuestionsProps) {
  const [open, setOpen] = useState(false);
  const [questions, setQuestions] = useState<LearningQuestion[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!open || (!courseId && !unassigned)) return;
    const controller = new AbortController();
    const params = new URLSearchParams(
      unassigned ? { unassigned: "true" } : { course_id: courseId! },
    );
    void fetch(`/api/v1/learning-questions?${params}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseError(response));
        return response.json() as Promise<LearningQuestion[]>;
      })
      .then((items) => {
        if (controller.signal.aborted) return;
        // 后端查询之外再约束展示范围，历史缺来源的记录不得猜测归入当前课。
        setQuestions(items.filter((item) =>
          unassigned ? item.course_id === null : item.course_id === courseId,
        ));
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "延伸问题加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, courseId, unassigned, refresh]);

  async function operate(question: LearningQuestion, action: "save" | "dismiss") {
    if (busy.has(question.id)) return;
    setBusy((previous) => new Set(previous).add(question.id));
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(
        `/api/v1/learning-questions/${encodeURIComponent(question.id)}/${action}`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await responseError(response));
      if (action === "save") {
        const saved = await response.json() as WishlistItem;
        setQuestions((previous) => previous?.map((item) => item.id === question.id
          ? { ...item, status: "saved", wishlist_id: saved.id }
          : item) ?? null);
        setNotice(saved.job ? "已加入待学清单；已有相关任务，可在生成中心查看。本次未启动生成。" : "已加入待学清单，可在生成中心查看；尚未开始生成课程。");
        onSaved?.();
      } else {
        setQuestions((previous) => previous?.filter((item) => item.id !== question.id) ?? null);
        setNotice("已忽略这条问题。");
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "操作失败，请重试");
    } finally {
      setBusy((previous) => {
        const next = new Set(previous);
        next.delete(question.id);
        return next;
      });
    }
  }

  return (
    <details
      className="my-8 min-w-0 rounded-xl border border-border font-sans"
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        const expanded = event.currentTarget.open;
        if (expanded) {
          setLoading(true);
          setError(null);
        }
        setOpen(expanded);
      }}
    >
      <summary className="min-h-11 cursor-pointer px-4 py-3 text-base font-medium">
        {unassigned ? "待归类问题" : "延伸问题"}
        {questions !== null && <span className="ml-2 text-sm font-normal text-muted-foreground">{questions.length} 条</span>}
      </summary>
      <div className="min-w-0 space-y-4 border-t border-border p-4">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {unassigned
            ? "这些历史问题缺少课程来源，保留在这里供你挑选。"
            : "答疑时产生的搜索线索，供你选择是否继续探索。"}
          搜索过不代表课件有缺漏，也不代表问题中的说法已核实。
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={loading || busy.size > 0}
            onClick={() => {
              setLoading(true);
              setError(null);
              setRefresh((value) => value + 1);
            }}
          >
            {loading ? "加载中…" : "刷新问题"}
          </Button>
          {loading && <span role="status" className="text-sm text-muted-foreground">正在读取问题…</span>}
        </div>
        {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
        {notice && <p role="status" className="text-sm text-success">{notice}</p>}
        {!loading && !error && questions?.length === 0 && (
          <p className="text-sm text-muted-foreground">{unassigned ? "没有待归类的问题。" : "本课暂时没有延伸问题。"}</p>
        )}
        <ul className="space-y-3">
          {questions?.map((question) => {
            const sectionIndex = sections?.findIndex((section) => section.id === question.page_id) ?? -1;
            const section = sectionIndex >= 0 ? sections?.[sectionIndex] : undefined;
            const timestamp = question.created_at ? Date.parse(question.created_at) : NaN;
            return (
              <li key={question.id} className="min-w-0 space-y-3 rounded-lg border border-border p-4">
                <p className="break-words text-base leading-relaxed">{question.question}</p>
                <div className="flex flex-wrap gap-x-3 gap-y-1 break-words text-sm text-muted-foreground">
                  {section
                    ? <a className="text-primary underline" href={`#sec-${sectionIndex}`}>来自第 {sectionIndex + 1} 节 · {section.heading}</a>
                    : question.page_id && <span>来源位置：{question.page_id}</span>}
                  {Number.isFinite(timestamp) && <time dateTime={question.created_at!}>{new Date(timestamp).toLocaleString("zh-CN")}</time>}
                  {unassigned && <span>课程来源未记录</span>}
                  {question.status === "saved" && <span className="text-success">已加入待学清单</span>}
                </div>
                {question.detail && (
                  <details className="text-sm text-muted-foreground">
                    <summary className="min-h-11 cursor-pointer py-3">查看搜索线索</summary>
                    <p className="whitespace-pre-wrap break-words leading-relaxed">{question.detail}</p>
                  </details>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="min-h-11"
                    disabled={loading || busy.has(question.id) || question.status === "saved"}
                    onClick={() => void operate(question, "save")}
                  >
                    {question.status === "saved" ? "已加入待学清单" : busy.has(question.id) ? "处理中…" : "加入待学清单"}
                  </Button>
                  <Button
                    variant="ghost"
                    className="min-h-11"
                    disabled={loading || busy.has(question.id)}
                    onClick={() => void operate(question, "dismiss")}
                  >忽略</Button>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </details>
  );
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // 非 JSON 错误仍显示 HTTP 状态，避免吞掉失败。
  }
  return `请求失败（HTTP ${response.status}），请重试`;
}
