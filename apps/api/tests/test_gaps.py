"""T2 错因结构化回归:gaps 从批改产出 → 落库 → 复习卡/答疑两个消费方,全离线。

替身边界(沿 test_eval_foundations 惯例):临时目录 SQLite/课件/traces,
模型入口一律 MagicMock,漏出替身的真实调用立即失败。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agent import tutor
from app.core import learning_store
from app.core.config import settings
from app.core.prompts import GRADE_OUTPUT_SPEC
from app.services import grader, mastery

_COURSE = {
    "id": "course",
    "title": "临时课程",
    "scenario": "自学",
    "version": 2,
    "meta": {},
    "sections": [
        {
            "id": "s1",
            "heading": "第一节",
            "blocks": [
                {"type": "p", "text": "正文"},
                {"type": "quiz", "id": "q1", "question": "更新什么", "pass_rule": "只追加变化"},
            ],
        },
        {
            "id": "s2",
            "heading": "第二节",
            "blocks": [
                {"type": "flashcards", "cards": [{"front": "问", "back": "答"}]},
            ],
        },
    ],
}


def _grade_response(payload: dict[str, Any]) -> SimpleNamespace:
    text = json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=80, output_tokens=20),
        stop_reason="end_turn",
    )


class GapTests(unittest.TestCase):
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
        db = patch.object(mastery, "_DB", settings.data_dir / "classroom.db")
        db.start()
        stack.callback(db.stop)
        for module in (tutor, grader):
            guard = patch.object(module, "get_llm_client",
                                 side_effect=AssertionError("禁止未模拟的模型调用"))
            guard.start()
            stack.callback(guard.stop)
        (settings.courses_dir / "course.csl.json").write_text(json.dumps(_COURSE))

    # ---- T2.1 gaps 解析(含旧格式兼容) ----

    def test_spec_contains_gaps_discipline(self) -> None:
        self.assertIn('"gaps"', GRADE_OUTPUT_SPEC)
        self.assertIn("空数组", GRADE_OUTPUT_SPEC)

    def test_grader_parses_gaps(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _grade_response({
            "score": 55,
            "comment": "✓ 对了方向\n✗ 缺了变化只追加\n→ 下一步重读该节",
            "gaps": ["没说清「只追加变化」", "  ", "把覆盖当成了默认策略"],
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            result = grader.grade_recitation("course", "q1", "复述内容", source="test")
        self.assertEqual(
            result["gaps"], ["没说清「只追加变化」", "把覆盖当成了默认策略"],
        )
        self.assertEqual(result["verdict"], "fail")

    def test_grader_old_format_without_gaps_is_compatible(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _grade_response({
            "score": 90, "comment": "✓ 全对\n✗ 无\n→ 下一步保持", "precise": "标准",
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            result = grader.grade_recitation("course", "q1", "复述内容", source="test")
        self.assertEqual(result["gaps"], [])

    def test_grader_gaps_malformed_and_cap(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _grade_response({
            "score": 40, "comment": "x", "gaps": "不是数组",
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            self.assertEqual(
                grader.grade_recitation("course", "q1", "答", source="test")["gaps"], [],
            )
        client.messages.create.return_value = _grade_response({
            "score": 40, "comment": "x",
            "gaps": [f"缺{i}" for i in range(6)],
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            self.assertEqual(len(
                grader.grade_recitation("course", "q1", "答", source="test")["gaps"],
            ), 4)

    # ---- T2.2 批改落库带 gaps / source=test 不落 ----

    def test_gaps_persist_and_empty_stored_as_null(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _grade_response({
            "score": 55, "comment": "✗ 缺甲", "gaps": ["缺甲"],
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            grader.grade_recitation("course", "q1", "复述")
        with learning_store._conn() as c:
            row = c.execute(
                "SELECT gaps, result FROM learning_grades WHERE course_id='course'"
            ).fetchone()
        self.assertEqual(json.loads(row["gaps"]), ["缺甲"])
        self.assertEqual(json.loads(row["result"])["gaps"], ["缺甲"])  # result JSON 同步携带
        # 空错因(pass 全对)存 NULL,与历史行同语义
        client.messages.create.return_value = _grade_response({
            "score": 95, "comment": "✓ 全对", "gaps": [],
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            grader.grade_recitation("course", "q1", "更好的复述")
        with learning_store._conn() as c:
            gaps = [r["gaps"] for r in c.execute(
                "SELECT gaps FROM learning_grades ORDER BY rowid").fetchall()]
        self.assertEqual(gaps, ['["缺甲"]', None])

    def test_source_test_writes_nothing(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _grade_response({
            "score": 20, "comment": "✗ 说反", "gaps": ["把覆盖当追加"],
        })
        with patch.object(grader, "get_llm_client", return_value=client):
            grader.grade_recitation("course", "q1", "复述", source="test")
        with learning_store._conn() as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM learning_grades").fetchone()[0], 0,
            )

    # ---- 增量迁移:旧库(无 gaps 列)打开即补列,历史行无损 ----

    def test_migration_alters_legacy_db(self) -> None:
        db = settings.data_dir / "classroom.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db) as c:
            c.execute(
                "CREATE TABLE learning_grades (id TEXT PRIMARY KEY, course_id TEXT,"
                " page_id TEXT, verdict TEXT, ts TEXT, result TEXT)"
            )
            c.execute(
                "INSERT INTO learning_grades VALUES('old','course','q1','pass','t','{}')"
            )
        learning_store._conn().close()
        with sqlite3.connect(db) as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(learning_grades)").fetchall()}
            n = c.execute("SELECT COUNT(*) FROM learning_grades").fetchone()[0]
            gaps = c.execute("SELECT gaps FROM learning_grades").fetchone()[0]
        self.assertIn("gaps", cols)
        self.assertEqual((n, gaps), (1, None))
        # 再开一次不重复迁移(幂等)
        learning_store._conn().close()
        with sqlite3.connect(db) as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM learning_grades").fetchone()[0], 1,
            )

    # ---- T2.3.1 due_reviews 带最近 gaps(最新非空;闪卡不带) ----

    def _mastery_due(self, page_id: str) -> None:
        with mastery._conn() as c:
            c.execute(
                "INSERT INTO checkpoint_mastery"
                " (course_id,page_id,history,mastery,stage,next_review_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?)",
                ("course", page_id, "[]", 0.5, 0, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )

    def test_due_reviews_carries_latest_nonempty_gaps(self) -> None:
        self._mastery_due("q1")
        # 先错(带错因)后过(空错因) → 仍取错的那些(最新非空语义)
        learning_store.record_result(
            "course", "q1", "差", {"verdict": "fail", "gaps": ["漏了变化只追加"]},
        )
        learning_store.record_result(
            "course", "q1", "好", {"verdict": "pass", "gaps": []},
        )
        items = {i.page_id: i for i in mastery.due_reviews().items}
        self.assertEqual(items["q1"].gaps, ["漏了变化只追加"])

    def test_due_reviews_latest_gaps_overwrite_and_flashcard_bare(self) -> None:
        self._mastery_due("q1")
        self._mastery_due("s2-fc0")  # 闪卡卡:同表不同键,从无批改记录
        learning_store.record_result("course", "q1", "一", {"verdict": "fail", "gaps": ["旧缺口"]})
        learning_store.record_result("course", "q1", "二", {"verdict": "fail", "gaps": ["新缺口"]})
        items = {i.page_id: i for i in mastery.due_reviews().items}
        self.assertEqual(items["q1"].gaps, ["新缺口"])  # 覆盖语义:每次批改存当次的
        self.assertEqual(items["s2-fc0"].gaps, [])  # 闪卡类无 gaps 不带

    def test_latest_gaps_tolerates_null_and_bad_json(self) -> None:
        learning_store.record_result("course", "q1", "答", {"verdict": "pass", "gaps": []})
        with learning_store._conn() as c:
            c.execute(
                "INSERT INTO learning_grades (id,course_id,page_id,verdict,ts,result,gaps)"
                " VALUES('bad','course','q1','fail','2026-01-02T00:00:00','{}','not-json')",
            )
        self.assertEqual(learning_store.latest_gaps("course", "q1"), [])
        self.assertEqual(learning_store.latest_gaps("course", "缺行"), [])

    # ---- T2.3.2 tutor 上下文注入 gaps(空 gaps 不注入) ----

    def _run_tutor(self, checkpoint: dict[str, Any] | None) -> str:
        stream = MagicMock()
        stream.__iter__.return_value = iter([
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="离线回答"),
            )
        ])
        stream.get_final_message.return_value = SimpleNamespace(
            stop_reason="end_turn", usage=SimpleNamespace()
        )
        client = MagicMock()
        client.messages.stream.return_value.__enter__.return_value = stream
        with (
            patch.object(tutor, "get_llm_client", return_value=client),
            patch.object(tutor, "build_system", return_value=[]),
            patch.object(tutor, "load_messages", return_value=[]),
            patch.object(tutor, "append_turn"),
        ):
            list(tutor.run_tutor(
                "帮我搞懂薄弱点", "模型底料", "s1",
                session_id="test-session", course_id="course", checkpoint=checkpoint,
            ))
        return str(client.messages.stream.call_args.kwargs["messages"][-1]["content"])

    def test_tutor_injects_gaps_guidance(self) -> None:
        current = self._run_tutor({
            "question": "检查点问题", "pass_rule": "标准", "answer": "复述",
            "verdict": "fail", "gaps": ["漏了变化只追加", "把覆盖当追加"],
        })
        self.assertIn("引导式解答", current)
        self.assertIn("学员上次复述的缺失点:漏了变化只追加；把覆盖当追加", current)
        self.assertIn("请针对性引导补齐这些缺口", current)

    def test_tutor_empty_or_missing_gaps_not_injected(self) -> None:
        for checkpoint in (
            {"question": "问", "pass_rule": "标准", "answer": "答", "verdict": "fail"},
            {"question": "问", "answer": "答", "gaps": []},
            {"question": "问", "answer": "答", "gaps": "坏值"},
        ):
            with self.subTest(gaps=checkpoint.get("gaps", "缺省")):
                current = self._run_tutor(checkpoint)
                self.assertIn("引导式解答", current)
                self.assertNotIn("学员上次复述的缺失点", current)


if __name__ == "__main__":
    unittest.main()
