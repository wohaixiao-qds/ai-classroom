"""课表(学习指挥台)数据组装:扫 vault + 课件 + 候选池,并成四泳道。

数据来源(见 P1.5 §四):
- 在学的   courses/*.csl.json(已出课)
- 能学的   vault 笔记(有内容、未被任何课的 source_notes 覆盖)
- 想学的   各 *待探.md 里未打勾的 `- [ ]` 项(顺序=文件内排列,规则二)
- 刚冒出的 trace 里 web_search 触发过的问题(课件答不了=天然候选)+ 候选池状态

vault 只读(边界铁律 5):本模块只 walk/read,绝不写。
规则一(哪些笔记算数):排除 `00-`/`_`/`.` 开头、根目录管理文件、99-System、待探索引。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.core.catalog_store import action_index
from app.core.config import settings
from app.core.progress import completion
from app.core.trace import read_traces
from app.schemas.catalog import Catalog, CourseItem, NoteItem, SparkItem, TodoItem
from app.schemas.csl import parse_course

_EXCLUDE_DIRS = {"99-System"}  # 系统目录,非学习内容
_ROOT_MGMT = {"术语表", "进度", "下次继续", "README", "CLAUDE"}  # 规则一:根目录管理文件
_NORM_RE = re.compile(r"[\s，。、？！?!,.:：;；]+")
_TODO_RE = re.compile(r"^- \[ \]\s*(.+)$")  # 未打勾的待探项
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _skip(name: str) -> bool:
    return name.startswith((".", "_", "00-"))


def _norm(q: str) -> str:
    """问题归一化(与 eval.norm_q 同规则):去空白标点,近似问法归一组。"""
    return _NORM_RE.sub("", q).lower()


def _area(full: Path, root: Path) -> str:
    """从相对路径的目录部分拼层级名,去掉编号前缀:03-Runtime → Runtime。"""
    parts = full.relative_to(root).parts[:-1]
    return " / ".join(re.sub(r"^\d+-", "", p) for p in parts)


def _norm_path(rel: str) -> str:
    """路径归一:剥掉每段的编号前缀(01-harness → harness),让课件 source_notes
    与实际 vault 路径能对上——目录事后改了编号也不失联(实测踩过)。"""
    return "/".join(re.sub(r"^\d+-", "", seg) for seg in rel.split("/"))


def _vault_map() -> dict[str, Path]:
    """知识库 norm 路径 → 真实路径 映射(老课件 source_notes 无编号,靠双方归一对上,同 B1 关联)。"""
    kb = settings.kb_dir
    out: dict[str, Path] = {}
    if not kb.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(kb):
        dirnames[:] = sorted(d for d in dirnames if not _skip(d) and d not in _EXCLUDE_DIRS)
        for fn in filenames:
            if fn.endswith(".md"):
                full = Path(dirpath) / fn
                out[_norm_path(str(full.relative_to(kb)))] = full
    return out


def _derive_topic(source_notes: list[str], vault_map: dict[str, Path]) -> str | None:
    """课程库分组钥匙:meta.topic 缺失时从 source_notes 实时推导。
    原料路径(相对/绝对皆可) → 读原料 JSON 的 topic;vault 路径 → 层级名(去编号)。"""
    for sn in source_notes:
        if "data/research" in sn:
            mp = settings.data_dir / "research" / Path(sn).name
            try:
                return str(json.loads(mp.read_text(encoding="utf-8"))["topic"])
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        if not Path(sn).is_absolute():
            real = vault_map.get(_norm_path(sn))
            if real:
                parts = real.relative_to(settings.kb_dir).parts[:-1]
                return " / ".join(re.sub(r"^\d+-", "", p) for p in parts) or None
    return None


def _load_courses() -> tuple[list[CourseItem], set[str]]:
    """扫已出课件 + 收集被覆盖的笔记路径(source_notes)。"""
    items: list[CourseItem] = []
    covered: set[str] = set()
    vault_map = _vault_map()
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        try:
            course = parse_course(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 单个坏课件不该拖垮整张课表
            continue
        items.append(
            CourseItem(
                id=course.id,
                title=course.title,
                pages=course.unit_count,
                checkpoints=course.checkpoint_count,
                topic=course.meta.topic or _derive_topic(course.meta.source_notes, vault_map),
                depends_on=course.meta.depends_on,
                ready=completion(course.id).ready,
            )
        )
        covered.update(_norm_path(sn) for sn in course.meta.source_notes)
    # 分组序稳定:有主题的按主题排(与 vault 编号天然对齐),未分组垫底
    items.sort(key=lambda c: (c.topic is None, c.topic or "", c.title))
    return items, covered


def _scan_notes(covered: set[str], prep: set[str], status_of: dict[str, str]) -> list[NoteItem]:
    """能学的:有笔记、未被任何课覆盖。"""
    root = settings.kb_dir
    notes: list[NoteItem] = []
    if not root.exists():
        return notes
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _skip(d) and d not in _EXCLUDE_DIRS]
        for fn in filenames:
            if not fn.endswith(".md") or _skip(fn) or "待探" in fn:
                continue
            stem = fn[:-3]
            if stem in _ROOT_MGMT:
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            if _norm_path(rel) in covered:
                continue  # 已被某课覆盖 → 归「在学的」(课卡代表),不重复出现
            notes.append(
                NoteItem(
                    title=stem,
                    path=rel,
                    area=_area(full, root),
                    requested=rel in prep,
                    status=status_of.get(rel),
                )
            )
    notes.sort(key=lambda n: n.path)
    return notes


def _scan_todos(research: set[str], status_of: dict[str, str]) -> list[TodoItem]:
    """想学的:各 *待探.md 里未打勾的 `- [ ]` 项,保持文件内顺序(规则二)。"""
    root = settings.kb_dir
    todos: list[TodoItem] = []
    if not root.exists():
        return todos
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip(d) and d not in _EXCLUDE_DIRS)
        for fn in sorted(filenames):
            if not fn.endswith(".md") or "待探" not in fn:
                continue
            full = Path(dirpath) / fn
            area = _area(full, root)
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # 编码/IO 异常不该拖垮整张课表(与 _load_courses/read_traces 同姿态)
            for line in text.splitlines():
                m = _TODO_RE.match(line.strip())
                if not m:
                    continue
                rest = m.group(1)
                bold = _BOLD_RE.search(rest)
                title = bold.group(1) if bold else re.split(r"[—(（]", rest, maxsplit=1)[0].strip()
                hint = _BOLD_RE.sub("", rest).strip(" —(（)）").strip() or None
                todos.append(
                    TodoItem(
                        title=title,
                        area=area,
                        hint=hint,
                        requested=title in research,
                        status=status_of.get(title),
                    )
                )
    return todos


def _sparks(confirmed: set[str], dismissed: set[str]) -> list[SparkItem]:
    """刚冒出的:trace 里 web_search 触发过的问题(课件答不了),按最新去重。"""
    rows = [
        r
        for r in read_traces("tutor.jsonl", limit=1000)  # read_traces 已最新在前
        if r.get("source") != "test" and r.get("searched")
    ]
    seen: set[str] = set()
    out: list[SparkItem] = []
    for r in rows:
        q = (r.get("question") or "").strip()
        key = _norm(q)
        if not q or key in seen or key in dismissed:
            continue
        seen.add(key)
        detail = " / ".join(
            str((c.get("args") or {}).get("query"))
            for c in r.get("tool_calls", [])
            if c.get("name") == "web_search"
        )
        out.append(
            SparkItem(
                question=q,
                key=key,
                page_id=r.get("page_id"),
                detail=detail or None,
                confirmed=key in confirmed,
            )
        )
    return out


def find_todo_area(title: str) -> str | None:
    """查一个待探项所在的 vault 层级(如「解析层」→ Agent / harness / Runtime)。
    job_runner 发起调研时用它把层级带进 topic,让课归位到知识版图正确位置。"""
    root = settings.kb_dir
    if not root.is_dir():
        return None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip(d) and d not in _EXCLUDE_DIRS)
        for fn in sorted(filenames):
            if not fn.endswith(".md") or "待探" not in fn:
                continue
            full = Path(dirpath) / fn
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if title in text:
                return _area(full, root)
    return None


def course_topic(course_id: str) -> str | None:
    """课件的主题(公开入口:P3 写回等要和课程库同一真相源——文件缺 topic 时实时推导)。"""
    p = settings.courses_dir / f"{course_id}.csl.json"
    try:
        course = parse_course(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 坏文件给 None,调用方自行兜底
        return None
    return course.meta.topic or _derive_topic(course.meta.source_notes, _vault_map())


def build_catalog() -> Catalog:
    """组装四泳道。"""
    idx = action_index()
    courses, covered = _load_courses()
    todo = _scan_todos(idx["research"], idx["status_of"])
    # 新主题入口:网页输入框发起的调研,主题不在 vault 待探里——并进「想学的」显示
    known = {t.title for t in todo}
    extra = [
        TodoItem(
            title=target,
            area="我想学 · 新主题",
            hint=None,
            requested=True,
            status=st,
        )
        for target, st in idx["status_of"].items()
        if target in idx["research"] and target not in known
    ]
    return Catalog(
        learning=courses,
        notes=_scan_notes(covered, idx["prep"], idx["status_of"]),
        todo=[*extra, *todo],
        sparks=_sparks(idx["confirmed"], idx["dismissed"]),
    )
