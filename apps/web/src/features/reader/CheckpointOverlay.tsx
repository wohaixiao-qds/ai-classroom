import { useState } from "react";
import Markdown from "react-markdown";
import { Sparkles } from "lucide-react";
import { motion } from "motion/react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { normalizeBold } from "../../utils/md";

/** 复述检查点弹层:复述文本 → POST /grade 批改(通过/存疑/未过 + 精准版)
 * pass 解锁继续;warn 看完精准版可继续或重述;fail 必须重述。
 * 批改文本按 markdown 渲染(grader 会用 **加粗** 等标记,纯文本会裸露星号)。
 * 遮罩走主题 token --overlay;进出动画由父级 AnimatePresence 驱动(reduced-motion 自动跳过)。 */
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
  onPass: () => void;
  /** 可选退出口:课堂自动弹出用不到;阅读器是用户手点的,要能反悔 */
  onClose?: () => void;
  /** 批改→答疑联动(P7 补):没过时把「我的回答+判定」带给答疑面板 */
  onAskTutor?: (answer: string, verdict: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<{
    verdict: string;
    comment: string;
    precise?: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  async function submit() {
    if (!answer.trim() || busy) return;
    setBusy(true);
    try {
      const resp = await fetch("/api/v1/grade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course_id: courseId, page_id: pageId, answer }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setResult(await resp.json());
    } catch (e) {
      setResult({
        verdict: "warn",
        comment: `批改服务异常: ${e}`,
        precise: "批改服务暂不可用,本轮已放行——但「动脑活不许代填」的规则仍适用,建议自查一遍。",
      });
      setAcknowledged(true);
    }
    setBusy(false);
  }

  const passed = result?.verdict === "pass" || (result?.verdict === "warn" && acknowledged);

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
              onChange={(e) => setAnswer(e.target.value)}
              rows={4}
              placeholder="用你自己的话写下来——说清才算学会"
              className="mb-4 leading-relaxed"
            />
            {onAskTutor && (
              <div className="mb-3 flex justify-end">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onAskTutor(answer, "未提交")}
                >
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
              <div className="flex items-start gap-2">
                <Badge
                  variant={
                    result.verdict === "pass"
                      ? "success"
                      : result.verdict === "warn"
                        ? "warning"
                        : "destructive"
                  }
                  className="mt-0.5 shrink-0"
                >
                  {result.verdict === "pass" ? "通过" : result.verdict === "warn" ? "存疑" : "未过"}
                </Badge>
                <span className="chat-md text-base leading-relaxed">
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
            {result.verdict !== "pass" && onAskTutor && (
              <div className="mb-3 flex justify-end">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onAskTutor(answer, result.verdict)}
                >
                  没懂,问 AI 老师
                </Button>
              </div>
            )}
            <div className="flex justify-end gap-2">
              {result.verdict !== "pass" && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setResult(null);
                    setAcknowledged(false);
                  }}
                >
                  ↺ 重新复述
                </Button>
              )}
              {result.verdict === "warn" && !acknowledged && (
                <Button variant="outline" onClick={() => setAcknowledged(true)}>
                  看过精准版了
                </Button>
              )}
              <Button onClick={onPass} disabled={!passed}>
                {passed ? "继续上课 →" : "通过后继续"}
              </Button>
            </div>
          </>
        )}
      </motion.div>
    </motion.div>
  );
}
