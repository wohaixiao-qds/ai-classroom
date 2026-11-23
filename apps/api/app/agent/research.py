"""找资料 Agent——零基础领域大纲 + 带原文定位的子题原料。

设计(docs/P2执行计划.md M2a,2026-08-24 定稿):
- 两阶段,中间人审:先出学习框架交用户审,再对选定子题深挖原料
- 大纲以领域权威地图为纲,从零基础设计;学习障碍按领域解释
- 原料每点附 source_id 与原文摘录,程序核对实际抓取正文;语义审查独立记录
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
from typing import Any, cast
from uuid import uuid4

from app.agent.tools import (  # noqa: F401  # web_search 供 _require_search 探针
    emit_call,
    fetch_page,
    web_search,
)
from app.core.config import settings
from app.core.job_progress import emit_progress
from app.core.llm import get_llm_client
from app.core.prompts import parse_json_reply
from app.core.trace import digest, observed, run_context, trace_research, update_run
from app.services.evidence import (
    fetch_error,
    locate_material,
    material_evidence,
    normalized_body,
    text_hash,
)
from app.services.evidence_review import review_claims

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

先 web_search 扫该主题的权威知识地图(官方文档、经典教材/课程、学术机构资料;
软件工程主题也可查 GitHub 项目 docs;时效敏感处用 week/month/year 再扫一遍)——大纲以权威
地图为纲,**不预设学习者有任何基础**。提交大纲前成功 fetch_page 深读至少 2 个有代表性的
权威/一手来源;适合时优先覆盖不同机构,但不为凑机构数加入无关材料。

只输出 JSON(不要其他内容):
{{"topic": "{topic}",
  "domain": "领域名(2~6字,如 Agent 工程)",
  "courses": [
    {{"id": "英文短横线slug",
      "title": "具体的课名",
      "goal": "学完能做什么(可验证的行为,禁「了解/熟悉」)",
      "why": "本课解决学习者的哪项理解障碍/常见误解/实际问题,与 goal 对应的一句话",
      "scope": "本课包含什么、明确不讲什么(避免与前后课重复)",
      "prereqs": ["前置课的id(只能取本列表内的id;入口课给 [])"],
      "part": "所属学习阶段(2~6字,如「起步」「核心机制」「工程化」「实战」)",
      "origin": "map",
      "source_quotes": [{{"url": "本轮成功抓取页面的完整 URL",
                         "quote": "支持本课目标/边界设计的逐字原文片段,至少30字符"}}]}}
  ]}}

硬规则:
- 3~8 门课,每门是一节约 8 分钟能读完的小课程
- part = 学习阶段,从基础到进阶排列;同篇回答同一个大问题,篇名 2~6 字
- 课程顺序即学习顺序:每门课只依赖它前面的课(prereqs 成 DAG),入口课无前置
- goal 写「学完能做什么」的可验证行为,禁「了解/熟悉」
- 每门课写清 scope(讲什么/不讲什么),并用本轮真实抓取正文中的 source_quotes 支持设计
- why 说明具体学习障碍或应用问题,泛泛的「重要/有用/是基础」不算。
  仅当主题本身属于 LLM/Agent 工程,且本课机制确实弥补模型的限制时,
  用「无状态会忘/输出会错/窗口会满/需要执行代理」等弱点解释设计动机;
  该分析不强制覆盖该领域的每门课。
  数学例:条件概率解决「把 P(A|B) 与 P(B|A) 混淆」;
  历史例:史料互证解决「把单一叙述当成已证实事实」。非模型主题不得套模型弱点。
- 沿 prereqs 走完全部课 = 零基础学习者完整走完该主题的入门,不留断链"""

_MATERIAL_PROMPT = """你是课题调研员,为课件作者收集一个子题的带来源原料。
底线:**每条要点都必须有据可查**。

主题:{topic} / 本次子题:{subtopic}

课程路线上下文(由程序根据已审大纲确定性注入,不得改写该课程目标):
{course_context}

调研分两步走:
第〇步:版本/生态敏感主题先用 recency=week 搜最新 release/开源/版本/动向;
数学基础、历史等稳定内容优先教材/学术机构/一手史料,不为近一周热度替换基础知识。
第一步:围绕本课目标和范围边界搜集证据。先覆盖目标所需的关键概念、机制、判据和可执行
例子;仅在明确缺口、来源冲突或必要条件未覆盖时继续搜索。不要重复搜集同一观点;每条要点
都必须服务于讲解、练习或判分,且带有实际原文摘录。
结构校验的 24~48 条要点与至少 6 个 URL 是当前原料密度下限。**要点密度决定课件深度
上限**:课件每个块都要有对应要点可挂,材料稀疏=课件只能写浅;只用于防材料空泛/单薄,
不代表研究质量分数,不得用重复观点凑数。

来源三要求(按此配比挑,不是随便搜到什么用什么):
1. **最权威**:依主题选官方文档/规范、经典教材、学术机构或一手史料
2. **时效适配**:版本/规范/生态动向来自官方近期资料;稳定理论不强制近一年
3. **应用经验**:工程主题至少 2 个来源是一线实践——官方博客的生产案例、大厂工程博客、
   高星项目的 README/ISSUE/迁移指南;要踩坑、性能、上线取舍这类「打过仗」的内容,
   不要纯概念科普文凑数;其他领域选有完整推导/史料分析/应用案例的资料

只输出 JSON(不要其他内容):
{{"topic": "{topic}",
  "subtopic": "{subtopic}",
  "sources": [{{"id": 1, "title": "来源标题", "url": "https://…"}}],
  "groups": [{{"heading": "要点组名",
               "points": [{{"text": "要点(一句)", "source_id": 1,
                            "quote": "逐字摘录原文(必填,至少12字符,保留原文语言)"}}]}}]}}

硬规则:points 里每条的 source_id 必须是 sources 里出现过的 id;
**sources 里每个 url 都必须是你用 fetch_page 实际抓取成功的**(没抓过的网址不许列)——
每条 quote 都要在对应 fetch_page 正文中逐字找到,不得翻译改写或只引标题;
摘录需包含支撑 text 的条件、数字、版本,不能张冠李戴;程序会核对位置并另做语义审查。
**版本号/规范条目/最新实践必须来自官方域名或其 changelog**(如 modelcontextprotocol.io、
github.com 官方 org、官方博客),社区文章只能作解释性补充;查这类信息时给 web_search 传
recency。拿不准的内容不要写。"""


# ---------- 交付物校验(有据硬闸;返回错误清单,空=通过) ----------


def validate_framework(d: dict[str, Any], fetched: set[str] | None = None) -> list[str]:
    """领域大纲校验(P7·M1):3~8 门、id 唯一、goal 可验证、prereqs 合法且成 DAG。"""
    courses = d.get("courses")
    if not isinstance(courses, list) or not courses:
        return ["courses 缺失或为空"]
    # 3~8 的依据(2026-11-17 互联网考据,数字不变):与在线课程模块数的教学设计
    # 惯例带重合(各家指引 3~7 / 4~8 / 5~9 交叠);MOOC 完课率随课程变长一致下降
    # (Jordan 2014, HarvardX/MITx 数百门),支持小体量书册;下界 3 是本产品结构
    # 需要(DAG 先修链 + 2~4 篇 + 完整路线叙事)。粒度锚=一节≈8 分钟样课(edX 视频
    # 参与度 6 分钟实证带的上沿;阅读≠视频,不硬换算)。
    # ⚠️ Miller 7±2 是工作记忆块容量,不是门数依据,勿引(Laws of UX 明文警告此误用)。
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
        if fetched is not None and not d.get("legacy") and not str(c.get("scope", "")).strip():
            errs.append(f"课「{cid}」缺 scope——说明本课讲什么、明确不讲什么")
    source_evidence = d.get("source_evidence")
    if isinstance(source_evidence, list):
        source_ids: set[int] = set()
        source_urls: set[str] = set()
        for source in source_evidence:
            if not isinstance(source, dict):
                errs.append("大纲来源记录格式错误")
                continue
            url = str(source.get("url", ""))
            sid = source.get("id")
            if type(sid) is not int or sid <= 0 or sid in source_ids or url in source_urls:
                errs.append("大纲来源必须有唯一的正整数编号和 URL")
            else:
                source_ids.add(sid)
            if not url.startswith("https://") or not str(source.get("snapshot_sha256", "")):
                errs.append(f"大纲来源[{source.get('id', '?')}]缺少 HTTPS URL 或正文指纹")
            if fetched is not None and url not in fetched:
                errs.append(f"大纲来源未在本轮成功抓取:{url[:160]}")
            source_urls.add(url)
        if fetched is not None and len(source_urls) < 2:
            errs.append("大纲至少需要 2 个不同且本轮成功抓取的来源 URL")
        for c in courses:
            if not isinstance(c, dict):
                continue
            refs = c.get("source_ids", [])
            if not isinstance(refs, list):
                errs.append(f"课「{c.get('id', '?')}」source_ids 必须是列表")
            elif any(type(ref) is not int or ref not in source_ids for ref in refs):
                errs.append(f"课「{c.get('id', '?')}」引用了不存在的大纲来源 id")
            elif not d.get("legacy") and not refs:
                errs.append(f"课「{c.get('id', '?')}」缺实际调研来源")
    elif fetched is not None:
        errs.append("大纲缺少基于本轮实际抓取建立的来源记录")
    # prereqs:合法引用 + 去重 + Kahn 环检测(先修链必须是 DAG)
    indeg: dict[str, int] = {cid: 0 for cid in ids}
    dependents: dict[str, list[str]] = {}
    for c in courses:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", "")).strip()
        seen_p: set[str] = set()
        prereqs = c.get("prereqs", [])
        if not isinstance(prereqs, list):
            errs.append(f"课「{cid}」prereqs 必须是列表")
            continue
        for pid in prereqs:
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
        if type(sid) is int and sid > 0 and sid not in ids:
            ids.add(sid)
            urls.add(str(s["url"]))
        else:
            errs.append(f"来源[{i}] id 必须是唯一的正整数")
    n_points = 0
    for gi, g in enumerate(groups, 1):
        for pi, p in enumerate(g.get("points", []) if isinstance(g, dict) else [], 1):
            n_points += 1
            pid = p.get("source_id") if isinstance(p, dict) else None
            if type(pid) is not int or pid not in ids:
                errs.append(
                    f"第{gi}组第{pi}条要点 source_id={pid!r} 不在来源清单——缺源,补上或删掉该条"
                )
            if not isinstance(p, dict) or not str(p.get("text") or "").strip():
                errs.append(f"第{gi}组第{pi}条要点 text 为空")
            if not str(p.get("quote") or "").strip():
                errs.append(f"第{gi}组第{pi}条要点缺 quote——无摘录的要点过不了可溯源审查")
    if n_points < 24:
        errs.append(f"要点只有 {n_points} 条(目标 24~48)——材料密度决定课件深度上限,再挖一挖")
    if len(urls) < 6:
        errs.append(f"来源只有 {len(urls)} 个不同 URL(目标≥6)——来源太单薄")
    if fetched is not None:
        unverified = sorted(urls - fetched)
        if unverified:
            errs.append(
                "以下来源未经 fetch_page 实际抓取,不许列(有据=真的读过): "
                + " ".join(unverified[:5])
            )
    if d.get("evidence_version") == 1:
        try:
            material_evidence(d)
        except (ValueError, TypeError, AttributeError) as exc:
            errs.append(f"原料证据复核失败:{exc}")
    return errs


def _attach_framework_sources(
    framework: dict[str, Any], tool_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """把大纲来源绑定到本轮真实成功抓取,不信任模型自报已读。"""
    pages: dict[str, tuple[str, dict[str, Any]]] = {}
    for call in tool_calls:
        if call.get("name") != "fetch_page" or call.get("error"):
            continue
        url = str(call.get("args", {}).get("url", ""))
        body = str(call.get("result", ""))
        if url and not fetch_error(body):
            pages.setdefault(url, (body, call))

    errors: list[str] = []
    cited_by_course: dict[str, list[tuple[str, str, str, int]]] = {}
    used_urls: list[str] = []
    excerpts_by_url: dict[str, list[str]] = {}
    courses = framework.get("courses", [])
    for course in courses if isinstance(courses, list) else []:
        if not isinstance(course, dict):
            continue
        cid = str(course.get("id", "?"))
        quotes = course.get("source_quotes")
        if not isinstance(quotes, list) or not quotes:
            errors.append(f"课「{cid}」缺 source_quotes,请引用实际用于设计本课的原文")
            continue
        cited: list[tuple[str, str, str, int]] = []
        for citation in quotes:
            if not isinstance(citation, dict):
                errors.append(f"课「{cid}」的来源引用格式无效")
                continue
            url = str(citation.get("url", "")).strip()
            quote = " ".join(str(citation.get("quote", "")).split())
            if not url.startswith("https://"):
                errors.append(f"课「{cid}」来源必须使用 HTTPS:{url[:160]}")
                continue
            if url not in pages:
                errors.append(f"课「{cid}」引用了未在本轮成功抓取的来源:{url[:160]}")
                continue
            body = normalized_body(pages[url][0])
            start = body.find(quote) if len(quote) >= 30 else -1
            if start < 0:
                errors.append(f"课「{cid}」来源片段不在实际抓取正文中:{url[:160]}")
                continue
            context = body[max(0, start - 200):start + len(quote) + 200]
            cited.append((url, quote, context, start))
            excerpts_by_url.setdefault(url, []).append(context)
            if url not in used_urls:
                used_urls.append(url)
        cited_by_course[cid] = list(dict.fromkeys(cited))
    if len(used_urls) < 2:
        errors.append("大纲来源少于 2 个本轮成功抓取的 URL,请补充权威地图来源")

    source_evidence: list[dict[str, Any]] = []
    for source_id, url in enumerate(used_urls, 1):
        body, call = pages[url]
        clean = normalized_body(body)
        header = re.match(r"^\[([^|\]]+)\|\s*https?://[^\]]+\]", body.strip())
        excerpt = "\n…\n".join(dict.fromkeys(excerpts_by_url.get(url, [])))
        source_evidence.append({
            "id": source_id,
            "title": header.group(1).strip() if header else url,
            "url": url,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(call["ts"])),
            "snapshot_sha256": text_hash(clean),
            "excerpt": excerpt[:3000],
        })
    source_id_by_url = {source["url"]: source["id"] for source in source_evidence}
    for course in courses if isinstance(courses, list) else []:
        if not isinstance(course, dict):
            continue
        course.pop("source_urls", None)
        course.pop("source_quotes", None)
        citations = cited_by_course.get(str(course.get("id", "")), [])
        course["source_ids"] = list(dict.fromkeys(
            source_id_by_url[url] for url, _quote, _context, _start in citations
            if url in source_id_by_url
        ))
    framework["source_evidence"] = source_evidence
    return framework, errors


def course_research_context(
    framework: dict[str, Any], selected: dict[str, Any],
) -> dict[str, Any]:
    """Small deterministic outline slice; keeps research tied to the reviewed learning route."""
    courses = framework.get("courses", [])
    by_id = {str(c.get("id")): c for c in courses if isinstance(c, dict)}
    selected_id = str(selected.get("id", ""))
    following = [c for c in courses if isinstance(c, dict)
                 and selected_id in (c.get("prereqs") or [])]
    return {
        "outline_topic": framework.get("topic", ""),
        "course_position": next(
            (index for index, course in enumerate(courses, 1)
             if isinstance(course, dict) and str(course.get("id", "")) == selected_id),
            None,
        ),
        "course_count": len(courses),
        "course_sequence": [
            {"title": c.get("title", ""), "goal": c.get("goal", ""),
             "part": c.get("part", "")}
            for c in courses if isinstance(c, dict)
        ],
        "course_id": selected_id,
        "course_title": selected.get("title", ""),
        "learning_goal": selected.get("goal", ""),
        "learning_barrier": selected.get("why", ""),
        "scope": selected.get("scope", ""),
        "prerequisites": [
            {"title": by_id[pid].get("title", ""), "goal": by_id[pid].get("goal", "")}
            for pid in selected.get("prereqs", []) if pid in by_id
        ],
        "following_courses": [
            {"title": c.get("title", ""), "goal": c.get("goal", ""), "scope": c.get("scope", "")}
            for c in following
        ],
    }

# ---------- 共享循环骨架 ----------

# _json_from_text 已提炼为 core.prompts.parse_json_reply(grader/self_eval/归位同用一份)



def _execute(name: str, args: dict[str, Any]) -> str:
    if name == "web_search":
        from app.agent.tools import web_search_multi

        # 稳定理论不能被默认近一年过滤掉;版本敏感查询由 prompt 要求显式传 recency。
        return web_search_multi(args["query"], args.get("recency"))
    if name == "fetch_page":
        return fetch_page(args["url"])
    return f"(未知工具 {name})"


def _serialize_block(block: Any) -> dict[str, Any]:
    """将 SDK 响应块原样回填对话;兼容轻量离线测试替身。"""
    dump = getattr(block, "model_dump", None)
    return cast(dict[str, Any], dump() if callable(dump) else vars(block))


def _review_material(material: dict[str, Any]) -> None:
    evidence = material_evidence(material)
    claims = [{"id": e["id"], "text": e["point"], "quote": e["quote"],
               "context": e["context"]} for e in evidence]
    previous = material.get("evidence_review")
    review = review_claims(claims, previous=previous) if previous else review_claims(claims)
    verdicts = {item["id"]: item for item in review["items"]}
    for item in evidence:
        verdict = verdicts[item["id"]]
        item.update(support=verdict["verdict"], reviewer=review["reviewer"],
                    reason=verdict["reason"])
    material.update(evidence=evidence, evidence_review=review)
    update_run(evidence_review=review)


def _report_review(material: dict[str, Any]) -> None:
    review = material.get("evidence_review") or {}
    items = material["evidence"]
    pending = sum(i.get("support") == "unreviewed" for i in items)
    update_run(research_evidence={
        "matched": sum(i.get("quote_status") == "matched" for i in items),
        "total": len(items),
        "reviewed": len(items) - pending,
        "review_error": review.get("error"),
        "verdicts": {status: sum(i.get("support") == status for i in items) for status in (
            "supported", "partial", "unsupported", "uncertain", "unreviewed",
        )},
    })


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


@observed("research")
def _loop(
    prompt: str,
    validator: Callable[[dict[str, Any], set[str] | None], list[str]],
    topic: str,
    phase: str,
    *, source: str = "user",
    research_context: dict[str, Any] | None = None,
    material_filename: str | None = None,
) -> dict[str, Any]:
    """调研循环:工具轮 → 最终交付 JSON → 校验,不过则反馈重交。校验通过才返回。"""
    # 离线批量循环放宽单次超时(与 prep.py 同因:长交付在中转慢速时 60s 不够)
    client = get_llm_client().with_options(timeout=240.0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_calls: list[dict[str, Any]] = []
    successful_fetches: dict[str, dict[str, Any]] = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    review_usage: dict[str, int] = {}
    review_s = 0.0
    model_s = 0.0
    outline_quality: dict[str, int] | None = None
    t0 = time.perf_counter()
    last_err: list[str] = []
    token_budget = 32768 if phase.startswith("material:") else 16384
    run_context(prompt=prompt, tools=RESEARCH_TOOLS,
                parameters={"max_tokens": token_budget, "max_turns": MAX_TURNS})

    for turn in range(MAX_TURNS):
        update_run(turns=turn + 1)
        last_turn = turn == MAX_TURNS - 1
        model_started = time.perf_counter()
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=token_budget,  # 带原文摘录的原料用32K,避免思考+完整JSON连续撞16K
            # 观测客户端返回 Any,dict messages 直传不再需要 ignore(历史上 SDK TypedDict 拒 dict)
            messages=messages,
            tools=[] if last_turn else RESEARCH_TOOLS,
        )
        model_s += time.perf_counter() - model_started
        u = resp.usage
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        update_run(usage=usage)

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            update_run(last_response={"stop_reason": resp.stop_reason,
                                      "block_types": [b.type for b in resp.content],
                                      "text_length": len(text), "max_tokens": token_budget})
            draft = {"role": "assistant", "content": text or "（未返回可用正文）"}
            d = None if resp.stop_reason == "max_tokens" else parse_json_reply(text)
            if d is None:
                # 保留模型的原始候选,让下一轮能针对截断/字段错误修复,而不是把
                # assistant 内容替换成省略号后丢失诊断上下文。
                reason = "输出预算耗尽" if resp.stop_reason == "max_tokens" else "未返回完整 JSON"
                last_err = [reason]
                update_run(validation_errors=last_err)
                messages += [draft, {"role": "user", "content": (
                    f"{reason}。优先保留覆盖学习目标的要点和原文,输出精简但完整的 JSON。"
                )}]
                continue
            # 有据硬闸的外部可验面:本次循环 fetch_page 真正抓成功的 URL 集
            fetched = {
                str(t["args"].get("url"))
                for t in tool_calls
                if t["name"] == "fetch_page" and not t.get("error")
            }
            # 不信模型自报的抓取/验证状态,只用本轮实际工具返回构造快照。
            if phase.startswith("material:"):
                for key in ("evidence_version", "evidence", "source_snapshots", "evidence_review"):
                    d.pop(key, None)
            if phase == "framework":
                d, source_errors = _attach_framework_sources(d, tool_calls)
                courses = d.get("courses", [])
                sources = d.get("source_evidence", [])
                valid_courses = [course for course in courses if isinstance(course, dict)]
                outline_quality = {
                    "courses": len(valid_courses),
                    "sourced_courses": sum(
                        bool(course.get("source_ids")) for course in valid_courses
                    ),
                    "sources": len(sources) if isinstance(sources, list) else 0,
                }
                errs = source_errors + validator(d, fetched)
            else:
                errs = validator(d, fetched)
            if not errs and phase.startswith("material:"):
                pages = {str(t["args"].get("url")): str(t["result"])
                         for t in tool_calls if t["name"] == "fetch_page" and not t.get("error")}
                d, errs = locate_material(d, pages)
                if not errs:
                    if research_context is not None:
                        d["research_context"] = research_context
                        d["research_context_hash"] = digest(research_context)
                    if material_filename:
                        _save(d, material_filename)
                    _report_review(d)
                    _review_material(d)
                    if material_filename:
                        _save(d, material_filename)
                    _report_review(d)
                    review = d.get("evidence_review") or {}
                    review_usage = review.get("usage", {})
                    review_s = float(review.get("elapsed_s", 0))
            if not errs:
                update_run(research_cost={
                    "generation_s": round(model_s, 3),
                    "tool_s": round(sum(t["ms"] for t in tool_calls) / 1000, 3),
                    "review_s": review_s,
                    "generation_usage": usage,
                    "review_usage": review_usage,
                    "total_usage": {key: count + review_usage.get(key, 0)
                                    for key, count in usage.items()},
                }, research_outline=outline_quality, validation_errors=[])
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
            update_run(validation_errors=errs)
            messages.append(draft)
            messages.append(
                {
                    "role": "user",
                    "content": "交付物不合格,逐条修完重新输出完整 JSON:\n- "
                    + "\n- ".join(errs),
                }
            )
            continue

        messages.append({
            "role": "assistant",
            "content": [_serialize_block(b) for b in resp.content],
        })
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            ts = time.time()
            try:
                args = dict(b.input)
                if b.name == "fetch_page" and str(args.get("url", "")) in successful_fetches:
                    previous = successful_fetches[str(args["url"])]
                    out, err = str(previous["result"]), None
                    reused_from = previous.get("call_index")
                else:
                    emit_call(b.name, args)
                    out, err = _execute(b.name, args), None
                    if b.name == "fetch_page":
                        err = fetch_error(out)
                    reused_from = None
            except Exception as e:  # noqa: BLE001 工具炸了不拖垮循环(错误回收)
                out, err = f"(抓取失败: {e})", str(e)
                reused_from = None
            call = {
                "name": b.name,
                "args": dict(b.input),
                "ts": ts,
                "ms": round((time.time() - ts) * 1000),
                "error": err,
                "result": out,
            }
            if reused_from is not None:
                call["reused_from_call"] = reused_from
            tool_calls.append(call)
            if b.name == "fetch_page" and not err:
                url = str(b.input.get("url", ""))
                if url not in successful_fetches:
                    successful_fetches[url] = {"result": out, "call_index": len(tool_calls) - 1}
                emit_progress("material" if phase.startswith("material:") else "research",
                              "running", f"已读取来源正文：{url}",
                              current=len(successful_fetches))
            update_run(tool_calls=tool_calls)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out,
                            "is_error": bool(err)})
        messages.append({"role": "user", "content": results})

    update_run(research_cost={
        "generation_s": round(model_s, 3),
        "tool_s": round(sum(t["ms"] for t in tool_calls) / 1000, 3),
        "review_s": review_s,
        "generation_usage": usage,
        "review_usage": review_usage,
        "total_usage": {key: count + review_usage.get(key, 0) for key, count in usage.items()},
    }, research_outline=outline_quality)
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
    tmp = p.with_suffix(f".{uuid4().hex}.tmp")
    data = {k: v for k, v in d.items() if k not in ("_usage", "_material_path")}
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)
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


def cached_material(
    topic: str,
    subtopic: str,
    *,
    research_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    p = settings.data_dir / "research" / f"{_slug(topic)}.{_slug(subtopic)}.material.json"
    d = _load_cached(p, validate_material)
    if d is not None and research_context is not None:
        expected = digest(research_context)
        if (d.get("research_context_hash") != expected
                or digest(d.get("research_context")) != expected):
            print(
                f"原料缓存未绑定当前大纲目标/边界({p.name}),不会静默套用旧材料;"
                "需重新调研或显式审阅绑定材料"
            )
            return None
    if d is not None:
        d["_material_path"] = str(p)  # 与 research_material 同:管线往下传
        if d.get("research_context_hash") and d.get("evidence_version") == 1:
            if any(item.get("support") == "unreviewed" for item in material_evidence(d)):
                _resume_material_review(topic, subtopic, d, p.name)
        n = sum(len(g.get("points", [])) for g in d["groups"])
        print(f"复用原料缓存:{p.name}({n} 条要点,未联网)")
    return d


@observed("research")
def _resume_material_review(
    topic: str, subtopic: str, material: dict[str, Any], filename: str,
) -> None:
    update_run(subtopic=subtopic, material_path=f"review:{subtopic}")
    _report_review(material)
    _review_material(material)
    _save(material, filename)
    _report_review(material)
    review = material["evidence_review"]
    update_run(research_cost={
        "generation_s": 0, "tool_s": 0, "review_s": review.get("elapsed_s", 0),
        "generation_usage": {}, "review_usage": review.get("usage", {}),
        "total_usage": review.get("usage", {}),
    })


def require_reviewed_material(material: dict[str, Any]) -> None:
    """新原料审查未完成时先停在调研阶段,重试不会生成另一份材料。"""
    if material.get("research_context_hash") and any(
        item.get("support") == "unreviewed" for item in material_evidence(material)
    ):
        raise RuntimeError("原料已保存，模型审查未完成；重试将使用保存的原文补审")


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


def research_framework(topic: str, *, source: str = "user") -> dict[str, Any]:
    """阶段1:以权威地图设计零基础领域大纲,产出交用户审。"""
    _require_search()
    d = _loop(
        _FRAMEWORK_PROMPT.format(topic=topic),
        validate_framework,
        topic,
        "framework",
        source=source,
    )
    _save(d, f"{_slug(topic)}.framework.json")
    return d


def research_material(
    topic: str,
    subtopic: str,
    *,
    source: str = "user",
    research_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """阶段2:选定子题的带来源原料(备课 agent 的输入)。"""
    context = research_context or {}
    _require_search()
    path = f"{_slug(topic)}.{_slug(subtopic)}.material.json"
    d = _loop(
        _MATERIAL_PROMPT.format(
            topic=topic,
            subtopic=subtopic,
            course_context=json.dumps(context, ensure_ascii=False, indent=2),
        ),
        validate_material,
        topic,
        f"material:{subtopic}",
        source=source,
        research_context=context,
        material_filename=path,
    )
    d.pop("_usage", None)
    d["_material_path"] = str(settings.data_dir / "research" / path)  # 管线往下传
    return d


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="找资料 Agent:框架(阶段1)/ 子题原料(阶段2)")
    ap.add_argument("topic")
    ap.add_argument("--subtopic", help="不传=阶段1出框架;传=阶段2出该子题原料")
    a = ap.parse_args()
    if a.subtopic:
        outline = cached_framework(a.topic)
        entry = next((c for c in (outline or {}).get("courses", [])
                      if c["title"] == a.subtopic), None)
        context = course_research_context(outline, entry) if outline and entry else None
        m = research_material(a.topic, a.subtopic, research_context=context)
        n_pts = sum(len(g.get("points", [])) for g in m["groups"])
        print(f"\n子题「{a.subtopic}」原料:{n_pts} 条要点 / {len(m['sources'])} 个来源")
    else:
        f = research_framework(a.topic)
        print(f"\n课程大纲({len(f['courses'])} 门课):")
        for i, s in enumerate(f["courses"], 1):
            print(f"  {i}. {s['title']} — {s.get('goal', '')} / {s.get('why', '')}")
        print('\n下一步:审完框架,挑一个子题跑 --subtopic "子题名"')
