import { useCallback, useEffect, useRef, useState } from "react";
import type { RevealApi } from "reveal.js";
import { ChatPanel } from "./features/chat/ChatPanel";
import { SlideDeck } from "./features/player/SlideDeck";
import { usePlayback } from "./features/player/usePlayback";
import type { Course } from "./types/csl";

const COURSE_URL = "/courses/harness-01.csl.json";

export default function App() {
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deckRef = useRef<RevealApi | null>(null);
  // 稳定取值器:避免 usePlayback 依赖抖动(历史教训:曾致重渲染死循环)
  const getDeck = useCallback(() => deckRef.current, []);

  useEffect(() => {
    fetch(COURSE_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Course>;
      })
      .then(setCourse)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error)
    return (
      <div className="flex h-full items-center justify-center">
        <p className="muted">
          课件加载失败: {error}（先运行 apps/scripts/sync-courses.sh）
        </p>
      </div>
    );
  if (!course)
    return <div className="flex h-full items-center justify-center muted">课件加载中…</div>;

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

/** 课件加载后挂载:播放引擎在顶层,左课件右对话共享同一节奏源 */
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
  return (
    <div className="flex h-full">
      <div className="relative min-w-0 flex-1">
        <SlideDeck course={course} playback={playback} onDeck={onDeck} />
      </div>
      <ChatPanel course={course} playback={playback} />
    </div>
  );
}
