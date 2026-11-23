import type { LucideIcon } from "lucide-react";

import { cn } from "../lib/utils";

/** 分区标题条(全站统一,替代 Lane/Eval Section/Library 三种写法):
 *  图标章 + 标题 + 计数徽章 + 一句提示 */
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
    <div className={cn("mb-3 flex flex-wrap items-center gap-x-2 gap-y-1", className)}>
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-secondary text-primary">
        <Icon size={15} aria-hidden="true" />
      </span>
      <h2 className="text-base font-semibold tracking-wide">{title}</h2>
      {count !== undefined && (
        <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-xs text-muted-foreground">
          {count}
        </span>
      )}
      {hint && <p className="basis-full text-sm leading-relaxed text-muted-foreground sm:basis-auto sm:flex-1">{hint}</p>}
    </div>
  );
}
