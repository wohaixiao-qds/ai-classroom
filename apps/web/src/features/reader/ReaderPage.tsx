import { ArrowLeft, BookOpen, MessageSquare, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ThemeSwitcher } from "../../components/ThemeSwitcher";
import { Button } from "../../components/ui/button";
import { PageError, PageLoading } from "../../components/PageState";
import { cn } from "../../lib/utils";
import type { components } from "../../types/api.gen";

type CompletionState = components["schemas"]["CompletionState"];
import { ChatPanel, type ProgressLike } from "../chat/ChatPanel";
import { isV2, parseCourse, type CourseV2 } from "../../types/csl";
import { Blocks, type CheckpointAskPayload } from "./Blocks";
import { EvidencePanel } from "./EvidencePanel";
import { LearningQuestions } from "../learning-questions/index";

/** 书页阅读器(P6·M2):节目录 + 正文块渲染 + 内嵌检查点/闪卡 + 答疑侧栏。
 *  断点=滚动位置(localStorage);深链 ?section=N(1 起算)落到第 N 节。 */
export function ReaderPage() {
  const { courseId = "harness-01" } = useParams();
  const [course, setCourse] = useState<CourseV2 | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCourse(null);
    setError(null);
    fetch(`/courses/${courseId}.csl.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<unknown>;
      })
      .then((d) => {
        const c = parseCourse(d);
        if (!isV2(c)) {
          setError("课件不是 v2 书页格式(幻灯片版已退役,请重跑迁移脚本)");
          return;
        }
        setCourse(c);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [courseId]);

  if (error)
    return (
      <PageError
        message={`课件加载失败: ${error}`}
        back={
          <Button asChild variant="secondary" size="sm">
            <Link to="/courses">返回学习</Link>
          </Button>
        }
      />
    );
  if (!course) return <PageLoading label="课件加载中…" />;
  return <Reader key={course.id} course={course} />;
}

function Reader({ course }: { course: CourseV2 }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const chatToggleRef = useRef<HTMLButtonElement>(null);
  const [active, setActive] = useState(0);
  const [showChat, setShowChat] = useState(false);
  const [invite, setInvite] = useState(false);
  const [doneState, setDoneState] = useState<CompletionState | null>(null);
  const [chatSeed, setChatSeed] = useState<
    { text: string; checkpoint?: CheckpointAskPayload } | null
  >(null);
  const articleRef = useRef<HTMLElement | null>(null); // 划词提问的作用域(正文区)
  const [selTerm, setSelTerm] = useState<string | null>(null); // 最近一次划词(面板提示条用)
  const [prefill, setPrefill] = useState<string | null>(null); // 划词→输入框可编辑预填
  const [searchParams] = useSearchParams();
  const restoredRef = useRef(false);
  // 三栏占比:左右栏宽全局持久化(跨课一致);中栏 flex-1 自适应
  const [panels, setPanels] = useState(() => {
    try {
      const raw = localStorage.getItem(PANELS_KEY);
      if (raw) {
        const p = JSON.parse(raw) as { toc?: number; chat?: number };
        return {
          toc: clampW(Number(p.toc) || DEFAULT_PANELS.toc, 160, 400),
          chat: clampW(Number(p.chat) || DEFAULT_PANELS.chat, 260, 560),
        };
      }
    } catch {
      /* 存不进就用默认 */
    }
    return DEFAULT_PANELS;
  });
  useEffect(() => {
    try {
      localStorage.setItem(PANELS_KEY, JSON.stringify(panels));
    } catch {
      /* 同上 */
    }
  }, [panels]);

  // 批改→答疑联动:复述没过,带着检查点全上下文去问 AI 老师
  const onAskTutor = useCallback((p: CheckpointAskPayload) => {
    setShowChat(true);
    setChatSeed({
      text: `我在复述检查点没过:「${p.question}」。我的回答:「${p.answer}」。帮我搞懂薄弱点。`,
      checkpoint: p,
    });
  }, []);

  /** 答疑侧栏的进度适配器:当前节 + 跳节(引用侧「第N页」按钮沿用) */
  const jumpToPage = useCallback((n: number) => {
    setShowChat(false);
    const scroller = scrollRef.current;
    if (scroller) scrollToSection(scroller, n, true);
  }, []);
  const playback: ProgressLike = {
    state: { page: active },
    jumpToPage,
  };

  // 滚动 spy:标题越过容器顶缘 1/3 处即激活对应节
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const marks = Array.from(el.querySelectorAll<HTMLElement>("[data-sec]"));
    const y = el.scrollTop + el.clientHeight / 3;
    let cur = 0;
    marks.forEach((m, i) => {
      if (m.offsetTop <= y) cur = i;
    });
    setActive(cur);
    // 断点节流落盘(300ms):{top 像素, sec 节序}——学习台「继续学」读 sec
    if (!restoredRef.current) return;
    clearTimeout(Number(el.dataset.tmr));
    el.dataset.tmr = String(
      window.setTimeout(() => {
        try {
          localStorage.setItem(posKey(course.id), JSON.stringify({ top: el.scrollTop, sec: cur }));
        } catch {
          /* 隐私模式等存不进就算了 */
        }
      }, 300),
    );
  }, [course.id]);

  // 首次定位:优先深链 ?section=N,其次断点(节号,老数据退像素),都无则到顶
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const secN = Number(searchParams.get("section"));
    let target = -1;
    if (Number.isInteger(secN) && secN >= 1 && secN <= course.sections.length) {
      target = secN - 1;
    } else {
      try {
        const raw = localStorage.getItem(posKey(course.id));
        if (raw) {
          const saved = JSON.parse(raw) as { top?: number; sec?: number };
          if (Number.isInteger(saved.sec)) target = saved.sec as number;
          else if ((saved.top ?? 0) > 0) el.scrollTop = saved.top as number;
        }
      } catch {
        /* 坏数据当没断点 */
      }
    }
    if (target >= 0) scrollToSection(el, target);
    restoredRef.current = true;
    // 深链只在进入时生效一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [course.id]);

  const onDone = useCallback(() => {
    void fetch(`/api/v1/progress/${course.id}/done`, { method: "POST" })
      .then((r) => r.json())
      .then((d: CompletionState) => {
        setDoneState(d);
        if (d.ready) setInvite(true);
      })
      .catch(() => {});
  }, [course.id]);

  // 浏览器标签页标题跟课名(P1 时代写死「harness 是什么」的遗留修复);离开恢复站名
  useEffect(() => {
    document.title = `${course.title} · AI 课堂`;
    return () => {
      document.title = "AI 课堂";
    };
  }, [course.title]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b border-border bg-secondary/50 px-3 py-2 sm:px-5">
        <Button asChild variant="ghost" className="min-h-10 shrink-0">
          <Link to="/courses" viewTransition><ArrowLeft aria-hidden="true" /> 学习</Link>
        </Button>
        <p className="hidden min-w-0 flex-1 truncate text-sm text-muted-foreground sm:block">{course.title}</p>
        <div className="ml-auto flex items-center gap-2">
          <Button
            ref={chatToggleRef}
            type="button"
            variant="outline"
            aria-controls="reader-chat"
            aria-expanded={showChat}
            className="min-h-10 lg:hidden"
            onClick={() => setShowChat((open) => !open)}
          >
            {showChat ? <BookOpen aria-hidden="true" /> : <MessageSquare aria-hidden="true" />}
            {showChat ? "返回阅读" : "答疑"}
          </Button>
          <ThemeSwitcher />
        </div>
      </header>
      <div className="route-content relative isolate flex min-h-0 flex-1 overflow-hidden">
        {/* 划词提问:选中正文浮出「问 AI 老师」+ 面板提示条(防系统悬浮窗遮盖)——
            都走可编辑预填:模板进输入框,用户补一句自己的话再 Enter 发 */}
        <SelectionAsk
          articleRef={articleRef}
          onSelected={setSelTerm}
          onAsk={(q) => {
            setShowChat(true);
            setPrefill(q);
            setSelTerm(null);
          }}
        />
        {/* 节目录 */}
        <nav
          aria-label="课程目录"
          style={{ width: panels.toc }}
          className="hidden max-w-[22%] shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-secondary/30 p-4 xl:flex"
        >
          <p className="mb-2 px-2 font-mono text-[11px] tracking-widest text-muted-foreground">目录</p>
          {course.sections.map((s, i) => (
            <button
              key={s.id}
              type="button"
              onClick={() => jumpToPage(i)}
              aria-current={active === i ? "location" : undefined}
              className={cn(
                "relative truncate rounded-md px-2 py-1.5 text-left text-[13px] leading-6 text-muted-foreground outline-none transition-colors hover:bg-secondary focus-visible:ring-[3px] focus-visible:ring-ring/40",
                active === i && "font-medium text-primary",
              )}
              title={s.heading}
            >
              {/* 滑动指示 pill:layoutId 让高亮底色在节间平滑迁移(motion FLIP) */}
              {active === i && (
                <motion.span
                  layoutId="toc-pill"
                  className="absolute inset-0 rounded-md bg-primary/10"
                  transition={{ duration: 0.25, ease: [0.22, 0.9, 0.3, 1] }}
                />
              )}
              <span className="relative">
                {i + 1}. {s.heading}
              </span>
            </button>
          ))}
        </nav>

        {/* 左手柄:拖拽调目录宽,双击复位 */}
        <ColResizeHandle
          label="目录栏宽"
          className="xl:flex"
          onDelta={(dx) =>
            setPanels((p) => ({ ...p, toc: clampW(p.toc + dx, 160, 400) }))
          }
          onReset={() => setPanels((p) => ({ ...p, toc: DEFAULT_PANELS.toc }))}
        />

        <main className={cn("flex min-w-0 flex-1 flex-col", showChat && "invisible lg:visible")}>
          {course.sections.length > 0 && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2 xl:hidden">
              <label htmlFor="reader-section" className="shrink-0 text-sm text-muted-foreground">目录</label>
              <select
                id="reader-section"
                value={Math.min(active, course.sections.length - 1)}
                onChange={(event) => jumpToPage(Number(event.target.value))}
                className="h-10 min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-sm text-foreground"
              >
                {course.sections.map((section, index) => (
                  <option key={section.id} value={index}>{index + 1}. {section.heading}</option>
                ))}
              </select>
            </div>
          )}
          {invite && (
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-primary/40 bg-card px-4 py-2">
              <Sparkles size={14} className="shrink-0 text-primary" aria-hidden="true" />
              <span className="mr-auto text-sm">这节课学完了，沉淀为笔记？</span>
              <Button size="sm" asChild>
                <Link to={`/courses/${course.id}?sink=1`} viewTransition>生成笔记草稿</Link>
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setInvite(false)}>稍后</Button>
            </div>
          )}
          <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto">
            <article ref={articleRef} className="mx-auto max-w-2xl px-4 py-8 font-reading sm:px-8 sm:py-12 [text-autospace:normal]">
              <header className="mb-10">
                <p className="font-mono text-xs tracking-widest text-primary">{course.scenario} · 书页版</p>
                <h1 className="mt-2 text-3xl font-semibold break-words sm:text-4xl">{course.title}</h1>
              </header>
              {course.sections.map((s, i) => (
                <section key={s.id} id={`sec-${i}`} data-sec className="mb-12 scroll-mt-6">
                  <h2 className={cn(
                    "mb-4 flex items-baseline gap-2.5 border-b border-border pb-2 text-xl font-medium tracking-tight transition-colors",
                    active === i && "border-primary/55",
                  )}>
                    <span className="font-mono text-sm text-primary">{String(i + 1).padStart(2, "0")}</span>
                    {s.heading}
                  </h2>
                  <Blocks
                    blocks={s.blocks}
                    courseId={course.id}
                    sectionId={s.id}
                    onAskTutor={onAskTutor}
                  />
                </section>
              ))}
              <EvidencePanel course={course} />
              {/* 来源清单:正文「源[N]」锚点按实际来源 id 跳转,旧课回落列表序号。
                  不进 sections 数组——TOC/学完进度/深链语义全部不受影响 */}
              {(course.meta.sources?.length ?? 0) > 0 && (
                <section id="sources" data-sec className="mb-12 scroll-mt-6">
                  <h2 className="mb-4 border-b border-border pb-2 text-lg font-medium tracking-tight text-muted-foreground">
                    来源
                  </h2>
                  <ol className="space-y-2">
                    {course.meta.sources!.map((s, i) => (
                      <li key={i} id={`src-${s.id ?? i + 1}`} className="scroll-mt-16 rounded-lg p-1.5">
                        <span className="mr-1.5 font-mono text-sm text-primary">[{s.id ?? i + 1}]</span>
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[15px] text-primary underline decoration-dotted hover:decoration-solid"
                          title={s.url}
                        >
                          {s.title}
                        </a>
                        {/* 完整显示(truncate 会截断长 URL 引发「链接没给全」的困惑;折行给全) */}
                        <span className="block pl-7 text-xs break-all text-muted-foreground">{s.url}</span>
                      </li>
                    ))}
                  </ol>
                </section>
              )}
              <LearningQuestions courseId={course.id} sections={course.sections} />
              <footer className="mt-14 border-t border-border pt-8 text-center">
                <Button onClick={onDone}>✅ 学完了,打卡</Button>
                {doneState && (
                  <p
                    className={cn(
                      "mt-3 text-[13px]",
                      doneState.ready ? "text-success" : "text-muted-foreground",
                    )}
                  >
                    ✓ 已打卡 · 检查点通过 {doneState.checkpoints_passed}/
                    {doneState.checkpoints_total}
                    {!doneState.ready && " — 通过全部检查点后,这里会邀请你沉淀为 vault 笔记"}
                  </p>
                )}
              </footer>
            </article>
          </div>
        </main>

        {/* 右手柄:拖拽调答疑宽(向左拖=变宽),双击复位 */}
        <ColResizeHandle
          label="答疑栏宽"
          className="lg:flex"
          onDelta={(dx) =>
            setPanels((p) => ({ ...p, chat: clampW(p.chat - dx, 260, 560) }))
          }
          onReset={() => setPanels((p) => ({ ...p, chat: DEFAULT_PANELS.chat }))}
        />

        {/* 答疑 */}
        <div
          id="reader-chat"
          data-open={showChat}
          style={{ width: panels.chat }}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || !showChat || !window.matchMedia("(width < 64rem)").matches) return;
            if (event.defaultPrevented || event.nativeEvent.isComposing) return;
            setShowChat(false);
            chatToggleRef.current?.focus();
          }}
          className="reader-chat flex min-w-0 shrink-0 flex-col bg-background max-lg:absolute max-lg:inset-0 max-lg:w-full! lg:max-w-[38%]"
        >
          <ChatPanel
            course={course}
            playback={playback}
            seed={chatSeed}
            onSeedConsumed={() => setChatSeed(null)}
            prefill={prefill}
            onPrefillConsumed={() => setPrefill(null)}
            selectionAsk={
              selTerm
                ? {
                    text: selTerm,
                    onAsk: () => {
                      setPrefill(selQuestion(selTerm));
                      setSelTerm(null);
                    },
                  }
                : null
            }
          />
        </div>
      </div>
    </div>
  );
}

function scrollToSection(scroller: HTMLDivElement, index: number, allowSmooth = false) {
  const section = scroller.querySelector<HTMLElement>(`#sec-${index}`);
  if (!section) return;
  const margin = Number.parseFloat(getComputedStyle(section).scrollMarginTop) || 0;
  const top = section.offsetTop - margin;
  const nearby = Math.abs(top - scroller.scrollTop) <= scroller.clientHeight;
  const smooth = allowSmooth && nearby && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // 只滚正文，避免目录和外层布局跟着 scrollIntoView 移动。
  scroller.scrollTo({ top, behavior: smooth ? "smooth" : "instant" });
}

function posKey(courseId: string) {
  return `reader-pos-${courseId}`;
}

/** 划词提问的问题文案(浮钮与面板提示条共用) */
function selQuestion(sel: string): string {
  const quote = sel.length > 100 ? `${sel.slice(0, 100)}…` : sel;
  return `我在课件里看到「${quote}」,这个概念/名词不懂,请用零基础能懂的话解释一下`;
}

/** 划词提问(2026-11-18):选中课件正文 2~200 字 → 选区上方浮出「问 AI 老师」+
 *  右侧答疑面板顶部出现「解释一下」提示条(双入口)→ 一键种子进答疑。
 *  浮钮可能被系统级悬浮窗(划词翻译等)遮盖——面板内提示条在页面内部,永远可见。
 *  正文区(article)外不弹;任何滚动即隐浮钮(提示条保留最近一次选中);fixed 定位取选区矩形。 */
function SelectionAsk({
  articleRef,
  onAsk,
  onSelected,
}: {
  articleRef: RefObject<HTMLElement | null>;
  onAsk: (q: string) => void;
  onSelected: (sel: string | null) => void;
}) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const selRef = useRef("");

  useEffect(() => {
    const hide = () => setPos(null);
    const onUp = (e: MouseEvent) => {
      // 点击提问入口自身(浮钮/提示条):mouseup 会先于 click 清掉选区,
      // 若在此清理状态会把按钮卸载、click 落空——跳过
      if ((e.target as Element)?.closest?.("[data-sel-ask]")) return;
      // 双击/拖选都先触发 selectionchange,等选区稳定再取
      window.setTimeout(() => {
        const sel = window.getSelection();
        const text = sel?.toString().trim() ?? "";
        if (
          !sel ||
          sel.rangeCount === 0 ||
          text.length < 2 ||
          text.length > 200 ||
          !articleRef.current?.contains(sel.anchorNode)
        ) {
          // 取消选中(点了空白/选区清空)→ 浮钮与提示条一起撤
          selRef.current = "";
          setPos(null);
          onSelected(null);
          return;
        }
        selRef.current = text;
        onSelected(text); // 面板提示条同步(遮不住的安全入口)
        const rect = sel.getRangeAt(0).getBoundingClientRect();
        setPos({ x: rect.left + rect.width / 2, y: rect.top });
      }, 10);
    };
    document.addEventListener("mouseup", onUp);
    window.addEventListener("scroll", hide, true); // 捕获:正文容器滚动也触发
    return () => {
      document.removeEventListener("mouseup", onUp);
      window.removeEventListener("scroll", hide, true);
    };
  }, [articleRef, onSelected]);

  if (!pos) return null;
  return (
    <button
      type="button"
      data-sel-ask
      style={{ left: pos.x, top: pos.y }}
      onClick={() => {
        const sel = selRef.current;
        window.getSelection()?.removeAllRanges();
        setPos(null);
        if (sel) onAsk(selQuestion(sel));
      }}
      className="anim-drop fixed z-50 -translate-x-1/2 -translate-y-[calc(100%+8px)] rounded-full border border-primary/40 bg-card px-3 py-1.5 text-xs font-medium text-primary shadow-lg outline-none transition-colors hover:bg-primary/10 focus-visible:ring-[3px] focus-visible:ring-ring/40"
    >
      💬 问 AI 老师
    </button>
  );
}

/** 三栏手动占比(2026-11-17):左右两栏可拖拽调宽,全局持久化(跨课一致),双击手柄复位。
 *  中栏 flex-1 自适应;正文本身保持 max-w-2xl 居中(阅读宽度是刻意设计)。 */
const DEFAULT_PANELS = { toc: 224, chat: 320 };
const PANELS_KEY = "reader-panels";
const clampW = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function ColResizeHandle({
  onDelta,
  onReset,
  label,
  className,
}: {
  onDelta: (dx: number) => void;
  onReset: () => void;
  label: string;
  className: string;
}) {
  const [dragging, setDragging] = useState(false);
  const start = (e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
    let last = e.clientX;
    const move = (ev: MouseEvent) => {
      onDelta(ev.clientX - last);
      last = ev.clientX;
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      document.body.classList.remove("select-none", "cursor-col-resize");
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    document.body.classList.add("select-none", "cursor-col-resize");
  };
  return (
    <div
      onMouseDown={start}
      onDoubleClick={onReset}
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          onDelta(event.key === "ArrowLeft" ? -16 : 16);
        } else if (event.key === "Home") {
          event.preventDefault();
          onReset();
        }
      }}
      title={`${label}:拖拽调宽,双击复位`}
      className={cn(
        "hidden w-2 shrink-0 cursor-col-resize justify-center focus-visible:bg-primary/25",
        className,
        dragging ? "bg-primary/25" : "hover:bg-primary/20",
      )}
    >
      <span
        className={cn(
          "my-auto h-full w-px",
          dragging ? "bg-primary/60" : "bg-border",
        )}
      />
    </div>
  );
}
