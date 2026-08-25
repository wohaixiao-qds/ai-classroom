import { useState } from "react";
import Markdown from "react-markdown";

/** 复述检查点弹层:复述文本 → POST /grade 批改(✅/⚠️/❌ + 🎯精准版)
 * pass 解锁继续;warn 看完精准版可继续或重述;fail 必须重述。
 * 批改文本按 markdown 渲染(grader 会用 **加粗** 等标记,纯文本会裸露星号)。 */
export function CheckpointOverlay({
  question,
  hint,
  courseId,
  pageId,
  onPass,
}: {
  question: string;
  hint: string | null;
  courseId: string;
  pageId: string;
  onPass: () => void;
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
      setResult({ verdict: "warn", comment: `批改服务异常: ${e}`, precise: "可点「跳过批改」继续(动脑活不许代填的规则仍适用)" });
      setAcknowledged(true);
    }
    setBusy(false);
  }

  const passed = result?.verdict === "pass" || (result?.verdict === "warn" && acknowledged);

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="mx-8 max-h-[85vh] max-w-lg overflow-y-auto rounded-2xl border border-(--line) bg-(--surface) p-8 shadow-2xl">
        <p className="accent mb-3 font-mono text-xs tracking-widest">◆ 复述检查点</p>
        <h3 className="mb-2 text-lg leading-relaxed">{question}</h3>
        {hint && <p className="muted mb-6 text-sm">提示: {hint}</p>}

        {!result ? (
          <>
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              rows={4}
              placeholder="用你自己的话写下来——说清才算学会"
              className="mb-4 w-full rounded-lg border border-(--line) bg-(--bg) p-3 text-sm leading-relaxed outline-none focus:border-(--accent)"
            />
            <div className="flex justify-end">
              <button
                onClick={submit}
                disabled={busy || !answer.trim()}
                className="rounded-full bg-(--accent) px-6 py-2 font-medium text-(--bg) disabled:opacity-40"
              >
                {busy ? "批改中…" : "提交批改"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-4 rounded-lg border border-(--line) bg-(--bg) p-4">
              <div className="mb-1 text-lg">
                {result.verdict === "pass" ? "✅" : result.verdict === "warn" ? "⚠️" : "❌"}{" "}
                <span className="chat-md inline-block text-base leading-relaxed">
                  <Markdown>{result.comment}</Markdown>
                </span>
              </div>
              {result.precise && (
                <div className="accent mt-2 text-sm leading-relaxed">
                  🎯 精准版:
                  <span className="chat-md inline-block">
                    <Markdown>{result.precise}</Markdown>
                  </span>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-3">
              {result.verdict !== "pass" && (
                <button
                  onClick={() => {
                    setResult(null);
                    setAcknowledged(false);
                  }}
                  className="rounded-full border border-(--line) px-5 py-2 text-sm"
                >
                  ↺ 重新复述
                </button>
              )}
              {result.verdict === "warn" && !acknowledged && (
                <button
                  onClick={() => setAcknowledged(true)}
                  className="rounded-full border border-(--line) px-5 py-2 text-sm"
                >
                  看过精准版了
                </button>
              )}
              <button
                onClick={onPass}
                disabled={!passed}
                className="rounded-full bg-(--accent) px-6 py-2 font-medium text-(--bg) disabled:opacity-40"
              >
                {passed ? "继续上课 →" : "通过后继续"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
