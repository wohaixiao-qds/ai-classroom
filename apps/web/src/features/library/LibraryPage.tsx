/** 课程库(甲方案):左侧主题树(领域→主题→层)筛选 + 课程卡 → 详情页 → 课堂。
 *  树从 topic 串自动生长("Agent / harness / Runtime"),与 vault 目录心智一致,零手工维护。
 *  topic 真源是后端 catalog 的实时推导(老课件文件里没有);此处拉取时合并进课程数据。 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, ChevronDown, ChevronRight, Folder, Play } from "lucide-react";
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

// ---------- 主题树 ----------

interface TreeNode {
  name: string;
  path: string[]; // 从根到本节点的路径(筛选键)
  children: TreeNode[];
  courses: Course[]; // 恰好挂在本节点的课(叶子层)
}

/** 主题串 → 树层级段。单段主题若以已知领域开头(「Agent 解析层」)提为两层。 */
function topicSegs(topic: string | null | undefined, domains: Set<string>): string[] {
  const t = topic ?? "未分组";
  const segs = t.split(" / ");
  if (segs.length === 1) {
    const i = segs[0].indexOf(" ");
    if (i > 0 && domains.has(segs[0].slice(0, i))) {
      return [segs[0].slice(0, i), segs[0].slice(i + 1)];
    }
  }
  return segs;
}

function deriveDomains(courses: Course[]): Set<string> {
  const domains = new Set<string>();
  for (const c of courses) {
    const segs = (topicOf(c) ?? "").split(" / ");
    if (segs.length > 1) domains.add(segs[0]);
  }
  return domains;
}

/** topic 真源:合并进 meta.topic 的 catalog 推导值(见拉取处) */
function topicOf(c: Course): string | null {
  return c.meta.topic ?? null;
}

function buildTree(courses: Course[], domains: Set<string>): TreeNode {
  const root: TreeNode = { name: "", path: [], children: [], courses: [] };
  for (const c of courses) {
    let node = root;
    for (const seg of topicSegs(topicOf(c), domains)) {
      let child = node.children.find((x) => x.name === seg);
      if (!child) {
        child = { name: seg, path: [...node.path, seg], children: [], courses: [] };
        node.children.push(child);
      }
      node = child;
    }
    node.courses.push(c);
  }
  return root;
}

function countCourses(n: TreeNode): number {
  return n.courses.length + n.children.reduce((s, x) => s + countCourses(x), 0);
}

function TreeView({
  node,
  sel,
  onSelect,
  depth = 0,
}: {
  node: TreeNode;
  sel: string[] | null;
  onSelect: (path: string[] | null) => void;
  depth?: number;
}) {
  return (
    <ul>
      {node.children.map((ch) => {
        const active = sel && sel.join("/") === ch.path.join("/");
        const expanded = sel ? sel.join("/").startsWith(ch.path.join("/")) : false;
        return (
          <li key={ch.path.join("/")}>
            <button
              onClick={() => onSelect(active ? null : ch.path)}
              className={`flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-xs transition-colors ${
                active
                  ? "bg-(--accent)/15 font-medium text-(--text) ring-1 ring-(--accent)/40"
                  : "muted hover:bg-(--surface) hover:text-(--text)"
              }`}
              style={{ paddingLeft: 8 + depth * 14 }}
            >
              {ch.children.length > 0 ? (
                expanded ? (
                  <ChevronDown size={12} className="shrink-0" />
                ) : (
                  <ChevronRight size={12} className="shrink-0" />
                )
              ) : (
                <Folder size={12} className="shrink-0" />
              )}
              <span className="min-w-0 flex-1 truncate">{ch.name}</span>
              <span className="shrink-0 font-mono opacity-60">{countCourses(ch)}</span>
            </button>
            {expanded && ch.children.length > 0 && (
              <TreeView node={ch} sel={sel} onSelect={onSelect} depth={depth + 1} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** sel 命中:课程层级段在选中路径之下(选中 Agent,则 Agent/harness/Runtime 的课都算) */
function inSelection(c: Course, sel: string[] | null, domains: Set<string>): boolean {
  if (!sel) return true;
  const segs = topicSegs(topicOf(c), domains);
  return sel.every((s, i) => segs[i] === s);
}

export function LibraryPage() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [sel, setSel] = useState<string[] | null>(null);
  useEffect(() => {
    // topic 真源=catalog 的实时推导(老课件文件里没有);拉取时合并进 meta.topic
    void fetch("/api/v1/catalog")
      .then((r) => r.json())
      .then(
        async (d: {
          learning: { id: string; topic: string | null }[];
        }) => {
          const topicById = new Map(d.learning.map((c) => [c.id, c.topic]));
          const all = await Promise.all(
            d.learning.map((c) =>
              fetch(`/courses/${c.id}.csl.json`).then((r) => r.json() as Promise<Course>),
            ),
          );
          setCourses(
            all.map((c) => ({
              ...c,
              meta: { ...c.meta, topic: c.meta.topic ?? topicById.get(c.id) ?? null },
            })),
          );
        },
      );
  }, []);

  if (!courses) return <div className="muted p-8 text-sm">加载中…</div>;

  const domains = deriveDomains(courses);
  const tree = buildTree(courses, domains);
  const shown = sel ? courses.filter((c) => inSelection(c, sel, domains)) : courses;

  // 选中节点时右侧仍按主题分节;「全部」时同
  const groups: { topic: string; courses: Course[] }[] = [];
  for (const c of shown) {
    const t = c.meta.topic ?? "未分组";
    const g = groups[groups.length - 1];
    if (g && g.topic === t) g.courses.push(c);
    else groups.push({ topic: t, courses: [c] });
  }

  return (
    <div className="flex h-full">
      {/* 左:主题树(领域→主题→层,点选过滤) */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-(--line) bg-(--surface2)">
        <div className="flex items-center justify-between px-3 py-2">
          <span className="muted text-xs font-medium">知识版图</span>
          {sel && (
            <button onClick={() => setSel(null)} className="accent text-xs">
              全部
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          <button
            onClick={() => setSel(null)}
            className={`mb-1 flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-xs ${
              sel ? "muted hover:text-(--text)" : "bg-(--accent)/15 font-medium text-(--text)"
            }`}
          >
            📚 全部课程
            <span className="ml-auto font-mono opacity-60">{courses.length}</span>
          </button>
          <TreeView node={tree} sel={sel} onSelect={setSel} />
        </div>
      </aside>

      {/* 右:课程卡(按主题分节) */}
      <div className="min-w-0 flex-1 overflow-y-auto px-6 py-8">
        <h1 className="mb-6 text-2xl font-bold">
          {sel ? sel.join(" / ") : "课程库"} · {shown.length} 门
        </h1>
        {groups.map((g) => (
          <section key={g.topic} className="mb-8">
            <h2 className="muted mb-3 font-mono text-xs tracking-wide">
              {g.topic} · {g.courses.length} 门
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {g.courses.map((c) => {
                const cp = c.pages.filter((p) => p.checkpoint).length;
                return (
                  <Link
                    key={c.id}
                    to={`/courses/${c.id}`}
                    className="rounded-xl border border-(--line) bg-(--surface) p-5 transition-colors hover:border-(--accent)"
                  >
                    <p className="accent mb-1 font-mono text-xs">✅ 可上课</p>
                    <h3 className="mb-2 text-lg font-medium">{c.title}</h3>
                    <p className="muted font-mono text-xs">
                      {c.pages.length} 页 · {cp} 检查点 · {c.meta.duration_min ?? "—"} 分钟
                    </p>
                    <p className="muted mt-2 truncate text-xs">{c.pages[0]?.eyebrow ?? ""}</p>
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
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
      {course.meta.topic && (
        <p className="muted mt-3 font-mono text-xs">📘 {course.meta.topic}</p>
      )}
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
