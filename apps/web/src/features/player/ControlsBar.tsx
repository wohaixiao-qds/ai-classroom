import { LayoutGrid, Pause, Play, RotateCcw } from "lucide-react";

import { Kbd } from "../../components/ui/kbd";
import { Slider } from "../../components/ui/slider";
import { Tooltip, TooltipContent, TooltipTrigger } from "../../components/ui/tooltip";
import { cn } from "../../lib/utils";
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
        className={cn(
          "mb-4 flex items-center gap-3 rounded-full border border-border bg-card/95 px-4 py-2 shadow-lg backdrop-blur transition-opacity",
          state.playing && "opacity-30 hover:opacity-100",
        )}
      >
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={toggle}
              aria-label={state.playing ? "暂停" : "播放"}
              className="flex size-9 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform outline-none hover:scale-105 focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-40"
              disabled={!ready}
            >
              {state.playing ? <Pause size={16} /> : <Play size={16} />}
            </button>
          </TooltipTrigger>
          <TooltipContent>
            {state.playing ? "暂停" : "播放"} <Kbd>空格</Kbd>
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={replayPage}
              className="flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
            >
              <RotateCcw size={13} /> 重讲
            </button>
          </TooltipTrigger>
          <TooltipContent>重讲本页</TooltipContent>
        </Tooltip>

        {/* 步进滑杆(A3):页内句级定位,拖动=画面亮到该句状态(停播) */}
        {sentences > 1 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-2">
                <Slider
                  value={[Math.min(state.sentence, sentences - 1)]}
                  max={sentences - 1}
                  step={1}
                  onValueChange={(v) => {
                    const s = v[0];
                    if (s !== undefined) seekSentence(s);
                  }}
                  className="w-28"
                  aria-label="页内句级定位"
                />
                <span className="font-mono text-xs text-muted-foreground">
                  {Math.min(state.sentence + 1, sentences)}/{sentences}
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent>拖动定位到某句(播放会从该句重念)</TooltipContent>
          </Tooltip>
        )}

        <span className="font-mono text-xs text-muted-foreground">
          {state.page + 1} / {totalPages}
        </span>

        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={onOverview}
              className="flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
            >
              <LayoutGrid size={13} /> 总览
            </button>
          </TooltipTrigger>
          <TooltipContent className="text-center">
            页总览 <Kbd>O</Kbd>
            <span className="mt-0.5 block text-[10px] text-muted-foreground">
              数字+回车跳页 · <Kbd>F</Kbd> 全屏
            </span>
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
