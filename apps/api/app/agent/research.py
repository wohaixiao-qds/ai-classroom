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
import random
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from anthropic._exceptions import RateLimitError

from app.agent.tools import (  # noqa: F401  # web_search 供 _require_search 探针
    emit_call,
    fetch_page,
    read_snapshot,
    set_snapshot_checkpoint,
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

# T2.5 历史压缩:输入体积优先(估算超限即压),轮数作辅助条件防早期误压。
# 系数 0.35:英文正文 ≈4 字符/token,中文 ≈1~1.5 字符/token,调研抓取以英文官方
# 文档为主——0.35 是偏保守(宁早压勿爆上下文)的折中;阈值 40k 是计划目标带宽上限。
_COMPRESS_TOKENS_LIMIT = 40_000
_COMPRESS_MIN_TURN = 4
_TOKEN_FACTOR = 0.35

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

# T2.6 本地快照回读:已抓网页正文持久化在抓取检查点文件里,对话历史压缩后(T2.5)
# 正文退出历史——需要重看原文段落时用它本地回读,绝不重新联网(AnySearch 提取本就
# 截断 8000 字符,回读上限=已保存正文)。仅装配给原料调研(铁律8:工具按 agent
# 精选装配);框架阶段没有抓取检查点,不给此工具。
_READ_SNAPSHOT_TOOL = {
    "name": "read_snapshot",
    "description": "本地回读已抓网页的正文段落(不联网)。"
    "正文已退出对话历史(历史只留摘要),需要重看某来源的原文细节时用此工具:"
    "传此前 fetch_page 成功过的 url,用 offset 翻页;引用回读内容时逐字摘录标头之后的"
    "正文段落本身。同一 URL 不要重复 fetch_page——内存与本地快照里已有,直接回读。",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "本轮已成功抓取过的完整 URL"},
            "offset": {"type": "integer", "description": "起始字符位置(默认 0)"},
            "length": {"type": "integer", "description": "读取长度(默认 4000,上限 8000)"},
        },
        "required": ["url"],
    },
}
MATERIAL_TOOLS = [*RESEARCH_TOOLS, _READ_SNAPSHOT_TOOL]

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
recency。拿不准的内容不要写。

止损纪律:搜索/抓取偶发网络失败会由工具层自动重试;若某方面反复尝试仍拿不到来源,
不要反复重试同一查询烧轮次——用手头已抓到的材料交付,材料不足的方面在 groups 里
如实少写或不写(密度闸会告诉你差多少,宁缺勿凑)。轮次有限,优先保证交付一份完整 JSON。"""


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


_OUTLINE_REVIEW_PROMPT = """你是课程大纲审核员。对照权威原文快照,
逐门课判定「这门课要讲的内容,原文撑不撑得起」。
权威原文快照(本轮真实抓取,SHA-256 已绑定,数据之外不得引入你的常识):
{snapshots}
课程大纲(逐门:标题/目标/范围/弱点归因/先修):
{courses}
只输出严格 JSON:
{{"courses": {{"<课程标题>": {{"verdict": "supported"|"unsupported",
"issues": ["一句话具体缺什么/错什么"]}}}}}}
supported=原文能撑起该课的核心概念与可操作目标;unsupported=撑不起(缺关键内容/与原文冲突/目标无法从原文得到练习材料)。
issues 引用课程标题原词;全部撑得起时 issues 为空数组。"""


def review_framework_semantics(d: dict[str, Any]) -> dict[str, Any]:
    """大纲级语义审查闸(P4):逐门课 goal/scope 对照本轮抓取的权威原文快照。

    模型结论作为程序闸的输入数据:报告绑定大纲内容哈希落盘,大纲一变即失效重审;
    无来源快照的存量大纲标 unanchored,不冒充已审。
    """
    evidence = d.get("source_evidence") or []
    if not isinstance(evidence, list) or not evidence:
        return {"status": "unanchored", "reviewer": "", "courses": {}, "content_hash": ""}
    snap_texts = []
    for ev in list(evidence)[:6]:
        if not isinstance(ev, dict):
            continue
        body = str(ev.get("excerpt", ""))[:2000]
        snap_texts.append(f"== {ev.get('title', '')} ({ev.get('url', '')}) ==\n{body}")
    courses_desc = json.dumps(
        [{"title": c.get("title", ""), "goal": c.get("goal", ""),
          "scope": c.get("scope", {}), "why": c.get("why", ""),
          "prereqs": c.get("prereqs", [])}
         for c in d.get("courses", []) if isinstance(c, dict)],
        ensure_ascii=False, indent=1,
    )
    prompt = _OUTLINE_REVIEW_PROMPT.format(
        snapshots="\n\n".join(snap_texts), courses=courses_desc,
    )
    base = {
        "reviewer": f"model:{settings.llm_model}",
        "prompt_hash": digest(prompt),
        "content_hash": digest(d.get("courses")),
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        response = (
            get_llm_client()
            .with_options(timeout=240.0)
            .messages.create(
                model=settings.llm_model,
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        parsed = parse_json_reply(text)
        courses_verdict = parsed.get("courses") if parsed else None
        if not isinstance(courses_verdict, dict):
            return {**base, "status": "review_error", "courses": {}}
    except Exception as exc:  # noqa: BLE001 审查服务失败标记重审,不静默通过
        return {**base, "status": "review_error", "error": type(exc).__name__, "courses": {}}
    failed = [title for title, v in courses_verdict.items()
              if isinstance(v, dict) and v.get("verdict") == "unsupported"]
    return {
        **base,
        "status": "passed" if not failed else "failed",
        "failed_courses": failed,
        "courses": courses_verdict,
    }


def framework_review_status(d: dict[str, Any]) -> str:
    """大纲审查状态(unanchored/unreviewed/review_error/passed/failed),含哈希失效判定。"""
    review = d.get("review")
    if not isinstance(review, dict) or not review:
        return "unanchored" if not (d.get("source_snapshots") or {}) else "unreviewed"
    if digest(d.get("courses")) != review.get("content_hash"):
        return "stale"  # 大纲改过,旧审查结论失效
    return str(review.get("status") or "unreviewed")


_COVERAGE_PROMPT = """你是课程材料审核员。对照课程约束,判断材料要点是否足以支撑教学,只报缺口。
课程约束(程序注入的权威约定,不可改写):
{constraints}
材料要点(逐条,每条带来源号):
{points}
只输出严格 JSON:{{"gaps": ["缺失或覆盖不足的具体方面(引用 scope/goal 原词)", ...]}}
材料足以支撑全部 scope 与 goal 时输出 {{"gaps": []}}。不许凭常识补课,只报缺口;一个缺口一句话。"""

# 覆盖审查按材料内容哈希缓存:同一材料重复交付不再调模型(缺口结论沿用,逼 agent 真改)。
_COVERAGE_MEMO: dict[str, dict[str, Any]] = {}


def review_material_coverage(
    d: dict[str, Any], research_context: dict[str, Any] | None,
) -> list[str]:
    """材料覆盖闸(P3):材料要点对照课程 goal/scope,缺什么当场点名打回。

    结论按材料内容哈希缓存(模型意见作为程序闸的输入数据):重复交付同哈希
    直接沿用结论,agent 循环的 MAX_TURNS 是有界兜底。
    """
    if not research_context:
        return []
    constraints = {
        "outline_topic": research_context.get("outline_topic", ""),
        "goal": research_context.get("learning_goal", ""),
        "scope": research_context.get("scope", {}),
        "learning_barrier": research_context.get("learning_barrier", ""),
        "prerequisites": research_context.get("prerequisites", []),
    }
    if not constraints["goal"] and not constraints["scope"]:
        return []  # 无大纲约束可对照(旧式独立调研),覆盖闸跳过
    h = digest(d)
    memo = _COVERAGE_MEMO.get(h)
    if memo is not None:
        return list(memo["errors"])  # 同哈希重复交付:沿用结论,不再调模型
    lines = []
    for gi, g in enumerate(d.get("groups", []), 1):
        for pi, p in enumerate(g.get("points", []), 1):
            lines.append(f"[组{gi}点{pi}] {p.get('text', '')}")
    prompt = _COVERAGE_PROMPT.format(
        constraints=json.dumps(constraints, ensure_ascii=False, indent=1),
        points="\n".join(lines) or "(空)",
    )
    errors: list[str] = []
    try:
        response = (
            get_llm_client()
            .with_options(timeout=240.0)
            .messages.create(
                model=settings.llm_model,
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        parsed = parse_json_reply(text)
        gaps = parsed.get("gaps") if parsed else None
        if isinstance(gaps, list):
            errors = [
                f"材料覆盖缺口:{str(g)[:120]}" for g in gaps
                if isinstance(g, str) and g.strip()
            ][:8]
    except Exception as exc:  # noqa: BLE001 覆盖审查失败降级放行,不拦调研(与密度闸不同层)
        _COVERAGE_MEMO[h] = {"errors": [], "review_error": type(exc).__name__}
        return []
    _COVERAGE_MEMO[h] = {"errors": errors}
    return errors


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
    if name == "read_snapshot":
        return read_snapshot(
            str(args.get("url", "")),
            offset=int(args.get("offset") or 0),
            length=int(args.get("length") or 4000),
        )
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
    这类真相在开工前报出来,不让模型带着坏工具在循环里挣扎(2026-08-24 实测踩过)。
    探针走 web_search 的全引擎 failover(缺陷#5):某引擎 403/欠费自动换下一个,
    全部失败才拦。"""
    probe = web_search("connectivity probe")
    if probe.startswith("(搜索失败") or probe.startswith("(搜索不可用"):
        raise RuntimeError(
            "所有搜索引擎均不可用(逐个探测):"
            f"{probe[:200]}。请检查 config/secrets.env 的搜索 key 或网络"
        )


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


def _sleep_backoff(seconds: float) -> None:
    """重试退避;测试 patch 本函数为零等待,避免套件真睡。"""
    time.sleep(seconds)


# ---------- 历史压缩(T2.5):正文退出对话历史,要点/引文/定位进结构化摘要 ----------
# 摘要保留清单(计划 T2.5):课程 goal/scope/排除项原文(首条 prompt + 摘要双保险)、
# 最新门禁反馈原文、每条候选要点(text+逐字 quote+source_id+快照定位);网页正文
# 从历史剔除——它们持久化在抓取检查点里(T2.1),模型经 read_snapshot(T2.6)回读。
# 「引文已命中快照」(quote_status)与「语义审查 supported」(semantic_review)分开
# 标记,永不合并为「已确认」。


_DIGEST_MARKER = "【调研历史压缩摘要】"


def _estimate_input_tokens(messages: list[dict[str, Any]]) -> int:
    """字符数×系数粗估输入 token(计划认可的做法,不引入 tokenizer 依赖)。"""
    return int(len(json.dumps(messages, ensure_ascii=False)) * _TOKEN_FACTOR)


def _msg_text(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def _latest_draft(middle: list[dict[str, Any]]) -> dict[str, Any] | None:
    """最近一次可解析的交付草稿——候选要点的权威来源;更早草稿是模型自己淘汰的旧版。

    复查修复B:压缩摘要本身是 user 角色(内嵌候选要点 JSON),二次压缩时若只扫
    assistant,上一份摘要的候选要点会丢失——摘要在场时也纳入扫描(取其内嵌 JSON)。
    """
    for msg in reversed(middle):
        role = msg.get("role")
        text = _msg_text(msg)
        if role == "assistant":
            d = parse_json_reply(text)
            if d is not None and (d.get("groups") or d.get("courses")):
                return d
        elif role == "user" and text.startswith(_DIGEST_MARKER):
            # 复查修复B:摘要含多个 JSON(课程约束+候选材料),整段 parse 会把
            # 两个对象拼一起而失败——从「候选要点」段头精准截取该段 JSON。
            marker = "## 候选要点(来自最近一次交付草稿,quote/快照定位逐字保留)\n"
            start = text.find(marker)
            if start < 0:
                continue
            seg = text[start + len(marker):]
            d = parse_json_reply(seg)
            if d is None:
                continue
            if d.get("groups") or d.get("courses"):
                return d
            # 摘要形态(_material_digest 产物: note+sources+points):重组回 groups
            # 草稿,二次压缩时候选要点(含 quote/定位/语义标记)不丢失。
            if d.get("points"):
                return {
                    "groups": [{"heading": "压缩前候选要点",
                                "points": d["points"]}],
                    "sources": d.get("sources", []),
                }
    return None


def _last_user_feedback(middle: list[dict[str, Any]]) -> str:
    """最近一条用户文本反馈原文(门禁打回/预算提示);上一轮的压缩摘要不计入。"""
    for msg in reversed(middle):
        text = _msg_text(msg) if msg.get("role") == "user" else ""
        if text.strip() and not text.startswith(_DIGEST_MARKER):
            return text
    return ""


def _title_of(body: str) -> str:
    header = re.match(r"^\[([^|\]]+)\|", body.strip())
    return header.group(1).strip() if header else "(无标题)"


def _material_digest(draft: dict[str, Any], pages: dict[str, str]) -> dict[str, Any]:
    """原料候选要点:quote_status 由程序对本地快照逐字定位重算(与交付时同一套
    locate_material,确定性,不引入模型意见);semantic_review 恒为 unreviewed——
    语义审查只在交付校验全过之后独立进行,两个标记绝不合并。"""
    located, _errs = locate_material(draft, pages)
    points = []
    for e in located.get("evidence", []):
        matched = e.get("quote_status") == "matched"
        points.append({
            "id": e.get("id"), "text": e.get("point"), "source_id": e.get("source_id"),
            "quote": e.get("quote"),
            "quote_status": "matched" if matched else "unmatched",
            "quote_start": e.get("quote_start") if matched else None,
            "quote_end": e.get("quote_end") if matched else None,
            "snapshot_sha256": e.get("source_hash") if matched else None,
            "semantic_review": "unreviewed",
        })
    return {
        "note": "quote_status=引文是否逐字命中本地快照(程序重算);semantic_review=语义审查"
                "状态——两者相互独立,引文命中≠语义审查通过,当前全部未做语义审查",
        "sources": draft.get("sources", []),
        "points": points,
    }


def _framework_digest(draft: dict[str, Any], pages: dict[str, str]) -> dict[str, Any]:
    """大纲候选课:保留 goal/scope/why/prereqs 原文与 source_quotes(逐字)。"""
    courses = []
    for c in draft.get("courses", []):
        if not isinstance(c, dict):
            continue
        quotes = []
        for q in c.get("source_quotes") or []:
            if not isinstance(q, dict):
                continue
            url = str(q.get("url", ""))
            quote = " ".join(str(q.get("quote", "")).split())
            body = normalized_body(pages.get(url, "")) if url in pages else ""
            quotes.append({
                "url": url, "quote": q.get("quote"),
                "quote_status": "matched" if len(quote) >= 30 and quote in body
                else "unmatched",
            })
        courses.append({"id": c.get("id"), "title": c.get("title"), "goal": c.get("goal"),
                        "scope": c.get("scope"), "why": c.get("why"), "part": c.get("part"),
                        "prereqs": c.get("prereqs"), "source_quotes": quotes})
    return {"note": "quote_status=引文是否逐字命中本地快照,与语义审查相互独立",
            "courses": courses}


def _build_history_digest(
    middle: list[dict[str, Any]],
    *,
    research_context: dict[str, Any] | None,
    successful_fetches: dict[str, dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    phase: str,
    turns_left: int = 0,
) -> str:
    parts = [
        _DIGEST_MARKER
        + f"(程序生成:{phase} 阶段此前约 {len(middle)} 条消息已压缩;"
        "已抓网页正文已存本地快照,并从对话历史剔除——需要重看原文段落时"
        "用 read_snapshot(url, offset) 本地回读,不要重新联网。)",
    ]
    if research_context:
        # goal/scope/排除项原文进摘要(补挖循环的首条 prompt 只带截断的上下文,
        # 摘要里带全量原文是双保险;不压缩=逐字保留)。
        constraint = {
            "goal": research_context.get("learning_goal", ""),
            "scope": research_context.get("scope", ""),
            "learning_barrier": research_context.get("learning_barrier", ""),
            "prerequisites": research_context.get("prerequisites", []),
        }
        parts.append("## 课程约束(程序注入的原文,不得改写)\n"
                     + json.dumps(constraint, ensure_ascii=False, indent=1))
    if successful_fetches:
        lines = [
            f"- {_title_of(str(e.get('result', '')))} | {url} | "
            f"sha256:{text_hash(str(e.get('result', '')))[:16]}"
            f"(全文 {len(str(e.get('result', '')))} 字符,read_snapshot 可回读)"
            for url, e in successful_fetches.items()
        ]
        parts.append("## 已抓来源(正文在本地快照,历史中已剔除)\n" + "\n".join(lines))
    n_points = 0
    draft_any = _latest_draft(middle)
    if isinstance(draft_any, dict):
        for g in draft_any.get("groups", []) if isinstance(draft_any.get("groups"), list) else []:
            n_points += len(g.get("points", []) if isinstance(g, dict) else [])
    parts.append(
        f"## 调研进度(程序注入)\n已抓 {len(successful_fetches)} 页 · 候选要点约 {n_points} 条 · "
        f"**剩余轮次 {turns_left}**——轮次耗尽未交付即整轮失败(已抓正文会存为 draft),"
        "请尽快整理已收集材料输出完整交付 JSON。"
    )
    draft = _latest_draft(middle)
    if draft is None:
        parts.append("## 候选要点\n(尚未产出可解析的交付草稿)")
    else:
        pages = {url: str(e.get("result", "")) for url, e in successful_fetches.items()}
        try:
            if isinstance(draft.get("courses"), list):
                payload: dict[str, Any] = _framework_digest(draft, pages)
            else:
                payload = _material_digest(draft, pages)
        except Exception:  # noqa: BLE001 压缩绝不打断调研;定位重算失败退回原草稿
            payload = draft
        parts.append("## 候选要点(来自最近一次交付草稿,quote/快照定位逐字保留)\n"
                     + json.dumps(payload, ensure_ascii=False, indent=1))
    feedback = _last_user_feedback(middle)
    if feedback:
        parts.append("## 最近一次校验反馈(原文)\n" + feedback)
    n_search = sum(1 for t in tool_calls if t["name"] == "web_search")
    parts.append(
        f"## 过程概要\nweb_search×{n_search},fetch_page 成功 {len(successful_fetches)} 页。"
        "本轮继续:按最新反馈修补候选要点或补缺口,然后输出完整交付 JSON。"
    )
    return "\n\n".join(parts)


def _compress_messages(
    messages: list[dict[str, Any]],
    *,
    research_context: dict[str, Any] | None,
    successful_fetches: dict[str, dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    phase: str,
    turns_left: int = 0,
) -> list[dict[str, Any]] | None:
    """T2.5:中间历史(messages[1:-2])替换为结构化摘要,保留首条 prompt 与
    最后一轮完整交互。无需压缩(中间历史为空)返回 None。

    - 最后一轮「完整交互」= 末尾 assistant+user 两条整体保留:tool_result 必须
      与它引用的 tool_use 同历史存活,单留一半会被 API 拒(引用缺失)。
    - 摘要消息用 user 角色——与既有「墙钟超限」提示同模式,连续 user 由端点合并
      为单轮(官方文档明示 consecutive turns are combined)。
    - 压缩数据源是循环级记录(successful_fetches/tool_calls/research_context),
      不是对旧摘要的再摘要——重复压缩不损失信息。
    """
    if len(messages) < 5:
        return None
    # 复查修复C:固定切片 [1:-2] 会产生孤儿 tool_result——若末尾是「告急 user」
    # 等追加消息,tool_use(assistant)被切走而它的 tool_result(user)留在保留区,
    # 端点拒收引用缺失。从尾部回溯:切片终点必须在 tool_result 消息之后(即
    # assistant/tool_use 轮的边界),保证保留区首条不是无配对的 tool_result。
    end = len(messages) - 2
    # 只前移「user 携带 tool_result 列表」的消息;assistant 轮(content list 含
    # tool_use+text)有文本,不会被误移。
    while end > 1 and messages[end].get("role") == "user" and isinstance(
        messages[end].get("content"), list
    ):
        end -= 1
    middle = messages[1:end]
    if not middle:
        return None
    digest_text = _build_history_digest(
        middle,
        research_context=research_context,
        successful_fetches=successful_fetches,
        tool_calls=tool_calls,
        phase=phase,
        turns_left=turns_left,
    )
    summary = {"role": "user", "content": digest_text}
    # 保留区用同一边界 end:移出摘要区的轮次必须整体进入保留区,
    # 否则孤儿 tool_result 留在保留区而引用的 tool_use 被压缩(复查问题C)。
    return [messages[0], summary, *messages[end:]]


@observed("research")
def _loop(
    prompt: str,
    validator: Callable[[dict[str, Any], set[str] | None], list[str]],
    topic: str,
    phase: str,
    *, source: str = "user",
    research_context: dict[str, Any] | None = None,
    material_filename: str | None = None,
    max_turns: int | None = None,
) -> dict[str, Any]:
    """调研循环:工具轮 → 最终交付 JSON → 校验,不过则反馈重交。校验通过才返回。"""
    # 离线批量循环放宽单次超时(与 prep.py 同因:长交付在中转慢速时 60s 不够)
    # 第一批边界控制:独立客户端 max_retries=0——SDK 自动重试(3×timeout≈720s 长尾)
    # 由应用层接管(transport_attempt 循环),超时/重试/终止策略统一在循环内决定。
    client = get_llm_client().with_options(timeout=300.0, max_retries=0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_calls: list[dict[str, Any]] = []
    successful_fetches: dict[str, dict[str, Any]] = {}
    # 中断恢复(复查修复A):从抓取检查点预填已抓正文——同 URL 不再进抓取执行;
    # 检查点缺失/损坏为 None 时走全新调研(与 _load_fetch_checkpoint 防御一致)。
    if material_filename:
        recovered = _load_fetch_checkpoint(material_filename) or {}
        for r_url, page in (recovered.get("pages") or {}).items():
            if isinstance(page, dict) and page.get("body"):
                successful_fetches[r_url] = {
                    "result": str(page["body"]),
                    "call_index": -1,  # 恢复项:非本轮调用,仅作去重与快照来源
                }
        if recovered:
            print(f"📦 从抓取检查点恢复 {len(successful_fetches)} 页已抓正文(不重复请求)",
                  flush=True)
    usage = {"input_tokens": 0, "output_tokens": 0}
    review_usage: dict[str, int] = {}
    review_s = 0.0
    model_s = 0.0
    outline_quality: dict[str, int] | None = None
    t0 = time.perf_counter()
    last_err: list[str] = []
    token_budget = 32768 if phase.startswith("material:") else 16384
    turns_budget = max_turns if max_turns is not None else MAX_TURNS
    # T2.6:read_snapshot 仅装配给原料调研(框架阶段无抓取检查点,不给此工具),
    # 并注入本循环的快照检查点路径作为该工具的本地回读源。
    tools = MATERIAL_TOOLS if phase.startswith("material:") else RESEARCH_TOOLS
    set_snapshot_checkpoint(_checkpoint_path(material_filename) if material_filename else None)
    run_context(prompt=prompt, tools=tools,
                parameters={"max_tokens": token_budget,
                            "max_turns": turns_budget})

    deliver_mode = False  # 墙钟超限后的交付模式:撤工具直到交付(第一批②)
    for turn in range(turns_budget):
        update_run(turns=turn + 1)
        # T2.5 历史压缩:输入体积优先(估算超 40k token 即压),轮数 ≥4 辅助条件。
        # 只动消息装配层:首条 prompt 与最后一轮完整交互原样保留,中间历史替换为
        # 结构化摘要(候选要点/引文定位/门禁反馈全保留);已抓正文从历史剔除——
        # 它们持久化在抓取检查点里,模型经 read_snapshot 本地回读。
        # 不触碰收笔判定与传输重试逻辑。
        turns_left_now = turns_budget - turn - 1
        if turns_left_now == 4 and turn != turns_budget - 1:
            messages.append({"role": "user", "content": (
                f"⚠️ 轮次预算告急:剩余 {turns_left_now} 轮。立即停止新的搜索/抓取,"
                "把已收集的全部材料整理成完整交付 JSON 输出(不要调用工具)。"
            )})
        if turn + 1 >= _COMPRESS_MIN_TURN:
            est_before = _estimate_input_tokens(messages)
            if est_before > _COMPRESS_TOKENS_LIMIT:
                compressed = _compress_messages(
                    messages,
                    research_context=research_context,
                    successful_fetches=successful_fetches,
                    tool_calls=tool_calls,
                    phase=phase,
                    turns_left=turns_budget - turn - 1,
                )
                if compressed is not None:
                    est_after = _estimate_input_tokens(compressed)
                    print(f"📦 历史压缩:输入估算 {est_before // 1000}k → "
                          f"{est_after // 1000}k token"
                          "(正文退出历史,要点/引文/定位保留,原文用 read_snapshot 回读)",
                          flush=True)
                    update_run(history_compressed={"turn": turn + 1,
                                                   "est_tokens_before": est_before,
                                                   "est_tokens_after": est_after})
                    messages = compressed
        last_turn = turn == turns_budget - 1
        model_started = time.perf_counter()
        # 第一批边界控制:独立客户端 max_retries=0(SDK 3×240s 的长尾由应用层接管),
        # 搜索轮 110s/交付轮 300s——交付 JSON 是重活,单独放宽。
        # P1 修正:模型可在任意普通轮输出完整交付,110s 会截断它(实测交付 226s)。
        # 重试时若上一轮 110s 超时且输出接近预算上限,升级为 300s 交付超时再试;
        # 交付模式/last_turn 直接用 300s。
        resp = None
        deliver_timeout = 300.0 if (last_turn or deliver_mode) else 110.0
        for transport_attempt in (1, 2):  # 应用层只重试 1 次,总等待 ≈2×timeout
            try:
                resp = client.messages.create(
                    model=settings.llm_model,
                    max_tokens=token_budget,
                    messages=messages,
                    tools=[] if (last_turn or deliver_mode) else tools,
                    timeout=deliver_timeout,
                )
                break
            except RateLimitError:
                raise  # 429 走 key 守卫与独立策略,不在调研循环里吞
            except Exception as exc:  # noqa: BLE001 传输类失败按下面 transient 策略处理
                if transport_attempt == 2:
                    raise
                transient = isinstance(exc, (TimeoutError, ConnectionError)) or (
                    type(exc).__name__ in ("APIConnectionError", "APITimeoutError",
                                           "InternalServerError", "OverloadedError"))
                if not transient:
                    raise
                # 110s 截断的大输出 = 可能是交付被截断,重试用 300s 交付超时
                if deliver_timeout < 300.0:
                    deliver_timeout = 300.0
                print(f"⚠️ 模型调用传输失败({type(exc).__name__}),"
                      f"以 {deliver_timeout:.0f}s 交付超时重试 1/1", flush=True)
                _sleep_backoff(5.0 + random.uniform(0, 10.0))
        if resp is None:
            raise RuntimeError("模型调用未返回")  # 防御:循环两轮都没赋值
        model_s += time.perf_counter() - model_started
        u = resp.usage
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        update_run(usage=usage)

        # 缺陷#8:兼容端点常把「文本(可能是交付 JSON)+幻觉 tool_use」混排,
        # stop=tool_use 时文本被整个丢弃——#14 实测 15.2k 输出疑似完整交付被浪费。
        # 先尝试解析文本中的 JSON,解析成功即走交付/校验流程(幻觉工具不执行);
        # 失败且非 last_turn 才继续工具轮。
        delivery_text = ""
        if resp.stop_reason == "tool_use":
            candidate = "".join(b.text for b in resp.content if b.type == "text")
            if len(candidate) > 500 and parse_json_reply(candidate) is not None:
                delivery_text = candidate
        if resp.stop_reason != "tool_use" or last_turn or deliver_mode or delivery_text:
            text = delivery_text or "".join(b.text for b in resp.content if b.type == "text")
            update_run(last_response={"stop_reason": resp.stop_reason,
                                      "block_types": [b.type for b in resp.content],
                                      "text_length": len(text), "max_tokens": token_budget})
            draft = {"role": "assistant", "content": text or "（未返回可用正文）"}
            d = None if resp.stop_reason == "max_tokens" and not delivery_text \
                else parse_json_reply(text)
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
            # 复查修复A:恢复来源同样可信(检查点写入时已带正文哈希)——
            # 模型经 read_snapshot 回读后交付,不再被拒为「未经 fetch_page 抓取」。
            fetched.update(url for url in successful_fetches
                           if successful_fetches[url].get("call_index") == -1)
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
                for r_url, entry in successful_fetches.items():
                    if entry.get("call_index") == -1 and r_url not in pages:
                        pages[r_url] = str(entry["result"])  # 历史恢复正文参与引文定位
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
                    # T2.1 抓取级持久检查点:每成功抓一页即原子落盘(临时+replace),
                    # kill -9 级中断也能恢复——已抓正文不重复请求。
                    if material_filename:
                        _save_fetch_checkpoint(
                            material_filename, url, out, tool_calls, research_context,
                        )
                emit_progress("material" if phase.startswith("material:") else "research",
                              "running", f"已读取来源正文：{url}",
                              current=len(successful_fetches))
            update_run(tool_calls=tool_calls)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out,
                            "is_error": bool(err)})
        messages.append({"role": "user", "content": results})
        # 整轮墙钟预算(第一批②):模型调用+工具执行合计超 6 分钟,强制收敛交付——
        # 单轮 ≠ 只有模型时间,fetch_page/web_search 也占墙钟;预算是软顶(下一轮收笔)。
        if not last_turn and (time.perf_counter() - model_started) > 360.0:
            print(f"⚠️ 第 {turn + 1} 轮墙钟超 360s,下一轮进入交付模式", flush=True)
            messages.append({"role": "user", "content": (
                "本轮耗时过长。立即停止搜索/抓取,基于已收集的全部材料输出完整交付 JSON,"
                "不要再调用任何工具。"
            )})
            deliver_mode = True  # 撤工具直到交付完成(交付重试也不带工具)

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
    msg = f"调研未在 {turns_budget} 轮内交付合格结果(最后问题: {last_err[:3]})"
    raise RuntimeError(msg)


def _slug(s: str) -> str:
    return re.sub(r"[^\w-]+", "-", s).strip("-")[:40] or "topic"


def _checkpoint_path(material_filename: str) -> Path:
    """T2.1 抓取级检查点路径(与 publication 审查 checkpoint 无关,勿混淆):
    `{slug}.material.checkpoint.json`——kill -9 级中断的可恢复现场。"""
    base = material_filename[:-5] if material_filename.endswith(".json") else material_filename
    return settings.data_dir / "research" / f"{base}.checkpoint.json"


def _save_fetch_checkpoint(
    material_filename: str, url: str, body: str,
    tool_calls: list[dict[str, Any]], research_context: dict[str, Any] | None,
) -> None:
    """每成功抓取一页即增量更新检查点(原子写):已抓正文+哈希+候选材料+缺口+约束哈希+阶段。
    读取方按 T2.2 状态语义恢复;任何一步损坏按 RevisionBlocked 式防御忽略整个检查点。"""
    path = _checkpoint_path(material_filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            existing = {}  # 损坏检查点不阻塞调研,重写即可
    pages = existing.get("pages") or {}
    pages[url] = {
        "body": body,
        "sha256": text_hash(body),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    cp: dict[str, Any] = {
        "version": 1,
        "pages": pages,
        "fetched_count": len(pages),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if research_context is not None:
        cp["research_context_hash"] = digest(research_context)
    tmp = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(cp, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _load_fetch_checkpoint(material_filename: str) -> dict[str, Any] | None:
    """读抓取检查点;损坏/缺失返回 None(调用方走全新调研)。"""
    path = _checkpoint_path(material_filename)
    if not path.exists():
        return None
    try:
        cp = json.loads(path.read_text(encoding="utf-8"))
        return cp if isinstance(cp, dict) and cp.get("pages") else None
    except (OSError, ValueError):
        return None


def _save_draft_from_checkpoint(
    material_filename: str, gaps: list[str],
    research_context: dict[str, Any] | None,
) -> str | None:
    """T2.3:把抓取检查点升级为 draft 文件(有网页正文,未过覆盖闸)。
    draft 不可被备课消费(cached_material 只认正式后缀);返回 draft 路径或 None。"""
    cp = _load_fetch_checkpoint(material_filename)
    if not cp or not cp.get("pages"):
        return None
    draft_path = Path(
        settings.data_dir / "research"
        / (material_filename.replace(".json", "") + ".draft.json")
    )
    draft = {
        "version": 1,
        "state": "draft",  # 状态标记:draft 不得进入备课缓存
        "pages": cp.get("pages", {}),
        "fetched_count": cp.get("fetched_count", 0),
        "unresolved_gaps": gaps[:6],
        "research_context_hash": digest(research_context) if research_context else None,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = draft_path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        tmp.replace(draft_path)
        print(f"已保存调研 draft({draft['fetched_count']} 页正文): {draft_path.name}", flush=True)
        return str(draft_path)
    finally:
        tmp.unlink(missing_ok=True)


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
    # 大纲级语义审查闸(P4):逐门课 goal/scope 对照本轮抓取的权威原文。
    # 结论(含失败)随大纲落盘;点单入口按 review_status 拦 unsupported 课。
    review = review_framework_semantics(d)
    d["review"] = review
    d["review_status"] = review.get("status", "review_error")
    _save(d, f"{_slug(topic)}.framework.json")
    return d


def research_material(
    topic: str,
    subtopic: str,
    *,
    source: str = "user",
    research_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """阶段2:选定子题的带来源原料(备课 agent 的输入)。

    轮次预算分层(E2E 缺陷#3):首轮 16 轮管广度抓取;首轮失败时若最后问题
    是覆盖缺口,进独立补挖循环(每轮 6 轮,最多 2 次)——打回循环有保底预算,
    不再与初次抓取共池导致「想补但没轮次」的死局。
    """
    context = research_context or {}
    _require_search()
    path = f"{_slug(topic)}.{_slug(subtopic)}.material.json"

    def validator(d: dict[str, Any], fetched: set[str] | None) -> list[str]:
        errs = validate_material(d, fetched)
        if not errs:  # 密度闸过了才跑覆盖审查(每轮模型调用,顺序在最贵之前)
            errs.extend(review_material_coverage(d, context))
        return errs

    last_errors: list[str] = []
    try:
        d = _loop(
            _MATERIAL_PROMPT.format(
                topic=topic,
                subtopic=subtopic,
                course_context=json.dumps(context, ensure_ascii=False, indent=2),
            ),
            validator,
            topic,
            f"material:{subtopic}",
            source=source,
            research_context=context,
            material_filename=path,
        )
    except RuntimeError as exc:
        # _loop 轮次耗尽抛 RuntimeError(含覆盖缺口清单);非缺口类失败照旧上抛
        msg = str(exc)
        if "材料覆盖缺口" not in msg:
            raise
        last_errors = [seg.strip() for seg in
                       msg.split("最后问题:")[1].strip("]'").split(";") if seg.strip()]
        # T2.3:覆盖闸打回即落 draft(有网页+候选材料,未过覆盖闸)——已抓正文不丢,
        # 下次点单可从 draft 续(draft 不可被备课消费,cached_material 只认正式后缀)。
        _save_draft_from_checkpoint(path, last_errors, context)
        print(f"首轮调研耗尽,已落 draft;进覆盖缺口补挖循环({len(last_errors)} 个缺口)",
              flush=True)
    else:
        d.pop("_usage", None)
        d["_material_path"] = str(settings.data_dir / "research" / path)
        return d
    # 覆盖闸补挖循环:缺口清单来自覆盖闸的意见文本,聚焦补挖,独立 6 轮预算。
    for bounce in range(2):
        gap_prompt = (
            f"你是课题调研员,为子题「{subtopic}」(主题:{topic})补齐材料缺口。\n"
            f"已有材料已覆盖其他方面,**只补以下缺口**,不要重复已有内容:\n"
            + "\n".join(f"- {g}" for g in last_errors)
            + "\n\n课程上下文:\n"
            + json.dumps(context, ensure_ascii=False, indent=2)[:2000]
            + "\n\n输出与材料相同的完整 JSON 结构"
            "(topic/subtopic/sources/groups+points,每点带逐字引文,全部来源必须真实抓取)。"
        )
        try:
            d = _loop(
                gap_prompt,
                validator,
                topic,
                f"material:{subtopic}:gap{bounce + 1}",
                source=source,
                research_context=context,
                material_filename=path,
                max_turns=6,
            )
        except RuntimeError as exc2:
            msg2 = str(exc2)
            if "材料覆盖缺口" not in msg2:
                raise
            last_errors = [seg.strip() for seg in
                           msg2.split("最后问题:")[1].strip("]'").split(";") if seg.strip()]
            print(f"补挖 {bounce + 1}/2 仍有缺口,{'继续' if bounce == 0 else '放弃'}", flush=True)
            continue
        d.pop("_usage", None)
        d["_material_path"] = str(settings.data_dir / "research" / path)
        return d
    raise TimeoutError(
        f"覆盖闸缺口经 2 轮补挖仍未补齐: {last_errors[:2]};"
        f"draft 已保存于 {path.replace('.json', '.draft.json')},"
        "请人工审阅该课 goal/scope 或从 draft 续挖"
    )


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
