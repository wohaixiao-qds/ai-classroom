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
from pathlib import Path
from typing import Any

from app.agent.tools import (  # noqa: F401  # web_search 供 _require_search 探针
    emit_call,
    fetch_page,
    web_search,
)
from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.trace import trace_research

MAX_TURNS = 16

RESEARCH_TOOLS = [
    {
        "name": "web_search",
        "description": "联网搜索(自动多引擎合并:中文社区+官方英文)。"
        "调研学习框架/子题资料时用;涉及版本号/规范/最新实践时传 recency 并优先官方域名。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索词"},
                "recency": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year"],
                    "description": "时效过滤:版本/最新实践类查询建议 month 或 year",
                },
            },
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

_FRAMEWORK_PROMPT = """你是课程大纲设计师,为一个**零基础学习者**设计「从入门到精通的完整学习路线」。

主题:{topic}

先 web_search 扫该主题的权威知识地图(官方文档目录结构 / GitHub 高星项目 docs /
经典教程章节;默认限定近一年,时效敏感处用 week/month 再扫一遍)——大纲以权威
地图为纲,**不预设学习者有任何基础**。

只输出 JSON(不要其他内容):
{{"topic": "{topic}",
  "domain": "领域名(2~6字,如 Agent 工程)",
  "courses": [
    {{"id": "英文短横线slug",
      "title": "课名(具体,如「解析层:模型输出与工具执行的桥梁」)",
      "goal": "学完能做什么(可验证的行为,禁「了解/熟悉」)",
      "why": "一句话:为什么它值得学/为什么放这个位置",
      "prereqs": ["前置课的id(只能取本列表内的id;入口课给 [])"],
      "part": "所属学习阶段(2~6字,如「起步」「核心机制」「工程化」「实战」)",
      "origin": "map"}}
  ]}}

硬规则:
- 3~8 门课,每门都是一节能讲完的粒度(参照「harness 是什么」≈8 分钟一课)
- part = 学习阶段,从基础到进阶排列;同篇回答同一个大问题,篇名 2~6 字
- 课程顺序即学习顺序:每门课只依赖它前面的课(prereqs 成 DAG),入口课无前置
- goal 写「学完能做什么」的可验证行为,禁「了解/熟悉」
- 沿 prereqs 走完全部课 = 零基础学习者完整走完该主题的入门,不留断链"""

_MATERIAL_PROMPT = """你是课题调研员,为课件作者收集一个子题的带来源原料。
底线:**每条要点都必须有据可查**。

主题:{topic} / 本次子题:{subtopic}

调研分两步走:
第〇步(必做):先用 recency=week 搜「主题 + 最新 release/开源/版本/动向」,确认近一周
有没有大事件(新版本、开源、安全公告)——有则纳入要点,别等捡到;没有再进第一步。
第一步:常规搜集,fetch_page 深读原文,凑够 8~20 条要点、3 个以上不同来源再交付。

来源三要求(按此配比挑,不是随便搜到什么用什么):
1. **最权威**:官方文档/规范/官方 changelog 打底(概念与机制的唯一依据)
2. **最新**:版本/规范/生态动向必须来自官方且近一年内(recency=year 起步,越新越好)
3. **生产级经验**:至少 2 个来源是一线实践——官方博客的生产案例、大厂工程博客、
   高星项目的 README/ISSUE/迁移指南;要踩坑、性能、上线取舍这类「打过仗」的内容,
   不要纯概念科普文凑数

只输出 JSON(不要其他内容):
{{"topic": "{topic}",
  "subtopic": "{subtopic}",
  "sources": [{{"id": 1, "title": "来源标题", "url": "https://…"}}],
  "groups": [{{"heading": "要点组名",
               "points": [{{"text": "要点(一句)", "source_id": 1,
                            "quote": "原文关键片段(可选)"}}]}}]}}

硬规则:points 里每条的 source_id 必须是 sources 里出现过的 id;
**sources 里每个 url 都必须是你用 fetch_page 实际抓取成功的**(没抓过的网址不许列)——
有据的意思是「真的读过」,不是「记得有这篇」;
**版本号/规范条目/最新实践必须来自官方域名或其 changelog**(如 modelcontextprotocol.io、
github.com 官方 org、官方博客),社区文章只能作解释性补充;查这类信息时给 web_search 传
recency。拿不准的内容不要写。"""


# ---------- 交付物校验(有据硬闸;返回错误清单,空=通过) ----------


def validate_framework(d: dict[str, Any], fetched: set[str] | None = None) -> list[str]:
    """领域大纲校验(P7·M1):3~8 门、id 唯一、goal 可验证、prereqs 合法且成 DAG。"""
    courses = d.get("courses")
    if not isinstance(courses, list) or not courses:
        return ["courses 缺失或为空"]
    # legacy 转换的大纲(旧 subtopics)免课数闸——历史形状如实保留,闸只管新设计
    if not d.get("legacy") and not 3 <= len(courses) <= 8:
        return ["courses 数量不在 3~8——大纲至少 3 门,至多 8 门"]
    errs: list[str] = []
    ids: set[str] = set()
    for i, c in enumerate(courses, 1):
        if not isinstance(c, dict):
            errs.append(f"第{i}门课不是对象")
            continue
        cid = str(c.get("id", "")).strip()
        if not cid:
            errs.append(f"第{i}门课缺 id")
        elif cid in ids:
            errs.append(f"课 id「{cid}」重复")
        ids.add(cid)
        if not str(c.get("title", "")).strip():
            errs.append(f"课「{cid}」缺 title")
        if not str(c.get("goal", "")).strip():
            errs.append(f"课「{cid}」缺 goal——写「学完能做什么」的可验证行为,禁「了解/熟悉」")
        if str(c.get("origin", "")) not in ("user", "map"):
            errs.append(f"课「{cid}」origin 必须是 user 或 map")
        if c.get("part") is not None and not str(c.get("part", "")).strip():
            errs.append(f"课「{cid}」part 若提供则不能是空串")
    # prereqs:合法引用 + 去重 + Kahn 环检测(先修链必须是 DAG)
    indeg: dict[str, int] = {cid: 0 for cid in ids}
    dependents: dict[str, list[str]] = {}
    for c in courses:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", "")).strip()
        seen_p: set[str] = set()
        for pid in c.get("prereqs", []) or []:
            pid = str(pid).strip()
            if pid == cid:
                errs.append(f"课「{cid}」自依赖没有意义")
            elif pid not in ids:
                errs.append(f"课「{cid}」的先修「{pid}」不在大纲里(悬空引用)")
            elif pid in seen_p:
                continue
            else:
                seen_p.add(pid)
                indeg[cid] = indeg.get(cid, 0) + 1
                dependents.setdefault(pid, []).append(cid)
    queue = [cid for cid in ids if indeg.get(cid, 0) == 0]
    seen: set[str] = set()
    while queue:
        cid = queue.pop()
        seen.add(cid)
        for nxt in dependents.get(cid, []):
            indeg[nxt] = indeg.get(nxt, 0) - 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    cycle = sorted(cid for cid in ids if cid not in seen)
    if cycle:
        errs.append(f"先修链成环:{cycle[:5]}——调整 prereqs 使其成 DAG")
    if not any(indeg.get(cid, 0) == 0 for cid in ids):
        errs.append("没有无前置的入口课——至少一门 prereqs=[]")
    return errs


def validate_material(d: dict[str, Any], fetched: set[str] | None = None) -> list[str]:
    """有据硬闸(2026-08-24 升级:外部可验)。fetched=本次循环 fetch_page 实际抓取成功的 URL 集;
    sources 里任何没抓取过的 URL 都打回——「记得有这篇」不算有据,「真的读过」才算。"""
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
    if fetched is not None:
        unverified = sorted(urls - fetched)
        if unverified:
            errs.append(
                "以下来源未经 fetch_page 实际抓取,不许列(有据=真的读过): "
                + " ".join(unverified[:5])
            )
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
        from app.agent.tools import web_search_multi

        # 默认时间窗近一年(不靠模型自觉传参——实测漏传导致上周开源事件被漏掉)
        return web_search_multi(args["query"], args.get("recency") or "year")
    if name == "fetch_page":
        return fetch_page(args["url"])
    return f"(未知工具 {name})"


def _require_search() -> None:
    """fail-fast + 真探针:不止查 key 在不在,还真搜一次——把「余额不足/key 无效/网络不通」
    这类真相在开工前报出来,不让模型带着坏工具在循环里挣扎(2026-08-24 实测踩过)。"""
    from app.agent.tools import search_provider

    p = search_provider()
    if not p:
        msg = (
            "无可用搜索 provider:请在 config/secrets.env 配 SEARCH_API_KEY(博查)"
            "或 TAVILY_API_KEY;AnySearch 匿名亦可,请检查网络"
        )
        raise RuntimeError(msg)
    probe = web_search("connectivity probe")
    if probe.startswith("(搜索失败") or probe.startswith("(搜索不可用"):
        raise RuntimeError(f"搜索探针失败({p}):{probe[:150]}")


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
    validator: Callable[[dict[str, Any], set[str] | None], list[str]],
    topic: str,
    phase: str,
) -> dict[str, Any]:
    """调研循环:工具轮 → 最终交付 JSON → 校验,不过则反馈重交。校验通过才返回。"""
    # 离线批量循环放宽单次超时(与 prep.py 同因:长交付在中转慢速时 60s 不够)
    client = get_llm_client().with_options(timeout=240.0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_calls: list[dict[str, Any]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    t0 = time.perf_counter()
    last_err: list[str] = []

    for turn in range(MAX_TURNS):
        last_turn = turn == MAX_TURNS - 1
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=16384,  # 5.3 思考常开共吃预算:8192 间歇被全烧光(实测同 prep)
            # 观测客户端返回 Any,dict messages 直传不再需要 ignore(历史上 SDK TypedDict 拒 dict)
            messages=messages,
            tools=[] if last_turn else RESEARCH_TOOLS,
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
            # 有据硬闸的外部可验面:本次循环 fetch_page 真正抓成功的 URL 集
            fetched = {
                str(t["args"].get("url"))
                for t in tool_calls
                if t["name"] == "fetch_page" and not t.get("error")
            }
            errs = validator(d, fetched)
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
                emit_call(b.name, dict(b.input))
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


# ---------- 缓存复用(P5·T1,借鉴 DeepTutor exploration.json #18)----------
# 调研产物本就按阶段落盘;这里补「读回来」的入口:改备课 prompt 重跑同主题时
# 零搜索零 fetch,直接进备课循环。缓存经同一套校验器复核,坏了自动回落真实调研。


def _load_cached(
    path: Path, validate: Callable[[dict[str, Any]], list[str]]
) -> dict[str, Any] | None:
    """读缓存文件并结构复核;缺失/损坏/校验不过都返回 None(回落真实调研)。"""
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"缓存损坏({path.name}:{e}),回落真实调研")
        return None
    if not isinstance(d, dict):
        return None
    errs = validate(d)
    if errs:
        print(f"缓存校验不过({path.name}: {errs[:2]}),回落真实调研")
        return None
    return d


def _legacy_to_outline(d: dict[str, Any]) -> dict[str, Any]:
    """旧框架(subtopics 清单)→ 大纲(courses)缓存兼容:顺序即位次,goal 借用 why。"""
    courses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, s in enumerate(d.get("subtopics", []), 1):
        title = str(s.get("title", "")).strip() if isinstance(s, dict) else ""
        slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-")[:24] or f"c{i}"
        if slug in seen:
            slug = f"{slug}-{i}"
        seen.add(slug)
        why = str(s.get("why", "")) if isinstance(s, dict) else ""
        courses.append(
            {
                "id": slug,
                "title": title,
                "goal": why or f"学完能讲清「{title[:20]}」",
                "why": why,
                "prereqs": [],
                "origin": str(s.get("origin", "map")),
            }
        )
    return {**d, "courses": courses, "domain": str(d.get("domain", "")), "legacy": True}


def cached_framework(topic: str) -> dict[str, Any] | None:
    p = settings.data_dir / "research" / f"{_slug(topic)}.framework.json"
    d = _load_cached(p, validate_framework)
    if d is not None:
        print(f"复用大纲缓存:{p.name}({len(d['courses'])} 门,未联网)")
        return d
    if not p.exists():
        return None
    try:
        legacy = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not (isinstance(legacy, dict) and "subtopics" in legacy):
        return None
    d = _legacy_to_outline(legacy)
    errs = validate_framework(d)
    if errs:
        print(f"旧框架转大纲后仍不合规({errs[:2]}),回落真实调研")
        return None
    print(
        f"复用旧框架缓存并转大纲形态:{p.name}({len(d['courses'])} 门,无先修链;"
        "建议 --refresh 重出带先修链的新大纲)"
    )
    return d


def cached_material(topic: str, subtopic: str) -> dict[str, Any] | None:
    p = settings.data_dir / "research" / f"{_slug(topic)}.{_slug(subtopic)}.material.json"
    d = _load_cached(p, validate_material)
    if d is not None:
        d["_material_path"] = str(p)  # 与 research_material 同:管线往下传
        n = sum(len(g.get("points", [])) for g in d["groups"])
        print(f"复用原料缓存:{p.name}({n} 条要点,未联网)")
    return d


def clear_research_cache(topic: str, subtopic: str | None = None) -> int:
    """删该主题的框架缓存(+全部子题原料,或指定子题的),返回删除数。--refresh 用。"""
    base = settings.data_dir / "research"
    targets = [base / f"{_slug(topic)}.framework.json"]
    if subtopic:
        targets.append(base / f"{_slug(topic)}.{_slug(subtopic)}.material.json")
    else:
        targets.extend(sorted(base.glob(f"{_slug(topic)}.*.material.json")))
    n = 0
    for p in targets:
        if p.exists():
            p.unlink()
            n += 1
    return n


def research_framework(topic: str) -> dict[str, Any]:
    """阶段1:学习框架(双源合流)。产出交用户审——缺口补不补、子题选哪个,人拍板。"""
    _require_search()
    d = _loop(
        _FRAMEWORK_PROMPT.format(topic=topic),
        validate_framework,
        topic,
        "framework",
    )
    _save(d, f"{_slug(topic)}.framework.json")
    return d


def research_material(topic: str, subtopic: str) -> dict[str, Any]:
    """阶段2:选定子题的带来源原料(备课 agent 的输入)。"""
    _require_search()
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
