"""使用临时课件验证章节索引与 SSE 路由,不调用模型或真实学习数据。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.routes import chat as chat_routes
from app.services.citation_guard import course_index_of, verify_citations


class CitationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.courses_dir = Path(tmp.name)
        patcher = patch.object(settings, "courses_dir", self.courses_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.course = {
            "title": "八节临时课件",
            "version": 2,
            "sections": [
                {
                    "id": f"s{i}",
                    "heading": f"标题{i}",
                    "blocks": [{"type": "p", "text": f"正文第{i}节 [第99节]"}],
                }
                for i in range(1, 9)
            ],
        }
        self.path = self.courses_dir / "test-course.csl.json"
        self.path.write_text(json.dumps(self.course), encoding="utf-8")

    def test_complete_index_includes_sections_outside_model_window(self) -> None:
        index = course_index_of("test-course")
        self.assertEqual(verify_citations("请看课件第5节和课件第8节", index), [])

    def test_invalid_sections_use_full_course_count(self) -> None:
        index = course_index_of("test-course")
        for answer in ("课件第0节", "课件第9节", "课件第99节"):
            with self.subTest(answer=answer):
                violations = verify_citations(answer, index)
                self.assertEqual(len(violations), 1)
                self.assertIn("本课共 8 个节", violations[0])
        self.assertTrue(verify_citations("课件第1页", index))

    def test_legacy_page_index_is_supported(self) -> None:
        self.path.write_text(json.dumps({"pages": [{}, {}]}), encoding="utf-8")
        index = course_index_of("test-course")
        self.assertEqual(verify_citations("课件第2页", index), [])
        self.assertTrue(verify_citations("课件第3页", index))
        self.assertTrue(verify_citations("课件第1节", index))

    def test_web_reference_validation_is_preserved(self) -> None:
        self.assertEqual(verify_citations("结论[1] https://example.com", ""), [])
        self.assertTrue(verify_citations("结论[2] https://example.com", ""))

    def test_chat_uses_complete_index_and_keeps_model_window(self) -> None:
        app = FastAPI()
        app.include_router(chat_routes.router)
        with (
            patch.object(chat_routes, "student_course_map", return_value=""),
            patch.object(chat_routes, "mastered_concepts", return_value=[]),
            patch.object(chat_routes, "ensure_session", return_value="test-session"),
            patch.object(chat_routes, "session_state_note", return_value=None),
            patch.object(chat_routes, "evaluate_answer", return_value=None),
            patch.object(chat_routes, "trace_tutor") as trace,
            TestClient(app) as client,
        ):
            for answer, corrected in (("请到课件第5节阅读", False), ("课件第9节", True)):
                with self.subTest(answer=answer):
                    events = iter([
                        {"type": "delta", "text": answer},
                        {"type": "final", "answer": answer, "tool_calls": []},
                    ])
                    with patch.object(chat_routes, "run_tutor", return_value=events) as run:
                        response = client.post("/api/v1/chat", json={
                            "course_id": "test-course", "current_page": "s2", "question": "问题"
                        })
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("event: done", response.text)
                    self.assertEqual("更正" in response.text, corrected)
                    model_material = run.call_args.args[1]
                    self.assertIn("正文第2节", model_material)
                    self.assertNotIn("正文第5节", model_material)
                    self.assertEqual(bool(trace.call_args.kwargs["guard_violations"]), corrected)

    def test_missing_course_returns_404_before_session_creation(self) -> None:
        app = FastAPI()
        app.include_router(chat_routes.router)
        with patch.object(chat_routes, "ensure_session") as ensure, TestClient(app) as client:
            response = client.post(
                "/api/v1/chat", json={"course_id": "missing", "question": "问题"}
            )
        self.assertEqual(response.status_code, 404)
        ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
