import type { CourseV2, EvidenceItem } from "../../types/csl";

const SUPPORT_LABEL: Record<EvidenceItem["support"], string> = {
  supported: "原料经模型初审",
  partial: "原料部分有据，需复核",
  unsupported: "原料未获支撑",
  uncertain: "原料支撑关系待确认",
  unreviewed: "原料语义待审",
};

/** 显示作者关联的原文,与「列了来源就算正文正确」区分开。 */
export function EvidencePanel({ course }: { course: CourseV2 }) {
  const items = new Map((course.meta.evidence ?? []).map((e) => [e.id, e]));
  const sections = course.sections.map((section) => ({
    heading: section.heading,
    id: section.id,
    refs: [...new Set(section.blocks.flatMap((b) => b.evidence_ids ?? []))]
      .map((id) => items.get(id))
      .filter((e): e is EvidenceItem => e !== undefined),
  })).filter((section) => section.refs.length > 0);
  const review = course.meta.publication_review;

  return (
    <section className="mb-10 rounded-[12px] border border-border bg-card p-4" aria-label="原文依据">
      <h2 className="text-base font-medium">内容审查与原文依据</h2>
      <p className="mt-2 text-sm">
        {review?.status === "program_passed"
          ? `程序核验通过 · ${new Date(review.reviewed_at).toLocaleDateString()}`
          : review?.status === "model_reviewed"
            ? `自动审查通过 · ${new Date(review.reviewed_at).toLocaleDateString()}`
            : review?.status === "blocked" ? "审查未通过 · 草稿"
              : review?.status === "unreviewed" ? "审查未完成 · 草稿" : "历史课程 · 尚未按新规则审查"}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        程序核验覆盖结构、证据关联与原文快照一致性；模型意见仅作诊断，不代表人工复核或事实绝对正确。
      </p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        以下是各节写作时关联的原文。摘录定位确认出处，原料模型初审与正文审校分别进行。
      </p>
      <div className="mt-3 divide-y divide-border">
        {sections.map((section) => (
          <details key={section.id} className="py-3">
            <summary className="cursor-pointer text-sm font-medium">
              {section.heading} · {section.refs.length} 条依据
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">{review?.status === "program_passed" ? "正文已通过程序核验，模型意见仅作诊断" : review?.status === "model_reviewed" ? "正文已完成自动语义审查" : "正文改写尚待审校"}</p>
            <ul className="mt-3 space-y-4">
              {section.refs.map((item) => {
                const source = course.meta.sources?.find((s, i) => (s.id ?? i + 1) === item.source_id);
                return (
                  <li key={item.id} className="min-w-0 text-sm">
                    <p>{item.point}</p>
                    {item.quote && (
                      <blockquote className="mt-1 border-l-2 border-border pl-3 text-muted-foreground [overflow-wrap:anywhere]">
                        {item.quote}
                      </blockquote>
                    )}
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      {source && (
                        <a className="text-primary underline decoration-dotted [overflow-wrap:anywhere]"
                          href={source.url} target="_blank" rel="noopener noreferrer">
                          源[{item.source_id}] {source.title}
                        </a>
                      )}
                      <span>{item.quote_status === "matched" ? "摘录已定位" : "摘录待核对"}</span>
                      <span>{SUPPORT_LABEL[item.support]}</span>
                    </div>
                    {item.reason && <p className="mt-1 text-xs text-muted-foreground">{item.reason}</p>}
                  </li>
                );
              })}
            </ul>
          </details>
        ))}
      </div>
    </section>
  );
}
