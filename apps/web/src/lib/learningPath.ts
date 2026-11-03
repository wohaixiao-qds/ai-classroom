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
  // 单门课拉取失败(404→SPA 兜底 HTML/坏 JSON)只跳过该门,不炸整页课程库。
  // 真实事故:备课中途被杀留下骨架课,发布副本缺失,catalog 有 id 而 public 无文件。
  const loaded = await Promise.all(
    items.map((c) =>
      fetch(`/courses/${c.id}.csl.json`)
        .then((r) => r.json())
        .then(parseCourse)
        .catch((e: unknown) => {
          console.warn(`课程 ${c.id} 加载失败,已跳过:`, e);
          return null;
        }),
    ),
  );
  const courses = loaded
    .filter((c): c is AnyCourse => c !== null)
    .map((c) => ({
      ...c,
      meta: { ...c.meta, topic: c.meta.topic ?? metaById.get(c.id)?.topic ?? null },
    }));
  return {
    courses,
    readyById: new Map(items.map((c) => [c.id, c.ready])),
  };
}

