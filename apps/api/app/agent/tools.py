"""答疑 Agent 的两个工具:web_search(联网查) 与 read_notes(读知识库)。
另有 fetch_page(抓网页正文)——找资料 Agent 专用实现(答疑清单不含它,铁律8)。

工具返回纯文本(观测走调用侧的轨迹),异常向上抛由循环做错误回收。
"""

from __future__ import annotations

import html as html_mod
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import settings


def _bocha_search(query: str) -> str:
    """博查搜索,返回 top 结果的标题/链接/摘要文本。"""
    req = urllib.request.Request(
        "https://api.bochaai.com/v1/web-search",
        data=json.dumps({"query": query, "count": 5, "summary": True}).encode(),
        headers={
            "Authorization": f"Bearer {settings.search_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data: dict[str, object] = json.loads(resp.read())
    lines = []
    for i, page in enumerate(data.get("data", {}).get("webPages", {}).get("value", []), 1):  # type: ignore[union-attr]
        lines.append(f"[{i}] {page.get('name')}\n{page.get('url')}\n{page.get('summary','')[:300]}")
    return "\n\n".join(lines) or "(无搜索结果)"


def _zhipu_search(query: str) -> str:
    """智谱 Web Search(search_std,¥0.01/次,Coding Plan 不含、按量余额计费)。"""
    req = urllib.request.Request(
        "https://open.bigmodel.cn/api/paas/v4/web_search",
        data=json.dumps(
            {
                "search_engine": "search_std",
                "search_query": query[:70],
                "count": 5,
                "search_intent": False,
                "content_size": "medium",
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    lines = []
    for i, r in enumerate(data.get("search_result", []), 1):
        lines.append(f"[{i}] {r.get('title')}\n{r.get('link')}\n{r.get('content','')[:300]}")
    return "\n\n".join(lines) or "(无搜索结果)"


def search_provider() -> str | None:
    """当前可用的搜索 provider:配了博查 key 用博查,否则智谱 key 复用(按量计费)。"""
    if settings.search_api_key:
        return "bocha"
    if settings.llm_api_key:
        return "zhipu"
    return None


def web_search(query: str) -> str:
    """联网搜索(自动选 provider),返回 top 结果的标题/链接/摘要文本。"""
    p = search_provider()
    try:
        if p == "bocha":
            return _bocha_search(query)
        if p == "zhipu":
            return _zhipu_search(query)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return f"(搜索失败 HTTP {e.code}:{body}——基于已有知识回答并注明未经核实)"
    return "(搜索不可用:未配置任何搜索 key。请基于已有知识回答,并注明未经联网核实)"


def read_notes(keyword: str) -> str:
    """按关键词在知识库里找笔记(只读),返回匹配文件名+片段。"""
    kb: Path = settings.kb_dir
    if not kb.is_dir():
        return "(知识库目录不存在)"
    hits: list[str] = []
    for md in kb.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        if keyword in text or keyword in md.name:
            for m in re.finditer(re.escape(keyword), text):
                start = max(0, m.start() - 80)
                snippet = text[start : m.start() + 120].replace("\n", " ")
                hits.append(f"《{md.relative_to(kb)}》…{snippet}…")
                break  # 每篇取一处
        if len(hits) >= 8:
            break
    return "\n\n".join(hits) or f"(知识库中没有找到「{keyword}」相关笔记)"


def fetch_page(url: str) -> str:
    """抓网页正文(标准库剥标签,截断防超上下文)。

    返回体强制带 [标题|URL] 头——调用方(找资料 agent)引用内容时一定拿得到出处。
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; ClassroomResearch/1.0)"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read(2_000_000)
        ctype = resp.headers.get("content-type", "")

    charset = re.search(r"charset=([\w-]+)", ctype)
    text_html = raw.decode(charset.group(1) if charset else "utf-8", errors="replace")

    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text_html)
    title = url
    if title_match:
        title = html_mod.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()[:120]

    # 去脚本/样式/导航类块 → 去标签 → 还原实体 → 压空白
    body = re.sub(r"(?is)<(script|style|nav|header|footer|svg)[^>]*>.*?</\1>", " ", text_html)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = html_mod.unescape(body)
    body = re.sub(r"[ \t\r]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n", body).strip()

    return f"[{title} | {url}]\n{body[:8000]}"


# 暴露给 LLM 的工具 schema(Anthropic tools 格式)
TOOLS = [
    {
        "name": "web_search",
        "description": "联网搜索。当问题涉及课件之外的知识、或需要最新实践/版本信息时使用。",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索词,中文或英文均可"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_notes",
        "description": "在学员的个人学习知识库(Obsidian 笔记)中检索。问题与其已学内容相关时使用。",
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string", "description": "关键词"}},
            "required": ["keyword"],
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    """工具派发:名字 → 函数。未知工具返回提示(不崩,模型会自我纠正)。"""
    if name == "web_search":
        return web_search(args["query"])
    if name == "read_notes":
        return read_notes(args["keyword"])
    return f"(未知工具 {name})"
