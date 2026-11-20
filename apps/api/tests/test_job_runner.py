"""任务入口回归:真实状态落临时 SQLite,模型、发布与 vault 写入均替换。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import job_runner
from app.core import catalog_store
from app.core.config import settings
from app.core.job_store import bind_material


class JobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = Path(tmp.name)
        for name in ("courses_dir", "data_dir", "traces_dir"):
            directory = self.tmp_dir / name
            directory.mkdir()
            directory_patch = patch.object(settings, name, directory)
            directory_patch.start()
            self.addCleanup(directory_patch.stop)
        db_patch = patch.object(catalog_store, "_DB", self.tmp_dir / "classroom.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.target = "测试笔记.md"
        catalog_store.record_action("request_prep", self.target)
        bind_material("request_prep", self.target, {"_material_path": self.target},
                      legacy_course_id="test-course")
        # 已有产物供失败后续写,失败路径不得清掉它。
        self.partial_path = self.tmp_dir / "partial.csl.json"
        self.partial = json.dumps({"id": "partial", "sections": [{"id": "s1"}]})
        self.partial_path.write_text(self.partial, encoding="utf-8")
        self.prep: MagicMock = self._patch("app.agent.prep.run_prep")
        self.prep.return_value = {"ok": True, "course": {"id": "test-course"}}
        self._patch("app.agent.prep._material_from_note").return_value = {}
        self._patch("app.services.publication.ensure_publication").side_effect = (
            lambda course, *_args, **_kwargs: course
        )
        self.publish = self._patch("app.services.tts_compile.publish_courses")
        self.attribute = self._patch("app.services.outline_attribution.attribute_all")
        self.attribute.return_value = {"placements": [], "unplaceable": []}
        self._patch("app.job_runner.signal.signal")
        self._patch("builtins.print")

    def _patch(self, name: str) -> MagicMock:
        patcher = patch(name)
        mock: MagicMock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _status(self) -> tuple[str, str | None]:
        with catalog_store._conn() as conn:
            row = conn.execute(
                "SELECT status, detail FROM catalog_actions WHERE target=?"
                " ORDER BY id DESC LIMIT 1",
                (self.target,),
            ).fetchone()
        return row["status"], row["detail"]

    def _run(self, kind: str = "request_prep") -> int:
        with patch.object(sys, "argv", ["app.job_runner", kind, self.target]):
            return job_runner._main()

    def test_success_is_done_only_after_publish(self) -> None:
        def publish(course_id: str) -> None:
            self.assertEqual(course_id, "test-course")
            self.assertEqual(self._status(), ("running", None))

        self.publish.side_effect = publish
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._status(), ("done", "test-course"))
        self.publish.assert_called_once()

    def test_failed_validation_is_failed_and_preserves_partial(self) -> None:
        self.prep.return_value = {"ok": False, "course": {"id": "test-course"}}
        self.assertEqual(self._run(), 1)
        status, detail = self._status()
        self.assertEqual(status, "failed")
        self.assertIn("未通过校验", detail or "")
        self.assertEqual(self.partial_path.read_text(encoding="utf-8"), self.partial)
        self.publish.assert_not_called()
        self.attribute.assert_not_called()

    def test_prep_exception_is_failed(self) -> None:
        self.prep.side_effect = RuntimeError("模型调用失败")
        self.assertEqual(self._run(), 1)
        self.assertEqual(self._status(), ("failed", "模型调用失败"))
        self.publish.assert_not_called()

    def test_publish_exception_is_failed(self) -> None:
        self.publish.side_effect = OSError("发布失败")
        self.assertEqual(self._run(), 1)
        self.assertEqual(self._status(), ("failed", "发布失败"))
        self.attribute.assert_not_called()

    def test_attribution_failure_does_not_fail_published_course(self) -> None:
        self.attribute.side_effect = RuntimeError("归位失败")
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._status(), ("done", "test-course"))
        self.publish.assert_called_once()

    def test_unknown_kind_is_failed(self) -> None:
        self.assertEqual(self._run("unknown"), 1)
        self.assertEqual(self._status(), ("failed", "未知任务类型: unknown"))
        self.prep.assert_not_called()
        self.publish.assert_not_called()

    def test_missing_outline_course_is_failed(self) -> None:
        self.target = "测试领域::缺失课"
        catalog_store.record_action("outline_prep", self.target)
        self._patch("app.agent.research.cached_framework").return_value = {
            "courses": [{"title": "另一门课"}]
        }
        self._patch("app.services.vault_sync.sync_outline")
        self.assertEqual(self._run("outline_prep"), 1)
        self.assertEqual(self._status(), ("failed", "大纲里没有这门课: 缺失课"))
        self.prep.assert_not_called()
        self.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
