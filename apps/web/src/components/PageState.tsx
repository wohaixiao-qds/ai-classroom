import type { LucideIcon } from "lucide-react";
import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/utils";
import { Button } from "./ui/button";

/** 页面级加载态(骨架占位,避免布局跳动) */
export function PageLoading({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
      <LoaderCircle size={15} className="animate-spin" />
      {label}
    </div>
  );
}

/** 页面级错误态(可带重试) */
export function PageError({
  message,
  onRetry,
  back,
}: {
  message: string;
  onRetry?: () => void;
  back?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <p className="text-sm text-destructive">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          重试
        </Button>
      )}
      {back}
    </div>
  );
}

/** 空态:图标 + 一句话说明 + 可选动作区 */
export function EmptyState({
  icon: Icon,
  title,
  hint,
  children,
  className,
}: {
  icon: LucideIcon;
  title: string;
  hint?: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center",
        className,
      )}
    >
      <Icon size={20} className="text-muted-foreground/60" />
      <p className="text-sm text-foreground/80">{title}</p>
      {hint && <p className="max-w-md text-xs leading-relaxed text-muted-foreground">{hint}</p>}
      {children}
    </div>
  );
}
