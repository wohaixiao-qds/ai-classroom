import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "../lib/utils";

type JobKind = "request_prep" | "request_research" | "outline_prep";

/** 后台任务实时 feed:一个盒子装下模型全程干活的过程——
 *  顶部不确定进度光条(进行中)+「思考中」等待态(带秒数)+阶段消息逐行浮入
 *  (submit_plan 规划 / init_course 建骨架 / write_section 逐节写 / validate_csl 终验)。
 *  2s 轮询 /api/v1/jobs/log;active=false 停轮询保留末屏(失败回看原因用)。 */
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
  const [elapsed, setElapsed] = useState(0); // 本轮任务已等待秒数(挂载起算,纯观感)
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

  // 等待计时:第一段 LLM 调用可能几分钟,让「没输出」也有时间感
  useEffect(() => {
    if (!active) return;
    const t0 = Date.now();
    setElapsed(0);
    const t = window.setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [active, target]);

  // 新输出滚到底部
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [lines]);

  return (
    /* 单一表面:进度光条贴在盒顶,滚动区在下——进度/思考/输出不散在卡片各处 */
    <div className={cn("overflow-hidden rounded-lg border border-border", className)}>
      {active && <div className="anim-progress h-1 rounded-t-lg" />}
      <div
        ref={boxRef}
        className="max-h-56 min-h-[72px] overflow-y-auto bg-background/60 pl-3 pr-5 py-2 font-mono text-[11px] leading-5"
      >
        {lines.length === 0 ? (
          active ? (
            <p className="flex items-center gap-1.5 text-muted-foreground">
              <LoaderCircle size={12} className="shrink-0 animate-spin text-primary" />
              模型思考中(规划/调研),第一批输出马上来
              <span className="ml-auto tabular-nums">{elapsed}s</span>
            </p>
          ) : (
            <p className="text-muted-foreground">还没有这次任务的日志</p>
          )
        ) : (
          lines.map((l, i) => (
            <p
              key={`${i}-${l.slice(0, 12)}`}
              className={cn(lineTone(l), i >= freshFrom && "anim-rise")}
            >
              {l}
            </p>
          ))
        )}
      </div>
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
