/** 学习台(甲方案):继续学 + 快捷开课 + 推荐(想学的/刚冒出的)。
 *  「在学什么」的首页;课程全量在课程库,生成管理在生成中心。 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { Lane } from "../../components/Lane";
import { useCatalog } from "../../hooks/useCatalog";

/** 读本地断点(与播放引擎同 key):学习台展示「上次学到第N页」 */
function progressOf(courseId: string): { p: number } | null {
  try {
    const raw = localStorage.getItem(`classroom-progress-${courseId}`);
    return raw ? (JSON.parse(raw) as { p: number }) : null;
  } catch {
    return null;
  }
}

export function HomePage() {
  const { cat, err, act } = useCatalog();
  const [topic, setTopic] = useState("");

  if (err) return <div className="muted p-8 text-sm">加载失败:{err}</div>;
  if (!cat) return <div className="muted p-8 text-sm">加载中…</div>;

  const learning = cat.learning.map((c) => ({ ...c, prog: progressOf(c.id) }));
  const continuing = learning.filter((c) => c.prog && c.prog.p > 0);

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-8">
      <h1 className="text-2xl font-bold">学习台</h1>

      {/* 快捷开课:新主题一句话 → 生成中心接手(调研+备课+音频一条龙) */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = topic.trim();
          if (!t) return;
          setTopic("");
          void act("request_research", t, t);
        }}
        className="flex gap-2"
      >
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="我想学…(新主题,如 MCP / RAG / 编译原理)"
          className="flex-1 rounded-lg border border-(--line) bg-(--bg) px-3 py-2 text-sm outline-none focus:border-(--accent)"
        />
        <button
          type="submit"
          disabled={!topic.trim()}
          className="rounded-lg bg-(--accent) px-4 text-sm font-medium text-(--bg) disabled:opacity-40"
        >
          开课
        </button>
      </form>

      <Lane emoji="📖" title="继续学" count={continuing.length} hint="从上次的断点接着学">
        {continuing.length ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {continuing.map((c) => (
              <Link
                key={c.id}
                to={`/c/${c.id}`}
                className="rounded-xl border border-(--line) bg-(--surface) p-4 transition-colors hover:border-(--accent)"
              >
                <p className="accent mb-1 font-mono text-xs">▶ 接着学 · 第 {c.prog!.p + 1} 页</p>
                <h3 className="mb-1 font-medium">{c.title}</h3>
                <p className="muted font-mono text-xs">
                  {c.pages} 页 · {c.checkpoints} 检查点
                </p>
              </Link>
            ))}
          </div>
        ) : (
          <p className="muted text-sm">
            还没有进行中的课——去
            <Link to="/courses" className="accent underline">
              课程库
            </Link>
            挑一门,或上面输入新主题开课
          </p>
        )}
      </Lane>

      <Lane emoji="⬜" title="想学的" count={cat.todo.length} hint="待探清单,点「调研」自动出课">
        <ul className="space-y-2">
          {cat.todo.map((t, i) => (
            <li
              key={`${t.title}::${i}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-(--line) bg-(--surface) px-4 py-2"
            >
              <div className="min-w-0">
                <span className="text-sm">{t.title}</span>
                {t.hint && <span className="muted ml-2 text-xs">{t.hint}</span>}
                <span className="muted ml-2 font-mono text-xs opacity-60">{t.area}</span>
              </div>
              <button
                type="button"
                disabled={t.requested && t.status !== "failed"}
                onClick={() => void act("request_research", t.title, t.title)}
                className="accent shrink-0 text-xs disabled:opacity-60"
              >
                {t.status === "running"
                  ? "⏳ 调研备课中…"
                  : t.status === "done"
                    ? "✓ 已出课"
                    : t.status === "failed"
                      ? "⚠️ 重试"
                      : t.requested
                        ? "✓ 已请求"
                        : "调研"}
              </button>
            </li>
          ))}
        </ul>
      </Lane>

      <Lane emoji="💡" title="刚冒出的" count={cat.sparks.length} hint="课件答不了的问题 = 衍生候选">
        {cat.sparks.length === 0 ? (
          <p className="muted text-sm">还没有——上课问到课件覆盖不了的地方时,会自动冒到这里。</p>
        ) : (
          <div className="space-y-2">
            {cat.sparks.map((s) => (
              <div key={s.key} className="rounded-lg border border-(--line) bg-(--surface) px-4 py-3">
                <p className="mb-1 text-sm">{s.question}</p>
                {s.detail && <p className="muted mb-2 font-mono text-xs">🔍 {s.detail}</p>}
                {s.confirmed ? (
                  <span className="accent text-xs">✓ 已确认值得学</span>
                ) : (
                  <div className="flex gap-4">
                    <button
                      type="button"
                      onClick={() => void act("confirm_spark", s.key, s.question)}
                      className="accent text-xs"
                    >
                      确认值得学
                    </button>
                    <button
                      type="button"
                      onClick={() => void act("dismiss_spark", s.key, s.question)}
                      className="muted text-xs hover:text-(--text)"
                    >
                      忽略
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Lane>
    </div>
  );
}
