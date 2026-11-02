import { CheckCircle2, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { KindIcon } from "../../components/KindIcon";
import { cn } from "../../lib/utils";
import type { Course } from "../../types/csl";
import type { usePlayback } from "./usePlayback";

export function PageSidebar({
  course,
  playback,
  onLayoutChange,
}: {
  course: Course;
  playback: ReturnType<typeof usePlayback>;
  onLayoutChange: () => void; // 折叠/拖宽后让 reveal 重新排版
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [width, setWidth] = useState(210);
  const dragRef = useRef<{ x: number; w: number } | null>(null);

  const toggleCollapse = useCallback(() => {
    setCollapsed((c) => !c);
    setTimeout(onLayoutChange, 360); // 等折叠动画完再重排 reveal
  }, [onLayoutChange]);

  // 右缘拖宽(pointer events;release 在 window 上兜底)
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (dragRef.current) {
        setWidth(Math.min(360, Math.max(150, dragRef.current.w + e.clientX - dragRef.current.x)));
      }
    };
    const onUp = () => {
      if (dragRef.current) {
        dragRef.current = null;
        onLayoutChange();
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [onLayoutChange]);

  if (collapsed) {
    return (
      <button
        onClick={toggleCollapse}
        title="展开页导航"
        className="flex w-10 shrink-0 flex-col items-center gap-2 border-r border-border bg-secondary/50 pt-4 text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
      >
        <PanelLeftOpen size={16} />
        <span className="font-mono text-xs [writing-mode:vertical-rl]">{course.pages.length}页</span>
      </button>
    );
  }

  return (
    <aside
      className="relative flex shrink-0 flex-col border-r border-border bg-secondary/50"
      style={{ width }}
    >
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">本课结构</span>
        <button
          onClick={toggleCollapse}
          title="收起"
          className="rounded p-1 text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
        >
          <PanelLeftClose size={15} />
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto px-2 pb-3">
        {course.pages.map((p, i) => {
          const cur = i === playback.state.page;
          return (
            <li key={p.id}>
              <button
                onClick={() => playback.jumpToPage(i)}
                className={cn(
                  "group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                  cur
                    ? "bg-primary/15 font-medium text-foreground ring-1 ring-primary/40"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <span className="font-mono opacity-60">{i + 1}</span>
                <span className="text-muted-foreground group-hover:text-foreground">
                  <KindIcon kind={p.content.kind} />
                </span>
                <span className="min-w-0 flex-1 truncate">{p.title || p.eyebrow || p.id}</span>
                {p.checkpoint && (
                  <span title="有检查点" className="shrink-0 text-primary">
                    <CheckCircle2 size={12} />
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {/* 右缘拖宽把手 */}
      <div
        onPointerDown={(e) => {
          dragRef.current = { x: e.clientX, w: width };
        }}
        className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize transition-colors hover:bg-primary/40"
        title="拖动调宽"
      />
    </aside>
  );
}
