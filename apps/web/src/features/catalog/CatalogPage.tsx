/** 课表页(临时占位):B1 将做成四泳道学习指挥台,现在先列已出课件 */
import { Link } from "react-router-dom";

const COURSES = [{ id: "harness-01", title: "harness 是什么", pages: 7, checkpoints: 3 }];

export function CatalogPage() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="mb-6 text-2xl font-bold">课表</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {COURSES.map((c) => (
          <Link
            key={c.id}
            to={`/c/${c.id}`}
            className="rounded-xl border border-(--line) bg-(--surface) p-5 transition-colors hover:border-(--accent)"
          >
            <p className="accent mb-1 font-mono text-xs">✅ 可上课</p>
            <h2 className="mb-2 text-lg font-medium">{c.title}</h2>
            <p className="muted font-mono text-xs">
              {c.pages} 页 · {c.checkpoints} 个检查点
            </p>
          </Link>
        ))}
      </div>
      <p className="muted mt-8 text-sm">
        B1 将把这里做成四泳道学习指挥台：✅ 已出课 / 📝 有笔记未出课 / ⬜ 待探 / 💡 衍生候选
      </p>
    </div>
  );
}
