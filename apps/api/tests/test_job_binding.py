"""任务绑定回归:临时 SQLite/课件,不启动子进程或外部模型。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import PropertyMock, patch

from fastapi import HTTPException

from app import job_runner
from app.agent import prep
from app.core import catalog_store, job_store
from app.core.config import settings
from app.routes import catalog, outline
from app.schemas.catalog import CatalogAction
from app.services import executor
from app.services.tts_compile import publish_courses


class JobBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in ("courses_dir", "data_dir", "traces_dir"):
            directory = Path(tmp.name) / name
            directory.mkdir()
            field_patch = patch.object(settings, name, directory)
            field_patch.start()
            self.addCleanup(field_patch.stop)
        db_patch = patch.object(catalog_store, "_DB", settings.data_dir / "classroom.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        argv_patch = patch.object(sys, "argv", ["runner", "outline_prep", "甲::共同课名"])
        argv_patch.start()
        self.addCleanup(argv_patch.stop)
        self.material: dict[str, Any] = {
            "subtopic": "共同课名", "topic": "领域甲", "_material_path": "materials/a.json",
            "groups": [{"heading": "材料", "points": [{"text": "原始内容", "source_id": 1}]}],
        }

    def write_course(self, cid: str, **meta: Any) -> None:
        prep._course_path(cid).write_text(json.dumps({
            "id": cid, "title": "共同课名", "version": 2,
            "sections": [{"id": "s1", "heading": "主题", "blocks": []}], "meta": meta,
        }), encoding="utf-8")

    def bound_run(self, target: str, material: dict[str, Any]) -> dict[str, Any]:
        def model(data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            binding = kwargs["job_binding"]
            cid = binding["course_id"]
            self.write_course(cid, job_binding_id=binding["id"], job_kind="outline_prep",
                              job_target=target)
            return {"ok": True, "course": {"id": cid}, "resume": kwargs["resume_course_id"]}

        with (patch.object(sys, "argv", ["runner", "outline_prep", target]),
              patch.object(prep, "run_prep", side_effect=model)):
            return job_runner._bound_prep("outline_prep", target, material)

    def test_same_title_different_topics_get_distinct_courses_and_resume_exactly(self) -> None:
        first = self.bound_run("甲::共同课名", self.material)
        second = self.bound_run("乙::共同课名", dict(self.material, topic="领域乙"))
        self.assertNotEqual(first["course"]["id"], second["course"]["id"])
        resumed = self.bound_run("甲::共同课名", self.material)
        self.assertEqual(resumed["resume"], first["course"]["id"])
        catalog_store.record_action("outline_prep", "甲::共同课名")
        catalog_store.set_status("甲::共同课名", "done")
        self.assertEqual(outline._existing_courses_index("甲")[0]["共同课名"],
                         [first["course"]["id"]])

    def test_changed_material_is_rejected_before_model_and_keeps_snapshot(self) -> None:
        self.bound_run("甲::共同课名", self.material)
        original = job_store.get_binding("outline_prep", "甲::共同课名")
        with patch.object(prep, "run_prep") as model:
            with self.assertRaisesRegex(ValueError, "材料已变化"):
                job_runner._bound_prep("outline_prep", "甲::共同课名",
                                       dict(self.material, groups=[]))
        model.assert_not_called()
        self.assertEqual(job_store.get_binding("outline_prep", "甲::共同课名"), original)

    def test_changed_or_missing_plan_blocks_recovery(self) -> None:
        binding = job_store.bind_material("outline_prep", "甲::共同课名", self.material)
        cid = binding["course_id"]
        self.write_course(cid, job_binding_id=binding["id"])
        plan = prep._plan_path(cid)
        plan.parent.mkdir(parents=True)
        plan.write_text('{"sections": []}')
        job_store.record_plan(binding["id"], plan)
        for delete in (False, True):
            if delete:
                plan.unlink()
            else:
                plan.write_text('{"sections": [1]}')
            with self.subTest(delete=delete), patch.object(prep, "run_prep") as model:
                with self.assertRaisesRegex(ValueError, "规划已变化或丢失"):
                    job_runner._bound_prep("outline_prep", "甲::共同课名", self.material)
                model.assert_not_called()

    def test_new_job_does_not_adopt_unrelated_same_title(self) -> None:
        self.write_course("unrelated", topic="其他领域")
        result = self.bound_run("甲::共同课名", self.material)
        self.assertIsNone(result["resume"])
        self.assertNotEqual(result["course"]["id"], "unrelated")

    def test_prep_init_uses_reserved_id_and_records_plan_fingerprint(self) -> None:
        binding = job_store.bind_material("outline_prep", "甲::共同课名", self.material)
        _, dispatch, _ = prep._make_tools([], material_groups=["材料"], job_binding=binding)
        plan = [{"id": f"s{i}", "heading": f"节{i}", "has_quiz": True, "covers": "材料"}
                for i in range(1, 4)]
        with patch.object(sys.stdin, "isatty", return_value=False):
            dispatch["submit_plan"]({"sections": plan})
        dispatch["init_course"]({"id": "model-picked-id", "title": "共同课名",
                                 "scenario": "自学", "source_notes": ["材料"]})
        self.assertFalse(prep._course_path("model-picked-id").exists())
        course = prep._load(prep._course_path(binding["course_id"]))
        assert course is not None
        self.assertEqual(course["meta"]["job_binding_id"], binding["id"])
        saved = job_store.get_binding("outline_prep", "甲::共同课名")
        assert saved is not None
        self.assertTrue(saved["plan_hash"])
        job_store.check_plan(saved, prep._plan_path(binding["course_id"]))

    def test_legacy_recovery_requires_unique_provenance(self) -> None:
        target = "甲::共同课名"
        old = catalog_store.record_action("outline_prep", target)
        catalog_store.set_status(target, "failed", action_id=old["id"])
        current = catalog_store.record_action("outline_prep", target)
        self.write_course("old", source_notes=[self.material["_material_path"]])
        self.write_course("foreign", topic="其他领域")
        self.assertEqual(job_runner._legacy_course("outline_prep", target, self.material,
                                                  current["id"]), "old")
        self.write_course("old-duplicate", source_notes=[self.material["_material_path"]])
        with self.assertRaisesRegex(ValueError, "多份课件"):
            job_runner._legacy_course("outline_prep", target, self.material, current["id"])

    def test_duplicate_dispatch_is_atomic_and_old_attempt_cannot_finish_new_attempt(self) -> None:
        target = "同一目标"
        first = catalog_store.record_action("request_prep", target)
        duplicate = catalog_store.record_action("request_prep", target)
        self.assertFalse(duplicate["created"])
        self.assertEqual(first["id"], duplicate["id"])
        catalog_store.set_status(target, "cancelled", action_id=first["id"])
        retry = catalog_store.record_action("request_prep", target)
        catalog_store.set_status(target, "done", "迟到的旧结果", action_id=first["id"])
        latest = catalog_store.latest_job("request_prep", target)
        assert latest is not None
        self.assertEqual(latest["id"], retry["id"])
        self.assertEqual(latest["status"], "queued")
        self.assertNotEqual(executor.log_path_for("request_prep", target, first["id"]),
                            executor.log_path_for("request_prep", target, retry["id"]))

    def test_log_paths_do_not_collide_for_truncated_targets(self) -> None:
        a, b = "x" * 60 + "a", "x" * 60 + "b"
        self.assertNotEqual(executor.log_path_for("outline_prep", a, 1),
                            executor.log_path_for("outline_prep", b, 1))

    def test_cancelled_attempt_cannot_write_or_overwrite_its_terminal_status(self) -> None:
        target = "甲::共同课名"
        row = catalog_store.record_action("outline_prep", target)
        binding = job_store.bind_material("outline_prep", target, self.material)
        binding["action_id"] = row["id"]
        job_store.ensure_active(binding)
        catalog_store.set_status(target, "cancelled", action_id=row["id"])
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            job_store.ensure_active(binding)
        catalog_store.set_status(target, "done", action_id=row["id"])
        latest = catalog_store.latest_job("outline_prep", target)
        assert latest is not None
        self.assertEqual(latest["status"], "cancelled")

    def test_stale_running_job_is_retryable_but_new_queue_is_not_replaced(self) -> None:
        target = "甲::共同课名"
        row = catalog_store.record_action("outline_prep", target)
        executor.reconcile_job("outline_prep", target)
        self.assertFalse(catalog_store.record_action("outline_prep", target)["created"])
        with catalog_store._conn() as conn:
            conn.execute("UPDATE catalog_actions SET created_at=?,status='running' WHERE id=?",
                         ("2000-01-01T00:00:00", row["id"]))
        executor.reconcile_job("outline_prep", target)
        retry = catalog_store.record_action("outline_prep", target)
        self.assertTrue(retry["created"])
        self.assertNotEqual(retry["id"], row["id"])

    def test_spawn_failure_marks_exact_attempt_failed(self) -> None:
        row = catalog_store.record_action("request_prep", "笔记")
        with patch.object(subprocess, "Popen", side_effect=OSError("无法启动")):
            with self.assertRaises(OSError):
                executor.start_job("request_prep", "笔记", action_id=row["id"])
        latest = catalog_store.latest_job("request_prep", "笔记")
        assert latest is not None
        self.assertEqual(latest["status"], "failed")

    def test_publish_excludes_other_partial_jobs_and_catalog_hides_them(self) -> None:
        a = job_store.bind_material("outline_prep", "甲::共同课名", self.material)
        b = job_store.bind_material("outline_prep", "乙::共同课名", self.material)
        self.write_course(a["course_id"], job_binding_id=a["id"])
        self.write_course(b["course_id"], job_binding_id=b["id"])
        destination = settings.data_dir / "published"
        with patch.object(type(settings), "web_public_courses", new_callable=PropertyMock,
                          return_value=destination):
            with patch("app.services.publication.assert_publishable"):
                publish_courses(a["course_id"])
        self.assertTrue((destination / f"{a['course_id']}.csl.json").exists())
        self.assertFalse((destination / f"{b['course_id']}.csl.json").exists())
        self.assertFalse(outline._existing_courses_index()[2])

    def test_cancel_preserves_bound_skeleton_and_does_not_touch_same_title(self) -> None:
        row = catalog_store.record_action("outline_prep", "甲::共同课名")
        binding = job_store.bind_material("outline_prep", "甲::共同课名", self.material)
        skeleton = prep._course_path(binding["course_id"])
        skeleton.write_text(json.dumps({"id": binding["course_id"], "sections": []}))
        self.write_course("unrelated", topic="领域乙")
        with patch.object(sys, "argv", ["runner", "outline_prep", "甲::共同课名", str(row["id"])]):
            with self.assertRaises(SystemExit):
                job_runner._on_cancel(15, None)
        self.assertTrue(prep._course_path("unrelated").exists())
        self.assertTrue(skeleton.exists())

    def test_sample_retry_keeps_original_outline_course_after_reordering(self) -> None:
        target = "大纲"
        material = dict(self.material, _outline_course_id="intro", _outline_topic=target)
        binding = job_store.bind_material("request_research", target, material)
        row = catalog_store.record_action("request_research", target)
        fw = {"courses": [{"id": "other", "title": "另一门"},
                          {"id": "intro", "title": "共同课名"}]}
        with (
            patch.object(sys, "argv", ["runner", "request_research", target, str(row["id"])]),
            patch("app.agent.research.cached_framework", return_value=fw),
            patch("app.agent.research.cached_material", return_value=None) as cached,
            patch("app.agent.research.research_framework") as research_framework,
            patch("app.agent.research.research_material") as research_material,
            patch("app.services.vault_sync.sync_outline"),
            patch("app.services.vault_sync.theme_area", return_value="领域甲"),
            patch.object(prep, "run_prep", return_value={
                "ok": True, "course": {"id": binding["course_id"]},
            }) as model,
            patch("app.services.tts_compile.publish_courses"),
            patch("app.services.publication.ensure_publication",
                  side_effect=lambda course, *_args, **_kwargs: course),
            patch("app.services.outline_attribution.attribute_all", return_value={
                "placements": [], "unplaceable": [],
            }),
        ):
            self.assertEqual(job_runner._run(), binding["course_id"])
        research_framework.assert_not_called()
        research_material.assert_not_called()
        cached.assert_not_called()  # Once bound, only the saved job snapshot may be used.
        self.assertEqual(model.call_args.args[0]["_outline_course_id"], "intro")

    def test_catalog_route_does_not_launch_duplicate_job(self) -> None:
        req = CatalogAction(kind="request_prep", target="笔记")
        with patch.object(executor, "start_job", return_value="mock.log") as start:
            catalog.catalog_action(req)
            catalog.catalog_action(req)
        start.assert_called_once()

    def test_outline_route_allows_same_title_in_other_book_and_retry_of_partial(self) -> None:
        fw = {"courses": [{"id": "intro", "title": "共同课名"}]}
        self.write_course("other-book", job_kind="outline_prep", job_target="乙::共同课名")
        with (patch.object(outline, "_load_outline", return_value=fw),
              patch.object(outline, "start_job", return_value="mock.log") as start):
            outline.prep_course("甲", outline.OutlinePrepReq(title="共同课名"))
            outline.prep_course("甲", outline.OutlinePrepReq(title="共同课名"))
            start.assert_called_once()
            catalog_store.set_status("甲::共同课名", "failed")
            outline.prep_course("甲", outline.OutlinePrepReq(title="共同课名"))
            self.bound_run("甲::共同课名", self.material)
            self.assertEqual(start.call_count, 2)
            catalog_store.set_status("甲::共同课名", "done")
            with self.assertRaises(HTTPException) as err:
                outline.prep_course("甲", outline.OutlinePrepReq(title="共同课名"))
            self.assertEqual(err.exception.status_code, 409)
