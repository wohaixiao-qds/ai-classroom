import { LayoutGrid, Pause, Play, RotateCcw } from "lucide-react";
import type { usePlayback } from "./usePlayback";

/** 底部播放控制条:播放/重讲/步进滑杆/页码/总览入口。
 *  Slidev 式 hover 浮现:播放中半透明,鼠标靠近底部或暂停时全显。 */
export function ControlsBar({
  playback,
  totalPages,
  sentences,
  ready,
  onOverview,
}: {
  playback: ReturnType<typeof usePlayback>;
  totalPages: number;
  sentences: number;
  ready: boolean;
  onOverview: () => void;
}) {
  const { state, toggle, replayPage, seekSentence } = playback;
  return (
    <div className="fixed bottom-0 left-1/2 z-50 flex h-20 -translate-x-1/2 items-end justify-center">
      <div
        className={`mb-4 flex items-center gap-3 rounded-full border border-(--line) bg-(--surface) px-4 py-2 shadow-lg transition-opacity ${
          state.playing ? "opacity-30 hover:opacity-100" : "opacity-100"
        }`}
      >
        <button
          onClick={toggle}
          disabled:opacity-40
          className="flex h-9 w-9 items-center justify-center rounded-full bg-(--accent) text-(--bg) transition-transform hover:scale-105"
          title={state.playing ? "暂停(空格)" : "播放(空格)"}
          disabled={!ready}
        >
          {state.playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button
          onClick={replayPage}
          className="muted flex items-center gap-1 rounded-full px-2 py-1 text-xs hover:text-(--text)"
          title="重讲本页"
        >
          <RotateCcw size={13} /> 重讲
        </button>

        {/* 步进滑杆(A3):页内句级定位,拖动=画面亮到该句状态(停播) */}
        {sentences > 1 && (
          <div className="flex items-center gap-2" title="拖动定位到某句(播放会从该句重念)">
            <input
              type="range"
              min={0}
              max={sentences - 1}
              value={Math.min(state.sentence, sentences - 1)}
              onChange={(e) => seekSentence(Number(e.target.value))}
              className="w-28 accent-(--accent)"
            />
            <span className="muted font-mono text-xs">
              {Math.min(state.sentence + 1, sentences)}/{sentences}
            </span>
          </div>
        )}

        <span className="muted font-mono text-xs">
          {state.page + 1} / {totalPages}
        </span>
        <button
          onClick={onOverview}
          className="muted flex items-center gap-1 rounded-full px-2 py-1 text-xs hover:text-(--text)"
          title="页总览(o) · 也可敲数字+回车跳页 · f 全屏"
        >
          <LayoutGrid size={13} /> 总览
        </button>
      </div>
    </div>
  );
}
