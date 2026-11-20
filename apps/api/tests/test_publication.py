"""发布入口不可绕过,内容变化使审查失效;全部模型替身和临时产物。"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import PropertyMock, patch

from app.core.config import settings
from app.services.evidence import locate_material
from app.services.publication import (
    PublicationBlocked,
    assert_publishable,
    ensure_publication,
    report_path,
    review_course,
)
from app.services.tts_compile import publish_courses


class PublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key in ("courses_dir", "data_dir", "traces_dir"):
            path = Path(tmp.name) / key
            path.mkdir()
            patcher = patch.object(settings, key, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.material, errors = locate_material(
            {
                "sources": [{"id": 1, "url": "https://example.org/a", "title": "原始资料"}],
                "groups": [
                    {
                        "heading": "增量",
                        "points": [
                            {
                                "text": "只追加增量。",
                                "source_id": 1,
                                "quote": "Append changes and preserve history.",
                            }
                        ],
                    }
                ],
            },
            {
                "https://example.org/a": "Append changes and preserve history."
            },
        )
        self.assertEqual(errors, [])
        self.course: dict[str, Any] = {
            "id": "sample",
            "title": "增量更新",
            "version": 2,
            "scenario": "自学",
            "meta": {
                "source_notes": ["fixture.material.json"],
                "sources": self.material["sources"],
                "evidence": self.material["evidence"],
            },
            "sections": [
                {
                    "id": "s1",
                    "heading": "增量",
                    "blocks": [
                        {"type": "p", "text": "只追加增量。", "evidence_ids": ["g1p1"]},
                        {
                            "type": "quiz",
                            "id": "s1-cp",
                            "question": "如何保持历史？",
                            "pass_rule": "只追加",
                        },
                        {"type": "flashcards", "cards": [{"front": "增量？", "back": "只追加"}]},
                    ],
                }
            ],
        }
        self.path = settings.courses_dir / "sample.csl.json"
        self.path.write_text(json.dumps(self.course))

    def approve(self, claims: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.assertTrue(kwargs["course_mode"])
        return {
            "reviewer": "model:test",
            "items": [
                {"id": c["id"], "verdict": "supported", "reason": "证据支持"} for c in claims
            ],
        }

    def test_all_blocks_reviewed_then_publication_is_allowed(self) -> None:
        with patch("app.services.publication.review_claims", side_effect=self.approve) as model:
            report = review_course(self.course, self.material)
        self.assertEqual(report["status"], "model_reviewed")
        claims = model.call_args.args[0]
        self.assertEqual(len(claims), 3)
        self.assertIn("只追加", claims[1]["text"])
        self.assertIn("只追加", claims[2]["text"])
        assert_publishable(self.course)
        dst = settings.data_dir / "published"
        with (
            patch.object(
                type(settings), "web_public_courses", new_callable=PropertyMock, return_value=dst
            ),
            patch("app.core.job_store.incomplete_course_ids", return_value=set()),
        ):
            publish_courses("sample")
        self.assertTrue((dst / self.path.name).exists())

    def test_changed_question_or_source_invalidates_approval(self) -> None:
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            review_course(self.course, self.material)
        mutations: tuple[Callable[[dict[str, Any]], None], ...] = (
            lambda c: c["sections"][0]["blocks"][1].update(pass_rule="删除历史"),
            lambda c: c["meta"]["evidence"][0].update(quote="伪造"),
        )
        for mutate in mutations:
            changed = copy.deepcopy(self.course)
            mutate(changed)
            with self.assertRaises(PublicationBlocked):
                assert_publishable(changed)

    def test_self_declared_approval_without_report_is_rejected(self) -> None:
        self.course["meta"]["publication_review"] = {"status": "model_reviewed"}
        with self.assertRaises(PublicationBlocked):
            assert_publishable(self.course)

    def test_forged_snapshot_blocks_before_model_call(self) -> None:
        self.material["source_snapshots"]["https://example.org/a"]["text"] = "tampered"
        with patch("app.services.publication.review_claims") as model:
            report = review_course(self.course, self.material)
        self.assertEqual(report["status"], "blocked")
        model.assert_not_called()

    def test_partial_uncertain_unreviewed_and_missing_items_are_blocked(self) -> None:
        for verdict in ("partial", "uncertain", "unreviewed", "unsupported"):

            def review(
                claims: list[dict[str, Any]], expected: str = verdict, **kwargs: Any
            ) -> dict[str, Any]:
                output = self.approve(claims, **kwargs)
                output["items"][0]["verdict"] = expected
                return output

            with patch("app.services.publication.review_claims", side_effect=review):
                self.assertEqual(review_course(self.course, self.material)["status"],
                                 "unreviewed" if verdict == "unreviewed" else "blocked")
            with self.assertRaises(PublicationBlocked):
                assert_publishable(self.course)
        with patch("app.services.publication.review_claims", return_value={"items": []}):
            self.assertEqual(review_course(self.course, self.material)["status"], "blocked")

    def test_unreviewed_does_not_trigger_author_guessing_repairs(self) -> None:
        report = {"status": "blocked", "items": [{"verdict": "unreviewed"}], "errors": ["超时"]}
        with (
            patch("app.services.publication.review_course", return_value=report),
            patch("app.agent.prep.run_prep") as author,
        ):
            with self.assertRaises(PublicationBlocked):
                ensure_publication(self.course, self.material)
            author.assert_not_called()

    def test_repairs_are_bounded_to_two_and_preserve_draft(self) -> None:
        report = {"status": "blocked", "items": [{"verdict": "partial"}], "errors": ["缺少条件"]}
        with (
            patch("app.services.publication.review_course", return_value=report) as judge,
            patch(
                "app.agent.prep.run_prep", return_value={"ok": True, "course": self.course}
            ) as author,
        ):
            with self.assertRaises(PublicationBlocked):
                ensure_publication(self.course, self.material)
        self.assertEqual(judge.call_count, 3)
        self.assertEqual(author.call_count, 2)
        self.assertEqual(author.call_args.kwargs["resume_course_id"], "sample")
        self.assertTrue(self.path.exists())

    def test_failed_publish_preserves_previous_published_bytes(self) -> None:
        dst = settings.data_dir / "published"
        dst.mkdir()
        old = dst / self.path.name
        old.write_text("previous published version")
        with (
            patch.object(
                type(settings), "web_public_courses", new_callable=PropertyMock, return_value=dst
            ),
            patch("app.core.job_store.incomplete_course_ids", return_value=set()),
        ):
            with self.assertRaises(PublicationBlocked):
                publish_courses("sample")
        self.assertEqual(old.read_text(), "previous published version")
        self.assertFalse(report_path("sample").exists())

    def test_stopped_task_cannot_replace_published_course(self) -> None:
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            review_course(self.course, self.material)
        dst = settings.data_dir / "published"
        dst.mkdir()
        old = dst / self.path.name
        old.write_text("previous published version")
        with (
            patch.object(type(settings), "web_public_courses", new_callable=PropertyMock,
                         return_value=dst),
            patch("app.core.job_store.incomplete_course_ids", return_value=set()),
            patch("app.core.job_progress.ensure_job_active", side_effect=ValueError("已停止")),
        ):
            with self.assertRaisesRegex(ValueError, "已停止"):
                publish_courses("sample")
        self.assertEqual(old.read_text(), "previous published version")

    def test_stopped_task_cannot_save_final_review(self) -> None:
        with (
            patch("app.services.publication.review_claims", side_effect=self.approve),
            patch("app.core.job_progress.ensure_job_active", side_effect=ValueError("已停止")),
        ):
            with self.assertRaisesRegex(ValueError, "已停止"):
                review_course(self.course, self.material)
        self.assertFalse(report_path("sample").exists())

    def test_linked_factual_block_cannot_be_exempted_as_example(self) -> None:
        def exempt(claims: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            result = self.approve(claims, **kwargs)
            result["items"][0]["verdict"] = "not_applicable"
            return result

        with patch("app.services.publication.review_claims", side_effect=exempt):
            report = review_course(self.course, self.material)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("不适用" in error for error in report["errors"]))

    def test_bulk_publish_does_not_bypass_missing_report(self) -> None:
        dst = settings.data_dir / "published"
        with (
            patch.object(type(settings), "web_public_courses", new_callable=PropertyMock,
                         return_value=dst),
            patch("app.core.job_store.incomplete_course_ids", return_value=set()),
        ):
            publish_courses()
        self.assertFalse((dst / self.path.name).exists())
        self.assertTrue(self.path.exists())

    def test_new_draft_is_hidden_from_catalog_and_outline_before_first_review(self) -> None:
        from app.routes.outline import _existing_courses_index
        from app.services.catalog import _load_courses

        self.course["meta"]["publication_required"] = True
        self.path.write_text(json.dumps(self.course))
        with (
            patch("app.core.job_store.incomplete_course_ids", return_value=set()),
            patch("app.routes.outline.incomplete_course_ids", return_value=set()),
            patch("app.services.catalog._vault_map", return_value={}),
        ):
            self.assertEqual(_load_courses()[0], [])
            self.assertEqual(_existing_courses_index()[2], set())

    def test_legacy_unreviewed_courses_remain_distinct_from_new_drafts(self) -> None:
        from app.services.publication import is_review_draft

        self.assertFalse(is_review_draft(self.course))
        self.course["meta"]["publication_required"] = True
        self.assertTrue(is_review_draft(self.course))
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            review_course(self.course, self.material)
        self.assertFalse(is_review_draft(self.course))

    def test_final_judge_does_not_inherit_material_review_opinions(self) -> None:
        self.material["evidence"][0].update(support="supported", reviewer="author-model",
                                           reason="作者认为一切都正确")
        with patch("app.services.publication.review_claims", side_effect=self.approve) as model:
            review_course(self.course, self.material)
        evidence = model.call_args.args[0][0]["section"]["evidence"][0]
        self.assertNotIn("support", evidence)
        self.assertNotIn("reason", evidence)
        self.assertNotIn("point", evidence)

    def test_changed_source_url_is_rejected_before_judging(self) -> None:
        self.course["meta"]["sources"] = copy.deepcopy(self.course["meta"]["sources"])
        self.course["meta"]["sources"][0]["url"] = "https://invented.example/claim"
        with patch("app.services.publication.review_claims") as model:
            report = review_course(self.course, self.material)
        self.assertEqual(report["status"], "blocked")
        model.assert_not_called()
