import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "../lib/utils";

type JobKind = "request_prep" | "request_research" | "outline_prep";

/** 后台任务状态条:单行动态替换——最新事件即当前状态(模型心跳/工具在飞/阶段完成),
 *  像终端的状态行一样原地改写,不堆历史。2s 轮询 /api/v1/jobs/log 尾部取最新行。
 *  active=false 停轮询保留末屏(失败回看原因用)。 */
export function JobFeed({
  kind,
  target,
  active,
  className,
}: {
  kind: JobKind;
  target: string;
  active: boolean;
  className?: string;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const [elapsed, setElapsed] = useState(0); // 本轮任务已等待秒数(挂载起算,纯观感)

  useEffect(() => {
    let alive = true;
    const tick = () => {
      void fetch(`/api/v1/jobs/log?kind=${kind}&target=${encodeURIComponent(target)}`)
        .then((r) => r.json())
        .then((d: { exists?: boolean; lines?: string[] }) => {
          if (alive) setLines(d.lines ?? []);
        })
        .catch(() => {});
    };
    tick();
    if (!active) return;
    const t = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [kind, target, active]);

  // 等待计时:第一段 LLM 调用可能几分钟,让「没输出」也有时间感
  useEffect(() => {
    if (!active) return;
    const t0 = Date.now();
    setElapsed(0);
    const t = window.setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [active, target]);

  // 当前状态 = 最新一行(⋯ 模型调用在飞 / ↳ 工具在飞 / 阶段完成 / DONE / FAILED)
  const current = lines.length ? lines[lines.length - 1] : null;

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border", className)}>
      {active && <div className="anim-progress h-1 rounded-t-lg" />}
      <div className="flex min-h-[34px] items-center gap-2 bg-background/60 py-2 pl-3 pr-3 font-mono text-[11px]">
        {active && <LoaderCircle size={12} className="shrink-0 animate-spin text-primary" />}
        {/* 单行动态替换:key 随内容变,新状态淡入-rise 原地改写 */}
        <p
          key={current ?? "empty"}
          title={current ?? undefined}
          className={cn(
            "min-w-0 flex-1 truncate",
            current ? lineTone(current) : "text-muted-foreground",
            "anim-rise",
          )}
        >
          {current ?? (active ? "模型思考中(规划/调研),第一批输出马上来" : "还没有这次任务的日志")}
        </p>
        {active && (
          <span className="shrink-0 tabular-nums text-muted-foreground">{elapsed}s</span>
        )}
      </div>
    </div>
  );
}

/** 状态行着色:规划/建骨架/终验=品牌色,逐节写/在飞工具=正文色,失败=红,警告=黄,心跳=微亮 */
function lineTone(line: string): string {
  if (line.includes("FAILED") || line.includes("Traceback")) return "text-destructive";
  if (/^\s*\[(submit_plan|init_course|validate_csl)\]/.test(line) || line.includes("✅"))
    return "text-primary";
  if (/^\s*\[(write_section|research)/.test(line) || line.trim().startsWith("↳"))
    return "text-foreground/90";
  if (line.startsWith("✓ 模型调用")) return "text-foreground/70";
  if (line.trim().startsWith("⚠")) return "text-warning";
  return "text-muted-foreground";
}
