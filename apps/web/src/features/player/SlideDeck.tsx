import { useEffect, useRef } from "react";
import Reveal from "reveal.js";
import type { Course } from "../../types/csl";
import { SlidePage } from "./pages";

/** reveal.js 只负责翻页与 fragment 步进;React 负责 DOM 渲染。
 * 挂载后 init,卸载前 destroy——两者只在生命周期钩子握手。 */
export function SlideDeck({ course }: { course: Course }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const deck = new Reveal(ref.current, {
      hash: true,
      controls: true,
      progress: true,
      keyboard: true,
    });
    void deck.initialize();
    return () => {
      void deck.destroy();
    };
  }, []);

  return (
    <div className="reveal" ref={ref}>
      <div className="slides">
        {course.pages.map((p) => (
          <SlidePage key={p.id} page={p} />
        ))}
      </div>
    </div>
  );
}
