/** 生成中心(甲方案):「造课」的所有入口与状态集中一页。
 *  我想学(新主题)/ 能学的(笔记→备课)/ 任务动态(备课中/完成/失败)。
 *  框架审阅流(双源框架→挑子题)为下一步,先把生成管理归位。 */
import { useState } from "react";
import { Lane } from "../../components/Lane";
import { useCatalog } from "../../hooks/useCatalog";

export function StudioPage() {
  const { cat, err, act } = useCatalog();
  const [topic, setTopic] = useState("");

  if (err) return <div className="muted p-8 text-sm">加载失败:{err}</div>;
  if (!cat) return <div className="muted p-8 text-sm">加载中…</div>;

  // 任务动态:所有发起过生成的目标(notes + todo 含新主题),按状态分拣
  const jobs = [
    ...cat.todo.map((t) => ({ title: t.title, area: t.area, status: t.status, kind: "调研+备课" })),
    ...cat.notes
      .filter((n) => n.requested)
      .map((n) => ({ title: n.title, area: n.area, status: n.status, kind: "笔记备课" })),
  ];
  const running = jobs.filter((j) => j.status === "running");
  const finished = jobs.filter((j) => j.status !== "running");

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-8">
      <h1 className="text-2xl font-bold">生成中心</h1>

      <Lane emoji="🌱" title="我想学" count={0} hint="一句话开课:调研→备课→音频全自动,出炉进课程库">
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
            placeholder="新主题,如 MCP / RAG / 编译原理"
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
      </Lane>

      {running.length > 0 && (
        <Lane emoji="⏳" title="正在造" count={running.length} hint="分钟级后台任务,完成后自动进课程库">
          <ul className="space-y-2">
            {running.map((j, i) => (
              <li
                key={i}
                className="flex items-center gap-3 rounded-lg border border-(--accent)/40 bg-(--accent)/5 px-4 py-2 text-sm"
              >
                <span className="accent animate-pulse font-mono text-xs">⏳</span>
                <span className="flex-1 truncate">{j.title}</span>
                <span className="muted font-mono text-xs">{j.kind}</span>
              </li>
            ))}
          </ul>
        </Lane>
      )}

      <Lane emoji="📝" title="能学的" count={cat.notes.length} hint="有笔记未出课,点击请老师备课">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cat.notes.map((n) => (
            <button
              key={n.path}
              type="button"
              disabled={n.requested && n.status !== "failed"}
              onClick={() => void act("request_prep", n.path, n.title)}
              className="rounded-xl border border-(--line) bg-(--surface) p-4 text-left transition-colors hover:border-(--accent) disabled:opacity-60"
            >
              <p className="muted mb-1 font-mono text-xs">{n.area}</p>
              <p className="mb-1 font-medium">{n.title}</p>
              <p className="accent font-mono text-xs">
                {n.status === "running"
                  ? "⏳ 老师正在备课…"
                  : n.status === "done"
                    ? "✓ 已出课"
                    : n.status === "failed"
                      ? "⚠️ 失败,点此重试"
                      : n.requested
                        ? "✓ 已请求备课"
                        : "📝 请老师备课"}
              </p>
            </button>
          ))}
        </div>
      </Lane>

      {finished.length > 0 && (
        <Lane emoji="🗂" title="任务记录" count={finished.length} hint="近期发起过的生成">
          <ul className="space-y-1.5">
            {finished.map((j, i) => (
              <li
                key={i}
                className="flex items-center gap-3 rounded-lg border border-(--line) bg-(--surface) px-4 py-2 text-sm"
              >
                <span className="font-mono text-xs">
                  {j.status === "done" ? "✓" : j.status === "failed" ? "⚠️" : "·"}
                </span>
                <span className="flex-1 truncate">{j.title}</span>
                <span className="muted font-mono text-xs">
                  {j.status === "done" ? "已出课" : j.status === "failed" ? "失败" : "已请求"} ·{" "}
                  {j.kind}
                </span>
              </li>
            ))}
          </ul>
        </Lane>
      )}
    </div>
  );
}
