"""待学与延伸问题的隔离回归：临时 SQLite/笔记/轨迹，不调用模型或启动进程。"""
from __future__ import annotations

import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import catalog_store
from app.core.config import settings
from app.routes.wishlist import router
from app.services import wishlist


class WishlistTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key in ("data_dir", "kb_dir", "traces_dir"):
            path = Path(tmp.name) / key
            path.mkdir()
            mocked = patch.object(settings, key, path)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(catalog_store, "_DB", settings.data_dir / "classroom.db")
        mocked.start()
        self.addCleanup(mocked.stop)
        self.traces: list[dict[str, Any]] = []
        mocked = patch.object(wishlist, "read_traces", side_effect=lambda *_a, **_k: self.traces)
        mocked.start()
        self.addCleanup(mocked.stop)
        mocked = patch.object(wishlist, "start_job", side_effect=self._start)
        self.start = mocked.start()
        self.addCleanup(mocked.stop)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    @staticmethod
    def _start(kind: str, target: str, *, action_id: int) -> Path:
        catalog_store.set_status(target, "running", action_id=action_id)
        return Path("/isolated/job.log")

    def todo(self, rel: str, text: str = "- [ ] **原子性** — 事务边界") -> Path:
        path = settings.kb_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def trace(self, course: str | None = "course-a", **extra: Any) -> dict[str, Any]:
        return {
            "question": "如何检查事务原子性？", "course_id": course,
            "page_id": "section-2", "run_id": "run-a", "ts": "2026-11-19T12:00:00",
            "searched": True, "tool_calls": [
                {"name": "web_search", "args": {"query": "事务原子性"}},
            ], **extra,
        }

    def test_manual_save_is_trimmed_idempotent_and_never_starts_job(self) -> None:
        first = self.client.post("/api/v1/wishlist", json={"title": "  HTTP 缓存  "})
        second = self.client.post("/api/v1/wishlist", json={"title": "http   缓存"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["title"], "HTTP 缓存")
        self.assertEqual(first.json()["status"], "pending")
        self.assertIsNone(first.json()["job"])
        self.assertEqual(len(wishlist.list_items().items), 1)
        self.start.assert_not_called()

    def test_blank_and_oversized_titles_rejected(self) -> None:
        for title in ("   ", "\n\t", "a" * 501):
            with self.subTest(title=title[:10]):
                self.assertEqual(
                    self.client.post("/api/v1/wishlist", json={"title": title}).status_code, 422,
                )
        self.assertEqual(wishlist.list_items().pending_count, 0)
        self.start.assert_not_called()

    def test_vault_source_import_is_read_only_idempotent_and_does_not_revive_removed(self) -> None:
        path = self.todo("数据库/待探.md")
        original = path.read_bytes()
        first = wishlist.list_items().items[0]
        self.assertEqual(first.title, "原子性")
        self.assertIn("数据库/待探.md", first.sources[0].label)
        wishlist.update_item(first.id, "removed")
        path.write_text("说明文字\n" + original.decode(), encoding="utf-8")
        after_edit = path.read_bytes()
        self.assertEqual(wishlist.list_items().items, [])
        removed = wishlist.list_items("removed").items
        self.assertEqual(removed[0].id, first.id)
        self.assertEqual(path.read_bytes(), after_edit)
        self.assertEqual(len(wishlist.list_items("all").items), 1)
        self.start.assert_not_called()

    def test_same_area_keeps_all_sources_and_cross_domain_does_not_merge(self) -> None:
        self.todo("数据库/待探.md")
        self.todo("数据库/另一个待探.md")
        self.todo("物理/待探.md")
        items = wishlist.list_items().items
        self.assertEqual(len(items), 2)
        self.assertEqual(sorted(len(item.sources) for item in items), [1, 2])
        jobs = [wishlist.start_item(item.id).job for item in items]
        self.assertNotEqual(jobs[0].target, jobs[1].target)

    def test_old_todo_job_is_started_and_job_only_history_not_imported(self) -> None:
        self.todo("数据库/待探.md")
        previous = catalog_store.record_action("request_research", "原子性")
        catalog_store.set_status("原子性", "failed", "已有失败", action_id=previous["id"])
        catalog_store.record_action("request_research", "纯历史任务")
        self.assertEqual(wishlist.list_items().items, [])
        items = wishlist.list_items("started").items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].job.id, previous["id"])
        self.assertEqual(items[0].job.status, "failed")
        self.assertTrue(items[0].job.can_resume)
        self.assertEqual(wishlist.start_item(items[0].id).job.id, previous["id"])
        self.start.assert_not_called()

    def test_ambiguous_cross_domain_title_does_not_guess_legacy_job_ownership(self) -> None:
        self.todo("数据库/待探.md", "- [ ] **HTTP 缓存**")
        self.todo("网络/待探.md", "- [ ] **http   缓存**")
        previous = catalog_store.record_action("request_research", "HTTP 缓存")
        items = wishlist.list_items().items
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.status == "pending" and item.job is None for item in items))
        self.assertEqual(wishlist.list_items("started").items, [])
        self.assertEqual(catalog_store.latest_job("request_research", "HTTP 缓存")["id"],
                         previous["id"])
        self.start.assert_not_called()

    def test_same_domain_multiple_sources_can_link_legacy_bare_title_job(self) -> None:
        self.todo("数据库/待探.md")
        self.todo("数据库/另一个待探.md")
        previous = catalog_store.record_action("request_research", "原子性")
        self.assertEqual(wishlist.list_items().items, [])
        items = wishlist.list_items("started").items
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0].sources), 2)
        self.assertEqual(items[0].job.id, previous["id"])
        self.start.assert_not_called()

    def test_start_repeated_concurrent_requests_create_only_one_job(self) -> None:
        item = wishlist.save_manual("并发事务")
        # 先创建schema；并行调用验证SELECT/INSERT与条目绑定属于同一写事务。
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _n: wishlist.start_item(item.id), range(2)))
        self.assertEqual(sum(result.created for result in results), 1)
        self.assertEqual(results[0].job.id, results[1].job.id)
        self.start.assert_called_once()
        self.assertEqual(wishlist.list_items().items, [])
        self.assertEqual(wishlist.list_items("started").items[0].id, item.id)

    def test_failed_or_cancelled_job_is_linked_for_resume_not_started_again(self) -> None:
        item = wishlist.save_manual("恢复")
        job = wishlist.start_item(item.id).job
        catalog_store.set_status(job.target, "cancelled", action_id=job.id)
        with patch("app.services.job_lifecycle.process_alive", return_value=False):
            retried = wishlist.start_item(item.id)
        self.assertFalse(retried.created)
        self.assertEqual(retried.job.id, job.id)
        self.assertIn("任务区继续", retried.note)
        self.start.assert_called_once()

    def test_spawn_failure_is_visible_retains_item_and_recovery_uses_job_area(self) -> None:
        item = wishlist.save_manual("启动失败")

        def failure(kind: str, target: str, *, action_id: int) -> None:
            catalog_store.set_status(target, "failed", "模拟启动失败", action_id=action_id)
            raise OSError("process unavailable")

        self.start.side_effect = failure
        response = self.client.post(f"/api/v1/wishlist/{item.id}/start")
        self.assertEqual(response.status_code, 503)
        kept = wishlist.list_items().items[0]
        self.assertEqual(kept.id, item.id)
        self.assertEqual(kept.job.status, "failed")
        retry = self.client.post(f"/api/v1/wishlist/{item.id}/start")
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(retry.json()["created"])
        self.assertIn("任务区继续", retry.json()["note"])
        self.start.assert_called_once()

    def test_removal_does_not_stop_task_and_deleted_task_requires_explicit_restore(self) -> None:
        item = wishlist.save_manual("保留学习记录")
        job = wishlist.start_item(item.id).job
        wishlist.update_item(item.id, "removed")
        self.assertEqual(catalog_store.latest_job(job.kind, job.target)["status"], "running")
        self.assertEqual(self.client.post(f"/api/v1/wishlist/{item.id}/start").status_code, 409)
        wishlist.update_item(item.id, "pending")
        catalog_store.set_status(job.target, "deleted", action_id=job.id)
        # 已删除任务不会使已发起条目自动回到待办。
        wishlist.start_item(item.id)
        new_job = wishlist.list_items("started").items[0].job
        self.assertNotEqual(new_job.id, job.id)
        catalog_store.set_status(new_job.target, "deleted", action_id=new_job.id)
        self.assertEqual(wishlist.list_items().pending_count, 0)
        self.assertEqual(self.client.post(f"/api/v1/wishlist/{item.id}/start").status_code, 409)
        self.assertEqual(wishlist.list_items("started").items[0].job.status, "deleted")

    def test_questions_have_exact_course_provenance_and_missing_course_is_unassigned(self) -> None:
        self.traces[:] = [self.trace(), self.trace("course-b", run_id="run-b"),
                          self.trace(None, run_id="legacy"), self.trace(source="test")]
        current = wishlist.list_questions("course-a")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].run_id, "run-a")
        self.assertEqual(current[0].page_id, "section-2")
        self.assertEqual(current[0].created_at, "2026-11-19T12:00:00")
        self.assertEqual(current[0].detail, "事务原子性")
        self.assertEqual(len(wishlist.list_questions("course-b")), 1)
        unassigned = wishlist.list_questions(unassigned=True)
        self.assertEqual(len(unassigned), 1)
        self.assertIsNone(unassigned[0].course_id)
        self.assertEqual(wishlist.list_items().pending_count, 0)

    def test_question_save_is_atomic_idempotent_and_cross_course_independent(self) -> None:
        self.traces[:] = [self.trace(), self.trace("course-b", run_id="run-b")]
        first = wishlist.list_questions("course-a")[0]
        saved = wishlist.save_question(first.id)
        self.assertEqual(wishlist.save_question(first.id).id, saved.id)
        second = wishlist.list_questions("course-b")[0]
        self.assertEqual(second.status, "candidate")
        other = wishlist.save_question(second.id)
        self.assertNotEqual(other.id, saved.id)
        after = wishlist.list_questions("course-a")[0]
        self.assertEqual(after.status, "saved")
        self.assertEqual(after.wishlist_id, saved.id)
        self.assertEqual(saved.sources[0].course_id, "course-a")
        self.start.assert_not_called()
        self.assertNotEqual(wishlist.start_item(saved.id).job.target,
                            wishlist.start_item(other.id).job.target)

    def test_question_save_failure_rolls_back_both_state_and_wishlist(self) -> None:
        self.traces[:] = [self.trace()]
        question = wishlist.list_questions("course-a")[0]
        original = wishlist._upsert

        def fail_after_insert(*args: Any, **kwargs: Any) -> str:
            original(*args, **kwargs)
            raise sqlite3.OperationalError("isolated write failure")

        with patch.object(wishlist, "_upsert", side_effect=fail_after_insert):
            with self.assertRaises(sqlite3.OperationalError):
                wishlist.save_question(question.id)
        self.assertEqual(wishlist.list_questions("course-a")[0].status, "candidate")
        self.assertEqual(wishlist.list_items().pending_count, 0)

    def test_question_runs_keep_sources_and_dismiss_is_per_source(self) -> None:
        self.traces[:] = [self.trace(), self.trace(run_id="run-b")]
        questions = wishlist.list_questions("course-a")
        first = wishlist.save_question(questions[0].id)
        second = wishlist.save_question(questions[1].id)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(second.sources), 2)
        wishlist.dismiss_question(questions[0].id)
        self.assertEqual(len(wishlist.list_questions("course-a")), 1)
        self.assertEqual(len(wishlist.list_questions("course-a", include_dismissed=True)), 2)
        self.assertEqual(len(wishlist.list_items().items), 1)

    def test_trace_rotation_keeps_question_and_does_not_restore_removed_wishlist(self) -> None:
        self.traces[:] = [self.trace()]
        question = wishlist.list_questions("course-a")[0]
        saved = wishlist.save_question(question.id)
        wishlist.update_item(saved.id, "removed")
        self.traces.clear()
        self.assertEqual(wishlist.list_questions("course-a")[0].id, question.id)
        self.assertEqual(wishlist.list_items().items, [])
        # 用户明确再次加入，才恢复待处理。
        self.assertEqual(wishlist.save_question(question.id).status, "pending")

    def test_legacy_confirmed_question_imports_once_without_trace_or_course_guess(self) -> None:
        question = "事务会失败吗？"
        key = wishlist._norm(question)
        catalog_store.record_action("confirm_spark", key, question)
        items = wishlist.list_items().items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, question)
        unknown = wishlist.list_questions(unassigned=True)
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].status, "saved")
        wishlist.update_item(items[0].id, "removed")
        self.assertEqual(wishlist.list_items().items, [])
        self.assertEqual(len(wishlist.list_items("removed").items), 1)

    def test_legacy_global_key_does_not_override_new_per_source_actions(self) -> None:
        self.traces[:] = [self.trace(), self.trace("course-b", run_id="run-b")]
        catalog_store.record_action("confirm_spark", wishlist._norm(self.traces[0]["question"]))
        first = wishlist.list_questions("course-a")[0]
        self.assertEqual(first.status, "saved")
        wishlist.dismiss_question(first.id)
        self.assertEqual(wishlist.list_questions("course-a"), [])
        self.assertEqual(wishlist.list_questions("course-b")[0].status, "saved")

    def test_api_filters_and_missing_ids_are_explicit(self) -> None:
        self.assertEqual(self.client.get("/api/v1/wishlist?status=bad").status_code, 422)
        self.assertEqual(self.client.patch(
            "/api/v1/wishlist/missing", json={"status": "removed"},
        ).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/wishlist/missing/start").status_code, 404)
        self.assertEqual(self.client.post(
            "/api/v1/learning-questions/missing/save",
        ).status_code, 404)
        self.assertEqual(self.client.post(
            "/api/v1/learning-questions/missing/dismiss",
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/learning-questions?course_id=course-a&unassigned=true",
        ).status_code, 422)
