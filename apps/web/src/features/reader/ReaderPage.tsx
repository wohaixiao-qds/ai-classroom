import { Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
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
            <Link to="/">← 返回学习台</Link>
          </Button>
        }
      />
    );
  if (!course) return <PageLoading label="课件加载中…" />;
  return <Reader key={course.id} course={course} />;
}

function Reader({ course }: { course: CourseV2 }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const [invite, setInvite] = useState(false);
  const [doneState, setDoneState] = useState<CompletionState | null>(null);
  const [chatSeed, setChatSeed] = useState<
    { text: string; checkpoint: CheckpointAskPayload } | null
  >(null);
  const [searchParams] = useSearchParams();
  const restoredRef = useRef(false);

  // 批改→答疑联动:复述没过,带着检查点全上下文去问 AI 老师
  const onAskTutor = useCallback((p: CheckpointAskPayload) => {
    setChatSeed({
      text: `我在复述检查点没过:「${p.question}」。我的回答:「${p.answer}」。帮我搞懂薄弱点。`,
      checkpoint: p,
    });
  }, []);

  /** 答疑侧栏的进度适配器:当前节 + 跳节(引用侧「第N页」按钮沿用) */
  const jumpToPage = useCallback((n: number) => {
    scrollRef.current?.querySelector(`#sec-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
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
    if (target >= 0) el.querySelector(`#sec-${target}`)?.scrollIntoView({ block: "start" });
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

  return (
    <div className="flex h-full">
      {/* 节目录 */}
      <nav className="hidden w-56 shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-secondary/30 pl-3 pr-4 py-4 md:flex">
        <p className="mb-2 px-2 font-mono text-[11px] tracking-widest text-muted-foreground">目录</p>
        {course.sections.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => jumpToPage(i)}
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

      {/* 正文 */}
      <div className="relative min-w-0 flex-1">
        <Button
          asChild
          variant="secondary"
          size="sm"
          className="absolute top-4 left-4 z-40 rounded-full bg-card/90 shadow-sm backdrop-blur"
        >
          <Link to="/">← 课表</Link>
        </Button>
        {invite && (
          <div className="anim-drop absolute top-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-primary/50 bg-card/95 px-4 py-2 shadow-lg backdrop-blur">
            <Sparkles size={14} className="shrink-0 text-primary" />
            <span className="text-sm">这节课学完了,沉淀为笔记?</span>
            <Button size="sm" asChild>
              <Link to={`/courses/${course.id}?sink=1`} viewTransition>
                生成笔记草稿
              </Link>
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setInvite(false)}>
              稍后
            </Button>
          </div>
        )}
        <div ref={scrollRef} onScroll={onScroll} className="h-full overflow-y-auto">
          <article className="mx-auto max-w-2xl px-6 py-16 font-reading [text-autospace:normal]">
            <header className="mb-10">
              <p className="font-mono text-xs tracking-widest text-primary">{course.scenario} · 书页版</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight">{course.title}</h1>
            </header>
            {course.sections.map((s, i) => (
              <section key={s.id} id={`sec-${i}`} data-sec className="mb-12 scroll-mt-6">
                <h2 className="mb-4 flex items-baseline gap-2.5 border-b border-border pb-2 text-xl font-medium tracking-tight">
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
      </div>

      {/* 答疑 */}
      <div className="flex w-80 shrink-0 flex-col">
        <div className="flex justify-end border-b border-l border-border bg-secondary/50 px-3 py-2">
          <ThemeSwitcher />
        </div>
        <ChatPanel
          course={course}
          playback={playback}
          seed={chatSeed}
          onSeedConsumed={() => setChatSeed(null)}
        />
      </div>
    </div>
  );
}

function posKey(courseId: string) {
  return `reader-pos-${courseId}`;
}
