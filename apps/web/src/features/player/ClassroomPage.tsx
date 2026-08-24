import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { RevealApi } from "reveal.js";
import { ChatPanel } from "../chat/ChatPanel";
import { PageSidebar } from "./PageSidebar";
import { SlideDeck } from "./SlideDeck";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { usePlayback } from "./usePlayback";
import type { Course } from "../../types/csl";

/** 课堂页(沉浸):左课件 + 右答疑,仅留极简返回入口 */
export function ClassroomPage() {
  const { courseId = "harness-01" } = useParams();
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deckRef = useRef<RevealApi | null>(null);
  // 稳定取值器:避免 usePlayback 依赖抖动(历史教训:曾致重渲染死循环)
  const getDeck = useCallback(() => deckRef.current, []);

  useEffect(() => {
    setCourse(null);
    setError(null);
    fetch(`/courses/${courseId}.csl.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Course>;
      })
      .then(setCourse)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [courseId]);

  if (error)
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="muted">课件加载失败: {error}</p>
        <Link to="/" className="accent text-sm underline">
          ← 返回课表
        </Link>
      </div>
    );
  if (!course)
    return <div className="muted flex h-full items-center justify-center">课件加载中…</div>;

  return (
    <Classroom
      course={course}
      getDeck={getDeck}
      onDeck={(d) => {
        deckRef.current = d;
      }}
    />
  );
}

/** 课件加载后挂载:播放引擎在顶层,左导航+课件+对话共享同一节奏源 */
function Classroom({
  course,
  getDeck,
  onDeck,
}: {
  course: Course;
  getDeck: () => RevealApi | null;
  onDeck: (d: RevealApi | null) => void;
}) {
  const playback = usePlayback(course, getDeck);
  // 边栏折叠/拖宽改变 deck 宽度后,让 reveal 重新排版
  const relayout = useCallback(() => getDeck()?.layout(), [getDeck]);
  return (
    <div className="flex h-full">
      <PageSidebar course={course} playback={playback} onLayoutChange={relayout} />
      <div className="relative min-w-0 flex-1">
        <Link
          to="/"
          className="muted absolute top-4 left-4 z-50 rounded-full border border-(--line) bg-(--surface) px-3 py-1 text-xs hover:text-(--text)"
        >
          ← 课表
        </Link>
        <SlideDeck course={course} playback={playback} onDeck={onDeck} />
      </div>
      <div className="flex w-80 shrink-0 flex-col">
        <div className="flex justify-end border-b border-l border-(--line) bg-(--surface2) px-3 py-2">
          <ThemeSwitcher />
        </div>
        <ChatPanel course={course} playback={playback} />
      </div>
    </div>
  );
}
