import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import Markdown from "react-markdown";
import type { components } from "../../types/api.gen";
import type { Course } from "../../types/csl";
import type { usePlayback } from "../player/usePlayback";
import { normalizeBold } from "../../utils/md";

interface Msg {
  role: "user" | "assistant";
  text: string;
  tools?: { name: string; args: Record<string, unknown> }[];
}

/** 会话类型从 OpenAPI 生成产物派生(边界铁律 2),不再手抄 */
type SessionInfo = components["schemas"]["SessionInfo"];
type SessionTurn = components["schemas"]["SessionTurn"];

/** 右侧答疑对话区。
 *  记忆归后端(SQLite):本组件只持 session_id,不再自己攒历史递给后端。
 *  与播放解耦:只读 currentPage 让回答贴进度,不控制暂停/续播。 */
export function ChatPanel({
  course,
  playback,
}: {
  course: Course;
  playback: ReturnType<typeof usePlayback>;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [showList, setShowList] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const currentPage = course.pages[playback.state.page]?.id ?? null;
  const sessionKey = `classroom-session-${course.id}`;

  /** 把回答里的「课件第N页」变成可点按钮 → 跳到该页(A4)。
   *  支持多页连写:「课件第4页和第5页」「课件第4页、第5页」中每个页码都各自可点。 */
  const CITE_CLUSTER = /(课件第\s*\d+\s*页(?:[、,，和与及\s]*第\s*\d+\s*页)*)/g;

  const linkifyCitations = (nodes: ReactNode[]): ReactNode[] => {
    const out: ReactNode[] = [];
    nodes.forEach((node, k) => {
      if (typeof node !== "string") {
        out.push(node);
        return;
      }
      node.split(CITE_CLUSTER).forEach((seg, j) => {
        if (!/^课件第\s*\d+\s*页/.test(seg)) {
          if (seg) out.push(seg);
          return;
        }
        // seg 是引用簇(可能含多页):每个「第N页」切成按钮,「课件」「和」「、」留作文字
        const pageRe = /第\s*(\d+)\s*页/g;
        let last = 0;
        let i = 0;
        let m: RegExpExecArray | null = pageRe.exec(seg);
        while (m !== null) {
          if (m.index > last) out.push(seg.slice(last, m.index));
          const pageNo = Number(m[1]);
          out.push(
            <button
              key={`${k}-${j}-${i}`}
              type="button"
              onClick={() => playback.jumpToPage(pageNo - 1)}
              className="accent underline decoration-dotted hover:decoration-solid"
              title={`跳到第 ${pageNo} 页`}
            >
              {m[0]}
            </button>,
          );
          last = m.index + m[0].length;
          i += 1;
          m = pageRe.exec(seg);
        }
        if (last < seg.length) out.push(seg.slice(last));
      });
    });
    return out;
  };

  const mdComponents = {
    p: ({ children }: { children?: ReactNode }) => (
      <p>{linkifyCitations(Array.isArray(children) ? children : [children])}</p>
    ),
    li: ({ children }: { children?: ReactNode }) => (
      <li>{linkifyCitations(Array.isArray(children) ? children : [children])}</li>
    ),
  };

  // 恢复上次会话(刷新不丢对话)
  useEffect(() => {
    const saved = localStorage.getItem(sessionKey);
    if (!saved) return;
    setSessionId(saved);
    void fetch(`/api/v1/sessions/${saved}`)
      .then((r) => r.json())
      .then((d: { turns: SessionTurn[] }) => {
        setMsgs(
          (d.turns ?? []).map((t) => ({ role: t.role as Msg["role"], text: t.content })),
        );
      })
      .catch(() => localStorage.removeItem(sessionKey));
  }, [sessionKey]);

  async function loadSessions() {
    const d = (await fetch(`/api/v1/sessions?course_id=${course.id}`).then((r) => r.json())) as {
      sessions: SessionInfo[];
    };
    setSessions(d.sessions ?? []);
  }

  async function switchSession(id: string) {
    setShowList(false);
    setSessionId(id);
    localStorage.setItem(sessionKey, id);
    const d = (await fetch(`/api/v1/sessions/${id}`).then((r) => r.json())) as {
      turns: SessionTurn[];
    };
    setMsgs((d.turns ?? []).map((t) => ({ role: t.role as Msg["role"], text: t.content })));
  }

  function newSession() {
    setShowList(false);
    setSessionId(null);
    localStorage.removeItem(sessionKey);
    setMsgs([]);
  }

  async function ask() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      const resp = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: course.id,
          current_page: currentPage,
          question: q,
          session_id: sessionId,
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
          if (type === "session") {
            setSessionId(data.session_id);
            localStorage.setItem(sessionKey, data.session_id);
          } else if (type === "tool_call") {
            assistant.tools?.push({ name: data.name, args: data.args });
            setMsgs((m) => [...m]);
          } else if (type === "delta") {
            assistant.text += data.text; // 流式:逐段追加
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

  return (
    <aside className="flex min-h-0 flex-1 flex-col border-l border-(--line) bg-(--surface2)">
      <div className="flex items-center justify-between border-b border-(--line) px-4 py-3">
        <span className="text-sm font-medium">AI 老师 · 答疑</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => {
              setShowList(!showList);
              if (!showList) void loadSessions();
            }}
            className="muted rounded px-2 py-1 text-xs hover:text-(--text)"
            title="历史对话"
          >
            ☰
          </button>
          <button
            onClick={newSession}
            className="muted rounded px-2 py-1 text-xs hover:text-(--text)"
            title="开一轮新对话"
          >
            ＋
          </button>
        </div>
      </div>

      {showList && (
        <div className="max-h-48 overflow-y-auto border-b border-(--line) bg-(--bg)">
          {sessions.length === 0 && <p className="muted p-3 text-xs">还没有历史对话</p>}
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => void switchSession(s.id)}
              className={`block w-full px-3 py-2 text-left text-xs hover:bg-(--surface) ${
                s.id === sessionId ? "accent" : "muted"
              }`}
            >
              <span className="block truncate">{s.title ?? "(空对话)"}</span>
              <span className="font-mono opacity-60">
                {s.asks} 问 · {s.updated_at.slice(5, 16)}
              </span>
            </button>
          ))}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {msgs.length === 0 && (
          <p className="muted text-sm leading-relaxed">
            随时提问——课件内的直接讲,课件外的会联网查,学过的会翻你笔记。
          </p>
        )}
        {msgs.map((m, i) => {
          const isLive = busy && i === msgs.length - 1; // 仅"正在生成中"的这条
          return (
            <div key={i} className={m.role === "user" ? "text-right" : ""}>
              {/* 工具调用只在生成中作为"思考过程"实时展示,答完即隐藏,不留档 */}
              {isLive && m.tools && m.tools.length > 0 && (
                <div className="mb-1 space-y-0.5">
                  {m.tools.map((t, j) => (
                    <p key={j} className="muted font-mono text-xs">
                      🔍 正在查:{String(Object.values(t.args)[0])}
                    </p>
                  ))}
                </div>
              )}
              {m.role === "user" ? (
                <p className="inline-block max-w-[85%] rounded-lg bg-(--accent)/20 px-3 py-2 text-left text-sm">
                  {m.text}
                </p>
              ) : (
                <div className="chat-md text-sm leading-relaxed">
                  {m.text ? (
                    <Markdown components={mdComponents}>{normalizeBold(m.text)}</Markdown>
                  ) : isLive ? (
                    <span className="muted">思考中…</span>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
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
    </aside>
  );
}
