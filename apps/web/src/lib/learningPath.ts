// 学习路线:按先修依赖(meta.depends_on)排出建议学习顺序。
// 顺序 = 拓扑排序(Kahn);同分时保持课程库原有顺序;成环/孤儿课垫底不阻断。
// 纯函数 + 拉取,供课程库(路线条+卡片步数)与详情页(当前位置+上一课/下一课)共用。
import { parseCourse, type AnyCourse } from "../types/csl";

/** 拉全部课程并合并 catalog 推导的 topic(与 LibraryPage 原逻辑同源);
 * readyById 供路线条标「已学完」。 */
export async function fetchAllCourses(): Promise<{
  courses: AnyCourse[];
  readyById: Map<string, boolean>;
}> {
  const cat = await fetch("/api/v1/catalog").then((r) => r.json());
  const items = (cat as { learning: { id: string; topic: string | null; ready: boolean }[] })
    .learning;
  const metaById = new Map(items.map((c) => [c.id, c]));
  const courses = await Promise.all(
    items.map((c) =>
      fetch(`/courses/${c.id}.csl.json`).then((r) => r.json().then(parseCourse)),
    ),
  ).then((all) =>
    all.map((c) => ({
      ...c,
      meta: { ...c.meta, topic: c.meta.topic ?? metaById.get(c.id)?.topic ?? null },
    })),
  );
  return {
    courses,
    readyById: new Map(items.map((c) => [c.id, c.ready])),
  };
}

/** 建议学习顺序:依赖全部满足的课才排前面;同分按 courses 原序(与课程库分组一致)。 */
export function suggestOrder(courses: AnyCourse[]): AnyCourse[] {
  const byId = new Map(courses.map((c) => [c.id, c]));
  const pos = new Map(courses.map((c, i) => [c.id, i]));
  const indeg = new Map(courses.map((c) => [c.id, 0]));
  const dependents = new Map<string, string[]>();
  for (const c of courses) {
    for (const d of c.meta.depends_on ?? []) {
      if (d.id === c.id || !byId.has(d.id)) continue; // 自依赖/悬空引用不参与排序
      indeg.set(c.id, (indeg.get(c.id) ?? 0) + 1);
      dependents.set(d.id, [...(dependents.get(d.id) ?? []), c.id]);
    }
  }
  const queue = courses.filter((c) => indeg.get(c.id) === 0).map((c) => c.id);
  const done = new Set<string>();
  const out: AnyCourse[] = [];
  while (queue.length) {
    queue.sort((a, b) => pos.get(a)! - pos.get(b)!); // 稳定:同分保持课程库顺序
    const id = queue.shift()!;
    out.push(byId.get(id)!);
    done.add(id);
    for (const nxt of dependents.get(id) ?? []) {
      const left = (indeg.get(nxt) ?? 0) - 1;
      indeg.set(nxt, left);
      if (left === 0) queue.push(nxt);
    }
  }
  for (const c of courses) if (!done.has(c.id)) out.push(c); // 环/悬空:垫底,路线不断
  return out;
}
