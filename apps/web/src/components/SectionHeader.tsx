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
    <div className={cn("mb-3 flex items-center gap-2", className)}>
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-secondary text-primary">
        <Icon size={15} />
      </span>
      <h2 className="text-base font-semibold tracking-wide">{title}</h2>
      {count !== undefined && (
        <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-xs text-muted-foreground">
          {count}
        </span>
      )}
      {hint && <span className="truncate text-xs text-muted-foreground">· {hint}</span>}
    </div>
  );
}
