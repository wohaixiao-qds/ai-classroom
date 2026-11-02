/** 领域大纲·书籍目录(P7·M3):篇归类 + 课进度,直接回答「这本书学到哪了」。
 *  数据 = /api/v1/outlines + 各自详情;进度 = course_file_id 对上 readyById。 */
import { BookOpen, CircleCheck, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Card } from "../../components/ui/card";

interface OutlineCourse {
  id: string;
  title: string;
  goal: string;
  part?: string;
  prereq_titles?: string[];
  course_file_id?: string | null;
}

interface OutlineDetail {
  topic: string;
  domain: string;
  courses: OutlineCourse[];
}

export function OutlineToc({
  readyById,
  cursorId,
}: {
  readyById: Map<string, boolean>;
  cursorId?: string;
}) {
  const [details, setDetails] = useState<OutlineDetail[] | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const list = (await fetch("/api/v1/outlines").then((r) => r.json())) as {
          topic: string;
        }[];
        const ds = await Promise.all(
          list.map((o) =>
            fetch(`/api/v1/outlines/${encodeURIComponent(o.topic)}`).then((r) =>
              r.json(),
            ),
          ),
        );
        setDetails(ds as OutlineDetail[]);
      } catch {
        setDetails([]);
      }
    })();
  }, []);

  if (details === null) return null;
  if (details.length === 0) return null;

  return (
    <section className="mb-8 space-y-3">
      {details.map((d) => {
        // 按篇分组(保序);无 part 归「正文」
        const groups: { part: string; items: { c: OutlineCourse; i: number }[] }[] = [];
        d.courses.forEach((c, i) => {
          const part = c.part?.trim() || "正文";
          const last = groups[groups.length - 1];
          if (last && last.part === part) last.items.push({ c, i });
          else groups.push({ part, items: [{ c, i }] });
        });
        const doneCount = d.courses.filter(
          (c) => c.course_file_id && readyById.get(c.course_file_id),
        ).length;
        return (
          <Card key={d.topic} className="p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <h3 className="flex items-center gap-2 text-sm font-medium">
                <BookOpen size={14} className="text-primary" />
                {d.domain && `${d.domain} · `}
                {d.topic}
                <span className="font-mono text-xs font-normal text-muted-foreground">
                  目录 · {d.courses.length} 课
                </span>
              </h3>
              <span className="font-mono text-xs text-muted-foreground">
                已学 {doneCount} / {d.courses.length}
              </span>
            </div>
            <div className="space-y-3">
              {groups.map((g) => (
                <div key={g.part}>
                  {g.part !== "正文" && (
                    <p className="mb-1 border-b border-border pb-1 font-mono text-[11px] tracking-widest text-primary">
                      ◆ {g.part}
                    </p>
                  )}
                  <ol className="space-y-1">
                    {g.items.map(({ c, i }) => {
                      const done = !!(c.course_file_id && readyById.get(c.course_file_id));
                      const isCursor = !!c.course_file_id && c.course_file_id === cursorId;
                      const href = c.course_file_id
                        ? `/read/${c.course_file_id}`
                        : `/studio`;
                      return (
                        <li key={c.id}>
                          <Link
                            to={href}
                            className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-secondary"
                            title={c.goal}
                          >
                            <span className="font-mono text-xs text-muted-foreground">
                              {String(i + 1).padStart(2, "0")}
                            </span>
                            {done ? (
                              <CircleCheck size={13} className="shrink-0 text-success" />
                            ) : isCursor ? (
                              <Play size={13} className="shrink-0 text-primary" />
                            ) : (
                              <span className="w-[13px] shrink-0" />
                            )}
                            <span
                              className={`min-w-0 flex-1 truncate ${
                                done ? "text-muted-foreground" : isCursor ? "font-medium text-primary" : ""
                              }`}
                            >
                              {c.title}
                            </span>
                            <span className="hidden truncate text-xs text-muted-foreground sm:block sm:max-w-[40%]">
                              {c.goal}
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              ))}
            </div>
          </Card>
        );
      })}
    </section>
  );
}
