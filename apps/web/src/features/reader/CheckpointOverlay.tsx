import { useState } from "react";
import Markdown from "react-markdown";
import { ArrowRight, CheckCircle2, ChevronDown, CircleAlert, Sparkles } from "lucide-react";
import { motion } from "motion/react";


import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { Collapse } from "../../components/Collapse";
import { useCountUp } from "../../hooks/useCountUp";
import { normalizeBold } from "../../utils/md";
import { cn } from "../../lib/utils";

/** 结算环(A 案核心):分数环 + 数字滚上,useCountUp 同帧驱动弧线与数字
 *  (reduced-motion 直达终值);pass=success 色,未过=warning 色。 */
function ScoreRing({ score, passed }: { score: number; passed: boolean }) {
  const shown = useCountUp(score);
  const r = 30;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, shown ?? score));
  return (
    <div className="relative size-20 shrink-0" role="img" aria-label={`得分 ${score} 分`}>
      <svg viewBox="0 0 72 72" className="size-20 -rotate-90">
        <circle cx="36" cy="36" r={r} fill="none" stroke="var(--line)" strokeWidth="6" />
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke={passed ? "var(--success)" : "var(--warning)"}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct / 100)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold leading-none">{Math.round(pct)}</span>
        <span className={cn("mt-0.5 text-[10px]", passed ? "text-success" : "text-warning")}>
          {passed ? "通过" : "未过"}
        </span>
      </div>
    </div>
  );
}

/** 三段反馈行(✓对/✗缺/→下一步,配 GRADE_OUTPUT_SPEC 三行制)。
 *  无标记行(旧 trace 回放/服务异常路径)→ 返回 null,调用方回退整段 markdown。 */
function parseFeedback(comment: string): { icon: "good" | "gap" | "next"; text: string }[] | null {
  const rows = comment
    .split("\n")
    .map((l) => l.trim())
    .map((l) => {
      if (l.startsWith("✓")) return { icon: "good" as const, text: l.replace(/^✓\s*/, "") };
      if (l.startsWith("✗")) return { icon: "gap" as const, text: l.replace(/^✗\s*/, "") };
      if (l.startsWith("→")) return { icon: "next" as const, text: l.replace(/^→\s*/, "") };
      return null;
    })
    .filter((r): r is { icon: "good" | "gap" | "next"; text: string } => r !== null);
  return rows.length > 0 ? rows : null;
}

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
  const [compareOpen, setCompareOpen] = useState(true); // B 案:对照区默认展开,可折叠

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
  const feedbackRows = result ? parseFeedback(result.comment) : null;
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
        className={cn(
          "mx-8 max-h-[85vh] overflow-y-auto rounded-2xl border border-border bg-card p-8 shadow-2xl",
          result ? "max-w-2xl" : "max-w-lg", // 结果态放宽:左右对照需要宽度
        )}
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
            {/* A:结算环 + 三段反馈(✓对在哪/✗缺在哪/→下一步);无标记行回退整段 markdown */}
            <div className="mb-4 flex items-center gap-4">
              <ScoreRing score={result.score} passed={passed} />
              {feedbackRows ? (
                <div className="min-w-0 flex-1 space-y-1.5">
                  {feedbackRows.map((r) => (
                    <p key={r.icon} className="flex items-start gap-1.5 text-sm leading-relaxed">
                      {r.icon === "good" && (
                        <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-success" />
                      )}
                      {r.icon === "gap" && (
                        <CircleAlert size={15} className="mt-0.5 shrink-0 text-warning" />
                      )}
                      {r.icon === "next" && (
                        <ArrowRight size={15} className="mt-0.5 shrink-0 text-primary" />
                      )}
                      <span className="min-w-0 break-words">{r.text}</span>
                    </p>
                  ))}
                </div>
              ) : (
                <span className="chat-md min-w-0 flex-1 text-sm leading-relaxed">
                  <Markdown>{normalizeBold(result.comment)}</Markdown>
                </span>
              )}
            </div>
            {/* B:复述对照——左右分栏(窄屏自动堆叠),可折叠 */}
            {result.precise && (
              <div className="mb-4">
                <button
                  type="button"
                  onClick={() => setCompareOpen(!compareOpen)}
                  aria-expanded={compareOpen}
                  className="flex items-center gap-1 text-xs text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
                >
                  <ChevronDown
                    size={13}
                    className={cn("transition-transform", compareOpen && "rotate-180")}
                  />
                  复述对照{compareOpen ? "" : "（已折叠）"}
                </button>
                <Collapse open={compareOpen} className="mt-2">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="mb-1 text-[11px] font-medium text-muted-foreground">你的复述</p>
                      <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                        {answer}
                      </p>
                    </div>
                    <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                      <p className="mb-1 flex items-center gap-1 text-[11px] font-medium text-primary">
                        <Sparkles size={11} /> 标准表述
                      </p>
                      <span className="chat-md block text-sm leading-relaxed">
                        {/* grader 偶尔把「🎯精准版:」标签抄进字段,UI 已有标签,剥掉防重复 */}
                        <Markdown>
                          {normalizeBold(result.precise.replace(/^\s*🎯?\s*精准版\s*[:：]?\s*/, ""))}
                        </Markdown>
                      </span>
                    </div>
                  </div>
                </Collapse>
              </div>
            )}
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
