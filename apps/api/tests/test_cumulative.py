"""T3 书末综合复测回归:全书读完判定 → 薄弱+跨课组卷 → /grade 链落库 → 完成态。

替身边界(沿 test_gaps 惯例):临时目录 SQLite/课件/traces,真实 classroom.db 与
courses/ 绝不触碰;本任务零模型调用(组卷纯确定性,批改走前端真实提交)。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.core import learning_store, progress
from app.core.config import settings
from app.core.prompts import QUIZ_FAIRNESS_RULE
from app.schemas.learning import CumulativePaper
from app.services import cumulative

_TOPIC = "测试书"
_COURSE_TITLES = ["第一课", "第二课", "第三课"]


def _course(course_id: str, title: str, quiz_ids: list[str]) -> dict[str, Any]:
    """v2 课件:两节,每节一个 p + 一个 quiz 块(quiz id 由调用方指定)。"""
    sections = []
    for i, qid in enumerate(quiz_ids, 1):
        sections.append(
            {
                "id": f"s{i}",
                "heading": f"{title}第{i}节",
                "blocks": [
                    {"type": "p", "text": "正文", "evidence_ids": []},
                    {
                        "type": "quiz",
                        "id": qid,
                        "question": f"问题{qid}",
                        "hint": f"提示{qid}",
                        "pass_rule": "能应用到新情境",
                        "evidence_ids": [],
                    },
                ],
            }
        )
    return {
        "id": course_id,
        "title": title,
        "scenario": "自学",
        "version": 2,
        "meta": {},
        "sections": sections,
    }


def _framework() -> dict[str, Any]:
    return {
        "topic": _TOPIC,
        "domain": "测试域",
        "courses": [
            {"id": f"oc{i}", "title": t, "goal": f"目标{t}", "prereqs": [], "part": "第一篇"}
            for i, t in enumerate(_COURSE_TITLES, 1)
        ],
    }


def _pass(course_id: str, page_id: str) -> None:
    """一次真实 /grade 落库形态的 pass(进 learning_grades,source=user)。"""
    learning_store.record_result(
        course_id, page_id, "我的复述", {"verdict": "pass", "score": 80, "comment": "✓ 对"}
    )


def _pass_past(course_id: str, page_id: str) -> None:
    """读完之前的 pass:落库后把 ts 拨到 PAST,与 done_at(当下)拉开可比较的时序。

    ts 秒级分辨率,同一秒内「先过后读完」会退化成相等(>= 判 fresh),
    真实使用不会发生;测试里显式拨时间保证语义确定。
    """
    _pass(course_id, page_id)
    conn: sqlite3.Connection = sqlite3.connect(settings.data_dir / "classroom.db")
    try:
        conn.execute(
            "UPDATE learning_grades SET ts=? WHERE course_id=? AND page_id=?",
            (CumulativeTests.PAST, course_id, page_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mastery_row(
    db: Path, course_id: str, page_id: str, mastery: float, next_review_at: str | None
) -> None:
    from app.services.mastery import _SCHEMA

    conn: sqlite3.Connection = sqlite3.connect(db)
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO checkpoint_mastery"
            " (course_id,page_id,history,mastery,stage,next_review_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (course_id, page_id, "[]", mastery, 0, next_review_at, "2020-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


class CumulativeTests(unittest.TestCase):
    PAST = "2020-01-01T00:00:00"  # 早于任何 done_at/grade ts

    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        stack.enter_context(tmp)
        for key in ("data_dir", "courses_dir", "traces_dir"):
            directory = Path(tmp.name) / key
            directory.mkdir()
            p = patch.object(settings, key, directory)
            p.start()
            stack.callback(p.stop)
        # progress/mastery 的库路径是模块级常量,随 settings 一起换到临时目录
        # (learning_store/cumulative 是调用时解析,无需补丁)
        from app.services import mastery as mastery_mod

        for mod in (progress, mastery_mod):
            db = patch.object(mod, "_DB", settings.data_dir / "classroom.db")
            db.start()
            stack.callback(db.stop)

        # 书:三门大纲课,各挂一门 v2 课件(每课 2 个检查点,共 6)
        research = settings.data_dir / "research"
        research.mkdir()
        (research / f"{_TOPIC}.framework.json").write_text(
            json.dumps(_framework(), ensure_ascii=False), encoding="utf-8"
        )
        self.course_ids = [f"bk{i}" for i in range(1, 4)]
        for cid, title in zip(self.course_ids, _COURSE_TITLES, strict=True):
            d = _course(cid, title, [f"{cid}-q1", f"{cid}-q2"])
            (settings.courses_dir / f"{cid}.csl.json").write_text(
                json.dumps(d, ensure_ascii=False), encoding="utf-8"
            )
        self.db_path = settings.data_dir / "classroom.db"

    def _finish_book(self) -> None:
        """三门课全部打卡 + 检查点全过(复用完成判定链;pass 拨到过去,读完=当下)。"""
        for cid in self.course_ids:
            progress.mark_done(cid)
            for qid in (f"{cid}-q1", f"{cid}-q2"):
                _pass_past(cid, qid)

    # ---- 读完判定 ----

    def test_not_ready_when_book_unfinished(self) -> None:
        # 只读完第一门:书没读完 → not_ready,无卷
        progress.mark_done(self.course_ids[0])
        for qid in (f"{self.course_ids[0]}-q1", f"{self.course_ids[0]}-q2"):
            _pass_past(self.course_ids[0], qid)
        paper = cumulative.build_paper(_TOPIC)
        self.assertEqual(paper.status, "not_ready")
        self.assertEqual(paper.items, [])

    def test_not_ready_when_outline_missing(self) -> None:
        with self.assertRaises(ValueError):
            cumulative.build_paper("不存在的书")

    def test_available_when_book_finished(self) -> None:
        self._finish_book()
        paper = cumulative.build_paper(_TOPIC)
        self.assertEqual(paper.status, "available")
        self.assertEqual(paper.total_checkpoints, 6)
        # 卷容量:总检查点 ≥3 → 3~5,这里 6 → 5
        self.assertEqual(len(paper.items), 5)

    # ---- 抽样:薄弱优先 + 跨课覆盖 ----

    def test_weak_checkpoints_picked_first(self) -> None:
        self._finish_book()
        # 第一课 q1 掌握度被打到很低(薄弱梯队),必须进卷
        _mastery_row(self.db_path, self.course_ids[0], f"{self.course_ids[0]}-q1", 0.3, None)
        paper = cumulative.build_paper(_TOPIC)
        self.assertEqual(paper.status, "available")
        picked = {it.page_id for it in paper.items}
        self.assertIn(f"{self.course_ids[0]}-q1", picked)
        weak_item = next(it for it in paper.items if it.page_id == f"{self.course_ids[0]}-q1")
        self.assertTrue(weak_item.due is False)
        self.assertEqual(weak_item.mastery, 0.3)

    def test_due_checkpoints_picked_first(self) -> None:
        self._finish_book()
        # 第二课 q2 复习到期未测(2020 年就该测了)→ 薄弱梯队
        _mastery_row(
            self.db_path, self.course_ids[1], f"{self.course_ids[1]}-q2", 1.0, self.PAST
        )
        paper = cumulative.build_paper(_TOPIC)
        item = next(it for it in paper.items if it.page_id == f"{self.course_ids[1]}-q2")
        self.assertTrue(item.due)

    def test_cross_course_coverage(self) -> None:
        self._finish_book()
        paper = cumulative.build_paper(_TOPIC)
        covered = {it.course_id for it in paper.items}
        self.assertEqual(covered, set(self.course_ids))  # 三门课各至少一题

    def test_untested_outranks_already_retested(self) -> None:
        self._finish_book()
        # epoch 后:第一课 q1 已重测过(高掌握度),第二课 q1 没重测过 → 后者优先进卷
        _pass(self.course_ids[0], f"{self.course_ids[0]}-q1")
        _mastery_row(self.db_path, self.course_ids[0], f"{self.course_ids[0]}-q1", 1.0, None)
        paper = cumulative.build_paper(_TOPIC)
        picked = {it.page_id for it in paper.items}
        self.assertIn(f"{self.course_ids[1]}-q1", picked)
        self.assertNotIn(f"{self.course_ids[0]}-q1", picked)  # 已重测过的让位

    def test_weak_first_when_courses_exceed_paper_size(self) -> None:
        # 六门课(课数 > 卷容量 5)→ 只取每课最优,薄弱课排在前面
        research = settings.data_dir / "research"
        titles = [f"课{i}" for i in range(1, 7)]
        fw = {
            "topic": _TOPIC,
            "domain": "测试域",
            "courses": [
                {"id": f"oc{i}", "title": t, "goal": f"目标{t}", "prereqs": [], "part": "P"}
                for i, t in enumerate(titles, 1)
            ],
        }
        (research / f"{_TOPIC}.framework.json").write_text(
            json.dumps(fw, ensure_ascii=False), encoding="utf-8"
        )
        for i, title in enumerate(titles, 1):
            cid = f"bk{i}"
            (settings.courses_dir / f"{cid}.csl.json").write_text(
                json.dumps(_course(cid, title, [f"{cid}-q1"]), ensure_ascii=False),
                encoding="utf-8",
            )
            progress.mark_done(cid)
            _pass_past(cid, f"{cid}-q1")
        # 前三门课的检查点都打到低掌握度(全书最薄弱,梯队 0);
        # 后三门 ≥0.9(不薄弱,梯队 1),掌握度递减定死课序:bk6 > bk5 > bk4
        for i in (1, 2, 3):
            _mastery_row(self.db_path, f"bk{i}", f"bk{i}-q1", 0.1, None)
        _mastery_row(self.db_path, "bk4", "bk4-q1", 0.95, None)
        _mastery_row(self.db_path, "bk5", "bk5-q1", 0.92, None)
        _mastery_row(self.db_path, "bk6", "bk6-q1", 0.91, None)
        paper = cumulative.build_paper(_TOPIC)
        self.assertEqual(len(paper.items), 5)
        self.assertEqual(
            {it.course_id for it in paper.items}, {"bk1", "bk2", "bk3", "bk5", "bk6"}
        )

    # ---- 完成态(防重复疲劳) ----

    def test_completed_after_all_checkpoints_repassed(self) -> None:
        self._finish_book()
        first = cumulative.build_paper(_TOPIC)
        self.assertEqual(first.status, "available")
        # 读完之后全书每个检查点再各过一次(模拟一轮或多轮综合复测)
        for cid in self.course_ids:
            for qid in (f"{cid}-q1", f"{cid}-q2"):
                _pass(cid, qid)
        paper = cumulative.build_paper(_TOPIC)
        self.assertEqual(paper.status, "completed")
        self.assertTrue(all(it.fresh_pass for it in paper.items))

    def test_partial_retest_still_available(self) -> None:
        self._finish_book()
        # 只重测了卷里一部分 → 还没闭环,继续邀请
        first = cumulative.build_paper(_TOPIC)
        for it in first.items[:2]:
            _pass(it.course_id, it.page_id)
        paper = cumulative.build_paper(_TOPIC)
        self.assertEqual(paper.status, "available")

    # ---- 卷面定位信息(与 /grade 入参形态对齐) ----

    def test_items_carry_positioning_fields(self) -> None:
        self._finish_book()
        paper = cumulative.build_paper(_TOPIC)
        it = paper.items[0]
        self.assertTrue(it.course_id and it.section_id and it.page_id)
        self.assertIn(it.section_no, (1, 2))  # 节序(深链 /read?section=N 用)
        self.assertEqual(it.question, f"问题{it.page_id}")
        self.assertEqual(it.pass_rule, "能应用到新情境")
        self.assertTrue(it.section_heading.startswith(it.course_title))

    # ---- 路由壳:薄、404 语义、OpenAPI 出契约 ----

    def test_route_returns_paper(self) -> None:
        self._finish_book()
        from app.routes.outline import book_cumulative

        paper = book_cumulative(_TOPIC)
        self.assertIsInstance(paper, CumulativePaper)
        self.assertEqual(paper.status, "available")

    def test_route_openapi_contract_registered(self) -> None:
        from app.main import app

        schema = app.openapi()
        self.assertIn("CumulativePaper", schema["components"]["schemas"])
        self.assertIn("CumulativeItem", schema["components"]["schemas"])
        paths = schema["paths"]
        self.assertIn("/api/v1/books/{topic}/cumulative", paths)

    # ---- T3.1 应用型考题纪律进了共享风格 ----

    def test_application_style_rule_in_prompts(self) -> None:
        self.assertIn("情境化", QUIZ_FAIRNESS_RULE)
        self.assertIn("pass_rule", QUIZ_FAIRNESS_RULE)
        from app.agent import prep

        self.assertIn(QUIZ_FAIRNESS_RULE, prep._SHARED_STYLE)


if __name__ == "__main__":
    unittest.main()
