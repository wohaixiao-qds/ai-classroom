"""Research output is bound to fetched sources and the reviewed course contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agent import research
from app.core import catalog_store
from app.core.config import settings
from app.routes import outline as outline_routes


class ResearchProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        self.data_dir.mkdir()
        self.courses_dir = Path(tmp.name) / "courses"
        self.courses_dir.mkdir()
        self.traces_dir = Path(tmp.name) / "traces"
        self.traces_dir.mkdir()
        for name, value in (("data_dir", self.data_dir), ("courses_dir", self.courses_dir),
                            ("traces_dir", self.traces_dir)):
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        db = patch.object(catalog_store, "_DB", self.data_dir / "classroom.db")
        db.start()
        self.addCleanup(db.stop)

    @staticmethod
    def calls(urls: list[str], *, failed: set[str] | None = None) -> list[dict[str, Any]]:
        failed = failed or set()
        return [
            {
                "name": "fetch_page",
                "args": {"url": url},
                "ts": 1795147200,
                "error": "fetch failed" if url in failed else None,
                "result": f"[Source {i} | {url}]\n" + ("Evidence text. " * 60),
            }
            for i, url in enumerate(urls, 1)
        ]

    def test_outline_sources_are_captured_only_from_successful_fetches(self) -> None:
        url1, url2, fake = (
            "https://docs.example.org/eval",
            "https://lab.example.net/harness",
            "https://never-fetched.example.org/page",
        )
        outline: dict[str, Any] = {"courses": [
            {"id": "c1", "source_quotes": [
                {"url": url1, "quote": "Evidence text. Evidence text. Evidence text."},
                {"url": url2, "quote": "Evidence text. Evidence text. Evidence text."},
            ]},
            {"id": "c2", "source_quotes": [
                {"url": fake, "quote": "Evidence text. Evidence text. Evidence text."},
            ]},
        ]}
        captured, errors = research._attach_framework_sources(
            outline, self.calls([url1, url2])
        )
        self.assertTrue(any("未在本轮成功抓取" in error for error in errors))
        sources = captured["source_evidence"]
        self.assertEqual([source["url"] for source in sources], [url1, url2])
        self.assertEqual(captured["courses"][0]["source_ids"], [1, 2])
        self.assertEqual(captured["courses"][1]["source_ids"], [])
        self.assertTrue(all(source["snapshot_sha256"] for source in sources))
        self.assertTrue(all(source["fetched_at"] for source in sources))
        self.assertIn("Evidence text.", sources[0]["excerpt"])

    def test_framework_validation_preserves_source_references_and_legacy_outlines(self) -> None:
        data: dict[str, Any] = {
            "topic": "test",
            "courses": [
                {"id": "a", "title": "A", "goal": "do A", "origin": "map",
                 "prereqs": [], "source_ids": [1]},
                {"id": "b", "title": "B", "goal": "do B", "origin": "map",
                 "prereqs": ["a"], "source_ids": [2]},
                {"id": "c", "title": "C", "goal": "do C", "origin": "map",
                 "prereqs": ["b"], "source_ids": [1]},
            ],
            "source_evidence": [
                {"id": 1, "url": "https://docs.example.org/a", "snapshot_sha256": "abc"},
                {"id": 2, "url": "https://lab.example.net/b", "snapshot_sha256": "def"},
            ],
        }
        self.assertEqual(research.validate_framework(data), [])
        data["courses"][0]["source_ids"] = [99]
        self.assertTrue(any("不存在" in error for error in research.validate_framework(data)))
        legacy: dict[str, Any] = {**data, "legacy": True, "source_evidence": []}
        for course in legacy["courses"]:
            course.pop("source_ids", None)
        self.assertFalse(any("来源" in error for error in research.validate_framework(legacy)))

    def test_course_context_contains_goal_prerequisites_and_following_scope(self) -> None:
        framework: dict[str, Any] = {"topic": "Agent eval", "courses": [
            {"id": "a", "title": "基础", "goal": "画出系统边界", "scope": "模型和循环"},
            {"id": "b", "title": "裁判", "goal": "校准裁判", "scope": "一致性与偏差",
             "prereqs": ["a"]},
            {"id": "c", "title": "CI", "goal": "建立回归门", "scope": "门禁",
             "prereqs": ["b"]},
        ]}
        context = research.course_research_context(framework, framework["courses"][1])
        self.assertEqual(context["learning_goal"], "校准裁判")
        self.assertEqual(context["scope"], "一致性与偏差")
        self.assertEqual(context["prerequisites"][0]["goal"], "画出系统边界")
        self.assertEqual(context["following_courses"][0]["goal"], "建立回归门")

    def test_material_cache_with_stale_goal_context_is_not_reused(self) -> None:
        path = self.data_dir / "research" / "eval.course.material.json"
        path.parent.mkdir(parents=True)
        data = {
            "topic": "eval",
            "subtopic": "course",
            "sources": [{"id": i, "title": f"s{i}", "url": f"https://example.org/{i}"}
                        for i in range(1, 7)],
            "groups": [{"heading": "facts", "points": [
                {"text": f"fact {i}", "source_id": (i % 6) + 1,
                 "quote": "a sufficiently long quote"}
                for i in range(24)
            ]}],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        context = {"course_id": "eval", "learning_goal": "changed"}
        with patch("builtins.print") as message:
            self.assertIsNone(research.cached_material("eval", "course", research_context=context))
        self.assertTrue(any("不会静默套用旧材料" in str(call) for call in message.call_args_list))

    def test_successful_fetch_is_deduplicated_within_a_research_run(self) -> None:
        url = "https://docs.example.org/page"
        tool_blocks = [
            SimpleNamespace(type="tool_use", name="fetch_page", id=f"call-{i}",
                            input={"url": url})
            for i in range(2)
        ]
        response = SimpleNamespace(content=tool_blocks, stop_reason="tool_use",
                                   usage=SimpleNamespace(input_tokens=0, output_tokens=0))
        final = SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok":true}')],
                                stop_reason="end_turn",
                                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        client = SimpleNamespace()
        client.with_options = lambda **_: client
        client.messages = SimpleNamespace(create=unittest.mock.Mock(side_effect=[response, final]))
        fetch = unittest.mock.Mock(return_value=f"[Page | {url}]\n" + ("body " * 100))
        trace = unittest.mock.Mock()
        with (patch.object(research, "get_llm_client", return_value=client),
              patch.object(research, "_execute", side_effect=lambda name, args: fetch(args["url"])),
              patch.object(research, "trace_research", side_effect=trace)):
            result = research._loop("prompt", lambda _d, _f: [], "topic", "test")
        self.assertTrue(result["ok"])
        self.assertEqual(fetch.call_count, 1)
        calls = trace.call_args.kwargs["tool_calls"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["reused_from_call"], 0)

    def test_framework_trace_records_source_coverage_and_cost(self) -> None:
        urls = ["https://docs.example.org/evals", "https://lab.example.net/harness"]
        quote = "The evaluation guide requires representative held-out tasks."
        courses = [
            {"id": "intro", "title": "Define the boundary", "goal": "Draw the system boundary",
             "scope": "Harness boundary, not model training", "origin": "map", "part": "Basics",
             "prereqs": [], "source_quotes": [{"url": urls[0], "quote": quote}]},
            {"id": "judge", "title": "Calibrate the judge", "goal": "Measure judge agreement",
             "scope": "Agreement and bias, not production tracing", "origin": "map",
             "part": "Design",
             "prereqs": ["intro"], "source_quotes": [{"url": urls[1], "quote": quote}]},
            {"id": "gate", "title": "Build a regression gate", "goal": "Run a release check",
             "scope": "CI thresholds, not dataset authoring", "origin": "map", "part": "Practice",
             "prereqs": ["judge"], "source_quotes": [{"url": urls[0], "quote": quote}]},
        ]
        blocks = [
            SimpleNamespace(type="tool_use", name="fetch_page", id=f"fetch-{i}",
                            input={"url": url})
            for i, url in enumerate(urls)
        ]
        tool_response = SimpleNamespace(
            content=blocks, stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=12, output_tokens=4),
        )
        final_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps({"topic": "Agent eval",
                                                                      "courses": courses}))],
            stop_reason="end_turn", usage=SimpleNamespace(input_tokens=20, output_tokens=30),
        )
        client = SimpleNamespace()
        client.with_options = lambda **_: client
        client.messages = SimpleNamespace(create=unittest.mock.Mock(
            side_effect=[tool_response, final_response]
        ))
        progress = unittest.mock.Mock()

        def fetch(_name: str, args: dict[str, str]) -> str:
            return f"[Guide | {args['url']}]\n{quote} " + ("More source text. " * 20)

        with (patch.object(research, "get_llm_client", return_value=client),
              patch.object(research, "_execute", side_effect=fetch),
              patch.object(research, "emit_call"),
              patch.object(research, "update_run", side_effect=progress),
              patch.object(research, "trace_research")):
            result = research._loop(
                "prompt", research.validate_framework, "Agent eval", "framework"
            )

        self.assertEqual(result["courses"][0]["source_ids"], [1])
        recorded = [call.kwargs for call in progress.call_args_list]
        final = next(fields for fields in recorded if fields.get("research_outline"))
        self.assertEqual(final["research_outline"], {
            "courses": 3, "sourced_courses": 3, "sources": 2,
        })
        self.assertEqual(final["research_cost"]["total_usage"], {
            "input_tokens": 32, "output_tokens": 34,
        })

    def test_outline_get_and_edit_preserve_server_generated_sources(self) -> None:
        topic = "Harness Eval"
        folder = self.data_dir / "research"
        folder.mkdir()
        path = folder / f"{research._slug(topic)}.framework.json"
        saved = {
            "topic": topic,
            "domain": "Agent",
            "source_evidence": [{
                "id": 1,
                "title": "Official guide",
                "url": "https://docs.example.org/evals",
                "fetched_at": "2026-11-20T12:00:00Z",
                "snapshot_sha256": "deadbeef",
                "excerpt": "A verified excerpt from the saved page.",
            }],
            "courses": [
                {"id": "one", "title": "One", "goal": "do one", "why": "barrier",
                 "scope": "in/out", "prereqs": [], "origin": "map", "source_ids": [1]},
                {"id": "two", "title": "Two", "goal": "do two", "why": "barrier",
                 "scope": "in/out", "prereqs": ["one"], "origin": "map", "source_ids": [1]},
                {"id": "three", "title": "Three", "goal": "do three", "why": "barrier",
                 "scope": "in/out", "prereqs": ["two"], "origin": "map", "source_ids": [1]},
            ],
        }
        path.write_text(json.dumps(saved), encoding="utf-8")
        detail = outline_routes.get_outline(topic)
        self.assertEqual(detail["source_status"], "recorded")
        self.assertEqual(detail["source_evidence"], saved["source_evidence"])
        self.assertEqual(detail["courses"][0]["source_ids"], [1])
        with patch("app.services.vault_sync.sync_outline"):
            edit = outline_routes.OutlineEdit(courses=detail["courses"])
            outline_routes.save_outline(topic, edit)
        reread = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(reread["source_evidence"], saved["source_evidence"])
        self.assertEqual(reread["courses"][0]["source_ids"], [1])

    def _coverage_context(self) -> dict[str, Any]:
        return {"outline_topic": "测试主题", "learning_goal": "能实现一个最小解析层",
                "scope": {"讲": "解析链", "不讲": "流式"}, "prerequisites": []}

    def test_material_coverage_gate_bounces_and_caches_by_hash(self) -> None:
        material = {
            "sources": [{"id": i, "title": f"s{i}", "url": f"https://example.org/{i}"}
                        for i in range(1, 7)],
            "groups": [{"heading": "facts", "points": [
                {"text": f"fact {i}", "source_id": (i % 6) + 1,
                 "quote": "a sufficiently long quote"} for i in range(24)]}],
            "evidence_version": 1,
        }
        gaps_reply = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(
                {"gaps": ["流式部分无材料覆盖"]}))],
            stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        research._COVERAGE_MEMO.clear()
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = [gaps_reply, gaps_reply]
        with (patch.object(research, "get_llm_client", return_value=client),
              patch.object(research, "_require_search", lambda: None)):
            errs = research.review_material_coverage(material, self._coverage_context())
            self.assertTrue(any("材料覆盖缺口" in e for e in errs))
            # 同哈希重复交付:沿用缓存结论,不再调模型
            errs2 = research.review_material_coverage(material, self._coverage_context())
            self.assertEqual(errs2, errs)
        self.assertEqual(client.messages.create.call_count, 1)
        # 无大纲约束(旧式独立调研):覆盖闸跳过
        with patch.object(research, "get_llm_client", return_value=client):
            self.assertEqual(research.review_material_coverage(material, None), [])
            self.assertEqual(client.messages.create.call_count, 1)

    def test_material_coverage_service_failure_degrades_to_pass(self) -> None:
        material = {
            "sources": [{"id": i, "title": f"s{i}", "url": f"https://example.org/{i}"}
                        for i in range(1, 7)],
            "groups": [{"heading": "facts", "points": [
                {"text": f"fact {i}", "source_id": (i % 6) + 1,
                 "quote": "a sufficiently long quote"} for i in range(24)]}],
            "evidence_version": 1,
        }
        research._COVERAGE_MEMO.clear()
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = RuntimeError("endpoint down")
        with patch.object(research, "get_llm_client", return_value=client):
            self.assertEqual(
                research.review_material_coverage(material, self._coverage_context()), [])

    def test_framework_review_semantics_and_status_lifecycle(self) -> None:
        fw: dict[str, Any] = {
            "topic": "测试主题",
            "sources": [{"id": 1, "url": "https://example.org/1"}],
            "source_evidence": [
                {"id": 1, "title": "原文页", "url": "https://example.org/1",
                 "excerpt": "原文相关论述内容", "snapshot_sha256": "x"},
            ],
            "courses": [{"id": "c1", "title": "课一", "goal": "能画图", "why": "弱点",
                         "scope": {}, "prereqs": []}],
        }
        passed = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(
                {"courses": {"课一": {"verdict": "supported", "issues": []}}}))],
            stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        failed = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(
                {"courses": {"课一": {"verdict": "unsupported",
                                      "issues": ["原文没有画图相关内容"]}}}))],
            stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = [passed, failed]
        with patch.object(research, "get_llm_client", return_value=client):
            review = research.review_framework_semantics(fw)
            self.assertEqual(review["status"], "passed")
            fw["review"] = review
            self.assertEqual(research.framework_review_status(fw), "passed")
            review2 = research.review_framework_semantics(fw)
            self.assertEqual(review2["status"], "failed")
            self.assertEqual(review2["failed_courses"], ["课一"])
        fw["review"] = review2
        self.assertEqual(research.framework_review_status(fw), "failed")
        # 大纲改动后旧审查失效
        fw["courses"][0]["goal"] = "改成别的目标"
        self.assertEqual(research.framework_review_status(fw), "stale")
        # 无快照的存量大纲
        no_snap = {"topic": "t", "courses": fw["courses"]}
        self.assertEqual(research.framework_review_status(no_snap), "unanchored")

    def test_outline_prep_refuses_failed_review_course(self) -> None:
        # 点单闸的判定路径:framework_review_status=failed 时 job_runner 侧拒绝点单。
        from app.agent.research import framework_review_status
        from app.core.trace import digest

        courses: list[dict[str, Any]] = [{"id": "c1", "title": "课一", "prereqs": []}]
        fw: dict[str, Any] = {"topic": "t", "courses": courses,
              "review": {"status": "failed", "content_hash": digest(courses),
                         "courses": {"课一": {"verdict": "unsupported",
                                              "issues": ["原文撑不起"]}}}}
        self.assertEqual(framework_review_status(fw), "failed")
        fw["courses"][0]["goal"] = "改目标"
        self.assertEqual(framework_review_status(fw), "stale")

    def test_order_gate_per_course_verdict_not_book_wide(self) -> None:
        # 点单闸按单课 verdict 判定(E2E 缺陷修复):整书 failed 时 supported 单课
        # 放行、unsupported 单课拒——一刀切曾把 6/7 门 supported 课全部堵死。
        from app.agent.research import framework_review_status
        from app.core.trace import digest

        courses: list[dict[str, Any]] = [
            {"id": "c1", "title": "好课", "prereqs": []},
            {"id": "c2", "title": "坏课", "prereqs": []},
        ]
        fw: dict[str, Any] = {"topic": "t", "courses": courses,
              "review": {"status": "failed", "content_hash": digest(courses),
                         "courses": {"好课": {"verdict": "supported", "issues": []},
                                     "坏课": {"verdict": "unsupported",
                                              "issues": ["原文撑不起"]}}}}
        self.assertEqual(framework_review_status(fw), "failed")
        # 模拟 job_runner 闸逻辑
        for title, expect_block in (("好课", False), ("坏课", True)):
            entry = fw["review"]["courses"].get(title) or {}
            verdict = str(entry.get("verdict", ""))
            blocked = (framework_review_status(fw) == "failed"
                       and verdict == "unsupported")
            self.assertEqual(blocked, expect_block, title)



if __name__ == "__main__":
    unittest.main()
