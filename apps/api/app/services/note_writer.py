"""学习沉淀写回(P3·N1)—— 学完一节课,三源蒸馏成笔记,确认闸后写回 vault。

三源:课件骨架(讲了什么) / SQLite 对话(我问过什么) / grade 轨迹(纠偏了什么)。
分流:vault 无同主题笔记 → 新建整篇;已有 → 末尾追加日期块(易审校不污染原结构)。
铁律:vault 只读,唯此模块经**人确认**后写,且仅限 新笔记/追加块/待探勾选 三种动作。
蒸馏 = 单次 LLM 调用(无再决策,不进循环)。

用法:
    uv run python -m app.note_writer <course_id> [--dry]   # --dry 只出草稿不问
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.memory import list_sessions, session_history
from app.core.trace import read_traces

# ---------- 收集:三源会话事实 ----------


def _course_of(course_id: str) -> dict[str, Any]:
    p = settings.courses_dir / f"{course_id}.csl.json"
    d: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return d


def _render_course(course: dict[str, Any]) -> str:
    """课件骨架给 LLM:讲过的话就是「讲了什么」的第一手事实。v2 节→块,v1 页兼容。"""
    lines = [f"# {course['title']}(场景:{course['scenario']})"]
    if course.get("version") == 2:
        for i, sec in enumerate(course.get("sections", []), 1):
            lines.append(f"\n[第{i}节] {sec.get('heading', '')}")
            for b in sec.get("blocks", []):
                bt = b.get("type")
                if bt in ("p", "callout"):
                    lines.append(f"  {b.get('text', '')}")
                elif bt == "quiz":
                    rule = b.get("pass_rule") or "—"
                    lines.append(f"  ◆检查点:{b.get('question', '')}(标准:{rule})")
                elif bt == "flashcards":
                    lines.extend(
                        f"  ▫闪卡:{card.get('front', '')} → {card.get('back', '')}"
                        for card in b.get("cards", [])
                    )
        return "\n".join(lines)
    for i, page in enumerate(course.get("pages", []), 1):
        lines.append(f"\n[第{i}页] {page.get('title') or page.get('eyebrow') or page['id']}")
        for s in page["script"]:
            lines.append(f"  {s['text']}")
        if page.get("checkpoint"):
            cp = page["checkpoint"]
            lines.append(f"  ◆检查点:{cp['question']}(标准:{cp.get('pass_rule', '—')})")
    return "\n".join(lines)


def _render_dialogs(course_id: str, limit: int = 10) -> str:
    """该课的答疑问答(我问过什么——最个性化的部分)。"""
    out: list[str] = []
    for s in list_sessions(course_id)[:limit]:
        for t in session_history(s["id"]):
            tag = "问" if t["role"] == "user" else "答"
            out.append(f"{tag}:{t['content'][:300]}")
    return "\n".join(out) or "(本轮没有提问记录)"


def _render_grades(course_id: str) -> str:
    """检查点批改(哪里被纠偏——最值得复习的地方)。"""
    out = []
    for g in read_traces("grade.jsonl", limit=200):
        if g.get("course_id") != course_id:
            continue
        score = g.get("score")
        score_s = f"{score}分 · " if score is not None else ""
        precise = str(g.get("precise") or "")[:150]
        out.append(
            f"[{g.get('verdict')}{(' ' + score_s) if score_s else ''}"
            f"{g.get('page_id')}]:复述「{g.get('answer', '')[:80]}」"
            f"→ {g.get('comment', '')[:120]}"
            + (f"  ▸标准表述:{precise}" if precise else "")
        )
    return "\n".join(out) or "(没有检查点批改记录)"


# ---------- 落点:目录解析 + 新建/追加分流 ----------


def _norm(seg: str) -> str:
    return re.sub(r"^\d+-", "", seg)


def _dir_for_topic(topic: str) -> tuple[Path, bool]:
    """topic(如 Agent / harness / Runtime)→ vault 真实目录(编号目录靠归一匹配)。"""
    want = "/".join(_norm(s) for s in topic.split(" / "))
    kb = settings.kb_dir
    for d in [p for p in kb.rglob("*") if p.is_dir()]:
        rel = d.relative_to(kb).as_posix()
        if "/".join(_norm(s) for s in rel.split("/")) == want:
            return d, True
    return kb, False  # 找不到 → 落根(闸里明示,人确认)


def _existing_note(title: str) -> Path | None:
    """vault 里已有同名笔记?(决定新建还是追加)"""
    for md in settings.kb_dir.rglob(f"{title}.md"):
        if "待探" not in md.name:
            return md
    return None


def _todo_edit(title: str) -> tuple[Path, str, str] | None:
    """待探行勾选:找到含该主题的待探行 → (文件, 原行, 新行)。"""
    import time

    today = time.strftime("%Y-%m-%d")
    stem = title.split("(")[0].strip()
    for md in settings.kb_dir.rglob("*待探*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for ln in text.splitlines():
            if ln.strip().startswith("- [ ]") and stem in ln:
                new = ln.replace("- [ ]", "- [x]", 1).rstrip()
                new = f"{new}({today})→ [[{stem}]] ✅"
                return md, ln, new
    return None


# ---------- 蒸馏:单次 LLM ----------

_NEW_PROMPT = """你是笔记整理员,把一节 AI 课的学习过程蒸馏成一份符合学员 vault 风格的笔记。
只整理「发生过的事实」,不添加课程外的新知识;巩固区必须留空(动脑活不代填)。

课件内容(讲了什么):
{course}

学员的提问与回答(我问过什么):
{dialogs}

检查点批改记录(哪里被纠偏):
{grades}

主题:{title} · 所属层级:{topic}

只输出 Markdown 笔记本体(从 --- frontmatter 开始,不要额外说明),结构:
---
领域: {domain}
类型: 笔记
状态: 🌱
来源: 课程 {course_id}(AI 课)· {date}
---
# {title}
> 一句话:这节课学了什么
## 核心认知(5~8 条,课件要点蒸馏,重要术语与关联概念用 [[双链]])
## 我问过的(有真实提问才写,没有就删掉这节)
## 纠偏记录(有批改才写,没有就删掉)
## 巩固(留空!只给题目不给答案)
- [ ] 用自己的话默写:{title}最核心的一点
- ________________
## 🔗 关联
[[上游相关概念]](从课件 eyebrow/双链线索里挑 2~3 个)"""

_APPEND_PROMPT = """你是笔记整理员。学员已有笔记《{title}》,今天又上了一节相关 AI 课。
只输出**要追加到笔记末尾的日期块**(增量内容,不重复已有笔记里的点),从 ## 开始,不要额外说明。

已有笔记(避免重复):
{existing}

--- 以下为本课新事实 ---
课件:
{course}

学员提问:
{dialogs}

纠偏记录:
{grades}

输出格式:
## ⏫ {date} 增补(课程《{course_id}»)
### 新学到的(3~6 条,[[双链]]重要概念)
### 新问出的(有才写)
### 巩固(留空,只给题)
"""


def build_draft(course_id: str) -> dict[str, Any]:
    """生成写回草稿(不落盘)。返回 {mode, note_path, content, todo_edit}。"""
    import time

    from app.services.catalog import course_topic

    course = _course_of(course_id)
    title = course["title"].split("(")[0].strip() or course["title"]
    # topic 与课程库同一真相源(catalog 推导),文件里缺也不怕
    topic = course_topic(course_id) or "未分组"
    domain = topic.split(" / ")[0]
    today = time.strftime("%Y-%m-%d")

    existing = _existing_note(title)
    course_txt = _render_course(course)
    dialogs = _render_dialogs(course_id)
    grades = _render_grades(course_id)

    # 离线蒸馏放宽单次超时(同 prep/research):三源蒸馏要写整篇笔记,
    # 中转慢速时 60s 必掐死(实测 ReadTimeout);chat 的 60s 交互护栏不受影响
    client = get_llm_client().with_options(timeout=240.0)
    if existing:
        prompt = _APPEND_PROMPT.format(
            title=title,
            existing=existing.read_text(encoding="utf-8")[:4000],
            course=course_txt[:6000],
            dialogs=dialogs[:3000],
            grades=grades[:1500],
            date=today,
            course_id=course_id,
        )
        note_path = existing
        mode = "append"
    else:
        d, found = _dir_for_topic(topic)
        prompt = _NEW_PROMPT.format(
            course=course_txt[:6000],
            dialogs=dialogs[:3000],
            grades=grades[:1500],
            title=title,
            topic=topic,
            domain=domain,
            course_id=course_id,
            date=today,
        )
        note_path = d / f"{title}.md"
        mode = "new" if found else "new-root"

    resp = client.messages.create(
        model=settings.llm_model,
        max_tokens=16384,  # 思考模型的思考块也吃预算:蒸馏整课笔记思考很重,
        # 实测 8192 被全烧光零文本(同 grader,这里更深)
        messages=[{"role": "user", "content": prompt}],
    )
    content = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not content:
        raise RuntimeError(
            f"笔记蒸馏零文本输出(stop={resp.stop_reason}, "
            f"blocks={[b.type for b in resp.content]})——多为思考块吃尽预算"
        )
    if content.startswith("```"):  # 容忍围栏(同 grader)
        content = content.strip("`").removeprefix("markdown").strip()
    # 删掉空占位节(「(无)」),有真内容的才留
    content = re.sub(r"\n## [^\n]+\n+\(无\)\n?", "\n", content)
    return {
        "mode": mode,
        "title": title,
        "note_path": str(note_path),
        "content": content,
        "todo_edit": _todo_edit(course["title"]),
    }


_RECHECK_PROMPT = """你是笔记审校员。学员有一篇已学的笔记,现在拿到了一份基于最新开源实践
(Codex CLI/DeepSeek dsh/Anthropic 工程博客)的外证调研材料。
只输出**要追加到笔记末尾的日期块**——对照笔记原文,给「印证/补充/演进」三类增量;
笔记里已被印证的论断只需一句点名(不重抄),重点是笔记没有的新东西。
原文一字不提修改建议;没增量就只输出一行"(外证完成:本文论断全部被最新实践印证)"。

已有笔记:
{note}

外证材料(最新实践,带来源):
{material}

输出格式(Markdown,从 ## 开始,不要额外说明):
## ⏫ {date} 外证增补(来源:Codex CLI / DeepSeek dsh / Anthropic 工程博客)
### ✅ 被印证的(逐条一句点名,注 [[相关原文小节]])
### ➕ 新补充的(笔记没有的新知识/新数字,重要概念 [[双链]])
### 🔀 已演进的(笔记说法需更新的地方:旧说法 → 现状,带来源)
"""


def build_recheck(note_rel: str, material_path: str) -> dict[str, Any]:
    """外证增补:已有笔记 + 最新调研材料 → 末尾日期块草稿(不落盘,确认闸后追加)。"""
    import time

    note_path = settings.kb_dir / note_rel
    note_text = note_path.read_text(encoding="utf-8")
    material = json.loads(Path(material_path).read_text(encoding="utf-8"))

    src_lines = "\n".join(
        f"[{s['id']}] {s['title'][:40]} | {s['url'][:60]}" for s in material["sources"]
    )
    mat_lines = ""
    for g in material["groups"]:
        mat_lines += f"\n## {g['heading']}"
        for p in g["points"]:
            sid = f"(源[{p.get('source_id')}])" if p.get("source_id") else ""
            mat_lines += f"\n- {p['text']}{sid}"

    client = get_llm_client().with_options(timeout=240.0)
    resp = client.messages.create(
        model=settings.llm_model,
        max_tokens=16384,  # 思考模型的思考块也吃预算(同 grader/note 蒸馏,见上)
        messages=[
            {
                "role": "user",
                "content": _RECHECK_PROMPT.format(
                    note=note_text[:5000],
                    material=(src_lines + mat_lines)[:7000],
                    date=time.strftime("%Y-%m-%d"),
                ),
            }
        ],
    )
    content = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not content:
        raise RuntimeError(
            f"外证增补零文本输出(stop={resp.stop_reason}, "
            f"blocks={[b.type for b in resp.content]})——多为思考块吃尽预算"
        )
    if content.startswith("```"):
        content = content.strip("`").removeprefix("markdown").strip()
    return {"mode": "append", "note_path": str(note_path), "content": content, "todo_edit": None}


def apply_draft(draft: dict[str, Any]) -> None:
    """确认后执行写回:新笔记 / 追加块 / 待探勾选。只这三种动作,别的不碰。"""
    p = Path(draft["note_path"])
    if draft["mode"] == "append":
        with p.open("a", encoding="utf-8") as f:
            f.write("\n\n" + draft["content"] + "\n")
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(draft["content"] + "\n", encoding="utf-8")
    if draft["todo_edit"]:
        md, old, new = draft["todo_edit"]
        md.write_text(
            md.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8"
        )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="学习沉淀写回(P3):草稿→确认→落盘")
    ap.add_argument("course_id", nargs="?", help="按课件写回(学完闸由 API 层把关)")
    ap.add_argument("--recheck", metavar="NOTE", help="外证增补模式:vault 笔记相对路径")
    ap.add_argument("--material", help="外证材料 JSON 路径(--recheck 时必填)")
    ap.add_argument("--dry", action="store_true", help="只看草稿,不询问不落盘")
    a = ap.parse_args()

    if a.recheck:
        if not a.material:
            ap.error("--recheck 需要同时给 --material <调研材料.json>")
        d = build_recheck(a.recheck, a.material)
    elif a.course_id:
        d = build_draft(a.course_id)
    else:
        ap.error("给 course_id,或 --recheck NOTE --material MAT")
    print(f"模式:{'追加到已有笔记' if d['mode'] == 'append' else '新建笔记'}")
    print(f"落点:{d['note_path']}")
    if d["todo_edit"]:
        md, old, new = d["todo_edit"]
        print(f"待探勾选({md.name}):\n  - {old.strip()}\n  + {new.strip()}")
    print("\n----- 草稿 -----\n")
    print(d["content"])
    print("\n----- 草稿结束 -----")
    if a.dry:
        print("(--dry:未写回)")
    else:
        if input("\n确认写回 vault? [y/N] ").strip().lower() == "y":
            apply_draft(d)
            print(f"✅ 已写回:{d['note_path']}")
        else:
            print("已取消,vault 未动")
