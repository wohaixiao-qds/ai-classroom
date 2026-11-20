"""真实工具与循环的恢复/交付回归;模型替身,产物仅写临时目录。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agent import prep
from app.core.config import settings


def section(sid: str, quiz: bool = True) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [{"type": "p", "text": f"{sid} 的完整正文。"}]
    if quiz:
        blocks.append({"type": "quiz", "id": f"{sid}-cp", "question": "如何验证？",
                       "pass_rule": "说明验证步骤"})
    return {"id": sid, "heading": sid, "blocks": blocks}


def response(*calls: tuple[str, dict[str, Any]]) -> SimpleNamespace:
    blocks = []
    for i, (name, args) in enumerate(calls):
        block = MagicMock(type="tool_use", name=name)
        block.name, block.input, block.id = name, args, f"call-{i}"
        block.model_dump.return_value = {
            "type": "tool_use", "name": name, "input": args, "id": block.id,
        }
        blocks.append(block)
    return SimpleNamespace(content=blocks, stop_reason="tool_use" if calls else "end_turn",
                           usage=SimpleNamespace())


class PrepRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in ("courses_dir", "data_dir", "traces_dir"):
            directory = Path(tmp.name) / name
            directory.mkdir()
            p = patch.object(settings, name, directory)
            p.start()
            self.addCleanup(p.stop)
        brief_patch = patch.object(prep, "_course_brief", return_value="")
        brief_patch.start()
        self.addCleanup(brief_patch.stop)
        limit_patch = patch.object(prep, "MAX_TURNS", 8)
        limit_patch.start()
        self.addCleanup(limit_patch.stop)
        tty_patch = patch.object(sys.stdin, "isatty", return_value=False)
        tty_patch.start()
        self.addCleanup(tty_patch.stop)
        self.plan = [
            {"id": f"s{i}", "heading": f"主题{i}", "has_quiz": True, "covers": f"材料{i}"}
            for i in range(1, 4)
        ]
        self.material = {"subtopic": "测试课", "groups": [
            {"heading": f"材料{i}", "points": []} for i in range(1, 4)
        ]}
        _, self.dispatch, self.state = prep._make_tools(
            [], material_groups=[f"材料{i}" for i in range(1, 4)]
        )

    def init(self) -> None:
        self.dispatch["submit_plan"]({"sections": self.plan})
        result = self.dispatch["init_course"]({
            "id": "test", "title": "测试课", "scenario": "自学", "source_notes": ["test.md"],
        })
        self.assertIn("骨架已建", result)

    def run_model(self, replies: list[SimpleNamespace]) -> tuple[dict[str, Any], MagicMock]:
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = replies
        with patch.object(prep, "get_llm_client", return_value=client):
            result = prep.run_prep(self.material, resume_course_id="test", source="test")
        return result, client

    def test_plan_saved_with_coverage_and_locked_after_init(self) -> None:
        self.init()
        saved = json.loads(prep._plan_path("test").read_text())
        self.assertEqual(saved["sections"], self.plan)
        self.assertIn("锁定", self.dispatch["submit_plan"]({"sections": self.plan}))

    def test_duplicate_plan_ids_rejected_without_course(self) -> None:
        self.plan[1]["id"] = "s1"
        self.assertIn("重复", self.dispatch["submit_plan"]({"sections": self.plan}))
        self.assertIsNone(self.state["plan"])

    def test_missing_section_and_quiz_block_delivery(self) -> None:
        self.init()
        for sid in ("s1", "s2"):
            self.dispatch["write_section"]({"section": section(sid, quiz=False)})
        report = self.dispatch["validate_csl"]({})
        self.assertIn("s3", report)
        self.assertIn("尚未交付", report)
        self.assertIn("缺少带明确 pass_rule", report)
        self.assertTrue(report.startswith("❌"))

    def test_unplanned_id_rejected_and_missing_sections_insert_in_plan_order(self) -> None:
        self.init()
        self.assertIn("不在规划", self.dispatch["write_section"]({"section": section("other")}))
        for sid in ("s3", "s1", "s2"):
            self.dispatch["write_section"]({"section": section(sid)})
        course = prep._load(prep._course_path("test"))
        assert course is not None
        self.assertEqual([s["id"] for s in course["sections"]], ["s1", "s2", "s3"])
        self.assertTrue(self.dispatch["validate_csl"]({}).startswith("✅"))

    def test_resume_restores_plan_and_final_check_requires_missing_quiz_and_section(self) -> None:
        self.init()
        self.dispatch["write_section"]({"section": section("s1", quiz=False)})
        result, client = self.run_model([
            response(),  # 不能只凭已有的一节就交付
            response(("write_section", {"section": section("s1")}),
                     ("write_section", {"section": section("s3")})),
            response(),  # 即使已有两个测验,仍不能漏 s2
            response(("write_section", {"section": section("s2")})),
            response(),
        ])
        self.assertTrue(result["ok"])
        self.assertEqual([s["id"] for s in result["course"]["sections"]], ["s1", "s2", "s3"])
        first = client.messages.create.call_args_list[0].kwargs
        self.assertEqual({t["name"] for t in first["tools"]},
                         {"write_section", "validate_csl", "read_notes"})
        prompt = first["messages"][0]["content"]
        self.assertIn("已恢复原规划", prompt)
        self.assertIn("材料3", prompt)

    def test_legacy_resume_requires_replan_preserving_existing_ids(self) -> None:
        self.init()
        self.dispatch["write_section"]({"section": section("s1")})
        prep._plan_path("test").unlink()
        bad_plan = [dict(s, id=f"new-{s['id']}") for s in self.plan]
        result, client = self.run_model([
            response(("write_section", {"section": section("s2")})),
            response(("submit_plan", {"sections": bad_plan})),
            response(("submit_plan", {"sections": self.plan})),
            response(("write_section", {"section": section("s2")}),
                     ("write_section", {"section": section("s3")})),
            response(),
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(prep._plan_path("test").read_text())["sections"], self.plan)
        first = client.messages.create.call_args_list[0].kwargs
        self.assertIn("submit_plan", {t["name"] for t in first["tools"]})
        feedback = str(first["messages"])
        self.assertIn("还没 submit_plan", feedback)
        self.assertIn("保留已有节 id", feedback)

    def test_corrupt_plan_fails_before_model_call(self) -> None:
        self.init()
        prep._plan_path("test").write_text("{")
        with patch.object(prep, "get_llm_client") as model:
            with self.assertRaisesRegex(ValueError, "规划损坏"):
                prep.run_prep(self.material, resume_course_id="test", source="test")
        model.assert_not_called()

    def test_plan_delivery_rejects_duplicate_sections_and_empty_quiz_rule(self) -> None:
        sections = [section("s1"), section("s1"), section("s3")]
        sections[-1]["blocks"][-1]["pass_rule"] = " "
        errors = prep._plan_delivery_errors({"sections": sections}, self.plan)
        self.assertTrue(any("重复" in e for e in errors))
        self.assertTrue(any("s2" in e and "尚未交付" in e for e in errors))
        self.assertTrue(any("s3" in e and "pass_rule" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
