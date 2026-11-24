import { Children, cloneElement, isValidElement, useEffect, useRef, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import Markdown from "react-markdown";
import { AlertTriangle, CheckCircle2, Info, Lightbulb, RotateCw } from "lucide-react";
import { AnimatePresence } from "motion/react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";
import type { Block } from "../../types/csl";
import { linkifyUrls } from "../../utils/linkify";
import { normalizeBold } from "../../utils/md";
import { CheckpointOverlay } from "./CheckpointOverlay";

export interface CheckpointAskPayload {
  question: string;
  pass_rule: string | null;
  answer: string;
  verdict: string;
  gaps?: string[]; // 上次复述的结构化缺失点(T2);空/缺省=无错因记录
}

/** 「源[N]」→ 页尾来源清单锚点(溯源):备课管线的调研来源硬闸在课件 meta.sources
 *  落了清单,正文标记链化后点击平滑滚到对应条目并高亮闪一下(直接 DOM 注类,
 *  1.6s 后摘除,不走 React 状态)。目标条目不存在(坏生成)则原地不动。
 *  簇匹配:模型常连写「源[1][2][3]」——「源」字后的标号串整体捕获逐个链化
 *  (旧版只吃「源[1]」,跟写的 [2][3] 落空成灰字)。 */
const SRC_CLUSTER_RE = /源\s*((?:\[\d+\]|[\d]+)(?:[\s,，、和与及]*(?:\[\d+\]|\d+))*)/g;

function jumpToSource(n: string, e: React.MouseEvent) {
  e.preventDefault();
  const el = document.getElementById(`src-${n}`);
  if (!el) return;
  const bounds = el.getBoundingClientRect();
  const nearby = bounds.top >= -window.innerHeight && bounds.bottom <= window.innerHeight * 2;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: nearby && !reduceMotion ? "smooth" : "instant", block: "center" });
  el.classList.add("rounded", "bg-primary/10", "ring-2", "ring-primary/40");
  window.setTimeout(() => {
    el.classList.remove("rounded", "bg-primary/10", "ring-2", "ring-primary/40");
  }, 1600);
}

function linkifySources(children: ReactNode): ReactNode {
  const walk = (node: ReactNode, keyBase: string): ReactNode[] => {
    if (typeof node === "string") {
      const out: ReactNode[] = [];
      let last = 0;
      let i = 0;
      for (const m of node.matchAll(SRC_CLUSTER_RE)) {
        // 源标记之间的普通文本段:裸 URL 也链化(课件正文常直接甩地址,不链化
        // 长链会被容器右缘切断=「链接没给全」;与答疑消息区同用一份 linkifyUrls)
        if (m.index > last) out.push(...linkifyUrls(node.slice(last, m.index), `${keyBase}-t${i}`));
        // 「源[N]」簇整体升为 mono 上标(设计稿 sup.src:11px 赭石);簇内标号逐个链化可点
        out.push(
          <sup key={`${keyBase}-sup${i++}`} className="font-mono text-[11px] leading-none">
            源
            {Array.from(m[1].matchAll(/\d+/g)).map((num) => (
              <a
                key={`${keyBase}-${i++}`}
                href={`#src-${num[0]}`}
                className="text-primary outline-none decoration-dotted underline-offset-2 hover:underline"
                title="跳到来源清单"
                onClick={(e) => jumpToSource(num[0], e)}
              >
                {`[${num[0]}]`}
              </a>
            ))}
          </sup>,
        );
        last = m.index + m[0].length;
      }
      if (last < node.length) out.push(...linkifyUrls(node.slice(last), `${keyBase}-tend`));
      return out;
    }
    // 容器(strong/em/code…)递归:源标记偶尔嵌在强调里
    const el = node as ReactElement<{ children?: ReactNode }>;
    if (isValidElement(node) && el.props.children != null) {
      return [
        cloneElement(
          el,
          el.props,
          ...Children.toArray(el.props.children).flatMap((c, j) => walk(c, `${keyBase}-${j}`)),
        ),
      ];
    }
    return [node];
  };
  return <>{Children.toArray(children).flatMap((c, j) => walk(c, `s${j}`))}</>;
}

/** p/callout 共用:markdown 渲染 + 源标记链化 */
const sourceMdComponents = {
  p: ({ children }: { children?: ReactNode }) => <p>{linkifySources(children)}</p>,
  li: ({ children }: { children?: ReactNode }) => <li>{linkifySources(children)}</li>,
};

/** v2 块渲染:节内块按序即版式(P6 书页形态)。quiz 内嵌复述卡,闪卡点按翻面+自评。 */
export function Blocks({
  blocks,
  courseId,
  sectionId,
  onAskTutor,
}: {
  blocks: Block[];
  courseId: string;
  sectionId: string;
  onAskTutor?: (payload: CheckpointAskPayload) => void;
}) {
  let fcCount = 0;
  return (
    <div className="flex flex-col gap-5">
      {blocks.map((b, i) => {
        // 闪卡块 id 渲染期合成:<节id>-fc<序>,与后端 flash_lookup 同约定(M4)
        const blockId = b.type === "flashcards" ? `${sectionId}-fc${fcCount++}` : undefined;
        return (
          <BlockView
            key={i}
            block={b}
            courseId={courseId}
            blockId={blockId}
            onAskTutor={onAskTutor}
          />
        );
      })}
    </div>
  );
}

function BlockView({
  block,
  courseId,
  blockId,
  onAskTutor,
}: {
  block: Block;
  courseId: string;
  blockId?: string;
  onAskTutor?: (payload: CheckpointAskPayload) => void;
}) {
  switch (block.type) {
    case "p":
      // prose 管结构默认(列表/引用/标题节奏);中文微排版按 CLREQ:行高 1.9、
      // 两端对齐、中西文间距(text-autospace,Chrome 123+)、避免孤字(text-wrap pretty)
      return (
        <div className="prose max-w-none text-[15.5px] prose-p:my-0 prose-p:leading-[1.9] prose-p:text-justify prose-p:text-foreground/90 prose-p:[text-wrap:pretty] prose-strong:text-foreground prose-code:rounded prose-code:bg-[color:var(--code-bg)] prose-code:px-1 prose-code:font-mono prose-code:text-[13px] prose-code:text-primary prose-code:before:content-[''] prose-code:after:content-['']">
          <Markdown components={sourceMdComponents}>{normalizeBold(block.text)}</Markdown>
        </div>
      );
    case "diagram":
      return <MermaidDiagram code={block.code} caption={block.caption} />;
    case "code":
      return (
        <figure className="overflow-hidden rounded-[12px] border border-border bg-[color:var(--code-bg)]">
          <div className="flex items-center justify-between border-b border-border bg-card/60 px-3 py-1.5">
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
          <div className="overflow-x-auto rounded-[12px] border border-border bg-card">
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
        tip: { icon: Lightbulb, box: "border-primary/40 bg-primary/5", ink: "text-primary", label: "要点" },
        // 坑 callout(设计稿 .pitfall):纸黄三色卡 + 左 3px 墨黄粗边 + 墨黄标题字
        warn: {
          icon: AlertTriangle,
          box: "border-[color:var(--warn-line)] bg-[color:var(--warn-bg)]",
          ink: "text-[color:var(--warn-ink)]",
          label: "注意",
        },
        note: { icon: Info, box: "border-border bg-secondary/50", ink: "text-primary", label: "注" },
      }[block.kind];
      const Icon = cfg.icon;
      return (
        <div
          className={cn(
            "flex gap-2.5 rounded-xl border px-4 py-3 text-[14px] leading-7",
            block.kind === "warn" &&
              "rounded-[10px] border-l-[3px] border-l-[color:var(--warn-ink)] text-[15px] leading-[1.9]",
            cfg.box,
          )}
        >
          <Icon size={16} className={cn("mt-1.5 shrink-0", cfg.ink)} />
          <div>
            <span className={cn("mr-1.5 font-medium", cfg.ink)}>{cfg.label}:</span>
            {linkifySources(block.text)}
          </div>
        </div>
      );
    }
    case "quiz":
      return <QuizCard block={block} courseId={courseId} onAskTutor={onAskTutor} />;
    case "flashcards":
      return <FlashCards cards={block.cards} courseId={courseId} blockId={blockId ?? ""} />;
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
    <figure className="overflow-hidden rounded-[12px] border border-border bg-[color:var(--code-bg)]">
      {failed ? (
        <pre className="overflow-x-auto p-4 font-mono text-[12px] leading-6 text-muted-foreground">
          <code>{code}</code>
        </pre>
      ) : svg ? (
        <div
          className="anim-rise flex justify-center p-4 [&_svg]:max-w-full"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
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
function QuizCard({
  block,
  courseId,
  onAskTutor,
}: {
  block: Extract<Block, { type: "quiz" }>;
  courseId: string;
  onAskTutor?: (payload: CheckpointAskPayload) => void;
}) {
  const [open, setOpen] = useState(false);
  const [passedResult, setPassedResult] = useState<{
    score: number;
    comment: string;
    precise?: string;
    answer: string;
  } | null>(null);
  // 上次复述的错因(T2):回查拿到就在未过态显示「上次漏了」,复习回测先看旧缺口
  const [lastGaps, setLastGaps] = useState<string[]>([]);
  const passed = passedResult !== null;

  // 结果回查(P7):挂载时查最近一次批改——刷新/隔天再来看,通过态不丢
  useEffect(() => {
    void fetch(
      `/api/v1/grade/last?course_id=${encodeURIComponent(courseId)}&page_id=${encodeURIComponent(block.id)}`,
    )
      .then((r) => r.json())
      .then((d: { found: boolean; verdict?: string; score?: number; comment?: string; precise?: string; answer?: string; gaps?: string[] }) => {
        if (d.found && d.verdict === "pass" && d.score !== undefined) {
          setPassedResult({
            score: d.score,
            comment: d.comment ?? "",
            precise: d.precise ?? undefined,
            answer: d.answer ?? "",
          });
        }
        if (d.found && Array.isArray(d.gaps)) {
          setLastGaps(d.gaps.filter((g) => typeof g === "string" && g.trim() !== ""));
        }
      })
      .catch(() => {});
  }, [block.id, courseId]);
  return (
    // 复述检查点卡(设计稿 .checkpoint):纸底 + 赭石虚线框 1.5px/圆角 14;
    // 通过态虚线转绿(--ok),打勾字保持 success,状态一眼可辨
    <div
      className={cn(
        "rounded-[14px] border-[1.5px] border-dashed bg-card px-4 py-3.5 transition-colors duration-300 ease-out",
        passed
          ? "border-[color:color-mix(in_srgb,var(--ok)_55%,var(--line))]"
          : "border-[color:color-mix(in_srgb,var(--accent)_55%,var(--line))]",
      )}
    >
      <p className="mb-2 font-mono text-[11px] tracking-widest text-primary">◆ 复述检查点</p>
      <p className="text-[15px] leading-7">{block.question}</p>
      {block.hint && <p className="mt-1 text-[13px] text-muted-foreground">提示: {block.hint}</p>}
      {!passed && lastGaps.length > 0 && (
        <div className="mt-2 rounded-[10px] border border-[color:var(--warn-line)] bg-[color:var(--warn-bg)] px-3 py-2 text-[13px] leading-6">
          <p className="font-medium text-[color:var(--warn-ink)]">上次漏了:</p>
          <ul className="space-y-0.5">
            {lastGaps.map((g, i) => (
              <li key={i} className="break-words text-foreground/80">· {g}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3">
        {passed ? (
          <span className="anim-pop inline-flex items-center gap-1.5 text-sm text-success">
            <CheckCircle2 size={15} /> 已通过 · {passedResult.score} 分
          </span>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            开始复述
          </Button>
        )}
      </div>
      {passedResult && (
        <div className="mt-2 space-y-1 text-[13px] leading-6">
          <p>
            <span className="font-medium text-foreground/80">我的回答:</span>
            <span className="text-muted-foreground">{passedResult.answer}</span>
          </p>
          {passedResult.precise && (
            <p>
              <span className="font-medium text-foreground/80">标准表述:</span>
              <span className="text-muted-foreground">{passedResult.precise}</span>
            </p>
          )}
        </div>
      )}
      <AnimatePresence>
        {open && (
          <CheckpointOverlay
            question={block.question}
            hint={block.hint}
            courseId={courseId}
            pageId={block.id}
            onPass={(r) => {
              setPassedResult({
                score: r.score,
                comment: r.comment,
                precise: r.precise,
                answer: r.answer,
              });
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
          onAskTutor={(answer, verdict, gaps) => {
            setOpen(false);
            onAskTutor?.({
              question: block.question,
              pass_rule: block.pass_rule,
              answer,
              verdict,
              // 弹层本次批改的错因优先;没批过(「没懂」直问)回落到回查到的历史错因
              gaps: gaps && gaps.length > 0 ? gaps : lastGaps,
            });
          }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

/** 闪卡:点按翻面;翻后自评「记得/忘了」→ /flash/report,与检查点同一套间隔排期(M4) */
function FlashCards({
  cards,
  courseId,
  blockId,
}: {
  cards: { front: string; back: string }[];
  courseId: string;
  blockId: string;
}) {
  const [flipped, setFlipped] = useState<Set<number>>(new Set());
  const [reported, setReported] = useState<Map<number, boolean>>(new Map());
  const toggle = (i: number) =>
    setFlipped((s) => {
      const n = new Set(s);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });
  const report = (i: number, remembered: boolean) => {
    setReported((m) => new Map(m).set(i, remembered));
    void fetch("/api/v1/flash/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: courseId, block_id: blockId, remembered }),
    }).catch(() => {});
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {cards.map((c, i) => {
        const isFlipped = flipped.has(i);
        const verdict = reported.get(i);
        return (
          <div key={i} className="rounded-[12px] border border-border bg-card px-4 py-3.5">
            <button
              type="button"
              onClick={() => toggle(i)}
              className="block w-full text-left [perspective:900px]"
              aria-label={isFlipped ? `${c.back}。返回问题` : `${c.front}。查看答案`}
            >
              {/* 正反两面网格同格堆叠(容器高度=较高面),内层 preserve-3d 旋转翻面 */}
              <div
                className={cn(
                  "grid transition-transform duration-(--dur-med) ease-out transform-3d motion-reduce:transition-none",
                  isFlipped && "rotate-y-180",
                )}
              >
                <div className="[grid-area:1/1] backface-hidden" aria-hidden={isFlipped}>
                  <p className="font-mono text-[11px] tracking-widest text-muted-foreground">问</p>
                  <p className="mt-1 text-[14px] leading-7">{c.front}</p>
                  {!verdict && (
                    <span className="mt-2 inline-flex items-center gap-1 text-[12px] text-muted-foreground">
                      <RotateCw size={11} /> 翻面
                    </span>
                  )}
                </div>
                <div className="[grid-area:1/1] backface-hidden rotate-y-180" aria-hidden={!isFlipped}>
                  <p className="font-mono text-[11px] tracking-widest text-primary">答</p>
                  <p className="mt-1 text-[14px] leading-7">{c.back}</p>
                </div>
              </div>
            </button>
            {isFlipped &&
              (verdict === undefined ? (
                <div className="anim-rise mt-2.5 flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => report(i, true)}>
                    记得了
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => report(i, false)}>
                    忘了
                  </Button>
                </div>
              ) : (
                <p className="anim-rise mt-2.5 text-[12px] text-muted-foreground">
                  {verdict ? "✓ 已记入,按间隔排下次复习" : "↺ 明天再来过这张"}
                </p>
              ))}
          </div>
        );
      })}
    </div>
  );
}
