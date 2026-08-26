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
from typing import Any

from app.core.config import settings


def _bocha_search(query: str, recency: str | None = None) -> str:
    """博查搜索(中文生态强)。recency: day/week/month/year。"""
    body: dict[str, Any] = {"query": query, "count": 5, "summary": True}
    if recency:
        body["freshness"] = {"day": "oneDay", "week": "oneWeek",
                             "month": "oneMonth", "year": "oneYear"}[recency]
    req = urllib.request.Request(
        "https://api.bochaai.com/v1/web-search",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {settings.search_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data: Any = json.loads(resp.read())
    lines = []
    for i, page in enumerate((data.get("data") or {}).get("webPages", {}).get("value", []), 1):
        lines.append(f"[{i}] {page.get('name')}\n{page.get('url')}\n{page.get('summary','')[:300]}")
    return "\n\n".join(lines) or "(无搜索结果)"


def _tavily_search(query: str, recency: str | None = None) -> str:
    """Tavily(LLM 原生,免费 1000/月;官方英文内容强)。"""
    body: dict[str, Any] = {"query": query, "max_results": 5, "search_depth": "basic"}
    if recency:
        body["days"] = {"day": 1, "week": 7, "month": 30, "year": 365}[recency]
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {settings.tavily_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data: Any = json.loads(resp.read())
    lines = []
    for i, r in enumerate(data.get("results", []), 1):
        lines.append(f"[{i}] {r.get('title')}\n{r.get('url')}\n{str(r.get('content',''))[:300]}")
    return "\n\n".join(lines) or "(无搜索结果)"


# 引擎注册表:名字 / 调用 / key 探测(顺序即优先级)
def _anysearch_search(query: str, recency: str | None = None) -> str:
    """AnySearch(agent 原生搜索;API 无时间过滤参数,recency 忽略——多引擎合并时由其它引擎兜时效)。"""
    headers = {
        "Content-Type": "application/json",
        "X-Anysearch-Client": "classroom/1.0",
    }
    if settings.anysearch_api_key:
        headers["Authorization"] = f"Bearer {settings.anysearch_api_key}"
    req = urllib.request.Request(
        "https://api.anysearch.com/v1/search",
        data=json.dumps({"query": query, "max_results": 5}).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        envelope: Any = json.loads(resp.read())
    if envelope.get("code", 0) != 0:
        msg = f"(AnySearch 错误:{envelope.get('message', '?')})"
        raise OSError(msg)
    lines = []
    for i, r in enumerate((envelope.get("data") or {}).get("results") or [], 1):
        lines.append(
            f"[{i}] {r.get('title') or '(无题)'}\n{r.get('url')}"
            f"\n{str(r.get('content') or r.get('snippet') or '')[:300]}"
        )
    return "\n\n".join(lines) or "(无搜索结果)"


def anysearch_extract(url: str) -> str:
    """AnySearch 全文提取(干净 Markdown,截 5 万字)→ 统一 [标题|URL] 头。"""
    headers = {
        "Content-Type": "application/json",
        "X-Anysearch-Client": "classroom/1.0",
    }
    if settings.anysearch_api_key:
        headers["Authorization"] = f"Bearer {settings.anysearch_api_key}"
    req = urllib.request.Request(
        "https://api.anysearch.com/v1/extract",
        data=json.dumps({"url": url}).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        envelope: Any = json.loads(resp.read())
    if envelope.get("code", 0) != 0:
        msg = f"AnySearch extract 错误:{envelope.get('message', '?')}"
        raise OSError(msg)
    d = envelope.get("data") or {}
    title = str(d.get("title") or url)[:120]
    return f"[{title} | {url}]\n{str(d.get('content') or '')[:8000]}"




_ENGINES: list[tuple[str, Any, Any]] = [
    ("bocha", _bocha_search, lambda: settings.search_api_key),
    ("anysearch", _anysearch_search, lambda: True),  # 匿名可用,永远参与合并
    ("tavily", _tavily_search, lambda: settings.tavily_api_key),
]





def search_provider() -> str | None:
    """主 provider(单引擎调用,答疑用):博查 → AnySearch → Tavily。"""
    for name, _fn, has_key in _ENGINES:
        if has_key():
            return name
    return None


def web_search(query: str, recency: str | None = None) -> str:
    """联网搜索(主 provider),返回 top 结果的标题/链接/摘要文本。答疑用。"""
    p = search_provider()
    for name, fn, has_key in _ENGINES:
        if p == name and has_key():
            try:
                return str(fn(query, recency))
            except urllib.error.HTTPError as e:
                body = e.read().decode()[:200]
                return f"(搜索失败 HTTP {e.code}:{body}——基于已有知识回答并注明未经核实)"
    return "(搜索不可用:未配置任何搜索 key。请基于已有知识回答,并注明未经联网核实)"


def web_search_multi(query: str, recency: str | None = None) -> str:
    """多引擎合并观测(找资料 agent 用):博查中文生态 + AnySearch/Tavily 官方英文互补;
    单引擎失败不拖垮整体——把「社区视角」和「官方最新视角」都摆给模型。"""
    parts: list[str] = []
    for name, fn, has_key in _ENGINES:
        if not has_key():
            continue
        try:
            r = fn(query, recency)
        except urllib.error.HTTPError as e:
            r = f"(该引擎失败 HTTP {e.code},忽略)"
        parts.append(f"## 搜索引擎 {name}\n{r}")
    return "\n\n".join(parts) if parts else web_search(query, recency)


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
    """抓网页正文:优先 AnySearch 提取(干净 Markdown),失败回落本地剥标签(截断防超上下文)。

    返回体强制带 [标题|URL] 头——调用方(找资料 agent)引用内容时一定拿得到出处。
    """
    try:
        return anysearch_extract(url)
    except Exception:  # noqa: BLE001 提取服务不可用/不支持该页 → 本地剥标签兜底
        pass
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
