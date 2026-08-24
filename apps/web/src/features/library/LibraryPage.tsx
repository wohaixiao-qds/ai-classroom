/** 课程库(甲方案):全部课程 → 课程详情页 → 课堂。
 *  三层漏斗的「库→详情→播放」,详情页是大纲/来源/检查点的枢纽。 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, Play } from "lucide-react";
import type { Course } from "../../types/csl";

/** 页型 → 小图标(详情页大纲用;课堂边栏有自己的一份) */
const KIND_ICON: Record<string, string> = {
  cover: "🎬",
  formula: "📐",
  diagram: "🖼",
  duo: "🆚",
  code: "💻",
  table: "📊",
  quiz: "❓",
};

export function LibraryPage() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  useEffect(() => {
    // 课程库数据从课件 JSON 自取(catalog 的 learning 只有摘要,详情要页大纲)
    void fetch("/api/v1/catalog")
      .then((r) => r.json())
      .then(async (d: { learning: { id: string }[] }) => {
        const all = await Promise.all(
          d.learning.map((c) =>
            fetch(`/courses/${c.id}.csl.json`).then((r) => r.json() as Promise<Course>),
          ),
        );
        setCourses(all);
      });
  }, []);

  if (!courses) return <div className="muted p-8 text-sm">加载中…</div>;
  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="mb-6 text-2xl font-bold">课程库 · {courses.length} 门</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {courses.map((c) => {
          const cp = c.pages.filter((p) => p.checkpoint).length;
          return (
            <Link
              key={c.id}
              to={`/courses/${c.id}`}
              className="rounded-xl border border-(--line) bg-(--surface) p-5 transition-colors hover:border-(--accent)"
            >
              <p className="accent mb-1 font-mono text-xs">✅ 可上课</p>
              <h2 className="mb-2 text-lg font-medium">{c.title}</h2>
              <p className="muted font-mono text-xs">
                {c.pages.length} 页 · {cp} 检查点 · {c.meta.duration_min ?? "—"} 分钟
              </p>
              <p className="muted mt-2 truncate text-xs">{c.pages[0]?.eyebrow ?? ""}</p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/** 课程详情页:大纲 + 来源(有据可查) + 关联笔记 + 进课堂 */
export function CourseDetailPage() {
  const { courseId = "" } = useParams();
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCourse(null);
    setError(null);
    fetch(`/courses/${courseId}.csl.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Course>;
      })
      .then(setCourse)
      .catch((e: unknown) => setError(String(e)));
  }, [courseId]);

  if (error) return <div className="muted p-8 text-sm">课件加载失败:{error}</div>;
  if (!course) return <div className="muted p-8 text-sm">加载中…</div>;

  const cps = course.pages.filter((p) => p.checkpoint);

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <Link to="/courses" className="muted text-xs hover:text-(--text)">
        ← 课程库
      </Link>
      <div className="mt-3 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{course.title}</h1>
          <p className="muted mt-1 font-mono text-xs">
            {course.scenario} · {course.pages.length} 页 ·{" "}
            {sumSentences(course)} 句 · {cps.length} 检查点
          </p>
        </div>
        <Link
          to={`/c/${course.id}`}
          className="flex shrink-0 items-center gap-2 rounded-full bg-(--accent) px-5 py-2.5 text-sm font-medium text-(--bg) transition-transform hover:scale-105"
        >
          <Play size={15} /> 进课堂
        </Link>
      </div>

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium tracking-wide">本课大纲</h2>
        <ul className="space-y-1.5">
          {course.pages.map((p, i) => (
            <li
              key={p.id}
              className="flex items-center gap-3 rounded-lg border border-(--line) bg-(--surface) px-4 py-2 text-sm"
            >
              <span className="muted font-mono text-xs">{i + 1}</span>
              <span>{KIND_ICON[p.content.kind] ?? "📄"}</span>
              <span className="flex-1 truncate">{p.title || p.eyebrow || p.id}</span>
              {p.checkpoint && (
                <span title="有复述检查点" className="flex text-(--accent)">
                  <CheckCircle2 size={13} />
                </span>
              )}
              <span className="muted font-mono text-xs opacity-60">
                {p.script.length} 句
              </span>
            </li>
          ))}
        </ul>
      </section>

      {course.meta.sources?.length ? (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium tracking-wide">来源(有据可查)</h2>
          <ul className="space-y-1">
            {course.meta.sources.map((s, i) => (
              <li key={i} className="text-xs">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="accent hover:underline"
                >
                  [{i + 1}] {s.title || s.url}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {course.meta.source_notes.length ? (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium tracking-wide">关联材料</h2>
          <ul className="muted space-y-1 font-mono text-xs">
            {course.meta.source_notes.map((n) => (
              <li key={n} title={n}>
                · {n.split("/").slice(-1)[0]}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function sumSentences(c: Course): number {
  return c.pages.reduce((n, p) => n + p.script.length, 0);
}
