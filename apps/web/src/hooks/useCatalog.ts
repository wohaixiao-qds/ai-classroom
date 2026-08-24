/** 课表数据共享 hook:学习台/生成中心共用一份 /catalog 拉取、动作提交、跑批轮询。 */
import { useCallback, useEffect, useState } from "react";
import type { ActionKind, Catalog } from "../types/catalog";

export function useCatalog() {
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
        setErr(null);
      })
      .catch((e: unknown) => setErr(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const anyRunning =
    cat?.notes.some((n) => n.status === "running") || cat?.todo.some((t) => t.status === "running");

  // 有任务在跑时轮询刷新(备课/调研是分钟级后台任务)
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [anyRunning, load]);

  const act = useCallback(
    async (kind: ActionKind, target: string, label: string) => {
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
      load();
    },
    [load],
  );

  return { cat, err, act, load };
}
