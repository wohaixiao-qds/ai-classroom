import { useCallback, useEffect, useRef, useState } from "react";
import Reveal from "reveal.js";
import type { RevealApi } from "reveal.js";
import type { Course } from "../../types/csl";
import { SlidePage } from "./pages";
import { ControlsBar } from "./ControlsBar";
import { CheckpointOverlay } from "./CheckpointOverlay";
import { SubtitleBar } from "./SubtitleBar";
import { ChatPanel } from "../chat/ChatPanel";
import { usePlayback } from "./usePlayback";

/** reveal.js 只负责翻页与 fragment 步进;React 负责 DOM 渲染;
 * usePlayback 负责节奏(音频 ended → 步进/翻页/检查点)。 */
export function SlideDeck({ course }: { course: Course }) {
  const [ready, setReady] = useState(false);
  const deckEl = useRef<HTMLDivElement>(null);
  const deckRef = useRef<RevealApi | null>(null);
  // 稳定的 deck 取值器:引用不变,避免下游 useEffect 依赖抖动导致重渲染循环
  const getDeck = useCallback(() => deckRef.current, []);
  const playback = usePlayback(course, getDeck);

  useEffect(() => {
    if (!deckEl.current) return;
    const deck = new Reveal(deckEl.current, {
      hash: false, // 节奏权交给播放引擎,不用 hash 记页
      controls: false, // 控制统一到底部控制条
      progress: true,
      keyboard: { 32: () => {}, 78: () => {}, 80: () => {} }, // 方向键仍可用;空格/N/P 交给播放引擎
    });
    deckRef.current = deck;
    void deck.initialize().then(() => setReady(true));

    // 空格 = 播放/暂停
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        e.preventDefault();
        playback.toggle();
      }
    };
    document.addEventListener("keydown", onKey);

    // 手动翻页(键盘) → 同步引擎状态
    const onSlide = (e: Event) => playback.gotoPage((e as unknown as { indexh: number }).indexh);
    deck.on("slidechanged", onSlide);
    return () => {
      document.removeEventListener("keydown", onKey);
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
      <SubtitleBar course={course} playback={playback} />
      <ChatPanel course={course} playback={playback} />
      <ControlsBar
        playback={playback}
        totalPages={course.pages.length}
        ready={ready}
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
