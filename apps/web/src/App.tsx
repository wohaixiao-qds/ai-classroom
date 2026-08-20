import { useEffect, useState } from "react";
import { SlideDeck } from "./features/player/SlideDeck";
import { ThemeSwitcher } from "./features/player/ThemeSwitcher";
import type { Course } from "./types/csl";

const COURSE_URL = "/courses/harness-01.csl.json";

export default function App() {
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    <>
      <ThemeSwitcher />
      <SlideDeck course={course} />
    </>
  );
}
