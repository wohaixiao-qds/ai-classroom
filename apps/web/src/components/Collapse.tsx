import type { ReactNode } from "react";

import { cn } from "../lib/utils";

/** 折叠展开:grid-rows 0fr→1fr 过渡(内容高度自适应,子元素保持挂载不丢状态)。
 *  替代 `{open && <div>}` 条件渲染硬弹;reduced-motion 下全局归零块自动接管。 */
export function Collapse({
  open,
  children,
  className,
}: {
  open: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid transition-[grid-template-rows] duration-(--dur-med) ease-out",
        open ? "[grid-template-rows:1fr]" : "[grid-template-rows:0fr]",
        className,
      )}
    >
      <div className="min-h-0 overflow-hidden" inert={!open}>{children}</div>
    </div>
  );
}
