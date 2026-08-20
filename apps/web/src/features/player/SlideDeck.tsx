import { useEffect, useRef } from "react";
import Reveal from "reveal.js";
import type { RevealApi } from "reveal.js";
import type { Course } from "../../types/csl";
import { SlidePage } from "./pages";
import { ControlsBar } from "./ControlsBar";
import { CheckpointOverlay } from "./CheckpointOverlay";
import { usePlayback } from "./usePlayback";

/** reveal.js 只负责翻页与 fragment 步进;React 负责 DOM 渲染;
 * usePlayback 负责节奏(音频 ended → 步进/翻页/检查点)。 */
export function SlideDeck({ course }: { course: Course }) {
  const deckEl = useRef<HTMLDivElement>(null);
  const deckRef = useRef<RevealApi | null>(null);
  const playback = usePlayback(course, () => deckRef.current);

  useEffect(() => {
    if (!deckEl.current) return;
    const deck = new Reveal(deckEl.current, {
      hash: false, // 节奏权交给播放引擎,不用 hash 记页
      controls: false, // 控制统一到底部控制条
      progress: true,
      keyboard: true, // 方向键手动翻页仍可用
    });
    deckRef.current = deck;
    void deck.initialize();

    // 手动翻页(键盘) → 同步引擎状态
    const onSlide = (e: Event) => playback.gotoPage((e as unknown as { indexh: number }).indexh);
    deck.on("slidechanged", onSlide);
    return () => {
      deck.off("slidechanged", onSlide);
      void deck.destroy();
      deckRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deck 初始化仅一次
  }, []);

  return (
    <>
      <div className="reveal" ref={deckEl}>
        <div className="slides">
          {course.pages.map((p) => (
            <SlidePage key={p.id} page={p} />
          ))}
        </div>
      </div>
      <ControlsBar
        playback={playback}
        totalPages={course.pages.length}
        pageId={course.pages[playback.state.page]?.id}
      />
      {playback.state.checkpointOpen && (
        <CheckpointOverlay
          question={course.pages[playback.state.page].checkpoint?.question ?? ""}
          onPass={playback.passCheckpoint}
        />
      )}
    </>
  );
}
