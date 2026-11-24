import type { LucideIcon } from "lucide-react";

import { cn } from "../lib/utils";

/** 分区标题条(全站统一):三段式(design/library.html .sec)——
 *  图标+标题 | 渐隐细线 | mono 右注;hint 一句提示独立一行在细线下方 */
export function SectionHeader({
  icon: Icon,
  title,
  count,
  hint,
  className,
}: {
  icon: LucideIcon;
  title: string;
  count?: number;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("mb-4 flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      <Icon size={15} className="shrink-0 text-(--text-faint)" aria-hidden="true" />
      <h2 className="text-base font-bold tracking-wide">{title}</h2>
      <span
        aria-hidden="true"
        className="h-px min-w-8 flex-1 bg-[linear-gradient(90deg,var(--line),transparent)]"
      />
      {count !== undefined && <span className="font-mono text-xs text-(--text-faint)">{count}</span>}
      {hint && <p className="w-full text-sm leading-relaxed text-muted-foreground">{hint}</p>}
    </div>
  );
}
