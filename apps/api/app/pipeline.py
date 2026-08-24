"""端到端备课管线(M4):主题 → 学习框架 → [人审/auto 选子题] → 原料 → 课件 → 音频 → 发布。

一条命令验收(设计方案 §五 P2):新主题 30 分钟内变可上课课件。
人审闸在框架之后:交互模式停下让你挑子题;--auto 取第一个「你的足迹」子题
(无足迹则取第一个),供自动化/验收跑。

用法:
    uv run python -m app.pipeline "主题"                       # 交互:出框架后停下等你挑
    uv run python -m app.pipeline "主题" --subtopic "子题"      # 直接指定子题
    uv run python -m app.pipeline "主题" --auto                # 自动选子题(验收/自动化)
"""

from __future__ import annotations

import argparse
import time
from typing import Any

BUDGET_MIN = 30  # 验收红线:30 分钟内变课件


def pick_subtopic(framework: dict[str, Any], auto: bool) -> tuple[str, str | None]:
    """选子题:返回 (子题名, 前置子题名)。auto=足迹优先;交互=打印后等你输入。"""
    subs = framework["subtopics"]
    for i, s in enumerate(subs, 1):
        tag = "你的足迹" if s.get("origin") == "user" else "地图补充"
        print(f"  {i}. {s['title']}  [{tag}] — {s.get('why', '')}")
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
    return chosen["title"], prev


def run_pipeline(topic: str, subtopic: str | None = None, auto: bool = False) -> dict[str, Any]:
    from app.agent.prep import run_prep
    from app.agent.research import research_framework, research_material
    from app.services.tts_compile import compile_course_audio, publish_courses

    t0 = time.perf_counter()
    print("① 学习框架(双源:权威地图 + 你的待探足迹)…")
    fw = research_framework(topic)
    print(f"框架 {len(fw['subtopics'])} 个子题:")
    prev = None
    if subtopic:
        titles = [s["title"] for s in fw["subtopics"]]
        i = titles.index(subtopic) if subtopic in titles else 0
        prev = titles[i - 1] if i > 0 else None
        print(f"→ 指定子题:「{subtopic}」(前置:{prev or '无'})")
    else:
        subtopic, prev = pick_subtopic(fw, auto)

    print("\n② 子题原料(带来源硬闸)…")
    material = research_material(topic, subtopic)
    n_pts = sum(len(g.get("points", [])) for g in material["groups"])
    print(f"原料:{n_pts} 条要点 / {len(material['sources'])} 个来源")

    print("\n③ 备课循环(写→验→改,客观终止)…")
    r = run_prep(material, prev_subtopic=prev)
    if not r["ok"]:
        print("⚠️ 备课软着陆,人工接着审")
        return r
    course = r["course"]

    print("\n④ 音频编译 + 发布前端…")
    done, fail = compile_course_audio(str(course["id"]))
    publish_courses()
    mins = (time.perf_counter() - t0) / 60
    cp = sum(1 for p in course["pages"] if p.get("checkpoint"))
    print(
        f"\n{'✅' if mins <= BUDGET_MIN else '⚠️ 超时'} 交付:courses/{course['id']}.csl.json "
        f"| {len(course['pages'])} 页 / {sum(len(p['script']) for p in course['pages'])} 句 / "
        f"{cp} 检查点 / 音频 {done} 句(失败 {fail}) | 总耗时 {mins:.1f} 分钟"
        f"(红线 {BUDGET_MIN})"
    )
    r["minutes"] = round(mins, 1)
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="端到端备课管线")
    ap.add_argument("topic")
    ap.add_argument("--subtopic")
    ap.add_argument("--auto", action="store_true")
    a = ap.parse_args()
    run_pipeline(a.topic, subtopic=a.subtopic, auto=a.auto)
