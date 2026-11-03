import { useEffect, useRef, useState } from "react";

/** 数字滚动:rAF ease-out 从当前值滑到新值;系统开「减少动态效果」时直达终值。
 *  target 为 null(加载中/非数值)时返回 null,由调用方决定展示原值。 */
export function useCountUp(target: number | null): number | null {
  const [display, setDisplay] = useState<number | null>(target);
  const shownRef = useRef(0); // 最新帧值(换目标续跑/卸载落位的基准)

  useEffect(() => {
    if (target === null) {
      setDisplay(null);
      return;
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      shownRef.current = target;
      setDisplay(target);
      return;
    }
    const from = shownRef.current;
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / 600);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = from + (target - from) * eased;
      shownRef.current = v;
      setDisplay(v);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  return display;
}
