import * as React from "react";

import { cn } from "../../lib/utils";

/** 键位提示小方块(课堂页 o / f / 空格 等快捷键说明) */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "pointer-events-none inline-flex h-5 min-w-5 select-none items-center justify-center gap-1 rounded-sm border border-border bg-secondary px-1 font-mono text-[10px] font-medium text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Kbd };
