"""找资料 Agent(P2·M2a)—— 学新课题的调研循环:框架(双源) + 子题原料(带来源)。

设计(docs/P2执行计划.md M2a,2026-08-24 定稿):
- 两阶段,中间人审:先出学习框架交用户审,再对选定子题深挖原料
- 框架双源合流:源A 权威地图(联网扫官方文档/高星项目/教程目录);
  源B 用户足迹(vault 待探清单,主题已有时注入)。用户顺序优先、地图缺口显式标出
- 有据硬闸:原料每条要点必挂 source_id,落盘前程序校验,缺源打回重交(机制非恳求)
- 终止:交付物 JSON 通过校验(客观判据);MAX_TURNS=16 软着陆
- 离线 CLI:非流式调用,trace 落 research.jsonl

用法:
    uv run python -m app.agent.research "主题"                     # 阶段1:框架
    uv run python -m app.agent.research "主题" --subtopic "子题"   # 阶段2:原料
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from app.agent.tools import fetch_page, web_search
from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.trace import trace_research

MAX_TURNS = 16

RESEARCH_TOOLS = [
    {
        "name": "web_search",
        "description": "联网搜索。调研学习框架/子题资料时用,"
        "优先权威源(官方文档、高星项目、经典教程)。",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索词"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "抓取网页正文(带[标题|URL]头,正文截断)。"
        "搜索结果值得深读时用;引用内容必记该 URL。",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "完整 URL"}},
            "required": ["url"],
        },
    },
]

_FRAMEWORK_PROMPT = """你是学习路线调研员,为一个学习主题产出「学习框架」——拆成可逐课学习的子题清单。

主题:{topic}

{seed}

先 web_search 扫该主题的权威知识地图(官方文档目录结构 / GitHub 高星项目 docs /
经典教程章节),再按下述规则合流:
- 用户清单里已有的子题:保留,且排在前面、保持用户的相对顺序(origin 标 "user")
- 地图里有、用户清单没有的:列为补充(origin 标 "map")——这是用户清单外的缺口
- 用户有、地图没有的:保留(origin 标 "user",独特衍生往往最值钱)

只输出 JSON(不要其他内容):
{{"topic": "{topic}",
  "subtopics": [{{"title": "子题名", "why": "一句话:学它解决什么", "origin": "user|map"}}]}}
子题 5~10 个,每个都是一节课能讲完的粒度(参照「harness 是什么」≈8分钟一课)。"""

_MATERIAL_PROMPT = """你是课题调研员,为课件作者收集一个子题的带来源原料。
底线:**每条要点都必须有据可查**。

主题:{topic} / 本次子题:{subtopic}

用 web_search 找权威资料,fetch_page 深读值得读的原文。凑够 8~20 条要点、3 个以上不同来源再交付。

只输出 JSON(不要其他内容):
{{"topic": "{topic}",
  "subtopic": "{subtopic}",
  "sources": [{{"id": 1, "title": "来源标题", "url": "https://…"}}],
  "groups": [{{"heading": "要点组名",
               "points": [{{"text": "要点(一句)", "source_id": 1,
                            "quote": "原文关键片段(可选)"}}]}}]}}

硬规则:points 里每条的 source_id 必须是 sources 里出现过的 id;拿不准的内容不要写。"""


# ---------- 交付物校验(有据硬闸;返回错误清单,空=通过) ----------


def validate_framework(d: dict[str, Any]) -> list[str]:
    subs = d.get("subtopics")
    if not isinstance(subs, list) or not subs:
        return ["subtopics 缺失或为空——至少给出 5 个子题"]
    errs = []
    for i, s in enumerate(subs, 1):
        if not isinstance(s, dict) or not str(s.get("title", "")).strip():
            errs.append(f"第{i}个子题缺 title")
        if str(s.get("origin", "")) not in ("user", "map"):
            errs.append(f"第{i}个子题 origin 必须是 user 或 map")
    return errs


def validate_material(d: dict[str, Any]) -> list[str]:
    srcs = d.get("sources")
    groups = d.get("groups")
    if not isinstance(srcs, list) or not srcs:
        return ["sources 缺失——至少 3 个来源"]
    if not isinstance(groups, list) or not groups:
        return ["groups 缺失或为空"]
    ids: set[int] = set()
    urls: set[str] = set()
    errs: list[str] = []
    for i, s in enumerate(srcs, 1):
        if not isinstance(s, dict) or not str(s.get("url", "")).startswith("http"):
            errs.append(f"来源[{i}] url 非法")
            continue
        if not str(s.get("title", "")).strip():
            errs.append(f"来源[{i}] 缺 title")
        sid = s.get("id")
        if isinstance(sid, int):
            ids.add(sid)
            urls.add(str(s["url"]))
    n_points = 0
    for gi, g in enumerate(groups, 1):
        for pi, p in enumerate(g.get("points", []) if isinstance(g, dict) else [], 1):
            n_points += 1
            pid = p.get("source_id") if isinstance(p, dict) else None
            if not isinstance(pid, int) or pid not in ids:
                errs.append(
                    f"第{gi}组第{pi}条要点 source_id={pid!r} 不在来源清单——缺源,补上或删掉该条"
                )
    if n_points < 8:
        errs.append(f"要点只有 {n_points} 条(目标 8~20)——再挖一挖")
    if len(urls) < 3:
        errs.append(f"来源只有 {len(urls)} 个不同 URL(目标≥3)——来源太单薄")
    return errs


# ---------- 共享循环骨架 ----------


def _json_from_text(text: str) -> dict[str, Any] | None:
    """从模型最终回复抠 JSON(容忍 ```json 围栏)。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").removeprefix("json").strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        d = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def _execute(name: str, args: dict[str, Any]) -> str:
    if name == "web_search":
        return web_search(args["query"])
    if name == "fetch_page":
        return fetch_page(args["url"])
    return f"(未知工具 {name})"


def _user_seed(topic: str) -> str:
    """源B:扫 vault 待探清单里与主题相关的未打勾项(用户足迹,只读)。"""
    kb = settings.kb_dir
    if not kb.is_dir():
        return ""
    lines: list[str] = []
    for md in kb.rglob("*待探*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        if topic.split()[0] not in text:
            continue
        for ln in text.splitlines():
            if ln.strip().startswith(("- [ ]", "- [x]")):
                lines.append(ln.strip())
    if not lines:
        return "用户知识库中没有该主题的既有足迹(全新主题)。"
    return "用户的既有足迹(待探清单,顺序即用户意愿):\n" + "\n".join(lines[:30])


def _loop(
    prompt: str,
    validator: Callable[[dict[str, Any]], list[str]],
    topic: str,
    phase: str,
) -> dict[str, Any]:
    """调研循环:工具轮 → 最终交付 JSON → 校验,不过则反馈重交。校验通过才返回。"""
    client = get_llm_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_calls: list[dict[str, Any]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    t0 = time.perf_counter()
    last_err: list[str] = []

    for turn in range(MAX_TURNS):
        last_turn = turn == MAX_TURNS - 1
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=8192,
            messages=messages,  # type: ignore[arg-type]  # dict 字面量 vs SDK TypedDict,同 tutor.py 现象
            tools=[] if last_turn else RESEARCH_TOOLS,  # type: ignore[arg-type]
        )
        u = resp.usage
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0

        if resp.stop_reason != "tool_use":
            d = _json_from_text("".join(b.text for b in resp.content if b.type == "text"))
            if d is None:
                messages.append({"role": "assistant", "content": "…"})
                messages.append(
                    {"role": "user", "content": "没解析出 JSON。只输出 JSON 本体,不要别的文字。"}
                )
                continue
            errs = validator(d)
            if not errs:
                d["_usage"] = usage
                trace_research(
                    topic=topic,
                    material_path=phase,
                    tool_calls=tool_calls,
                    ok=True,
                    elapsed_s=time.perf_counter() - t0,
                    usage=usage,
                )
                return d
            last_err = errs
            messages.append({"role": "assistant", "content": "…"})
            messages.append(
                {
                    "role": "user",
                    "content": "交付物不合格,逐条修完重新输出完整 JSON:\n- "
                    + "\n- ".join(errs),
                }
            )
            continue

        messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            ts = time.time()
            try:
                out, err = _execute(b.name, dict(b.input)), None
            except Exception as e:  # noqa: BLE001 工具炸了不拖垮循环(错误回收)
                out, err = f"(抓取失败: {e})", str(e)
            tool_calls.append(
                {
                    "name": b.name,
                    "args": dict(b.input),
                    "ms": round((time.time() - ts) * 1000),
                    "error": err,
                }
            )
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        messages.append({"role": "user", "content": results})

    trace_research(
        topic=topic,
        material_path=phase,
        tool_calls=tool_calls,
        ok=False,
        elapsed_s=time.perf_counter() - t0,
        usage=usage,
        error=f"MAX_TURNS 耗尽;最后的校验问题: {last_err[:3]}",
    )
    msg = f"调研未在 {MAX_TURNS} 轮内交付合格结果(最后问题: {last_err[:3]})"
    raise RuntimeError(msg)


def _slug(s: str) -> str:
    return re.sub(r"[^\w-]+", "-", s).strip("-")[:40] or "topic"


def _save(d: dict[str, Any], filename: str) -> None:
    p = settings.data_dir / "research" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    d.pop("_usage", None)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已落盘: {p}")


def research_framework(topic: str) -> dict[str, Any]:
    """阶段1:学习框架(双源合流)。产出交用户审——缺口补不补、子题选哪个,人拍板。"""
    d = _loop(
        _FRAMEWORK_PROMPT.format(topic=topic, seed=_user_seed(topic)),
        validate_framework,
        topic,
        "framework",
    )
    _save(d, f"{_slug(topic)}.framework.json")
    return d


def research_material(topic: str, subtopic: str) -> dict[str, Any]:
    """阶段2:选定子题的带来源原料(备课 agent 的输入)。"""
    d = _loop(
        _MATERIAL_PROMPT.format(topic=topic, subtopic=subtopic),
        validate_material,
        topic,
        f"material:{subtopic}",
    )
    path = f"{_slug(topic)}.{_slug(subtopic)}.material.json"
    _save(d, path)
    d["_material_path"] = str(settings.data_dir / "research" / path)  # 管线往下传
    return d


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="找资料 Agent:框架(阶段1)/ 子题原料(阶段2)")
    ap.add_argument("topic")
    ap.add_argument("--subtopic", help="不传=阶段1出框架;传=阶段2出该子题原料")
    a = ap.parse_args()
    if a.subtopic:
        m = research_material(a.topic, a.subtopic)
        n_pts = sum(len(g.get("points", [])) for g in m["groups"])
        print(f"\n子题「{a.subtopic}」原料:{n_pts} 条要点 / {len(m['sources'])} 个来源")
    else:
        f = research_framework(a.topic)
        print(f"\n学习框架({len(f['subtopics'])} 个子题):")
        for i, s in enumerate(f["subtopics"], 1):
            tag = "你的足迹" if s.get("origin") == "user" else "地图补充(清单外缺口)"
            print(f"  {i}. {s['title']}  [{tag}] — {s.get('why', '')}")
        print('\n下一步:审完框架,挑一个子题跑 --subtopic "子题名"')
