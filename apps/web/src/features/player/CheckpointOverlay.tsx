/** 复述检查点弹层:页面讲完自动弹出,学员复述后点「通过」继续。
 * T6 会接入批改 Agent:复述文本 → LLM 评 ✅/⚠️/❌ → 通过才放行。 */
export function CheckpointOverlay({
  question,
  onPass,
}: {
  question: string;
  onPass: () => void;
}) {
  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="mx-8 max-w-lg rounded-2xl border border-(--line) bg-(--surface) p-8 shadow-2xl">
        <p className="accent mb-3 font-mono text-xs tracking-widest">◆ 复述检查点</p>
        <h3 className="mb-6 text-lg leading-relaxed">{question}</h3>
        <p className="muted mb-8 text-sm leading-relaxed">
          课堂已暂停。用你自己的话复述一遍（现在可以在心里或出声说，T6
          将接入 AI 批改），确认能说清后继续。
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onPass}
            className="rounded-full bg-(--accent) px-6 py-2 font-medium text-(--bg)"
          >
            我复述完了，继续 →
          </button>
        </div>
      </div>
    </div>
  );
}
