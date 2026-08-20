import type { CSSProperties, ReactNode } from "react";
import type { Fragment, Page, PageContent } from "../../types/csl";

/** 把 fragment(effect+target) 变成元素的步进属性:reveal 管 .visible,我们管动画 */
function stepOf(frags: Fragment[], target: string) {
  const f = frags.find((x) => x.target === target);
  if (!f) return {};
  return { className: "fragment step", "data-anim": f.effect } as Record<string, string>;
}

/** 极简 **加粗** 解析 */
function md(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((seg, i) =>
    seg.startsWith("**") ? <b key={i}>{seg.slice(2, -2)}</b> : <span key={i}>{seg}</span>,
  );
}

export function SlidePage({ page }: { page: Page }) {
  return (
    <section data-page-id={page.id}>
      {page.content.kind !== "cover" && page.eyebrow && <p className="eyebrow">{page.eyebrow}</p>}
      {page.content.kind !== "cover" && page.title && <h2 className="deck-h2">{page.title}</h2>}
      <PageBody page={page} />
      {page.checkpoint && (
        <p className="muted mt-8 text-sm">
          ◆ 复述检查点：{page.checkpoint.question}
        </p>
      )}
    </section>
  );
}

function PageBody({ page }: { page: Page }) {
  const c = page.content;
  switch (c.kind) {
    case "cover":
      return <Cover page={page} />;
    case "formula":
      return <Formula page={page} content={c} />;
    case "diagram":
      return <Diagram page={page} content={c} />;
    case "duo":
      return <Duo page={page} content={c} />;
    case "code":
      return <Code content={c} />;
    case "table":
      return <Table page={page} content={c} />;
    case "quiz":
      return <Quiz content={c} />;
  }
}

/* ---------- 各页型 ---------- */

function Cover({ page }: { page: Page }) {
  const c = page.content;
  if (c.kind !== "cover") return null;
  const step = (t: string) => stepOf(page.fragments, t);
  return (
    <div>
      <h1 className="deck-h1" {...step("title")}>
        {page.title}
      </h1>
      {c.equation && (
        <p className="blue mt-8 font-mono text-xl md:text-2xl" {...step("equation")}>
          {c.equation}
        </p>
      )}
      <div className="muted mt-12 flex gap-10 text-sm" {...step("meta")}>
        {c.meta.map(([k, v]) => (
          <span key={k}>
            {k} <b className="font-medium text-(--text)">{v}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

function Formula({ page, content }: { page: Page; content: Extract<PageContent, { kind: "formula" }> }) {
  const step = (t: string) => stepOf(page.fragments, t);
  return (
    <div>
      <div className="mb-10 flex flex-wrap items-baseline gap-3 font-mono text-3xl font-bold md:text-5xl">
        {content.items.map((item, i) => (
          <span
            key={i}
            className={`fragment step ${/LLM/.test(item) ? "blue" : /harness/.test(item) ? "accent" : "muted"}`}
            data-anim="pop"
          >
            {item}
          </span>
        ))}
      </div>
      <p className="fragment step text-xl md:text-2xl leading-relaxed" {...step("conclusion")}>
        {md(content.conclusion)}
      </p>
      {content.derived && (
        <p
          className="fragment step accent mt-6 font-mono text-2xl font-bold md:text-3xl"
          {...step("derived")}
          data-anim="pop"
        >
          {content.derived}
        </p>
      )}
    </div>
  );
}

function Diagram({ page, content }: { page: Page; content: Extract<PageContent, { kind: "diagram" }> }) {
  const step = (t: string) => stepOf(page.fragments, t);
  return (
    <div className="grid grid-cols-2 items-center gap-10">
      <object type="image/svg+xml" data={`/courses/assets/${content.asset}`} className="w-full max-w-xl" aria-label="图解" />
      <div className="flex flex-col gap-6">
        {content.legend.map((l, i) => (
          <div key={l.label} className="flex items-start gap-4" {...step(`legend-${i}`)}>
            <span
              className="mt-1.5 h-3.5 w-3.5 flex-none rounded-sm"
              style={{ background: `var(--${l.color})` } as CSSProperties}
            />
            <div>
              <b className="block text-base">{l.label}</b>
              <p className="muted text-sm leading-relaxed">{l.note}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Duo({ page, content }: { page: Page; content: Extract<PageContent, { kind: "duo" }> }) {
  const step = (t: string) => stepOf(page.fragments, t);
  const card = (card: Extract<PageContent, { kind: "duo" }>["left"], id: string) => (
    <div
      className="rounded-xl border border-(--line) bg-(--surface) p-7"
      {...step(id)}
    >
      <h3 className="mb-3 text-lg">
        {card.title}
        <span className="muted ml-3 rounded-full border border-(--line) px-3 py-0.5 font-mono text-xs tracking-widest">
          {card.tag}
        </span>
      </h3>
      <p className="muted leading-relaxed">{md(card.body)}</p>
    </div>
  );
  return (
    <div>
      <div className="grid grid-cols-2 gap-7">
        {card(content.left, "card-left")}
        {card(content.right, "card-right")}
      </div>
    </div>
  );
}

function Code({ content }: { content: Extract<PageContent, { kind: "code" }> }) {
  return (
    <div>
      <pre className="overflow-x-auto rounded-xl border border-(--line) bg-(--surface) p-6 font-mono text-sm leading-loose md:text-base">
        {content.lines.map((l, i) => (
          <span key={i} className="fragment block step" data-anim="coderise">
            <span className={l.highlight === "llm" ? "accent" : l.highlight === "harness" ? "blue" : ""}>
              {l.code}
            </span>
            {l.comment && <span className="muted">  # {l.comment}</span>}
          </span>
        ))}
      </pre>
      {content.note && (
        <p className="fragment step muted mt-5 text-sm leading-relaxed">
          {md(content.note)}
        </p>
      )}
    </div>
  );
}

function Table({ page, content }: { page: Page; content: Extract<PageContent, { kind: "table" }> }) {
  return (
    <div>
      <table className="w-full border-collapse text-sm md:text-base">
        <thead>
          <tr>
            {content.headers.map((h) => (
              <th
                key={h}
                className="muted border-b border-(--line) px-3 pb-4 text-left font-mono text-xs tracking-widest uppercase"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {content.rows.map((row, i) => (
            <tr key={i} className="fragment step" {...stepOf(page.fragments, `row-${i}`)}>
              {row.map((cell, j) => (
                <td key={j} className="border-b border-(--line) px-3 py-4 leading-relaxed align-top">
                  {j === 0 ? <b>{cell}</b> : cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {content.note && (
        <p className="fragment step muted mt-6 text-sm">⚠️ {content.note}</p>
      )}
    </div>
  );
}

function Quiz({ content }: { content: Extract<PageContent, { kind: "quiz" }> }) {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      {content.questions.map((q, i) => (
        <div key={i} className="flex items-baseline gap-5">
          <span className="accent font-mono font-bold">Q{i + 1}</span>
          <p className="fragment step text-lg leading-relaxed md:text-xl" data-anim="quizIn">
            {q}
          </p>
        </div>
      ))}
    </div>
  );
}
