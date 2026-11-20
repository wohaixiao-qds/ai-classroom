"""生成中心任务控制与事件的隔离回归。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from app.core import catalog_store, job_store
from app.core.config import settings
from app.core.job_events import events_for, record_event
from app.services import executor, job_lifecycle


class JobLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key in ("courses_dir", "data_dir"):
            path = Path(tmp.name) / key
            path.mkdir()
            p = patch.object(settings, key, path)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(catalog_store, "_DB", settings.data_dir / "classroom.db")
        p.start()
        self.addCleanup(p.stop)
        self.kind, self.target = "outline_prep", "主题::第一课"
        self.action = catalog_store.record_action(self.kind, self.target)

    def test_events_are_persistent_and_reject_stale_or_stopped_writes(self) -> None:
        record_event(self.kind, self.target, "write", "completed", "第1节",
                     action_id=self.action["id"], current=1, total=3)
        detail = job_lifecycle.detail_job(self.kind, self.target)
        self.assertEqual(detail["events"][0]["current"], 1)
        catalog_store.set_status(self.target, "cancelled", action_id=self.action["id"])
        record_event(self.kind, self.target, "publish", "completed", "不应记录",
                     action_id=self.action["id"])
        new = catalog_store.record_action(self.kind, self.target)
        record_event(self.kind, self.target, "publish", "completed", "旧尝试",
                     action_id=self.action["id"])
        self.assertEqual(len(events_for(self.kind, self.target)), 1)
        self.assertNotEqual(new["id"], self.action["id"])

    def test_resume_keeps_binding_and_prevents_running_duplicate(self) -> None:
        binding = job_store.bind_material(self.kind, self.target, {"groups": []})
        with self.assertRaises(ValueError):
            job_lifecycle.resume_job(self.kind, self.target)
        catalog_store.set_status(self.target, "cancelled", action_id=self.action["id"])
        with (patch.object(job_lifecycle, "start_job") as start,
              patch.object(job_lifecycle, "process_alive", return_value=False)):
            result = job_lifecycle.resume_job(self.kind, self.target)
        start.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(job_store.get_binding(self.kind, self.target)["id"], binding["id"])

    def test_deleted_task_cannot_be_resurrected_and_draft_is_archived(self) -> None:
        binding = job_store.bind_material(self.kind, self.target, {})
        path = settings.courses_dir / f"{binding['course_id']}.csl.json"
        path.write_text(json.dumps({"meta": {"job_binding_id": binding["id"]}}))
        checkpoint = settings.data_dir / "publication" / f"{binding['course_id']}.checkpoint.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text("{}")
        catalog_store.set_status(self.target, "cancelled", action_id=self.action["id"])
        with (patch.object(job_lifecycle, "process_alive", return_value=False),
              patch.object(type(settings), "web_public_courses",
                           new_callable=PropertyMock,
                           return_value=settings.data_dir / "published")):
            result = job_lifecycle.delete_job(self.kind, self.target)
        self.assertTrue(result["ok"])
        self.assertFalse(path.exists())
        self.assertFalse(checkpoint.exists())
        self.assertTrue((settings.data_dir / "deleted-jobs" / str(self.action["id"])
                         / checkpoint.name).exists())
        self.assertTrue((settings.data_dir / "deleted-jobs" / str(self.action["id"])
                         / path.name).exists())
        catalog_store.set_status(self.target, "done", "late", action_id=self.action["id"])
        self.assertEqual(catalog_store.latest_job(self.kind, self.target)["status"], "deleted")
        self.assertEqual(job_lifecycle.list_jobs(), [])
        with self.assertRaises(LookupError):
            job_lifecycle.resume_job(self.kind, self.target)

    def test_published_course_is_kept_when_deleting_task(self) -> None:
        binding = job_store.bind_material(self.kind, self.target, {})
        cid = binding["course_id"]
        path = settings.courses_dir / f"{cid}.csl.json"
        path.write_text(json.dumps({"meta": {"job_binding_id": binding["id"]}}))
        published = settings.data_dir / "published"
        published.mkdir()
        (published / path.name).write_text("published")
        catalog_store.set_status(self.target, "done", cid, action_id=self.action["id"])
        with (patch.object(job_lifecycle, "process_alive", return_value=False),
              patch.object(type(settings), "web_public_courses", new_callable=PropertyMock,
                           return_value=published)):
            job_lifecycle.delete_job(self.kind, self.target)
        self.assertTrue(path.exists())

    def test_stopping_task_cannot_be_deleted_or_resumed_while_process_alive(self) -> None:
        with (patch.object(job_lifecycle, "cancel_job") as cancel,
              patch.object(job_lifecycle, "process_alive", return_value=True)):
            with self.assertRaisesRegex(ValueError, "正在停止"):
                job_lifecycle.delete_job(self.kind, self.target)
            cancel.assert_called_once()
        self.assertNotEqual(catalog_store.latest_job(self.kind, self.target)["status"], "deleted")

    def test_list_reconciles_abandoned_attempt_and_missing_pid_stop_is_effective(self) -> None:
        with catalog_store._conn() as c:
            c.execute("UPDATE catalog_actions SET created_at='2020-01-01T00:00:00' WHERE id=?",
                      (self.action["id"],))
        rows = job_lifecycle.list_jobs()
        self.assertEqual(rows[0]["status"], "failed")
        second = catalog_store.record_action(self.kind, self.target)
        result = executor.cancel_job(self.kind, self.target)
        self.assertTrue(result["cancelled"])
        self.assertEqual(catalog_store.latest_job(self.kind, self.target)["status"], "cancelled")
        self.assertNotEqual(second["id"], self.action["id"])

    def test_cancelled_queue_cannot_spawn_and_reused_pid_is_not_killed(self) -> None:
        catalog_store.set_status(self.target, "cancelled", action_id=self.action["id"])
        with patch.object(executor.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "拒绝启动"):
                executor.start_job(self.kind, self.target, action_id=self.action["id"])
        spawn.assert_not_called()
        action = catalog_store.record_action(self.kind, self.target)
        path = executor.log_path_for(self.kind, self.target, action["id"]).with_suffix(".pid")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("12345")
        with (patch.object(executor, "_owns_process", return_value=False),
              patch.object(executor.os, "killpg") as kill):
            self.assertTrue(executor.cancel_job(self.kind, self.target)["cancelled"])
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
