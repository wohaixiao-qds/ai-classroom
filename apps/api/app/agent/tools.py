"""答疑 Agent 的两个工具:web_search(联网查) 与 read_notes(读知识库)。

工具返回纯文本(观测走调用侧的轨迹),异常向上抛由循环做错误回收。
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from app.core.config import settings


def web_search(query: str) -> str:
    """博查搜索,返回 top 结果的标题/链接/摘要文本。"""
    if not settings.search_api_key:
        return "(搜索不可用:未配置 SEARCH_API_KEY。请基于已有知识回答,并注明未经联网核实)"
    req = urllib.request.Request(
        "https://api.bochaai.com/v1/web-search",
        data=json.dumps({"query": query, "count": 5, "summary": True}).encode(),
        headers={
            "Authorization": f"Bearer {settings.search_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    lines = []
    for i, page in enumerate(data.get("data", {}).get("webPages", {}).get("value", []), 1):
        lines.append(f"[{i}] {page.get('name')}\n{page.get('url')}\n{page.get('summary','')[:300]}")
    return "\n\n".join(lines) or "(无搜索结果)"


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
