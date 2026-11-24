"""书末综合复测(T3):一本书(= 一份领域大纲)全部课程读完 → 抽样组卷邀请复测。

抽样策略(用户拍板「薄弱 + 跨课覆盖」):
- 第一梯队 薄弱:checkpoint_mastery 掌握度低于过门线(0.9)或复习到期未测;
- 第二梯队 未测过:全书读完之后还没重新 pass 过的检查点;
- 组卷用「每课轮流取最优」:课数 ≤ 卷容量时每门课至少一题(跨课覆盖),
  课多于容量时按各课最优候选的薄弱序取(薄弱优先),不硬凑均匀。
- 结果走现有 /grade 链,判过照常进 mastery 间隔轮——不建新表,不动 due_reviews 语义
  (综合复测是书页横幅入口,与「今日复习」到期队列是两条线)。

防重复疲劳(轻量,不建新表):完成判定 = 全书读完时刻(各课 done_at 取最大)之后,
learning_grades 里该书全部检查点各有一次 pass(任务口径「查全部检查点 pass 状态,
复用完成判定的同一存储」)——一轮卷只有 3~5 题,横幅会以薄弱优先持续邀请下一轮,
直到全书检查点都重测闭环;之后 status=completed,横幅不再自动弹出,可手动重测。
组卷随机量用「主题+读完时刻」做种子:同一轮内多次拉卷稳定,读完时刻一变(重读打卡)
自然换卷,不引入持久化的卷号。
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from typing import Any

from app.core.config import settings
from app.core.progress import completion
from app.schemas.learning import CumulativeItem, CumulativePaper
from app.services.mastery import GATE
from app.services.mastery import _conn as _mastery_conn

PAPER_MIN = 3
PAPER_MAX = 5


def _book_files(topic: str) -> tuple[list[str], list[str]]:
    """一本书的课件 id 有序清单(按大纲课序展开)+ 课标题表。

    出课判定三件套与列表/详情端点同源(勿两处漂移);服务层反向懒加载路由模块
    避免环(routes.outline → services.cumulative 薄壳)。
    """
    from app.routes.outline import (
        _course_file_ids,
        _existing_courses_index,
        _outline_linked_ids,
    )
    from app.services.outline_attribution import _load_outline

    d = _load_outline(topic)  # ValueError: 没有这本大纲 → 路由层转 404
    by_title, id_title, all_ids = _existing_courses_index(topic)
    linked = _outline_linked_ids(topic)
    file_ids: list[str] = []
    titles: list[str] = []
    for c in d["courses"]:
        refs = _course_file_ids(c, by_title, id_title, all_ids, linked)
        file_ids.extend(refs)
        titles.extend(id_title.get(r, r) for r in refs)
    return file_ids, titles


def _course_checkpoints(course_id: str, title: str) -> list[dict[str, Any]]:
    """一门课的检查点清单(裸 json 双版本,v2 quiz 块为准)。坏课件跳过不拖垮组卷。"""
    p = settings.courses_dir / f"{course_id}.csl.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 同 mastery._load_course 姿态
        return []
    out: list[dict[str, Any]] = []
    if d.get("version") == 2:
        for no, sec in enumerate(d.get("sections", []), 1):
            for b in sec.get("blocks", []):
                if b.get("type") == "quiz":
                    out.append(
                        {
                            "course_id": course_id,
                            "course_title": title,
                            "section_id": str(sec.get("id", "")),
                            "section_no": no,
                            "section_heading": str(sec.get("heading", "")),
                            "page_id": str(b.get("id", "")),
                            "question": str(b.get("question", "")),
                            "hint": b.get("hint"),
                            "pass_rule": b.get("pass_rule"),
                        }
                    )
    else:  # v1 容忍:页检查点(存量迁移前课件)
        for no, pg in enumerate(d.get("pages", []), 1):
            cp = pg.get("checkpoint")
            if cp:
                out.append(
                    {
                        "course_id": course_id,
                        "course_title": title,
                        "section_id": str(pg.get("id", "")),
                        "section_no": no,
                        "section_heading": str(pg.get("title") or pg.get("eyebrow") or ""),
                        "page_id": str(pg.get("id", "")),
                        "question": str(cp.get("question", "")),
                        "hint": cp.get("hint"),
                        "pass_rule": None,
                    }
                )
    return out


def _read_epoch(file_ids: list[str]) -> str | None:
    """全书读完时刻 = 各课 done_at 取最大(读完整书那一刻;重读打卡会刷新,自然换卷)。"""
    if not file_ids:
        return None
    db = settings.data_dir / "classroom.db"  # 调用时解析,临时目录测试即插即用
    if not db.exists():
        return None
    conn: sqlite3.Connection = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" for _ in file_ids)
        rows = conn.execute(
            f"SELECT done_at FROM course_progress WHERE course_id IN ({marks}) AND done=1",
            file_ids,
        ).fetchall()
    finally:
        conn.close()
    stamps = [str(r["done_at"]) for r in rows if r["done_at"]]
    return max(stamps) if stamps else None


def _fresh_pass_ids(file_ids: list[str], epoch: str | None) -> set[tuple[str, str]]:
    """读完时刻之后 pass 过的检查点集(learning_grades 一条 SQL;ts 同格式可直接比较)。"""
    out: set[tuple[str, str]] = set()
    conn = learning_store_conn()
    try:
        marks = ",".join("?" for _ in file_ids)
        rows = conn.execute(
            "SELECT DISTINCT course_id, page_id FROM learning_grades"
            f" WHERE verdict='pass' AND course_id IN ({marks})"
            + (" AND ts >= ?" if epoch else ""),
            (*file_ids, epoch) if epoch else file_ids,
        ).fetchall()
        for r in rows:
            out.add((str(r[0]), str(r[1])))
    finally:
        conn.close()
    return out


def learning_store_conn() -> sqlite3.Connection:
    """learning_grades 连接(库路径调用时解析,测试临时目录即插即用)。"""
    from app.core.learning_store import _conn

    return _conn()


def _mastery_rows(file_ids: list[str]) -> dict[tuple[str, str], sqlite3.Row]:
    with _mastery_conn() as c:
        marks = ",".join("?" for _ in file_ids)
        rows = c.execute(
            f"SELECT * FROM checkpoint_mastery WHERE course_id IN ({marks})", file_ids
        ).fetchall()
    return {(str(r["course_id"]), str(r["page_id"])): r for r in rows}


def _paper_size(total: int) -> int:
    """卷容量:总检查点 ≥3 抽 3~5,不足则全抽(1~2 题的薄书也要能复测)。"""
    if total < PAPER_MIN:
        return total
    return min(PAPER_MAX, total)


def _spread_by_course(
    ordered: list[tuple[tuple[float, ...], CumulativeItem]], size: int
) -> list[CumulativeItem]:
    """跨课覆盖取样:先每课轮流各取一题(课内按薄弱序,课序=各课最优候选的薄弱序),
    再用全书统一薄弱序填满剩余席位(跳过已选)。

    课 ≤ 容量 → 每课至少一题;课 > 容量 → 只做第一轮(薄弱课优先),不硬凑均匀。
    """
    by_course: dict[str, list[tuple[tuple[float, ...], CumulativeItem]]] = {}
    for key, item in ordered:
        by_course.setdefault(item.course_id, []).append((key, item))
    for items in by_course.values():
        items.sort(key=lambda pair: pair[0])
    course_order = sorted(by_course, key=lambda cid: by_course[cid][0][0])
    picked: list[CumulativeItem] = []
    # 第一轮:每课一题(覆盖优先)
    for cid in course_order:
        if len(picked) >= size:
            break
        picked.append(by_course[cid].pop(0)[1])
    # 剩余席位:按全书薄弱序补,跳过已选(保证薄弱优先不被覆盖稀释)
    if len(picked) < size:
        chosen = {id(it) for it in picked}
        for _, item in ordered:
            if len(picked) >= size:
                break
            if id(item) not in chosen:
                picked.append(item)
                chosen.add(id(item))
    return picked


def build_paper(topic: str) -> CumulativePaper:
    """组卷主入口:书读完判定 → 抽样 → 完成态判定。只读,不写任何状态。"""
    file_ids, titles = _book_files(topic)
    if not file_ids:
        return CumulativePaper(
            status="not_ready", topic=topic, total_checkpoints=0, passed_count=0, items=[]
        )
    ready = {fid: completion(fid).ready for fid in dict.fromkeys(file_ids)}
    finished = all(ready.get(fid, False) for fid in file_ids)

    candidates: list[dict[str, Any]] = []
    for fid, title in zip(file_ids, titles, strict=True):
        candidates.extend(_course_checkpoints(fid, title))
    if not finished or not candidates:
        return CumulativePaper(
            status="not_ready",
            topic=topic,
            total_checkpoints=len(candidates),
            passed_count=0,
            items=[],
        )

    epoch = _read_epoch(file_ids)
    fresh = _fresh_pass_ids(file_ids, epoch)
    mastery_rows = _mastery_rows(file_ids)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    # 全书统一薄弱序:梯队(薄弱0/未复测1/已复测2) → 掌握度升序 → 轮内稳定随机
    keys = "|".join(f"{c['course_id']}:{c['page_id']}" for c in candidates)
    rng = random.Random(f"{topic}|{epoch or ''}|{keys}")
    ordered: list[tuple[tuple[float, ...], CumulativeItem]] = []
    for c in candidates:
        key_id = (str(c["course_id"]), str(c["page_id"]))
        row = mastery_rows.get(key_id)
        m_value = float(row["mastery"]) if row is not None else None
        due = bool(
            row is not None and row["next_review_at"] and str(row["next_review_at"]) <= now
        )
        weak = due or (m_value is not None and m_value < GATE)
        fresh_pass = key_id in fresh
        if weak:
            tier = 0.0
        elif not fresh_pass:
            tier = 1.0
        else:
            tier = 2.0
        sort_key = (tier, m_value if m_value is not None else 0.0, rng.random())
        ordered.append(
            (
                sort_key,
                CumulativeItem(
                    course_id=str(c["course_id"]),
                    course_title=str(c["course_title"]),
                    section_id=str(c["section_id"]),
                    section_no=int(c["section_no"]),
                    section_heading=str(c["section_heading"]),
                    page_id=str(c["page_id"]),
                    question=str(c["question"]),
                    hint=c["hint"],
                    pass_rule=c["pass_rule"],
                    mastery=m_value,
                    due=due,
                    fresh_pass=fresh_pass,
                ),
            )
        )
    ordered.sort(key=lambda pair: pair[0])
    items = _spread_by_course(ordered, _paper_size(len(ordered)))
    passed_count = sum(1 for it in items if it.fresh_pass)
    # 完成态(轻量,任务口径「查 learning_grades 里该书全部检查点 pass 状态」):
    # 读完时刻之后,全书每个检查点都各有一次 pass——全书的综合复测确认闭环。
    # 一轮卷只有 3~5 题,横幅会以薄弱优先持续邀请下一轮,直到全书重测完;
    # 全部通过后 status=completed,横幅不再自动出(前端可手动重测)。
    completed = epoch is not None and all(
        (str(c["course_id"]), str(c["page_id"])) in fresh for c in candidates
    )
    return CumulativePaper(
        status="completed" if completed else "available",
        topic=topic,
        total_checkpoints=len(candidates),
        passed_count=passed_count,
        items=items,
    )
