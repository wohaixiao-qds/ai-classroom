import type { Course } from "../../types/csl";
import type { usePlayback } from "./usePlayback";

/** 字幕栏:显示当前朗读的讲稿句(音频暂停时隐藏) */
export function SubtitleBar({
  course,
  playback,
}: {
  course: Course;
  playback: ReturnType<typeof usePlayback>;
}) {
  const { playing, page, sentence } = playback.state;
  if (!playing) return null;
  const text = course.pages[page]?.script[sentence]?.text;
  if (!text) return null;
  return (
    <div className="pointer-events-none fixed bottom-20 left-1/2 z-40 w-fit max-w-[80vw] -translate-x-1/2">
      <p className="rounded-lg border border-(--line) bg-black/70 px-5 py-2.5 text-center text-base leading-relaxed text-(--text) shadow-lg backdrop-blur-sm">
        {text}
      </p>
    </div>
  );
}
