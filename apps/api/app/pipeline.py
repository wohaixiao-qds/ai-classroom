"""端到端备课管线(M4):主题 → 学习框架 → [人审/auto 选子题] → 原料 → 课件 → 音频 → 发布。

一条命令验收(设计方案 §五 P2):新主题 30 分钟内变可上课课件。
人审闸在框架之后:交互模式停下让你挑子题;--auto 取第一个「你的足迹」子题
(无足迹则取第一个),供自动化/验收跑。

用法:
    uv run python -m app.pipeline "主题"                       # 交互:出框架后停下等你挑
    uv run python -m app.pipeline "主题" --subtopic "子题"      # 直接指定子题
    uv run python -m app.pipeline "主题" --auto                # 自动选子题(验收/自动化)
    uv run python -m app.pipeline "主题" --subtopic "子题" --reuse   # 复用调研缓存重跑(零联网)
    uv run python -m app.pipeline "主题" --refresh              # 先清该主题调研缓存再全新调研
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from app.services.estimate import estimate_pipeline

BUDGET_MIN = 30  # 验收红线:30 分钟内变课件


def pick_subtopic(framework: dict[str, Any], auto: bool) -> tuple[str, str | None]:
    """选子题:返回 (子题名, 前置子题名)。auto=足迹优先;交互=打印后等你输入。"""
    subs = framework["courses"]
    for i, s in enumerate(subs, 1):
        tag = "你的足迹" if s.get("origin") == "user" else "地图补充"
        pre = "←" + ",".join(s.get("prereqs", [])) if s.get("prereqs") else ""
        print(f"  {i}. {s['title']}  [{tag}]{pre} — {s.get('goal') or s.get('why', '')}")
    idx = 0
    if auto:
        for i, s in enumerate(subs):
            if s.get("origin") == "user":
                idx = i
                break
    else:
        raw = input(f"选哪个子题(1~{len(subs)},回车=1): ").strip()
        idx = (int(raw) - 1) if raw.isdigit() and 1 <= int(raw) <= len(subs) else 0
    chosen = subs[idx]
    prev = subs[idx - 1]["title"] if idx > 0 else None  # 位置感:框架里的上一课
    print(f"\n→ 本次备课:「{chosen['title']}」(前置:{prev or '无,第一课'})")
    est = estimate_pipeline()
    print(
        f"⏱ 预计:原料调研 ≈{est['research']['min']} 分钟 / {int(est['research']['calls'])} 轮"
        f" · 备课 ≈{est['prep']['min']} 分钟 / {int(est['prep']['calls'])} 轮"
        f" · 合计 ≈{est['total_min']} 分钟({est['source']};红线 {BUDGET_MIN})"
    )
    return chosen["title"], prev


def run_pipeline(
    topic: str,
    subtopic: str | None = None,
    auto: bool = False,
    reuse: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    from app.agent.prep import confirm_depends_on, run_prep
    from app.agent.research import (
        cached_framework,
        cached_material,
        clear_research_cache,
        research_framework,
        research_material,
    )
    from app.services.tts_compile import publish_courses

    t0 = time.perf_counter()
    if refresh:
        n = clear_research_cache(topic, subtopic)
        print(f"♻️ 已清除调研缓存 {n} 个文件,全新调研")
    print("① 学习框架(双源:权威地图 + 你的待探足迹)…")
    fw = (reuse and cached_framework(topic)) or research_framework(topic)
    n_prereq = sum(1 for c in fw["courses"] if c.get("prereqs"))
    print(f"大纲 {len(fw['courses'])} 门课(先修链 {n_prereq} 条):")
    prev = None
    if subtopic:
        titles = [c["title"] for c in fw["courses"]]
        i = titles.index(subtopic) if subtopic in titles else 0
        prev = titles[i - 1] if i > 0 else None
        print(f"→ 指定子题:「{subtopic}」(前置:{prev or '无'})")
    else:
        subtopic, prev = pick_subtopic(fw, auto)

    print("\n② 子题原料(带来源硬闸)…")
    material = (reuse and subtopic and cached_material(topic, subtopic)) or research_material(
        topic, subtopic
    )
    # 大纲→vault 目录同步(全自动跟随)+ 写回落点=大纲篇目录
    from app.services.vault_sync import sync_outline, theme_area

    sync_outline(fw, topic=topic)
    area = theme_area(fw)
    if area:
        entry = next((c for c in fw["courses"] if c["title"] == subtopic), None)
        part = str((entry or {}).get("part") or "").strip()
        material["topic"] = f"{area} / {part}" if part else area
    else:
        # 兜底:vault 不可用时退回待探行归位(老机制)
        from app.services.catalog import find_todo_area

        fallback = find_todo_area(subtopic)
        if fallback:
            material["topic"] = fallback
    n_pts = sum(len(g.get("points", [])) for g in material["groups"])
    print(f"原料:{n_pts} 条要点 / {len(material['sources'])} 个来源")

    print("\n③ 备课循环(写→验→改,客观终止)…")
    selected: dict[str, Any] = next((c for c in fw["courses"] if c["title"] == subtopic), {})
    goal = str(selected.get("goal") or "")
    prereqs = [c["title"] for c in fw["courses"] if c["id"] in selected.get("prereqs", [])]
    r = run_prep(material, prev_subtopic=prev, learning_goal=goal, prerequisite_titles=prereqs)
    if not r["ok"]:
        print("⚠️ 备课软着陆,人工接着审")
        return r
    course = r["course"]

    if not auto:  # 交互模式:先修建议过一眼人审;auto(生成中心)直接落盘,日志可查
        confirm_depends_on(course)

    from app.services.publication import ensure_publication

    course = ensure_publication(course, material, learning_goal=goal, prerequisite_titles=prereqs)
    r["course"] = course
    print("\n④ 发布前端…")
    publish_courses(str(course["id"]))
    mins = (time.perf_counter() - t0) / 60
    secs = course.get("sections", [])
    n_quiz = sum(1 for s in secs for b in s.get("blocks", []) if b.get("type") == "quiz")
    print(
        f"\n{'✅' if mins <= BUDGET_MIN else '⚠️ 超时'} 交付:courses/{course['id']}.csl.json "
        f"| {len(secs)} 节 / {sum(len(s.get('blocks', [])) for s in secs)} 块 / "
        f"{n_quiz} 检查点 | 总耗时 {mins:.1f} 分钟"
        f"(红线 {BUDGET_MIN})"
    )
    r["minutes"] = round(mins, 1)
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="端到端备课管线")
    ap.add_argument("topic")
    ap.add_argument("--subtopic")
    ap.add_argument("--auto", action="store_true")
    cache = ap.add_mutually_exclusive_group()
    cache.add_argument(
        "--reuse", action="store_true", help="框架/原料命中缓存则不联网(改备课 prompt 重跑同主题用)"
    )
    cache.add_argument("--refresh", action="store_true", help="先清除该主题调研缓存再全新调研")
    a = ap.parse_args()
    run_pipeline(a.topic, subtopic=a.subtopic, auto=a.auto, reuse=a.reuse, refresh=a.refresh)
