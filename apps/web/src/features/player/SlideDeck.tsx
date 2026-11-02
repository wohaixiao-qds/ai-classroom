import { useEffect, useRef, useState } from "react";
import Reveal from "reveal.js";
import type { RevealApi } from "reveal.js";
import { CircleCheck, X } from "lucide-react";
import type { Course } from "../../types/csl";
import { SlidePage } from "./pages";
import { ControlsBar } from "./ControlsBar";
import { CheckpointOverlay } from "./CheckpointOverlay";
import { SubtitleBar } from "./SubtitleBar";
import { usePlayback } from "./usePlayback";

/** reveal.js 只负责翻页与 fragment 步进;React 负责 DOM 渲染;
 * usePlayback 负责节奏(音频 ended → 步进/翻页/检查点)。 */
export function SlideDeck({
  course,
  playback,
  onDeck,
  onReady,
}: {
  course: Course;
  playback: ReturnType<typeof usePlayback>;
  onDeck: (deck: RevealApi | null) => void;
  onReady?: () => void; // initialize 完成(deep-link 跳页要等它,否则 slide 会崩)
}) {
  const [ready, setReady] = useState(false);
  const [overviewOpen, setOverviewOpen] = useState(false);
  const deckEl = useRef<HTMLDivElement>(null);
  const digitsRef = useRef("");
  const overviewRef = useRef(false);
  overviewRef.current = overviewOpen; // 键盘回调里读最新值

  useEffect(() => {
    if (!deckEl.current) return;
    const deck = new Reveal(deckEl.current, {
      hash: false, // 节奏权交给播放引擎,不用 hash 记页
      controls: false, // 控制统一到底部控制条
      progress: true,
      transition: "fade", // 翻页 cross-fade(过场打磨)
      keyboard: { 32: () => {}, 78: () => {}, 80: () => {} }, // 方向键仍可用;空格/N/P 交给播放引擎
    });
    onDeck(deck);
    void deck.initialize().then(() => {
      setReady(true);
      onReady?.();
    });

    // 焦点在输入类元素(打字中)时让路,不抢按键
    const isTyping = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return (
        tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable
      );
    };

    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return; // 打字中:按键归输入框
      if (e.code === "Space") {
        e.preventDefault();
        playback.toggle();
        return;
      }
      // o = 页总览(Slidev 式);总览开着时 ESC/o 关闭
      if (e.key === "o" || e.key === "O") {
        setOverviewOpen((v) => !v);
        return;
      }
      if (e.key === "Escape" && overviewRef.current) {
        setOverviewOpen(false);
        return;
      }
      // f = 全屏切换
      if (e.key === "f" || e.key === "F") {
        if (document.fullscreenElement) void document.exitFullscreen();
        else void document.documentElement.requestFullscreen();
        return;
      }
      // 数字+回车 = 跳页(连敲几位页码)
      if (/^[0-9]$/.test(e.key)) {
        digitsRef.current += e.key;
        return;
      }
      if (e.key === "Enter" && digitsRef.current && !overviewRef.current) {
        const n = Number(digitsRef.current);
        digitsRef.current = "";
        if (n >= 1 && n <= course.pages.length) playback.jumpToPage(n - 1);
      }
    };
    document.addEventListener("keydown", onKey);

    // 手动翻页(键盘) → 同步引擎状态
    const onSlide = (e: Event) => playback.gotoPage((e as unknown as { indexh: number }).indexh);
    deck.on("slidechanged", onSlide);

    // 手动 fragment 步进(方向键页内)→ 对齐引擎句号(回声由引擎内确定性比对排除)。
    // 此前引擎对此事件是聋的:画面走了 sentence 停在原地,再播放就把画面拽回去(音画分家)。
    const onFrag = () => {
      requestAnimationFrame(() => {
        // 带上画面真实页号(而非引擎状态):跨页瞬间的回声靠它识别
        const slides = [...document.querySelectorAll(".reveal .slides > section")];
        const cur = slides.findIndex((el) => el.classList.contains("present"));
        playback.onManualFragment(
          cur,
          document.querySelectorAll(".present .fragment.visible").length,
        );
      });
    };
    // 注意:reveal 的事件是 fragmentshown/fragmenthidden——不存在 fragmentchanged!
    // (曾监听不存在的事件,引擎对页内步进全程失聪,三连修无效的根中根)
    deck.on("fragmentshown", onFrag);
    deck.on("fragmenthidden", onFrag);
    return () => {
      document.removeEventListener("keydown", onKey);
      deck.off("slidechanged", onSlide);
      deck.off("fragmentshown", onFrag);
      deck.off("fragmenthidden", onFrag);
      void deck.destroy();
      onDeck(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deck 初始化仅一次
  }, []);

  const sentences = course.pages[playback.state.page]?.script.length ?? 0;

  return (
    <>
      <div className="reveal" ref={deckEl}>
        <div className="slides">
          {course.pages.map((p) => (
            <SlidePage key={p.id} page={p} />
          ))}
        </div>
      </div>
      <SubtitleBar course={course} playback={playback} />
      <ControlsBar
        playback={playback}
        totalPages={course.pages.length}
        sentences={sentences}
        ready={ready}
        onOverview={() => setOverviewOpen(true)}
      />
      {playback.state.checkpointOpen && (
        <CheckpointOverlay
          question={course.pages[playback.state.page].checkpoint?.question ?? ""}
          hint={course.pages[playback.state.page].checkpoint?.hint ?? null}
          courseId={course.id}
          pageId={course.pages[playback.state.page].id}
          onPass={playback.passCheckpoint}
        />
      )}
      {overviewOpen && (
        <PageOverview course={course} playback={playback} onClose={() => setOverviewOpen(false)} />
      )}
    </>
  );
}

/** 页总览网格(Slidev Quick Overview 式,o 键/控制条呼出;双击进页) */
function PageOverview({
  course,
  playback,
  onClose,
}: {
  course: Course;
  playback: ReturnType<typeof usePlayback>;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-60 flex flex-col bg-overlay p-8 backdrop-blur-md"
      onClick={onClose}
    >
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">全课结构 · 点击进页(检查点页有标记)</p>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
          title="关闭(Esc / O)"
        >
          <X size={18} />
        </button>
      </div>
      <div className="grid flex-1 content-start gap-3 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
        {course.pages.map((p, i) => (
          <button
            key={p.id}
            onClick={(e) => {
              e.stopPropagation();
              playback.jumpToPage(i);
              onClose();
            }}
            className={`flex flex-col gap-2 rounded-xl border p-4 text-left transition-all hover:-translate-y-0.5 ${
              i === playback.state.page
                ? "border-primary bg-primary/10 shadow-md"
                : "border-border bg-card hover:border-primary/60 hover:shadow-md"
            }`}
          >
            <span className="font-mono text-xs text-muted-foreground">第 {i + 1} 页</span>
            <span className="text-sm font-medium">{p.title || p.eyebrow || p.id}</span>
            {p.checkpoint && (
              <span className="flex items-center gap-1 text-xs text-primary">
                <CircleCheck size={12} /> 检查点
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
