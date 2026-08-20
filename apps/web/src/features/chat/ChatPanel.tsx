import { useRef, useState } from "react";
import type { Course } from "../../types/csl";
import type { usePlayback } from "../player/usePlayback";

interface Msg {
  role: "user" | "assistant";
  text: string;
  tools?: { name: string; args: Record<string, unknown> }[];
}

/** 右侧答疑对话区:提问自动暂停课件,SSE 收 tool_call/answer 事件 */
export function ChatPanel({
  course,
  playback,
}: {
  course: Course;
  playback: ReturnType<typeof usePlayback>;
}) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const currentPage = course.pages[playback.state.page]?.id ?? null;

  async function ask() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    playback.pause(); // 提问自动暂停课堂
    setBusy(true);
    try {
      const history = msgs.slice(-6).map((m) => ({ role: m.role, content: m.text }));
      const resp = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: course.id,
          current_page: currentPage,
          question: q,
          history,
        }),
      });
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      const assistant: Msg = { role: "assistant", text: "", tools: [] };
      setMsgs((m) => [...m, assistant]);
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split("\n\n");
        buf = events.pop() ?? "";
        for (const raw of events) {
          const type = /^event: (.+)$/m.exec(raw)?.[1];
          const data = JSON.parse(/^data: (.+)$/m.exec(raw)?.[1] ?? "{}");
          if (type === "tool_call") {
            assistant.tools?.push({ name: data.name, args: data.args });
            setMsgs((m) => [...m]);
          } else if (type === "answer") {
            assistant.text = data.text;
            setMsgs((m) => [...m]);
          } else if (type === "error") {
            assistant.text = `⚠️ ${data.message}`;
            setMsgs((m) => [...m]);
          }
        }
        scrollRef.current?.scrollTo({ top: 1e9 });
      }
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: `⚠️ 连接失败: ${e}` }]);
    }
    setBusy(false);
  }

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed top-4 right-4 z-50 rounded-full border border-(--line) bg-(--surface) px-4 py-2 text-sm shadow-lg"
      >
        💬 提问
      </button>
    );

  return (
    <div className="fixed top-4 right-4 bottom-20 z-50 flex w-96 max-w-[85vw] flex-col rounded-2xl border border-(--line) bg-(--surface) shadow-2xl">
      <div className="flex items-center justify-between border-b border-(--line) px-4 py-3">
        <span className="text-sm font-medium">AI 老师 · 答疑</span>
        <div className="flex gap-2">
          {!playback.state.playing && (
            <button
              onClick={playback.play}
              className="rounded-full bg-(--accent) px-3 py-1 text-xs font-medium text-(--bg)"
            >
              ▶ 继续上课
            </button>
          )}
          <button onClick={() => setOpen(false)} className="muted px-2 text-sm">
            ✕
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {msgs.length === 0 && (
          <p className="muted text-sm leading-relaxed">
            随时提问——课件内的直接讲,课件外的会联网查,学过的会翻你笔记。
          </p>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : ""}>
            {m.tools && m.tools.length > 0 && (
              <div className="mb-1 space-y-0.5">
                {m.tools.map((t, j) => (
                  <p key={j} className="muted font-mono text-xs">
                    🔍 {t.name}({String(Object.values(t.args)[0])})
                  </p>
                ))}
              </div>
            )}
            <p
              className={
                m.role === "user"
                  ? "inline-block max-w-[85%] rounded-lg bg-(--accent)/20 px-3 py-2 text-left text-sm"
                  : "text-sm leading-relaxed"
              }
            >
              {m.text || (busy && i === msgs.length - 1 ? "思考中…" : "")}
            </p>
          </div>
        ))}
      </div>

      <div className="flex gap-2 border-t border-(--line) p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="例如:汽车类比再讲一遍"
          className="flex-1 rounded-lg border border-(--line) bg-(--bg) px-3 py-2 text-sm outline-none focus:border-(--accent)"
        />
        <button
          onClick={ask}
          disabled={busy || !input.trim()}
          className="rounded-lg bg-(--accent) px-4 text-sm font-medium text-(--bg) disabled:opacity-40"
        >
          发送
        </button>
      </div>
    </div>
  );
}
