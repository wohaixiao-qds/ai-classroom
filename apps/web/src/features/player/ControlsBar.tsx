import type { usePlayback } from "./usePlayback";

/** 底部播放控制条:播放/暂停 + 重讲本页 + 页码(检查点在进度条上的菱形标记 T6 完善) */
export function ControlsBar({
  playback,
  totalPages,
}: {
  playback: ReturnType<typeof usePlayback>;
  totalPages: number;
  pageId?: string;
}) {
  const { state, toggle, replayPage } = playback;
  return (
    <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-full border border-(--line) bg-(--surface) px-4 py-2 shadow-lg">
      <button
        onClick={toggle}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-(--accent) text-(--bg) transition-transform hover:scale-105"
        title={state.playing ? "暂停(空格)" : "播放(空格)"}
      >
        {state.playing ? "⏸" : "▶"}
      </button>
      <button
        onClick={replayPage}
        className="muted rounded-full px-3 py-1 text-sm hover:text-(--text)"
        title="重讲本页"
      >
        ↺ 重讲
      </button>
      <span className="muted font-mono text-xs">
        {state.page + 1} / {totalPages}
      </span>
    </div>
  );
}
