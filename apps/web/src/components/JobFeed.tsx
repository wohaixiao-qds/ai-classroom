import { useEffect, useRef, useState } from "react";

import { cn } from "../lib/utils";

type JobKind = "request_prep" | "request_research" | "outline_prep";

/** 后台任务实时 feed:2s 轮询 /api/v1/jobs/log 尾部,亮出 agent 循环的阶段消息
 *  (submit_plan 规划 / init_course 建骨架 / write_section 逐节写 / validate_csl 终验)。
 *  active=false 时停止轮询但保留最后一屏(失败回看原因用);新到的行 anim-rise 浮入。 */
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
  const [freshFrom, setFreshFrom] = useState(0); // 本次刷新新到的行起点(做浮入动画)
  const [exists, setExists] = useState(true);
  const prevLenRef = useRef(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      void fetch(`/api/v1/jobs/log?kind=${kind}&target=${encodeURIComponent(target)}`)
        .then((r) => r.json())
        .then((d: { exists?: boolean; lines?: string[] }) => {
          if (!alive) return;
          const next = d.lines ?? [];
          setFreshFrom(prevLenRef.current);
          prevLenRef.current = next.length;
          setExists(d.exists ?? false);
          setLines(next);
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

  // 新输出滚到底部
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [lines]);

  return (
    <div
      ref={boxRef}
      className={cn(
        "max-h-44 overflow-y-auto rounded-lg border border-border bg-background/70 px-3 py-2 font-mono text-[11px] leading-5",
        className,
      )}
    >
      {lines.length === 0 ? (
        <p className="text-muted-foreground">{exists ? "等第一行输出…" : "还没有这次任务的日志"}</p>
      ) : (
        lines.map((l, i) => (
          <p key={`${i}-${l.slice(0, 12)}`} className={cn(lineTone(l), i >= freshFrom && "anim-rise")}>
            {l}
          </p>
        ))
      )}
    </div>
  );
}

/** 阶段标记着色:规划/建骨架/终验=品牌色,逐节写=正文色,失败=红,警告=黄 */
function lineTone(line: string): string {
  if (line.includes("FAILED") || line.includes("Traceback")) return "text-destructive";
  if (/^\s*\[(submit_plan|init_course|validate_csl)\]/.test(line) || line.includes("✅"))
    return "text-primary";
  if (/^\s*\[(write_section|research)/.test(line)) return "text-foreground/90";
  if (line.trim().startsWith("⚠")) return "text-warning";
  return "text-muted-foreground";
}
