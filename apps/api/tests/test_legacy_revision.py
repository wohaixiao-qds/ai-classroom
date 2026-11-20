from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from app.core.config import settings
from app.core.trace import digest
from app.services.evidence import locate_material
from app.services.legacy_revision import (
    RevisionBlocked,
    audit_legacy_courses,
    create_revision,
    promote_revision,
    review_revision,
)


class LegacyRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.courses = self.root / "courses"
        self.data = self.root / "data"
        self.web = self.root / "web"
        for path in (self.courses, self.data, self.web):
            path.mkdir()
        self.patches = [
            patch.object(settings, "courses_dir", self.courses),
            patch.object(settings, "data_dir", self.data),
            patch.object(type(settings), "web_public_courses", new_callable=PropertyMock,
                         return_value=self.web),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        material, errors = locate_material(
            {
                "sources": [{"id": 1, "title": "原始资料", "url": "https://example.test/source"}],
                "groups": [{"heading": "事实", "points": [{
                    "text": "只追加历史。", "source_id": 1,
                    "quote": "Append changes and preserve history.",
                }]}],
            },
            {"https://example.test/source": "Append changes and preserve history."},
        )
        self.assertEqual(errors, [])
        self.material = material
        self.course = {
            "id": "legacy",
            "title": "历史课",
            "scenario": "自学",
            "version": 2,
            "meta": {
            "sources": material["sources"],
                "evidence": material["evidence"],
                "source_notes": ["material.json"],
            },
            "sections": [{"id": "s1", "heading": "事实", "blocks": [
                {"type": "p", "text": "只追加历史。", "evidence_ids": ["g1p1"]},
                {"type": "quiz", "id": "s1-cp", "question": "怎么做？", "pass_rule": "说出只追加"},
            ]}],
        }
        self.course_path = self.courses / "legacy.csl.json"
        self.course_path.write_text(json.dumps(self.course), encoding="utf-8")
        self.material_path = self.data / "material.json"
        self.material_path.write_text(json.dumps(material), encoding="utf-8")

    def approve(self, claims: list[dict], **kwargs: object) -> dict:
        return {"reviewer": "model:test", "items": [
            {"id": claim["id"], "verdict": "supported", "reason": "有原文依据"}
            for claim in claims
        ]}

    def test_review_isolated_and_promotion_keeps_id(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path, revision_id="pilot")
        old = self.course_path.read_bytes()
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            report = review_revision(paths)
        self.assertEqual(report["status"], "model_reviewed")
        self.assertEqual(self.course_path.read_bytes(), old)
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            manifest = promote_revision(paths)
        self.assertEqual(manifest["status"], "promoted")
        self.assertEqual(json.loads(self.course_path.read_text())["id"], "legacy")
        self.assertEqual(json.loads((self.web / self.course_path.name).read_text())["id"], "legacy")
        self.assertEqual(manifest["checkpoint_mapping"], {"s1-cp": "s1-cp"})

    def test_unreviewed_candidate_cannot_promote(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        with self.assertRaises(RevisionBlocked):
            promote_revision(paths)

    def test_concurrent_source_change_blocks_promotion(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            review_revision(paths)
        self.course["title"] = "被别人改过"
        self.course_path.write_text(json.dumps(self.course), encoding="utf-8")
        with self.assertRaisesRegex(RevisionBlocked, "正式源课件已变化"):
            promote_revision(paths)

    def test_checkpoint_removal_requires_explicit_mapping_or_redo(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        candidate = json.loads(paths.candidate.read_text())
        candidate["sections"][0]["blocks"].pop()
        paths.candidate.write_text(json.dumps(candidate), encoding="utf-8")
        # The review report is intentionally mocked: this test covers the promotion guard.
        paths.manifest.write_text(json.dumps({
            **json.loads(paths.manifest.read_text()),
            "status": "reviewed", "review_status": "model_reviewed",
            "candidate_hash": digest(paths.candidate.read_bytes().decode("utf-8")),
            "report_hash": digest({}),
        }), encoding="utf-8")
        paths.report.write_text(json.dumps({}), encoding="utf-8")
        with patch("app.services.legacy_revision.assert_publishable"):
            with self.assertRaisesRegex(RevisionBlocked, "逐个提供映射或显式标记重做"):
                promote_revision(paths)
            manifest = promote_revision(paths, relearning_required=["s1-cp"])
        self.assertEqual(manifest["relearning_required"], ["s1-cp"])
        self.assertEqual(manifest["checkpoint_mapping"], {})

    def test_candidate_or_publication_change_after_review_blocks_promotion(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        with patch("app.services.publication.review_claims", side_effect=self.approve):
            review_revision(paths)
        candidate = json.loads(paths.candidate.read_text())
        candidate["title"] = "绕过审查的修改"
        paths.candidate.write_text(json.dumps(candidate), encoding="utf-8")
        with self.assertRaisesRegex(RevisionBlocked, "候选在审查后发生变化"):
            promote_revision(paths)

    def test_relearn_marker_must_name_a_removed_checkpoint(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        candidate = json.loads(paths.candidate.read_text())
        candidate["sections"][0]["blocks"].pop()
        paths.candidate.write_text(json.dumps(candidate), encoding="utf-8")
        paths.manifest.write_text(json.dumps({
            **json.loads(paths.manifest.read_text()),
            "status": "reviewed", "review_status": "model_reviewed",
            "candidate_hash": __import__("app.core.trace", fromlist=["digest"]).digest(
                paths.candidate.read_bytes().decode("utf-8")
            ),
            "report_hash": digest({}),
        }), encoding="utf-8")
        paths.report.write_text(json.dumps({}), encoding="utf-8")
        with patch("app.services.legacy_revision.assert_publishable"):
            with self.assertRaisesRegex(RevisionBlocked, "未知旧检查点"):
                promote_revision(paths, relearning_required=["not-a-checkpoint"])

    def test_changed_checkpoint_meaning_requires_explicit_mapping_or_relearning(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        candidate = json.loads(paths.candidate.read_text())
        candidate["sections"][0]["blocks"][1]["question"] = "改成考察不同概念？"
        paths.candidate.write_text(json.dumps(candidate), encoding="utf-8")
        paths.manifest.write_text(json.dumps({
            **json.loads(paths.manifest.read_text()),
            "status": "reviewed", "review_status": "model_reviewed",
            "candidate_hash": digest(paths.candidate.read_bytes().decode("utf-8")),
            "report_hash": digest({}),
        }), encoding="utf-8")
        paths.report.write_text(json.dumps({}), encoding="utf-8")
        with patch("app.services.legacy_revision.assert_publishable"):
            with self.assertRaisesRegex(RevisionBlocked, "逐个提供映射或显式标记重做"):
                promote_revision(paths)
            manifest = promote_revision(
                paths,
                checkpoint_mapping={"s1-cp": "s1-cp"},
            )
        self.assertEqual(manifest["checkpoint_mapping"], {"s1-cp": "s1-cp"})

    def test_revision_ids_cannot_escape_revision_directory(self) -> None:
        with self.assertRaisesRegex(RevisionBlocked, "课程 id 无效"):
            create_revision("../legacy")
        with self.assertRaisesRegex(RevisionBlocked, "复审 id 无效"):
            create_revision("legacy", revision_id="../../outside")

    def test_promote_mapping_migrates_learning_records(self) -> None:
        paths = create_revision("legacy", material_path=self.material_path)
        candidate = json.loads(paths.candidate.read_text())
        candidate["sections"][0]["blocks"][1]["id"] = "s1-cp-new"
        paths.candidate.write_text(json.dumps(candidate), encoding="utf-8")
        paths.report.write_text(json.dumps({}), encoding="utf-8")
        paths.manifest.write_text(json.dumps({
            **json.loads(paths.manifest.read_text()),
            "status": "reviewed", "review_status": "model_reviewed",
            "candidate_hash": digest(paths.candidate.read_bytes().decode("utf-8")),
            "report_hash": digest({}),
        }), encoding="utf-8")
        database = self.data / "classroom.db"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                "CREATE TABLE learning_grades (id TEXT PRIMARY KEY, course_id TEXT, "
                "page_id TEXT, verdict TEXT, ts TEXT, result TEXT);"
                "CREATE TABLE checkpoint_mastery (course_id TEXT, page_id TEXT, "
                "history TEXT, mastery REAL, stage INTEGER, next_review_at TEXT, "
                "updated_at TEXT, PRIMARY KEY(course_id,page_id));"
            )
            connection.execute(
                "INSERT INTO learning_grades VALUES (?,?,?,?,?,?)",
                ("g1", "legacy", "s1-cp", "pass", "today", '{"page_id":"s1-cp"}'),
            )
            connection.execute(
                "INSERT INTO checkpoint_mastery VALUES (?,?,?,?,?,?,?)",
                ("legacy", "s1-cp", "[]", 0.8, 1, "tomorrow", "today"),
            )
        with patch("app.services.legacy_revision.assert_publishable"):
            manifest = promote_revision(paths, checkpoint_mapping={"s1-cp": "s1-cp-new"})
        self.assertEqual(manifest["checkpoint_mapping"], {"s1-cp": "s1-cp-new"})
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute(
                "SELECT page_id FROM learning_grades"
            ).fetchone()[0], "s1-cp-new")
            self.assertEqual(connection.execute(
                "SELECT page_id FROM checkpoint_mastery"
            ).fetchone()[0], "s1-cp-new")

    def test_audit_reports_unreviewed_legacy_course_without_writing(self) -> None:
        before = self.course_path.read_bytes()
        report = audit_legacy_courses()
        row = next(item for item in report["courses"] if item["course_id"] == "legacy")
        self.assertEqual(row["legacy_review_status"], "unreviewed")
        self.assertEqual(row["publication_gate"], "blocked")
        self.assertEqual(row["evidence_items"], 1)
        self.assertEqual(self.course_path.read_bytes(), before)
