"""可信依据来自实际产物、版本和确定性核验，不产生分数或虚构人工签字。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import catalog_store
from app.core.config import settings
from app.core.job_store import bind_material
from app.core.trace import digest
from app.main import app
from app.services.evidence import locate_material, material_evidence
from app.services.job_trust import build_job_trust
from app.services.publication import content_hash, report_path


class JobTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in ("data_dir", "courses_dir"):
            directory = Path(tmp.name) / name
            directory.mkdir()
            p = patch.object(settings, name, directory)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(catalog_store, "_DB", settings.data_dir / "classroom.db")
        p.start()
        self.addCleanup(p.stop)
        self.research = settings.data_dir / "research"
        self.research.mkdir()
        self.material, errors = locate_material({
            "sources": [{"id": 1, "title": "原文", "url": "https://example.org/a"}],
            "groups": [{"points": [{"text": "保留历史", "source_id": 1,
                                      "quote": "Append changes and preserve history."}]}],
        }, {"https://example.org/a": "Append changes and preserve history."})
        self.assertFalse(errors)

    def bind(self) -> dict[str, Any]:
        return bind_material("outline_prep", "主题::课程", self.material)

    def checks(self, **kwargs: Any) -> dict[str, Any]:
        report = build_job_trust("outline_prep", "主题::课程")
        return {c.id: c for c in report.checks}

    def test_no_records_are_unknown_and_no_score_or_identity_claim(self) -> None:
        result = build_job_trust("request_research", "新主题").model_dump()
        self.assertEqual(result["human_review"], "not_recorded")
        self.assertEqual(result["publication_status"], "unknown")
        self.assertTrue(all(c["status"] == "unknown" for c in result["checks"]))
        self.assertNotIn("score", result)

    def test_outline_mapping_is_not_claimed_as_coverage_or_authority(self) -> None:
        fw = {"topic": "主题", "courses": [{"id": "c1", "title": "课程", "goal": "做一个测试",
              "scope": "入门", "source_ids": [1], "prereqs": []}], "source_evidence": [
              {"id": 1, "title": "资料", "url": "https://example.org/a", "fetched_at": "today",
               "snapshot_sha256": "recorded-only", "excerpt": "正文摘录"}]}
        (self.research / "主题.framework.json").write_text(json.dumps(fw))
        r = build_job_trust("outline_prep", "主题::课程")
        self.assertEqual(r.outline_hash, digest(fw))
        self.assertEqual(r.sources[0].identity_status, "unverified")
        self.assertEqual(r.mappings[0].source_ids, [1])
        self.assertIn("不能据此判断领域完整性", self.checks()["outline_source_mapping"].detail)
        fw["courses"][0]["prereqs"] = ["c1"]
        (self.research / "主题.framework.json").write_text(json.dumps(fw))
        self.assertEqual(self.checks()["outline_structure"].status, "failed")

    def test_material_quotes_rechecked_and_hash_bound(self) -> None:
        self.bind()
        self.assertEqual(self.checks()["material_quotes"].status, "passed")
        with catalog_store._conn() as conn:
            conn.execute("UPDATE job_bindings SET material_hash='fake'")
        result = build_job_trust("outline_prep", "主题::课程")
        self.assertEqual(self.checks()["material_binding"].status, "failed")
        self.assertEqual(result.sources, [])

    def test_changed_snapshot_cannot_claim_quote_passed(self) -> None:
        self.material["source_snapshots"]["https://example.org/a"]["text"] += "changed"
        self.bind()
        self.assertEqual(self.checks()["material_quotes"].status, "failed")

    def test_model_review_is_separate_and_wrong_version_is_stale(self) -> None:
        evidence = material_evidence(self.material)
        claims = [{"id": e["id"], "text": e["point"], "quote": e["quote"],
                   "context": e["context"]} for e in evidence]
        self.material["evidence_review"] = {
            "reviewer": "model:judge", "input_hash": digest(claims),
            "items": [{"id": "g1p1", "verdict": "supported", "reason": "自动审查意见"}],
        }
        self.bind()
        r = build_job_trust("outline_prep", "主题::课程")
        self.assertEqual(r.reviews[0].status, "completed")
        self.assertEqual(r.reviews[0].reviewer, "model:judge")
        self.assertTrue(all(c.provider == "program" for c in r.checks))
        with catalog_store._conn() as conn:
            conn.execute("DELETE FROM job_bindings")
        self.material["evidence_review"]["input_hash"] = "stale"
        self.bind()
        self.assertEqual(build_job_trust("outline_prep", "主题::课程").reviews[0].status, "stale")

    def test_changed_final_course_invalidates_saved_report(self) -> None:
        binding = self.bind()
        course = {"id": binding["course_id"], "meta": {}, "sections": []}
        saved = {"content_hash": content_hash(course), "status": "model_reviewed",
                 "model_review": {"reviewer": "model:judge", "items": []}}
        p = report_path(course["id"])
        p.parent.mkdir()
        p.write_text(json.dumps(saved))
        course["title"] = "changed"
        (settings.courses_dir / f"{course['id']}.csl.json").write_text(json.dumps(course))
        r = build_job_trust("outline_prep", "主题::课程")
        self.assertEqual(r.publication_status, "blocked")
        self.assertEqual(r.reviews[0].status, "stale")
        self.assertEqual(self.checks()["publication_version"].status, "failed")

    def test_route_schema_and_validation_and_prebinding_material(self) -> None:
        (self.research / "主题.课程.material.json").write_text(json.dumps(self.material))
        with TestClient(app) as client:
            response = client.get("/api/v1/jobs/trust", params={
                "kind": "outline_prep", "target": "主题::课程"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["checks"][-1]["status"], "passed")
            self.assertEqual(client.get("/api/v1/jobs/trust", params={
                "kind": "bad", "target": "x"}).status_code, 422)
        self.assertIn("JobTrustReport", app.openapi()["components"]["schemas"])
