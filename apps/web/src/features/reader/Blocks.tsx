import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { AlertTriangle, CheckCircle2, Info, Lightbulb, RotateCw } from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import type { Block } from "../../types/csl";
import { normalizeBold } from "../../utils/md";
import { CheckpointOverlay } from "./CheckpointOverlay";

/** v2 块渲染:节内块按序即版式(P6 书页形态)。quiz 内嵌复述卡,闪卡点按翻面。 */
export function Blocks({ blocks, courseId }: { blocks: Block[]; courseId: string }) {
  return (
    <div className="flex flex-col gap-5">
      {blocks.map((b, i) => (
        <BlockView key={i} block={b} courseId={courseId} />
      ))}
    </div>
  );
}

function BlockView({ block, courseId }: { block: Block; courseId: string }) {
  switch (block.type) {
    case "p":
      // prose 管结构默认(列表/引用/标题节奏);中文微排版按 CLREQ:行高 1.9、
      // 两端对齐、中西文间距(text-autospace,Chrome 123+)、避免孤字(text-wrap pretty)
      return (
        <div className="prose max-w-none text-[15.5px] prose-p:my-0 prose-p:leading-[1.9] prose-p:text-justify prose-p:text-foreground/90 prose-p:[text-wrap:pretty] prose-strong:text-foreground prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:font-mono prose-code:text-[13px] prose-code:text-primary prose-code:before:content-[''] prose-code:after:content-['']">
          <Markdown>{normalizeBold(block.text)}</Markdown>
        </div>
      );
    case "diagram":
      return <MermaidDiagram code={block.code} caption={block.caption} />;
    case "code":
      return (
        <figure className="overflow-hidden rounded-xl border border-border">
          <div className="flex items-center justify-between border-b border-border bg-secondary/60 px-3 py-1.5">
            <Badge variant="secondary" className="font-mono text-[11px]">
              {block.language}
            </Badge>
          </div>
          <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-6">
            <code>{block.code}</code>
          </pre>
          {block.caption && (
            <figcaption className="border-t border-border px-4 py-2 text-[13px] text-muted-foreground">
              {block.caption}
            </figcaption>
          )}
        </figure>
      );
    case "table":
      return (
        <figure>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full border-collapse text-[14px]">
              <thead>
                <tr className="bg-secondary/60">
                  {block.header.map((h, i) => (
                    <th key={i} className="border-b border-border px-3 py-2 text-left font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, i) => (
                  <tr key={i} className="border-b border-border/60 last:border-b-0">
                    {row.map((cell, j) => (
                      <td key={j} className="px-3 py-2 align-top">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {block.caption && (
            <figcaption className="mt-1.5 text-[13px] text-muted-foreground">{block.caption}</figcaption>
          )}
        </figure>
      );
    case "callout": {
      const cfg = {
        tip: { icon: Lightbulb, cls: "border-primary/40 bg-primary/5", label: "要点" },
        warn: { icon: AlertTriangle, cls: "border-warning/50 bg-warning/10", label: "注意" },
        note: { icon: Info, cls: "border-border bg-secondary/50", label: "注" },
      }[block.kind];
      const Icon = cfg.icon;
      return (
        <div className={`flex gap-2.5 rounded-xl border px-4 py-3 text-[14px] leading-7 ${cfg.cls}`}>
          <Icon size={16} className="mt-1.5 shrink-0 text-primary" />
          <div>
            <span className="mr-1.5 font-medium">{cfg.label}:</span>
            {block.text}
          </div>
        </div>
      );
    }
    case "quiz":
      return <QuizCard block={block} courseId={courseId} />;
    case "flashcards":
      return <FlashCards cards={block.cards} />;
  }
}

/** mermaid 示意图:动态加载(不进主包);渲染失败降级为代码块(P6 验收要求) */
function MermaidDiagram({ code, caption }: { code: string; caption: string | null }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const idRef = useRef(`mmd-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let alive = true;
    setSvg(null);
    setFailed(false);
    (async () => {
      try {
        const m = (await import("mermaid")).default;
        m.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
        const { svg: out } = await m.render(idRef.current, code);
        if (alive) setSvg(out);
      } catch {
        if (alive) setFailed(true);
      } finally {
        // render 抛错时 mermaid 会把「语法错误炸弹」元素挂到 body——必须摘除,
        // 否则污染页面底部(实测 12.2.0;错误元素 id 为 d{id} 与 {id})
        for (const eid of [`d${idRef.current}`, idRef.current]) {
          document.getElementById(eid)?.remove();
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [code]);

  return (
    <figure className="overflow-hidden rounded-xl border border-border bg-card">
      {failed ? (
        <pre className="overflow-x-auto p-4 font-mono text-[12px] leading-6 text-muted-foreground">
          <code>{code}</code>
        </pre>
      ) : svg ? (
        <div className="flex justify-center p-4 [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">示意图渲染中…</div>
      )}
      {caption && (
        <figcaption className="border-t border-border px-4 py-2 text-[13px] text-muted-foreground">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

/** 内嵌复述检查点:复用 /grade 全链(批改→落库→排下次复习),通过就地打勾 */
function QuizCard({ block, courseId }: { block: Extract<Block, { type: "quiz" }>; courseId: string }) {
  const [open, setOpen] = useState(false);
  const [passed, setPassed] = useState(false);
  return (
    <div className={`rounded-xl border px-4 py-3.5 ${passed ? "border-success/50 bg-success/5" : "border-primary/40 bg-primary/5"}`}>
      <p className="mb-2 font-mono text-[11px] tracking-widest text-primary">◆ 复述检查点</p>
      <p className="text-[15px] leading-7">{block.question}</p>
      {block.hint && <p className="mt-1 text-[13px] text-muted-foreground">提示: {block.hint}</p>}
      <div className="mt-3">
        {passed ? (
          <span className="inline-flex items-center gap-1.5 text-sm text-success">
            <CheckCircle2 size={15} /> 已通过
          </span>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            开始复述
          </Button>
        )}
      </div>
      {open && (
        <CheckpointOverlay
          question={block.question}
          hint={block.hint}
          courseId={courseId}
          pageId={block.id}
          onPass={() => {
            setPassed(true);
            setOpen(false);
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

/** 闪卡:点按翻面(简单实现,P6 不做 3D 动画) */
function FlashCards({ cards }: { cards: { front: string; back: string }[] }) {
  const [flipped, setFlipped] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setFlipped((s) => {
      const n = new Set(s);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {cards.map((c, i) => (
        <button
          key={i}
          type="button"
          onClick={() => toggle(i)}
          className="rounded-xl border border-border bg-card px-4 py-3.5 text-left transition-colors hover:border-primary/40"
          title={flipped.has(i) ? "点回正面" : "点看答案"}
        >
          <p className="font-mono text-[11px] tracking-widest text-muted-foreground">
            {flipped.has(i) ? "答" : "问"}
          </p>
          <p className="mt-1 text-[14px] leading-7">{flipped.has(i) ? c.back : c.front}</p>
          <span className="mt-2 inline-flex items-center gap-1 text-[12px] text-muted-foreground">
            <RotateCw size={11} /> 翻面
          </span>
        </button>
      ))}
    </div>
  );
}
