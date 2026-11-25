"""本地人工证据审查 API 数据工作流的隔离回归。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from app.core.config import settings
from app.services import human_evidence_review
from app.services.evidence import text_hash
from app.services.human_evidence_review import CourseNotReviewable, ReviewConflict
from scripts.audit_evidence import audit, exit_code


class HumanEvidenceReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.courses = root / "courses"
        self.data = root / "data"
        self.courses.mkdir()
        self.data.mkdir()
        for name, value in (("courses_dir", self.courses), ("data_dir", self.data)):
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.course: dict[str, Any] = {
            "id": "review-fixture",
            "title": "证据审查样例",
            "version": 2,
            "scenario": "自学",
            "meta": {
                "source_notes": ["review-fixture.md"],
                "sources": [{"id": 3, "title": "官方文档", "url": "https://example.org/doc"}],
                "evidence": [{
                    "id": "g1p1",
                    "point": "系统支持增量更新。",
                    "source_id": 3,
                    "quote": "Only incremental changes are appended.",
                    "context": "Context. Only incremental changes are appended. More context.",
                    "source_hash": text_hash("source body"),
                    "quote_start": 9,
                    "quote_end": 9 + len("Only incremental changes are appended."),
                    "quote_status": "matched",
                }],
            },
            "sections": [{
                "id": "s1",
                "heading": "增量更新",
                "blocks": [{
                    "type": "p",
                    "text": "Only incremental changes are appended.",
                    "evidence_ids": ["g1p1"],
                }],
            }],
        }
        self._write_course()

    def _write_course(self) -> None:
        (self.courses / f"{self.course['id']}.csl.json").write_text(
            json.dumps(self.course), encoding="utf-8",
        )

    def test_lists_only_published_evidence_backed_courses(self) -> None:
        rows = human_evidence_review.list_courses()["courses"]
        self.assertEqual([row["course_id"] for row in rows], ["review-fixture"])
        self.assertEqual(rows[0]["total_blocks"], 1)
        (self.courses / "empty.csl.json").write_text(json.dumps({
            "id": "empty", "title": "无证据", "version": 2, "scenario": "自学",
            "meta": {"source_notes": ["empty.md"]},
            "sections": [{"id": "s1", "heading": "空", "blocks": [
                {"type": "p", "text": "无来源内容。", "exemplary": True},
            ]}],
        }), encoding="utf-8")
        rows = human_evidence_review.list_courses()["courses"]
        self.assertEqual([row["course_id"] for row in rows], ["review-fixture"])

    def test_review_is_saved_separately_and_consumed_by_existing_audit_format(self) -> None:
        page = human_evidence_review.get_course("review-fixture")
        item = page["blocks"][0]
        saved = human_evidence_review.save_review(
            "review-fixture", block_id=item["id"], input_hash=item["input_hash"],
            reviewer="学员", verdict="supported", reason="原文明确写了增量追加。",
        )
        self.assertEqual((saved["reviewed_blocks"], saved["total_blocks"]), (1, 1))
        record_path = self.data / "human-evidence-reviews" / "review-fixture.json"
        records = json.loads(record_path.read_text(encoding="utf-8"))
        report = audit(self.course, human_reviews=records)
        self.assertEqual(report["semantic_status"], "human_reviewed")
        self.assertEqual(exit_code(report), 0)
        published_course = json.loads(
            (self.courses / "review-fixture.csl.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("reviewer", published_course)

    def test_changed_content_invalidates_old_review_and_rejects_stale_save(self) -> None:
        item = human_evidence_review.get_course("review-fixture")["blocks"][0]
        self.course["sections"][0]["blocks"][0]["text"] = "Changed content."
        self._write_course()
        current = human_evidence_review.get_course("review-fixture")["blocks"][0]
        human_evidence_review.save_review(
            "review-fixture", block_id=item["id"], input_hash=current["input_hash"],
            reviewer="学员", verdict="uncertain", reason="准备验证冲突标签。",
        )
        self.course["sections"][0]["blocks"][0]["text"] = "Changed again."
        self._write_course()
        stale = human_evidence_review.get_course("review-fixture")["blocks"][0]
        self.assertTrue(stale["stale"])
        with self.assertRaises(ReviewConflict):
            human_evidence_review.save_review(
                "review-fixture", block_id=item["id"], input_hash=current["input_hash"],
                reviewer="学员", verdict="supported", reason="用旧页面提交。",
            )

    def test_uncertain_is_recorded_as_reviewed_but_not_a_pass(self) -> None:
        item = human_evidence_review.get_course("review-fixture")["blocks"][0]
        human_evidence_review.save_review(
            "review-fixture", block_id=item["id"], input_hash=item["input_hash"],
            reviewer="学员", verdict="uncertain", reason="摘录没有说明适用条件。",
        )
        records = json.loads(
            (self.data / "human-evidence-reviews" / "review-fixture.json").read_text()
        )
        report = audit(self.course, human_reviews=records)
        self.assertEqual(report["semantic_status"], "human_reviewed")
        self.assertEqual(exit_code(report), 2)

    def test_translation_uses_model_on_demand_without_changing_course_or_review_store(self) -> None:
        block = human_evidence_review.get_course("review-fixture")["blocks"][0]
        response = SimpleNamespace(
            content=[SimpleNamespace(
                type="text",
                text='{"quote":"只追加增量变更。","context":"上下文。只追加增量变更。更多上下文。"}',
            )],
            stop_reason="end_turn",
        )
        client = Mock()
        client.with_options.return_value = client
        client.messages.create.return_value = response
        course_path = self.courses / "review-fixture.csl.json"
        before_course = course_path.read_bytes()

        with patch.object(human_evidence_review, "get_llm_client", return_value=client):
            result = human_evidence_review.translate_evidence(
                "review-fixture", block_id=block["id"], evidence_id="g1p1",
                input_hash=block["input_hash"],
            )

        self.assertEqual(result["quote_translation"], "只追加增量变更。")
        self.assertEqual(result["context_translation"], "上下文。只追加增量变更。更多上下文。")
        client.messages.create.assert_called_once()
        self.assertEqual(course_path.read_bytes(), before_course)
        self.assertFalse((self.data / "human-evidence-reviews" / "review-fixture.json").exists())

    def test_translation_rejects_stale_content_without_calling_model(self) -> None:
        block = human_evidence_review.get_course("review-fixture")["blocks"][0]
        client = Mock()
        with patch.object(human_evidence_review, "get_llm_client", return_value=client):
            with self.assertRaises(ReviewConflict):
                human_evidence_review.translate_evidence(
                    "review-fixture", block_id=block["id"], evidence_id="g1p1",
                    input_hash="0" * 64,
                )
        client.messages.create.assert_not_called()

    def test_rejects_path_traversal_and_unknown_block_ids(self) -> None:
        with self.assertRaises(CourseNotReviewable):
            human_evidence_review.get_course("../secret")
        item = human_evidence_review.get_course("review-fixture")["blocks"][0]
        with self.assertRaises(CourseNotReviewable):
            human_evidence_review.save_review(
                "review-fixture", block_id="missing:1", input_hash=item["input_hash"],
                reviewer="学员", verdict="supported", reason="不存在的内容。",
            )
        self.assertFalse((self.data.parent / "secret.json").exists())


if __name__ == "__main__":
    unittest.main()
