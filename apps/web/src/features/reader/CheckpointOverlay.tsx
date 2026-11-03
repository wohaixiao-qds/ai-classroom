import { useState } from "react";
import Markdown from "react-markdown";
import { Sparkles } from "lucide-react";
import { motion } from "motion/react";


import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { normalizeBold } from "../../utils/md";
import { cn } from "../../lib/utils";

/** 复述检查点弹层:复述文本 → POST /grade 百分制批改。
 *  score≥70 判 pass(答案+精准版都保留进笔记);<70 判 fail——重新复述,
 *  或「问 AI 老师」带着检查点上下文答疑,学过一轮后再复述保底 70。
 *  批改文本按 markdown 渲染;遮罩走 --overlay;进出动画由父级 AnimatePresence 驱动。 */
export function CheckpointOverlay({
  question,
  hint,
  courseId,
  pageId,
  onPass,
  onClose,
  onAskTutor,
}: {
  question: string;
  hint: string | null;
  courseId: string;
  pageId: string;
  onPass: (result: { score: number; comment: string; precise?: string; answer: string }) => void;
  /** 可选退出口:阅读器是用户手点的,要能反悔 */
  onClose?: () => void;
  /** 批改→答疑联动(P7 补):没过时把「我的回答+判定」带给答疑面板 */
  onAskTutor?: (answer: string, verdict: string) => void;
}) {
  const [answer, setAnswer] = useState(() => {
    // 草稿持久(P7):关弹层/刷新不丢学员写了一半的回答
    try {
      return localStorage.getItem(`recite-draft-${courseId}:${pageId}`) ?? "";
    } catch {
      return "";
    }
  });
  const [tutored, setTutored] = useState(false); // 问过老师后置 true → 重述保底 70
  const [result, setResult] = useState<{
    verdict: string;
    score: number;
    comment: string;
    precise?: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!answer.trim() || busy) return;
    setBusy(true);
    try {
      const resp = await fetch("/api/v1/grade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: courseId,
          page_id: pageId,
          answer,
          tutored,
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setResult(await resp.json());
    } catch (e) {
      setResult({
        verdict: "fail",
        score: 0,
        comment: `批改服务异常: ${e}`,
        precise: "批改服务暂不可用,本轮不计成绩——稍后重试;「动脑活不许代填」的规则仍适用。",
      });
    }
    setBusy(false);
  }

  const passed = result?.verdict === "pass";
  const askTutor = (verdict: string) => {
    onAskTutor?.(answer, verdict);
    setTutored(true); // 问过老师:下一次复述保底 70(答疑学过一轮)
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15, ease: [0.22, 0.9, 0.3, 1] }}
      className="fixed inset-0 z-60 flex items-center justify-center bg-overlay backdrop-blur-sm"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 6 }}
        transition={{ duration: 0.25, ease: [0.22, 0.9, 0.3, 1] }}
        className="mx-8 max-h-[85vh] max-w-lg overflow-y-auto rounded-2xl border border-border bg-card p-8 shadow-2xl"
      >
        <p className="mb-3 font-mono text-xs tracking-widest text-primary">◆ 复述检查点</p>
        <h3 className="mb-2 text-lg leading-relaxed">{question}</h3>
        {hint && <p className="mb-6 text-sm text-muted-foreground">提示: {hint}</p>}

        {!result ? (
          <>
            <Textarea
              value={answer}
              onChange={(e) => {
                setAnswer(e.target.value);
                try {
                  localStorage.setItem(`recite-draft-${courseId}:${pageId}`, e.target.value);
                } catch {
                  /* 隐私模式存不进就算了 */
                }
              }}
              rows={4}
              placeholder="用你自己的话写下来——说清才算学会"
              className="mb-4 leading-relaxed"
            />
            {onAskTutor && (
              <div className="mb-3 flex justify-end">
                <Button variant="secondary" size="sm" onClick={() => askTutor("未提交")}>
                  没懂,问 AI 老师
                </Button>
              </div>
            )}
            <div className="flex justify-end gap-2">
              {onClose && (
                <Button variant="ghost" onClick={onClose}>
                  先不复述
                </Button>
              )}
              <Button onClick={submit} disabled={busy || !answer.trim()}>
                {busy ? "批改中…" : "提交批改"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-4 rounded-lg border border-border bg-background p-4">
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    "flex w-14 shrink-0 flex-col items-center rounded-lg py-2",
                    passed ? "bg-success/15 text-success" : "bg-warning/15 text-warning",
                  )}
                >
                  <span className="text-xl font-bold leading-none">{result.score}</span>
                  <span className="mt-0.5 text-[10px]">得分</span>
                </div>
                <span className="chat-md text-sm leading-relaxed">
                  <Markdown>{normalizeBold(result.comment)}</Markdown>
                </span>
              </div>
              {result.precise && (
                <div className="mt-2 flex items-start gap-1.5 text-sm leading-relaxed text-primary">
                  <Sparkles size={13} className="mt-1 shrink-0" />
                  <span>
                    精准版:
                    <span className="chat-md block">
                      {/* grader 偶尔把「🎯精准版:」标签抄进字段,UI 已有标签,剥掉防重复 */}
                      <Markdown>
                        {normalizeBold(result.precise.replace(/^\s*🎯?\s*精准版\s*[:：]?\s*/, ""))}
                      </Markdown>
                    </span>
                  </span>
                </div>
              )}
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {!passed && onAskTutor && (
                <Button variant="secondary" size="sm" onClick={() => askTutor(result.verdict)}>
                  没懂,问 AI 老师
                </Button>
              )}
              {!passed && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setResult(null);
                  }}
                >
                  ↺ 重新复述
                </Button>
              )}
              <Button
                onClick={() => {
                  if (!passed) return;
                  try {
                    localStorage.removeItem(`recite-draft-${courseId}:${pageId}`);
                  } catch {
                    /* 同上 */
                  }
                  onPass({
                    score: result.score,
                    comment: result.comment,
                    precise: result.precise,
                    answer,
                  });
                }}
                disabled={!passed}
              >
                通过后继续 →
              </Button>
            </div>
            {!passed && (
              <p className="mt-3 text-[11px] text-muted-foreground">
                70 分及格;没懂就问 AI 老师——学过一轮后再复述,核心说清即过。
              </p>
            )}
          </>
        )}
      </motion.div>
    </motion.div>
  );
}
