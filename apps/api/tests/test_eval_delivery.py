"""证据失败隔离、目标兑现与先修权威来源的离线回归。"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app import job_runner
from app.agent import prep
from app.core.config import settings
from app.services import evidence_review


def reply(items: list[dict[str, str]], **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))],
        stop_reason=extra.get("stop_reason", "end_turn"),
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


def verdict(cid: str) -> dict[str, str]:
    return {"id": cid, "verdict": "supported", "reason": "仅支持所给表述"}


class EvalDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key in ("courses_dir", "data_dir", "traces_dir"):
            directory = Path(tmp.name) / key
            directory.mkdir()
            patcher = patch.object(settings, key, directory)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.plan = [
            {"id": f"s{i}", "heading": f"主题{i}", "has_quiz": True, "covers": ""} for i in range(3)
        ]
        self.check = {
            "question": "设计工具描述的对照实验",
            "pass_rule": "固定模型与任务,只改描述,重复试验",
        }

    def review(
        self, responses: list[Any], claims: list[dict[str, str]]
    ) -> tuple[dict[str, Any], MagicMock]:
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = responses
        with patch.object(evidence_review, "get_llm_client", return_value=client):
            return evidence_review.review_claims(claims), client

    def test_partial_batch_preserves_success_and_retries_only_failed(self) -> None:
        result, client = self.review(
            [reply([verdict("a")]), reply([verdict("b")])], [{"id": "a"}, {"id": "b"}]
        )
        self.assertEqual([i["verdict"] for i in result["items"]], ["supported"] * 2)
        request = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertNotIn('"id": "a"', request)
        self.assertEqual(result["usage"], {"input_tokens": 20, "output_tokens": 40})
        self.assertNotIn("error", result)

    def test_budget_failure_records_diagnostic_and_is_bounded(self) -> None:
        empty = SimpleNamespace(
            content=[SimpleNamespace(type="thinking")],
            stop_reason="max_tokens",
            usage=SimpleNamespace(output_tokens=16384),
        )
        # 重试兜底最多 3 次:1 主批 + 3 次单块重审 = 4 次调用后仍 unreviewed。
        result, client = self.review([empty, empty, empty, empty], [{"id": "a"}])
        self.assertEqual(client.messages.create.call_count, 4)
        self.assertEqual(result["error"], "output_budget_exhausted")
        self.assertEqual(result["attempts"][0]["block_types"], ["thinking"])
        self.assertEqual(result["attempts"][0]["text_length"], 0)
        self.assertEqual(result["items"][0]["verdict"], "unreviewed")

    def test_failed_batch_does_not_discard_other_batches(self) -> None:
        # 整批超时 → 整批重试成功(4 块收);第 5 块单独补审成功。
        result, client = self.review(
            [TimeoutError(),
             reply([verdict("0"), verdict("1"), verdict("2"), verdict("3")]),
             reply([verdict("4")])],
            [{"id": str(i)} for i in range(5)],
        )
        self.assertTrue(all(i["verdict"] == "supported" for i in result["items"]))
        self.assertEqual(result["attempts"][0]["error"], "TimeoutError")

    def test_duplicate_input_is_rejected_before_call(self) -> None:
        with patch.object(evidence_review, "get_llm_client") as client:
            with self.assertRaises(ValueError):
                evidence_review.review_claims([{"id": "a"}, {"id": "a"}])
            client.assert_not_called()

    def test_goal_plan_cannot_fall_back_to_material_only_template(self) -> None:
        _, dispatch, state = prep._make_tools([], learning_goal="设计一个实验")
        for _ in range(4):
            self.assertIn("goal_check", dispatch["submit_plan"]({"sections": self.plan}))
        self.assertIsNone(state["plan"])
        self.plan[0]["goal_check"] = self.check
        with patch("sys.stdin.isatty", return_value=False):
            self.assertIn("规划通过", dispatch["submit_plan"]({"sections": self.plan}))
        self.assertEqual(state["plan"][0]["goal_check"], self.check)

    def test_concept_quiz_does_not_satisfy_promised_application(self) -> None:
        self.plan[0]["goal_check"] = self.check
        course: dict[str, Any] = {
            "sections": [
                {
                    "id": f"s{i}",
                    "blocks": [
                        {"type": "quiz", "question": "为什么需要评测", "pass_rule": "解释必要性"}
                    ],
                }
                for i in range(3)
            ]
        }
        self.assertTrue(
            any("应用题" in e for e in prep._plan_delivery_errors(course, self.plan, "设计实验"))
        )
        course["sections"][0]["blocks"].append({"type": "quiz", **self.check})
        self.assertEqual(prep._plan_delivery_errors(course, self.plan, "设计实验"), [])

    def test_goal_saved_and_changed_goal_refused_before_model_call(self) -> None:
        self.plan[0]["goal_check"] = self.check
        prep._save_plan("sample", self.plan, [], learning_goal="设计实验")
        self.assertEqual(
            json.loads(prep._plan_path("sample").read_text())["learning_goal"], "设计实验"
        )
        prep._course_path("sample").write_text(json.dumps({"id": "sample", "sections": []}))
        with patch.object(prep, "get_llm_client") as client:
            with self.assertRaisesRegex(ValueError, "学习目标已变化"):
                prep.run_prep(
                    {"groups": []}, resume_course_id="sample", learning_goal="实现 runner"
                )
            client.assert_not_called()

    def test_outline_empty_prereqs_override_model_for_both_entry_kinds(self) -> None:
        for kind in ("request_research", "outline_prep"):
            course: dict[str, Any] = {
                "id": "sample",
                "meta": {"job_kind": kind, "depends_on": [{"id": "unrelated"}]},
            }
            entry = {"id": "intro", "prereqs": []}
            job_runner._apply_outline_contract(course, {"courses": [entry]}, entry, "主题")
            self.assertEqual(course["meta"]["depends_on"], [])
            self.assertEqual(course["meta"]["outline_course_id"], "intro")

    def test_prerequisite_refs_resolve_without_adopting_other_topic_same_title(self) -> None:
        other: dict[str, Any] = {
            "id": "other",
            "title": "同名",
            "meta": {"job_target": "别的主题::同名", "outline_course_id": "intro"},
            "sections": [{"id": "s1"}],
        }
        own = copy.deepcopy(other)
        own["id"], own["meta"]["job_target"] = "own", "主题::同名"
        for course in (other, own):
            prep._course_path(course["id"]).write_text(json.dumps(course))
        entry = {"id": "second", "prereqs": ["intro"]}
        fw = {"courses": [{"id": "intro", "title": "同名"}, entry]}
        result: dict[str, Any] = {"id": "sample"}
        job_runner._apply_outline_contract(result, fw, entry, "主题")
        self.assertEqual([d["id"] for d in result["meta"]["depends_on"]], ["own"])

    def test_legacy_goal_upgrade_preserves_original_contract(self) -> None:
        _, dispatch, state = prep._make_tools([], learning_goal="设计实验")
        state["required_plan"] = copy.deepcopy(self.plan)
        proposed = copy.deepcopy(self.plan)
        proposed[0]["goal_check"] = self.check
        proposed[1]["heading"] = "偷偷换掉原章节"
        self.assertIn("不得变更", dispatch["submit_plan"]({"sections": proposed}))
        proposed[1]["heading"] = self.plan[1]["heading"]
        with patch("sys.stdin.isatty", return_value=False):
            self.assertIn("规划通过", dispatch["submit_plan"]({"sections": proposed}))

    def test_resume_inherits_goal_and_receives_authoritative_entry_context(self) -> None:
        self.plan[0]["goal_check"] = self.check
        prep._save_plan("sample", self.plan, [], learning_goal="设计实验")
        prep._course_path("sample").write_text(json.dumps({"id": "sample", "sections": []}))
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.return_value = SimpleNamespace(
            content=[], stop_reason="end_turn", usage=SimpleNamespace(),
        )
        with (patch.object(prep, "get_llm_client", return_value=client),
              patch.object(prep, "_course_brief", return_value="旧课:不应成为入口先修"),
              patch.object(prep, "MAX_TURNS", 1)):
            prep.run_prep({"groups": []}, resume_course_id="sample", source="test",
                          prerequisite_titles=[])
        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("大纲学习目标(交付约束):设计实验", prompt)
        self.assertIn("无,这是独立入口课", prompt)
        tool_names = [t["name"] for t in client.messages.create.call_args.kwargs["tools"]]
        self.assertNotIn("submit_plan", tool_names)
