/** 课表页 · 学习指挥台(B1):四泳道竖排分区。
 *  在学的=已出课(点进课堂)/ 能学的=有笔记未出课(请备课,P2 入口)/
 *  想学的=待探清单(请调研,P3 入口)/ 刚冒出的=衍生候选(确认/忽略)。
 *  点击动作走 POST /catalog/action,只记意图(P2/P3 未建),完成后重取刷新。 */
import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ActionKind, Catalog } from "../../types/catalog";

const CARD = "rounded-xl border border-(--line) bg-(--surface) p-4 transition-colors";

function Lane({
  emoji,
  title,
  count,
  hint,
  children,
}: {
  emoji: string;
  title: string;
  count: number;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="text-lg font-medium">
          {emoji} {title}
        </h2>
        <span className="muted font-mono text-xs">{count}</span>
        <span className="muted text-xs">· {hint}</span>
      </div>
      {children}
    </section>
  );
}

export function CatalogPage() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    void fetch("/api/v1/catalog")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: Catalog) => {
        setCat(d);
        setErr(null); // 成功即清错:一次瞬时抖动不至于把已加载的课表永久卡在失败页
      })
      .catch((e: unknown) => setErr(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // M5:有任务在跑时轮询刷新(备课/调研是分钟级后台任务)
  const anyRunning =
    cat?.notes.some((n) => n.status === "running") || cat?.todo.some((t) => t.status === "running");
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [anyRunning, load]);

  async function act(kind: ActionKind, target: string, label: string) {
    try {
      const r = await fetch("/api/v1/catalog/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, target, label }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch (e: unknown) {
      setErr(`操作失败:${String(e)}`);
      return;
    }
    load(); // 重取,反映新状态
  }

  if (err) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <p className="muted text-sm">课表加载失败:{err}</p>
      </div>
    );
  }
  if (!cat) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <p className="muted text-sm">加载中…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-8">
      <h1 className="text-2xl font-bold">课表 · 学习指挥台</h1>

      <Lane emoji="✅" title="在学的" count={cat.learning.length} hint="已出课,点进课堂">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cat.learning.map((c) => (
            <Link key={c.id} to={`/c/${c.id}`} className={`${CARD} hover:border-(--accent)`}>
              <p className="accent mb-1 font-mono text-xs">✅ 可上课</p>
              <h3 className="mb-1 font-medium">{c.title}</h3>
              <p className="muted font-mono text-xs">
                {c.pages} 页 · {c.checkpoints} 检查点
              </p>
            </Link>
          ))}
        </div>
      </Lane>

      <Lane emoji="📝" title="能学的" count={cat.notes.length} hint="有笔记未出课,点击请备课(P2)">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cat.notes.map((n) => (
            <button
              key={n.path}
              type="button"
              disabled={n.requested && n.status !== "failed"}
              onClick={() => void act("request_prep", n.path, n.title)}
              className={`${CARD} text-left hover:border-(--accent) disabled:opacity-60`}
            >
              <span className="muted mb-1 block font-mono text-xs">{n.area}</span>
              <span className="mb-1 block font-medium">{n.title}</span>
              <span className="accent block font-mono text-xs">
                {n.status === "running"
                  ? "⏳ 老师正在备课…"
                  : n.status === "done"
                    ? "✓ 已出课,进「在学的」"
                    : n.status === "failed"
                      ? "⚠️ 备课失败,点此重试"
                      : n.requested
                        ? "✓ 已请求备课"
                        : "📝 请老师备课"}
              </span>
            </button>
          ))}
        </div>
      </Lane>

      <Lane emoji="⬜" title="想学的" count={cat.todo.length} hint="待探清单,点击请调研(P3)">
        <ul className="space-y-2">
          {cat.todo.map((t, i) => (
            <li
              key={`${t.area}::${t.title}::${i}`}
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
          <p className="muted text-sm">还没有——问到课件覆盖不了的地方时,会自动冒到这里。</p>
        ) : (
          <div className="space-y-2">
            {cat.sparks.map((s) => (
              <div
                key={s.key}
                className="rounded-lg border border-(--line) bg-(--surface) px-4 py-3"
              >
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
