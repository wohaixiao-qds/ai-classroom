import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import Markdown from "react-markdown";
import { Brain, ChevronRight, History, MessageCircleQuestion, Plus, Search, Send } from "lucide-react";
import type { components } from "../../types/api.gen";
import type { Course, CourseV2 } from "../../types/csl";
import { normalizeBold } from "../../utils/md";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";

/** 对进度源的最小结构依赖:幻灯片(usePlayback)与书页(滚动 spy)各给一个适配器。
 *  不再 import usePlayback 类型——reader 形态不该反向依赖播放器。 */
export interface ProgressLike {
  state: { page: number };
  jumpToPage: (n: number) => void;
}

/** 答疑种子:带上下文自动发送。两类来源——批改联动(带检查点)/划词提问(纯文本) */
export interface ChatSeed {
  text: string;
  checkpoint?: {
    question: string;
    pass_rule: string | null;
    answer: string;
    verdict: string;
  };
}

interface Msg {
  role: "user" | "assistant";
  text: string;
  thinking?: string; // 思考过程(流式实时拼;不落会话历史,刷新后不回放)
  tools?: { name: string; args: Record<string, unknown> }[];
}

/** 会话类型从 OpenAPI 生成产物派生(边界铁律 2),不再手抄 */
type SessionInfo = components["schemas"]["SessionInfo"];
type SessionTurn = components["schemas"]["SessionTurn"];

/** 裸 URL → 可点链接(模型常直接甩地址而不写 markdown 链接语法)。
 *  字符集排除 CJK 与全角标点——「详情见 https://a.b/x。」止于 x,中文不粘进链接;
 *  尾部 ASCII 右括号仅在不成对时修剪(Wikipedia 路径括号是合法 URL 字符)。 */
const URL_RE = /https?:\/\/[^\s<>`"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+/gi;

function linkifyUrls(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(URL_RE)) {
    let url = m[0];
    while (/[.,;:!?]$/.test(url)) url = url.slice(0, -1);
    const opens = (url.match(/\(/g) ?? []).length;
    const closes = (url.match(/\)/g) ?? []).length;
    while (closes > opens && url.endsWith(")")) url = url.slice(0, -1);
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(
      <a
        key={`${keyBase}-u${i}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={url}
      >
        {url}
      </a>,
    );
    last = m.index + url.length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** 思考过程块(仿 ZCode):思考流式期间自动展开跟着长,答案文本开始落就自动
 *  折叠成一行,随时点开回看。仅当轮可看——不落会话历史,与工具调用同待遇。
 *  open 态用 manual ?? !settled 派生(不走 effect 折叠),用户手动开合优先于自动。 */
function ThinkingBlock({ text, settled }: { text: string; settled: boolean }) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? !settled;
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) boxRef.current?.scrollTo({ top: 1e9 }); // 思考跟着流滚底
  }, [text, open]);
  return (
    <div className="mb-1">
      <button
        type="button"
        onClick={() => setManual(!open)}
        aria-expanded={open}
        className="flex items-center gap-1 text-xs text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
      >
        {settled ? (
          <Brain size={12} />
        ) : (
          <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
        )}
        {settled ? "思考过程" : "思考中"}
        <ChevronRight size={12} className={cn("transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div
          ref={boxRef}
          className="mt-1 max-h-44 overflow-y-auto whitespace-pre-wrap break-words border-border border-l-2 pl-2 text-xs leading-relaxed text-muted-foreground"
        >
          {text}
        </div>
      )}
    </div>
  );
}

/** 右侧答疑对话区。
 *  记忆归后端(SQLite):本组件只持 session_id,不再自己攒历史递给后端。
 *  与播放解耦:只读 currentPage 让回答贴进度,不控制暂停/续播。 */
export function ChatPanel({
  course,
  playback,
  seed,
  onSeedConsumed,
  selectionAsk,
}: {
  course: Course | CourseV2;
  playback: ProgressLike;
  seed?: ChatSeed | null;
  onSeedConsumed?: () => void;
  /** 划词提问的面板内入口(防系统悬浮窗遮盖浮钮):最近一次课件选词+发送回调 */
  selectionAsk?: { text: string; onAsk: () => void } | null;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [showList, setShowList] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true); // 用户在底部附近才自动跟随;主动上翻阅读时不拽人

  const units = "pages" in course ? course.pages : course.sections;
  const currentPage = units[playback.state.page]?.id ?? null;

  // 批改→答疑联动:种子到达即自动发送(正忙则稍后重试)
  useEffect(() => {
    if (!seed) return;
    const t = window.setInterval(() => {
      if (!busy) {
        window.clearInterval(t);
        onSeedConsumed?.();
        void ask(seed.text, seed.checkpoint);
      }
    }, 1000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);
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
          if (seg) out.push(...linkifyUrls(seg, `${k}-${j}`));
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
              className="text-primary underline decoration-dotted outline-none hover:decoration-solid focus-visible:ring-[3px] focus-visible:ring-ring/40"
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
    a: ({ children, href }: { children?: ReactNode; href?: string }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
  };

  // 贴底跟随:在渲染提交后滚(DOM 已含最新流式文本)。之前在 SSE 读循环里 scrollTo,
  // React 还没提交新 DOM,滚的是旧高度,永远慢一拍(用户报:发完要手动再滚一次)
  useEffect(() => {
    if (stickRef.current) scrollRef.current?.scrollTo({ top: 1e9 });
  }, [msgs]);

  // 恢复上次会话(刷新不丢对话)
  useEffect(() => {
    const saved = localStorage.getItem(sessionKey);
    if (!saved) return;
    setSessionId(saved);
    void fetch(`/api/v1/sessions/${saved}`)
      .then((r) => r.json())
      .then((d: { turns: SessionTurn[] }) => {
        stickRef.current = true;
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
    stickRef.current = true;
    setMsgs((d.turns ?? []).map((t) => ({ role: t.role as Msg["role"], text: t.content })));
  }

  function newSession() {
    setShowList(false);
    setSessionId(null);
    localStorage.removeItem(sessionKey);
    stickRef.current = true;
    setMsgs([]);
  }

  function stop() {
    abortRef.current?.abort();
    setMsgs((m) => [
      ...m,
      { role: "assistant", text: "(已停止生成——已生成的部分保留在会话里,继续追问即可)" },
    ]);
  }

  async function ask(override?: string, checkpoint?: ChatSeed["checkpoint"]) {
    const q = (override ?? input).trim();
    if (!q || busy) return;
    if (!override) setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      const ac = new AbortController();
      abortRef.current = ac;
      const resp = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: course.id,
          current_page: currentPage,
          question: q,
          session_id: sessionId,
          checkpoint: checkpoint ?? null,
        }),
        signal: ac.signal,
      });
      if (!resp.ok || !resp.body) {
        // 后端 4xx/5xx 不再静默空泡——把错误亮给学员
        const detail = await resp.text().catch(() => "");
        setMsgs((m) => [
          ...m,
          {
            role: "assistant",
            text: "⚠️ 答疑服务异常(HTTP " + resp.status + "): " + (detail.slice(-200) || "请稍后重试"),
          },
        ]);
        setBusy(false);
        return;
      }
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let ended = false; // 收到 done 即完成——自评/落 trace 是服务端后台账,不等关流
      const assistant: Msg = { role: "assistant", text: "", tools: [] };
      setMsgs((m) => [...m, assistant]);
      while (reader && !ended) {
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
          } else if (type === "thinking") {
            assistant.thinking = (assistant.thinking ?? "") + data.text;
            setMsgs((m) => [...m]);
          } else if (type === "tool_call") {
            assistant.tools?.push({ name: data.name, args: data.args });
            setMsgs((m) => [...m]);
          } else if (type === "delta") {
            assistant.text += data.text; // 流式:逐段追加
            setMsgs((m) => [...m]);
          } else if (type === "error") {
            assistant.text = `⚠️ ${data.message}`;
            setMsgs((m) => [...m]);
          } else if (type === "done") {
            ended = true;
            break;
          }
        }
      }
      if (ended) void reader?.cancel().catch(() => {}); // 主动收尾:释放连接,不再读服务端余量
    } catch (e) {
      // 点停止的主动中止不算连接失败(stop 已给过提示),真网络错误才亮 ⚠️
      if ((e as Error)?.name !== "AbortError") {
        setMsgs((m) => [...m, { role: "assistant", text: `⚠️ 连接失败: ${e}` }]);
      }
    }
    setBusy(false);
  }

  return (
    <aside className="flex min-h-0 flex-1 flex-col border-l border-border bg-secondary/50">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-sm font-medium">AI 老师 · 答疑</span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => {
              setShowList(!showList);
              if (!showList) void loadSessions();
            }}
            title="历史对话"
          >
            <History size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={newSession} title="开一轮新对话">
            <Plus size={14} />
          </Button>
        </div>
      </div>

      {showList && (
        <div className="max-h-48 overflow-y-auto border-b border-border bg-background/60">
          {sessions.length === 0 && <p className="p-3 text-xs text-muted-foreground">还没有历史对话</p>}
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => void switchSession(s.id)}
              className={cn(
                "block w-full px-3 py-2 text-left text-xs transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/40",
                s.id === sessionId ? "text-primary" : "text-muted-foreground",
              )}
            >
              <span className="block truncate">{s.title ?? "(空对话)"}</span>
              <span className="font-mono opacity-60">
                {s.asks} 问 · {s.updated_at.slice(5, 16)}
              </span>
            </button>
          ))}
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={() => {
          const el = scrollRef.current;
          stickRef.current = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className="flex-1 space-y-3 overflow-y-auto overflow-x-hidden py-4 pl-4 pr-5"
      >
        {msgs.length === 0 && (
          <p className="text-sm leading-relaxed text-muted-foreground">
            随时提问——课件内的直接讲,课件外的会联网查,学过的会翻你笔记。
          </p>
        )}
        {msgs.map((m, i) => {
          const isLive = busy && i === msgs.length - 1; // 仅"正在生成中"的这条
          return (
            <div key={i} className={m.role === "user" ? "text-right" : ""}>
              {m.role === "assistant" && m.thinking && (
                <ThinkingBlock text={m.thinking} settled={!isLive || m.text.length > 0} />
              )}
              {/* 工具调用只在生成中实时展示,答完即隐藏,不留档 */}
              {isLive && m.tools && m.tools.length > 0 && (
                <div className="mb-1 space-y-0.5">
                  {m.tools.map((t, j) => (
                    <p key={j} className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                      <Search size={11} className="shrink-0" />
                      <span className="min-w-0 break-words">正在查:{String(Object.values(t.args)[0])}</span>
                    </p>
                  ))}
                </div>
              )}
              {m.role === "user" ? (
                <p className="inline-block max-w-[85%] rounded-lg rounded-br-sm bg-primary/15 px-3 py-2 text-left text-sm break-words">
                  {m.text}
                </p>
              ) : (
                <div className="chat-md text-sm leading-relaxed">
                  {m.text ? (
                    <Markdown components={mdComponents}>{normalizeBold(m.text)}</Markdown>
                  ) : isLive && !m.thinking ? (
                    <span className="text-muted-foreground">思考中…</span>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 划词提问提示条:页面内入口,系统悬浮窗遮不住;点「解释一下」即发送。
          data-sel-ask:mouseup 清理守卫识别自身,防 click 落空 */}
      {selectionAsk && (
        <div data-sel-ask className="flex items-center gap-2 border-t border-primary/30 bg-primary/5 px-3 py-2">
          <MessageCircleQuestion size={14} className="shrink-0 text-primary" />
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            选中了「{selectionAsk.text}」
          </span>
          <Button variant="secondary" size="sm" className="shrink-0" onClick={selectionAsk.onAsk}>
            解释一下
          </Button>
        </div>
      )}

      <div className="flex gap-2 border-t border-border p-3">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="例如:汽车类比再讲一遍"
        />
        {busy ? (
          <Button variant="outline" onClick={stop} title="停止生成">
            停止
          </Button>
        ) : (
          <Button onClick={() => void ask()} disabled={!input.trim()} title="发送">
            <Send size={14} />
            发送
          </Button>
        )}
      </div>
    </aside>
  );
}
