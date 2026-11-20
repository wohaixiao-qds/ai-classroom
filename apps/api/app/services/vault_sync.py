"""大纲→vault 目录同步(2026-11-03 用户拍板:「系统出的大纲和本地知识库目录一致,全自动跟随」)。

职责:大纲产生或调整后,保证 vault 侧目录与大纲结构一致——
- 主题目录:绑定持久化在 framework JSON 的 ``theme_dir`` 字段;
  首次解析顺序 = 别名表 → 绑定 → 归一名匹配 → 新建;
- 篇目录:按 courses 的 part 去重保序建 ``NN-<part>``;
  part 消失时其中笔记撤到主题根(不删数据);
- 大纲快照:主题目录下 ``大纲.md`` 每次同步重新生成(路线+goal+先修链+已出课✓);
- 只动目录与骨架文档,不动笔记内容。

策略注记:
- 目录编号是稳定 id 不是篇序——篇中段插入新篇时编号顺延不重排,篇序看大纲;
- part 改名 = 删旧篇+建新篇(旧篇笔记自动撤到主题根);
- 用户在 Obsidian 里改主题目录名会使绑定失联(会重建空目录),
  把 framework 的 theme_dir 改回新名即可;
- 触发点:outline_prep / request_research 出大纲后(job_runner)、
  大纲 PUT 落盘后(routes/outline)、pipeline --auto。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

# 存量主题的首绑(之后以 framework.theme_dir 为准,别名表只为免迁移)
_ALIAS: dict[str, str] = {
    "Agent Harness": "01-harness",
    "Agent 解析层": "02-解析层",
    "RAG 检索增强": "03-RAG",
    "MCP(Model Context Protocol)": "04-MCP",
    "MCP\uff08Model Context Protocol\uff09": "04-MCP",  # 全角括号变体(实测 fw topic 用它)
}

_EXCLUDE_TOP_DIRS = {"99-System", ".obsidian"}


def _norm(seg: str) -> str:
    """去「NN-」编号前缀(与 note_writer._dir_for_topic 同款归一)。"""
    return re.sub(r"^\d+-", "", seg.strip())


def _slug_like(s: str) -> str:
    """与 research._slug 同款(不 import agent 模块,复制三行)。"""
    return re.sub(r"[^\w-]+", "-", s).strip("-")[:40] or "topic"


def framework_path(topic: str) -> Path:
    return settings.data_dir / "research" / f"{_slug_like(topic)}.framework.json"


def _clean_theme(topic: str) -> str:
    """主题串 → 目录短名:去括注、去「Agent」领域前缀、空格转连字符。"""
    t = re.sub(r"[（(][^）)]*[）)]", "", topic).strip()
    t = re.sub(r"^Agent[\s /·]+", "", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", "-", t)[:24] or "theme"


def _parts_of(fw: dict[str, Any]) -> list[str]:
    """courses 的 part 去重保序(courses 本身按学习序排)。"""
    out: list[str] = []
    for c in fw.get("courses", []):
        p = str(c.get("part") or "").strip()
        if p and p not in out:
            out.append(p)
    return out


def _domain_base(fw: dict[str, Any]) -> Path | None:
    """vault 领域目录。fw 的 domain 是调研自由文本(实测有「Agent 工程」「RAG 工程」),
    取首词。已有主题保留绑定;新领域使用自己的目录,不再统一回落 Agent。"""
    kb = settings.kb_dir
    if not kb.is_dir():
        return None
    dom = (str(fw.get("domain") or "").strip() or "Agent").split()[0]
    dom = re.sub(r"[^\w-]", "", dom) or "未分类"
    legacy = kb / "Agent"
    bound = str(fw.get("theme_dir") or "").strip()
    alias = _ALIAS.get(str(fw.get("topic") or ""))
    # 旧 RAG/MCP 主题原本就在 Agent 下,领域适配不搬动既有笔记。
    if (bound and Path(bound).name == bound and (legacy / bound).is_dir()) or (
        alias and (legacy / alias).is_dir()
    ):
        return legacy
    return kb / dom


def _resolve_theme_dir(fw: dict[str, Any], topic: str) -> Path | None:
    """绑定 → 别名 → 归一名匹配;找不到返回 None(由调用方新建)。"""
    base = _domain_base(fw)
    if base is None or not base.is_dir():
        return None
    bound = str(fw.get("theme_dir") or "").strip()
    if bound and (base / bound).is_dir():
        return base / bound
    want = str(fw.get("topic") or topic)
    alias = _ALIAS.get(want) or _ALIAS.get(topic)
    if alias and (base / alias).is_dir():
        return base / alias
    cleaned = _norm(_clean_theme(want)).lower()
    for d in sorted(base.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            if _norm(d.name).lower() == cleaned:
                return d
    return None


def _create_theme_dir(fw: dict[str, Any], topic: str) -> Path | None:
    base = _domain_base(fw)
    if base is None:
        return None
    base.mkdir(exist_ok=True)
    bound = str(fw.get("theme_dir") or "").strip()
    name = bound or _clean_theme(str(fw.get("topic") or topic))
    if not re.match(r"^\d+-", name):
        nums = [int(m.group(1)) for d in base.iterdir() if (m := re.match(r"^(\d+)-", d.name))]
        name = f"{max(nums, default=0) + 1:02d}-{name}"
    d = base / name
    d.mkdir(exist_ok=True)
    return d


def _outline_stub(fw: dict[str, Any], theme: Path) -> None:
    """同步新建的主题目录补一枚最小导览(已有导览的主题不覆盖)。"""
    if any(theme.glob("00-*导览.md")):
        return
    topic = str(fw.get("topic") or theme.name)
    n = len(fw.get("courses", []))
    parts = _parts_of(fw)
    dom = (_domain_base(fw) or Path("Agent")).name
    body = (
        "---\n"
        f"领域: {dom}\n类型: 索引\n状态: 🚧 大纲同步自动建\n---\n\n"
        f"# {topic} · 导览(MOC)\n\n"
        f"> 由 ai-classroom 大纲同步自动创建(2026-11-03 起,目录跟随课堂大纲)。\n"
        f"> 想学/点单在生成中心;**笔记学完一门、经打卡→蒸馏→确认闸后写回一门**,落所在篇目录。\n\n"
        f"## 与课堂路线的对应\n\n"
        f"大纲 {n} 门" + (f"、{len(parts)} 篇:{' / '.join(parts)}" if parts else "") + "。"
        "路线全文见 [[大纲]](同步自动更新)。\n\n"
        f"## 🔗\n[[00-{dom}导览]] · [[大纲]]\n"
    )
    (theme / f"00-{_clean_theme(topic)}导览.md").write_text(body, encoding="utf-8")


def _course_published(course: dict[str, Any]) -> bool:
    """已出课判定(轻量版):course_ref / outline_course_id 反查 / 课名兜底。"""
    refs = [str(x).strip() for x in (course.get("course_refs") or []) if str(x).strip()]
    ref = str(course.get("course_ref") or "").strip() or (refs[0] if refs else "")
    if ref:
        return (settings.courses_dir / f"{ref}.csl.json").exists()
    title = str(course.get("title") or "").strip()
    oid = str(course.get("id") or "").strip()
    for p in settings.courses_dir.glob("*.csl.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(d.get("title", "")) == title or str(
            d.get("meta", {}).get("outline_course_id", "")
        ) == oid:
            return True
    return False


def _write_outline_doc(fw: dict[str, Any], theme: Path) -> None:
    """重生成主题目录下的 大纲.md(自动同步,永不过期)。"""
    topic = str(fw.get("topic") or theme.name)
    dom = (_domain_base(fw) or Path("Agent")).name
    lines = [
        "---",
        f"领域: {dom}",
        "类型: 索引",
        f"状态: 🔄 自动同步({time.strftime('%Y-%m-%d')})",
        "---",
        "",
        f"# 📍 {topic} · 课堂大纲(学习路线)",
        "",
        f"> 由 ai-classroom 生成中心「{topic}」大纲自动同步生成;想学/点单在生成中心。",
        "> **笔记学完一门、经打卡→蒸馏→确认闸后写回一门**,落所在篇目录;",
        "> 本文件每次大纲调整后自动重写。",
        "",
    ]
    parts = _parts_of(fw)
    idx = 0
    for part in parts:
        lines.append(f"### {part}")
        lines.append("")
        for c in fw.get("courses", []):
            if str(c.get("part") or "").strip() != part:
                continue
            idx += 1
            mark = "✅" if _course_published(c) else "⬜"
            preqs = "、".join(f"「{p}」" for p in c.get("prereqs", [])) or "—"
            lines.append(f"{idx}. {mark} **{c.get('title')}** — {c.get('goal')}")
            if c.get("why"):
                lines.append(f"   学习动机:{c.get('why')}")
            lines.append(f"   先修:{preqs}")
        lines.append("")
    if not parts:
        lines.append("## 路线")
        lines.append("")
        for i, c in enumerate(fw.get("courses", []), 1):
            mark = "✅" if _course_published(c) else "⬜"
            lines.append(f"{i}. {mark} **{c.get('title')}** — {c.get('goal')}")
            if c.get("why"):
                lines.append(f"   学习动机:{c.get('why')}")
        lines.append("")
    (theme / "大纲.md").write_text("\n".join(lines), encoding="utf-8")


def _sync_parts(theme: Path, parts: list[str]) -> list[str]:
    """建缺失篇目录;part 消失的目录把笔记撤到主题根再删(只看带编号的目录,附属层不动)。"""
    log: list[str] = []
    if not parts:
        return log
    existing = [d for d in theme.iterdir() if d.is_dir() and re.match(r"^\d+-", d.name)]
    by_norm: dict[str, Path] = {}
    used: set[int] = set()
    for d in existing:
        by_norm.setdefault(_norm(d.name), d)
        if m := re.match(r"^(\d+)-", d.name):
            used.add(int(m.group(1)))
    for p in parts:
        if p in by_norm:
            continue
        n = 1
        while n in used or (theme / f"{n:02d}-{p}").exists():
            n += 1
        used.add(n)
        d = theme / f"{n:02d}-{p}"
        d.mkdir(parents=True)
        log.append(f"建篇目录 {d.name}")
    part_set = set(parts)
    for d in existing:
        if _norm(d.name) in part_set:
            continue
        mds = [f for f in sorted(d.rglob("*.md")) if not f.name.startswith(".")]
        for f in mds:
            target = theme / f.name
            if target.exists():
                log.append(f"撤回跳过(重名):{f} → {target.name}")
                continue
            f.rename(target)
        if mds:
            log.append(f"篇「{d.name}」已不在大纲,{len(mds)} 篇笔记撤到主题根")
        if not any(d.iterdir()):
            d.rmdir()
            log.append(f"删空篇目录 {d.name}")
    return log


def sync_outline(fw: dict[str, Any], *, topic: str) -> str | None:
    """把一份大纲同步到 vault 目录;返回绑定的 theme_dir 名。幂等,失败返回 None 不抛。"""
    try:
        theme = _resolve_theme_dir(fw, topic) or _create_theme_dir(fw, topic)
        if theme is None:
            print(f"[vault-sync] 跳过:vault 目录不可用({settings.kb_dir})")
            return None
        log = _sync_parts(theme, _parts_of(fw))
        _outline_stub(fw, theme)
        _write_outline_doc(fw, theme)
        bound = theme.name
        if str(fw.get("theme_dir") or "") != bound:
            fw["theme_dir"] = bound
            p = framework_path(topic)
            if p.exists():
                p.write_text(
                    json.dumps(fw, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                log.append(f"绑定 theme_dir={bound}")
        area = theme_area(fw)
        msg = f"[vault-sync] {topic} → {area}" + (f" | {'; '.join(log)}" if log else "")
        print(msg)
        return bound
    except OSError as e:
        print(f"[vault-sync] 同步失败(不影响主流程): {e}")
        return None


def theme_area(fw: dict[str, Any]) -> str | None:
    """大纲主题的 vault 层级串(如 "Agent / RAG"),给 material.topic 拼 part 用。"""
    base = _domain_base(fw)
    if base is None:
        return None
    bound = str(fw.get("theme_dir") or "").strip()
    if not bound:
        theme = _resolve_theme_dir(fw, topic=str(fw.get("topic") or ""))
        bound = theme.name if theme else _ALIAS.get(str(fw.get("topic") or ""), "")
    if not bound:
        return None
    return f"{base.name} / {_norm(bound)}"
