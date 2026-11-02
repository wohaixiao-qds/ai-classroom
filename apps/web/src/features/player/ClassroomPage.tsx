import { Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import type { RevealApi } from "reveal.js";

import { ThemeSwitcher } from "../../components/ThemeSwitcher";
import { Button } from "../../components/ui/button";
import { PageError, PageLoading } from "../../components/PageState";
import { ChatPanel } from "../chat/ChatPanel";
import { PageSidebar } from "./PageSidebar";
import { SlideDeck } from "./SlideDeck";
import { usePlayback } from "./usePlayback";
import type { Course } from "../../types/csl";

/** 课堂页(沉浸):左课件 + 右答疑,仅留极简返回入口 */
export function ClassroomPage() {
  const { courseId = "harness-01" } = useParams();
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deckRef = useRef<RevealApi | null>(null);
  // 稳定取值器:避免 usePlayback 依赖抖动(历史教训:曾致重渲染死循环)
  const getDeck = useCallback(() => deckRef.current, []);

  useEffect(() => {
    setCourse(null);
    setError(null);
    fetch(`/courses/${courseId}.csl.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Course>;
      })
      .then(setCourse)
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

  return (
    <Classroom
      course={course}
      getDeck={getDeck}
      onDeck={(d) => {
        deckRef.current = d;
      }}
    />
  );
}

/** 课件加载后挂载:播放引擎在顶层,左导航+课件+对话共享同一节奏源 */
function Classroom({
  course,
  getDeck,
  onDeck,
}: {
  course: Course;
  getDeck: () => RevealApi | null;
  onDeck: (d: RevealApi | null) => void;
}) {
  const [invite, setInvite] = useState(false);
  // 引擎到达自然终点 → 上报「学完」;ready(检查点也全过)→ 弹沉淀邀请
  const onCourseComplete = useCallback(() => {
    void fetch(`/api/v1/progress/${course.id}/done`, { method: "POST" })
      .then((r) => r.json())
      .then((d: { ready: boolean }) => {
        if (d.ready) setInvite(true);
      })
      .catch(() => {});
  }, [course.id]);
  const playback = usePlayback(course, getDeck, onCourseComplete);
  const [deckReady, setDeckReady] = useState(false);

  // 深链定位(?page=N,1 起算):学习台「今日复习」跳到指定检查点页。
  // 必须等 reveal initialize 完成再 slide,否则 controlsLeft 未初始化直接崩
  const [searchParams] = useSearchParams();
  const deepPage = searchParams.get("page");
  const jumpedRef = useRef(false);
  useEffect(() => {
    if (!deckReady || jumpedRef.current) return;
    const n = Number(deepPage);
    if (!Number.isInteger(n) || n < 1 || n > course.pages.length) return;
    jumpedRef.current = true;
    playback.jumpToPage(n - 1);
    // 仅进入课堂时跳一次;jumpToPage 引用稳定,不必进依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deckReady]);

  // 边栏折叠/拖宽改变 deck 宽度后,让 reveal 重新排版
  const relayout = useCallback(() => getDeck()?.layout(), [getDeck]);
  return (
    <div className="flex h-full">
      <PageSidebar course={course} playback={playback} onLayoutChange={relayout} />
      <div className="relative min-w-0 flex-1">
        <Button
          asChild
          variant="secondary"
          size="sm"
          className="absolute top-4 left-4 z-50 rounded-full bg-card/90 shadow-sm backdrop-blur"
        >
          <Link to="/">← 课表</Link>
        </Button>
        {invite && (
          <div className="absolute top-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-primary/50 bg-card/95 px-4 py-2 shadow-lg backdrop-blur">
            <Sparkles size={14} className="shrink-0 text-primary" />
            <span className="text-sm">这节课学完了,沉淀为笔记?</span>
            <Button size="sm" asChild>
              <Link to={`/courses/${course.id}?sink=1`}>生成笔记草稿</Link>
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setInvite(false)}>
              稍后
            </Button>
          </div>
        )}
        <SlideDeck
          course={course}
          playback={playback}
          onDeck={onDeck}
          onReady={() => setDeckReady(true)}
        />
      </div>
      <div className="flex w-80 shrink-0 flex-col">
        <div className="flex justify-end border-b border-l border-border bg-secondary/50 px-3 py-2">
          <ThemeSwitcher />
        </div>
        <ChatPanel course={course} playback={playback} />
      </div>
    </div>
  );
}
