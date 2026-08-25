import { useCallback, useEffect, useRef, useState } from "react";
import type { RevealApi } from "reveal.js";
import type { Course } from "../../types/csl";

type RevealDeck = RevealApi;

export interface PlaybackState {
  playing: boolean;
  page: number; // 当前页索引
  sentence: number; // 当前句索引(下一句要播的)
  checkpointOpen: boolean; // 复述检查点弹层
}

const progressKey = (courseId: string) => `classroom-progress-${courseId}`;

/** 音画同步引擎:状态机 (page, sentence),音频 ended → 触发本句 fragments → 下一句/翻页。
 * reveal 只被调用 next()/slide(),节奏权完全在本引擎。
 * onCourseComplete:引擎到达课程自然终点(最后一页讲完/末页检查点通过)时回调一次——
 * 上层据此上报「学完」,驱动 P3 写回邀请。 */
export function usePlayback(
  course: Course,
  deck: () => RevealDeck | null,
  onCourseComplete?: () => void,
) {
  const [state, setState] = useState<PlaybackState>({
    playing: false,
    page: 0,
    sentence: 0,
    checkpointOpen: false,
  });
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stRef = useRef(state); // 音频回调里读最新状态
  stRef.current = state;
  const completeRef = useRef(onCourseComplete);
  completeRef.current = onCourseComplete;
  // 防重入:ended 可能重复触发(播放器怪癖/竞态),同一句只允许推进一次
  const advancedRef = useRef<string | null>(null);
  // 当前 audio.src 已加载到哪句:暂停续播时同句原地续放,不重头念
  const loadedRef = useRef<string | null>(null);
  // 引擎主动翻页/定位标记:置位时 slide 事件是引擎自己触发的,手动导航处理应忽略。
  // lastNavAt 加时间戳:同页定位只触发 fragmentchanged(不触发 slidechanged),
  // 标记可能无人消费而泄漏——过期判定防止吞掉下一次真实手动翻页(实测踩过)。
  const engineNavRef = useRef(false);
  const lastNavAt = useRef(0);
  const lastEnginePage = useRef(-1); // 引擎最近定位到的页(回声判定用:事件页号≠它→必是真人翻页)
  const resumeTimer = useRef<number | null>(null); // 快进去抖:停手后续播

  const markEngineNav = useCallback((page: number) => {
    engineNavRef.current = true;
    lastNavAt.current = Date.now();
    lastEnginePage.current = page;
  }, []);

  /** 引擎导航是否发生在近 400ms 内(自己 slide 的回声窗口) */
  const isEngineNavRecent = useCallback(() => Date.now() - lastNavAt.current < 400, []);

  const saveProgress = useCallback(
    (p: number, s: number) => {
      localStorage.setItem(progressKey(course.id), JSON.stringify({ p, s }));
    },
    [course.id],
  );

  // 恢复断点:仅挂载时执行一次(deck 为稳定引用)
  useEffect(() => {
    const saved = localStorage.getItem(progressKey(course.id));
    if (!saved) return;
    try {
      const { p } = JSON.parse(saved) as { p: number; s: number };
      if (0 < p && p < course.pages.length) {
        setState((s) => ({ ...s, page: p }));
        markEngineNav(p);
        deck()?.slide(p);
      }
    } catch {
      /* 损坏的进度直接忽略 */
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载恢复一次
  }, []);

  const audioUrl = (page: number, sentence: number) => {
    const a = course.pages[page]?.script[sentence]?.audio;
    return a ? `/courses/${a}` : null;
  };

  /** 第 page 页、讲到第 sentence 句时,累计应显示的 fragment 数(含本句)。
   * fragment 状态 = 当前句的确定函数——无论顺放/重讲/跳页,都据此精确定位,
   * 不靠增量 next() 盲推(那会在非线性入口与音频错位)。 */
  const fragmentCountUpto = useCallback(
    (page: number, sentence: number) => {
      const frags = course.pages[page]?.fragments ?? [];
      return frags.filter((f) => f.with_sentence <= sentence).length;
    },
    [course.pages],
  );

  /** 播放指定句:先把画面精确定位到该句应有的动画状态,再播音频 */
  const playSentence = useCallback(
    (page: number, sentence: number) => {
      const url = audioUrl(page, sentence);
      if (!url) {
        setState((s) => ({ ...s, playing: false }));
        return;
      }
      if (!audioRef.current) audioRef.current = new Audio();
      // 「讲到什么,亮什么」+ 精确定位:slide 到本页、fragment 索引 = 累计数-1
      // (reveal fragment 索引从 0 计,-1 表示一个都不显示)
      markEngineNav(page);
      deck()?.slide(page, 0, fragmentCountUpto(page, sentence) - 1);

      const audio = audioRef.current;
      audio.src = url;
      loadedRef.current = `${page}:${sentence}`;
      void audio.play();
      setState((s) => ({ ...s, playing: true, page, sentence }));
      saveProgress(page, sentence);
    },
    [deck, fragmentCountUpto, saveProgress],
  );

  /** 一句播完后的推进逻辑(引擎心脏) */
  const advance = useCallback(() => {
    const { page, sentence, checkpointOpen } = stRef.current;
    if (checkpointOpen) return; // 检查点未通过,引擎锁死
    const key = `${page}:${sentence}`;
    if (advancedRef.current === key) return; // 本句已推进过
    advancedRef.current = key;
    const pageData = course.pages[page];
    if (!pageData) return;

    // 2) 还有下一句 → 播下一句
    if (sentence + 1 < pageData.script.length) {
      playSentence(page, sentence + 1);
      return;
    }

    // 3) 本页讲完:检查点 → 暂停弹层
    if (pageData.checkpoint) {
      setState((s) => ({ ...s, playing: false, checkpointOpen: true }));
      return;
    }

    // 4) 翻页;最后一页 → 课程自然终点
    if (page + 1 >= course.pages.length) {
      setState((s) => ({ ...s, playing: false }));
      completeRef.current?.();
      return;
    }
    playSentence(page + 1, 0); // playSentence 内部已 slide 到新页并定位动画
  }, [course.pages, playSentence]);

  // 绑定 ended(单一来源)
  useEffect(() => {
    if (!audioRef.current) audioRef.current = new Audio();
    const audio = audioRef.current;
    const onEnded = () => advance();
    audio.addEventListener("ended", onEnded);
    return () => audio.removeEventListener("ended", onEnded);
  }, [advance]);

  // ---- 对外控制 ----

  const play = useCallback(() => {
    const { page, sentence, checkpointOpen } = stRef.current;
    if (checkpointOpen) return;
    // 同一句已在 audio 里 → 原地续放(保留暂停位置);否则才重新加载
    if (loadedRef.current === `${page}:${sentence}` && audioRef.current) {
      void audioRef.current.play();
      setState((s) => ({ ...s, playing: true }));
      return;
    }
    playSentence(page, sentence);
  }, [playSentence]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
    setState((s) => ({ ...s, playing: false }));
  }, []);

  const toggle = useCallback(() => {
    if (stRef.current.playing) pause();
    else play();
  }, [pause, play]);

  /** 手动跳页(键盘/点目录触发 slidechanged);引擎自己翻页时被 engineNavRef 挡掉 */
  const gotoPage = useCallback(
    (page: number) => {
      // 引擎自己触发的翻页:仅当「事件页号==引擎刚定位的页」且在回声窗口内才忽略。
      // 真人按键跨页的页号必不同——此前纯时间窗判定会把 400ms 内的真实跨页吞掉
      // (画面走了引擎赖在原页,音画分家,用户实测踩过)。
      if (
        engineNavRef.current &&
        page === lastEnginePage.current &&
        Date.now() - lastNavAt.current < 400
      ) {
        engineNavRef.current = false;
        return;
      }
      engineNavRef.current = false;
      const wasPlaying = stRef.current.playing;
      audioRef.current?.pause();
      advancedRef.current = null;
      setState((s) => ({ ...s, page, sentence: 0, checkpointOpen: false, playing: false }));
      saveProgress(page, 0);
      if (wasPlaying) playSentence(page, 0); // 上课中手动翻页 → 从新页接着讲
    },
    [playSentence, saveProgress],
  );

  /** 重讲本页:playSentence(page,0) 会把 fragment 收回到"只显示第0句应有"并重播 */
  const replayPage = useCallback(() => {
    const { page } = stRef.current;
    advancedRef.current = null;
    playSentence(page, 0);
  }, [playSentence]);

  /** 跳到指定页(答疑引用「课件第N页」点击用):停播、定位画面到该页开头 */
  const jumpToPage = useCallback(
    (page: number) => {
      if (page < 0 || page >= course.pages.length) return;
      audioRef.current?.pause();
      advancedRef.current = null;
      markEngineNav(page);
      deck()?.slide(page, 0, fragmentCountUpto(page, 0) - 1);
      setState((s) => ({ ...s, page, sentence: 0, checkpointOpen: false, playing: false }));
      saveProgress(page, 0);
    },
    [course.pages.length, deck, fragmentCountUpto, saveProgress, markEngineNav],
  );

  /** 手动定位到本页第 i 句(步进滑杆拖动):停播、画面亮到该句应有的动画状态 */
  const seekSentence = useCallback(
    (sentence: number) => {
      const { page } = stRef.current;
      const pageData = course.pages[page];
      if (!pageData || sentence < 0 || sentence >= pageData.script.length) return;
      audioRef.current?.pause();
      advancedRef.current = null;
      markEngineNav(page);
      deck()?.slide(page, 0, fragmentCountUpto(page, sentence) - 1);
      loadedRef.current = null; // 播放时从该句重念(不续旧音频)
      setState((s) => ({ ...s, sentence, playing: false, checkpointOpen: false }));
      saveProgress(page, sentence);
    },
    [course.pages, deck, fragmentCountUpto, saveProgress, markEngineNav],
  );

  /** 手动 fragment 步进(方向键页内步进,deck 已到位,引擎不碰画面位置):
   *  - 回声判定(确定性,不靠时间窗):可见 fragment 数 == 当前句期望值 → 引擎自己定位的回声,忽略
   *  - 对齐句号(反查:可见 fragment 数→句号)
   *  - 快进续播:原来在播 → 从对齐后的句子**接着讲**;原来暂停 → 只对齐不停播状态 */
  const onManualFragment = useCallback(
    (deckPage: number, visibleCount: number) => {
      const { page, sentence, playing, checkpointOpen } = stRef.current;
      // 跨页瞬间竞态:gotoPage→playSentence 的 slide 也会触发 fragmentchanged,
      // 而此刻 React 页号未提交(还是旧页)——若不挡,会在旧页里算出错误句号,
      // 650ms 后音频跳回旧页播(用户实测「快进后音画不同步」的真根因)。
      // 页号不一致 → 这是跨页回声,翻页只归 gotoPage 管。
      if (deckPage !== page) return;
      const pageData = course.pages[page];
      if (!pageData || checkpointOpen) return;
      if (visibleCount === fragmentCountUpto(page, sentence)) return; // 回声/已同步
      let s = 0;
      for (let i = 0; i < pageData.script.length; i++) {
        if (fragmentCountUpto(page, i) <= visibleCount) s = i;
        else break;
      }
      advancedRef.current = null;
      audioRef.current?.pause();
      loadedRef.current = null;
      setState((st) => ({ ...st, sentence: s, playing }));
      saveProgress(page, s);
      if (playing) {
        // 快进去抖续播:连按期间静默对齐,停手 650ms 后从落点接着讲——
        // 逐步重启音频会「咔哒-重来」不停,听着像解说跟不上(用户实测踩过)
        if (resumeTimer.current) window.clearTimeout(resumeTimer.current);
        resumeTimer.current = window.setTimeout(() => {
          resumeTimer.current = null;
          // 已在播(比如跨页续播已启动)就不重启同句,免得音频重头
          const a = audioRef.current;
          if (stRef.current.playing && (!a || a.paused)) {
            playSentence(stRef.current.page, stRef.current.sentence);
          }
        }, 650);
      }
    },
    [course.pages, fragmentCountUpto, playSentence, saveProgress],
  );

  /** 检查点通过,继续下一页 */
  const passCheckpoint = useCallback(() => {
    const { page } = stRef.current;
    advancedRef.current = null;
    setState((s) => ({ ...s, checkpointOpen: false }));
    if (page + 1 >= course.pages.length) {
      setState((s) => ({ ...s, playing: false }));
      completeRef.current?.(); // 末页检查点通过 = 课程自然终点
      return;
    }
    playSentence(page + 1, 0);
  }, [course.pages.length, playSentence]);

  return {
    state,
    play,
    pause,
    toggle,
    gotoPage,
    replayPage,
    passCheckpoint,
    jumpToPage,
    seekSentence,
    onManualFragment,
    isEngineNavRecent,
  };
}
