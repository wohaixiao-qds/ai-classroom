"""临时 SQLite/JSONL/课件与模型替身,不触碰真实学习记录。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from collections.abc import AsyncGenerator, Iterator
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent import prep, research, tutor
from app.core import catalog_store, learning_store, lessons, memory, progress, trace
from app.core.config import settings
from app.routes import chat
from app.routes import eval as eval_routes
from app.schemas.chat import ChatRequest
from app.services import catalog, grader, mastery, self_eval


class EvalTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key in ("data_dir", "courses_dir", "traces_dir"):
            directory = Path(tmp.name) / key
            directory.mkdir()
            p = patch.object(settings, key, directory)
            p.start()
            self.addCleanup(p.stop)
        db = patch.object(progress, "_DB", settings.data_dir / "classroom.db")
        db.start()
        self.addCleanup(db.stop)
        for module in (memory, mastery, catalog_store):
            store = patch.object(module, "_DB", settings.data_dir / "classroom.db")
            store.start()
            self.addCleanup(store.stop)
        # 生成器延迟执行,任何漏出测试替身的模型路径都必须立即失败。
        for module in (tutor, prep, research, grader, self_eval):
            guard = patch.object(module, "get_llm_client",
                                 side_effect=AssertionError("禁止未模拟的模型调用"))
            guard.start()
            self.addCleanup(guard.stop)
        course = {
            "id": "course",
            "title": "临时课程",
            "version": 2,
            "sections": [
                {
                    "id": "s1",
                    "heading": "增量更新：合并变化",
                    "blocks": [
                        {"type": "p", "text": "状态更新只附加变化", "exemplary": True},
                        {
                            "type": "quiz",
                            "id": "q1",
                            "question": "更新什么",
                            "pass_rule": "只追加变化",
                        },
                    ],
                }
            ],
        }
        (settings.courses_dir / "course.csl.json").write_text(json.dumps(course))

    def legacy(self, rows: list[dict[str, Any]]) -> None:
        (settings.traces_dir / "grade.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )

    def test_completion_survives_600_unrelated_rows_and_trace_removal(self) -> None:
        self.legacy(
            [
                {
                    "course_id": "course",
                    "page_id": "q1",
                    "verdict": "pass",
                    "answer": "变化",
                    "ts": "2026-01-01T00:00:00",
                },
                *[{"course_id": "other", "page_id": "q", "verdict": "fail"} for _ in range(600)],
                {
                    "course_id": "course",
                    "page_id": "q1",
                    "verdict": "fail",
                    "answer": "最新",
                    "ts": "2026-02-01T00:00:00",
                },
            ]
        )
        progress.mark_done("course")
        self.assertTrue(progress.completion("course").ready)
        self.assertIn("已学完", catalog.student_course_map())
        self.assertIn("增量更新", catalog.mastered_concepts())
        (settings.traces_dir / "grade.jsonl").unlink()
        self.assertTrue(progress.completion("course").ready)
        self.assertEqual(learning_store.last_result("course", "q1")["answer"], "最新")

    def test_test_results_excluded_and_run_id_idempotent(self) -> None:
        self.legacy([{"course_id": "test", "page_id": "q", "verdict": "pass", "source": "test"}])
        learning_store.record_result("course", "q1", "模拟", {"verdict": "pass"}, source="test")
        self.assertEqual(learning_store.passed_checkpoints(), {})
        for _ in range(2):
            learning_store.record_result("course", "q1", "变化", {"verdict": "pass"}, run_id="same")
        with learning_store._conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM learning_grades").fetchone()[0], 1)

    def test_migration_recovers_mastery_pass_without_logs(self) -> None:
        with sqlite3.connect(settings.data_dir / "classroom.db") as c:
            c.execute("CREATE TABLE checkpoint_mastery(course_id, page_id, history, updated_at)")
            c.execute(
                "INSERT INTO checkpoint_mastery VALUES(?,?,?,?)",
                ("course", "q1", '[{"ts":"2026-01-01","verdict":"pass"}]', "2026-01-01"),
            )
        self.assertEqual(learning_store.passed_checkpoints(), {"course": {"q1"}})
        self.assertEqual(learning_store.last_result("course", "q1")["recovered_from"], "mastery")

    def test_grader_records_raw_score_and_test_has_no_learning_effect(self) -> None:
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"score":30,"comment":"漏了变化"}')],
            usage=SimpleNamespace(input_tokens=80, output_tokens=20),
            stop_reason="end_turn",
        )
        client = MagicMock()
        client.messages.create.return_value = response
        with patch.object(grader, "get_llm_client", return_value=client):
            result = grader.grade_recitation("course", "q1", "答案", tutored=True, source="test")
        self.assertEqual((result["score"], result["raw_score"]), (70, 30))
        self.assertEqual(learning_store.passed_checkpoints(), {})
        row = trace.read_traces("grade.jsonl")[0]
        self.assertEqual((row["source"], row["raw_score"], row["turns"]), ("test", 30, 1))
        self.assertEqual(row["status"], "succeeded")

    def test_lifecycle_merge_and_delayed_assessment_preserve_order(self) -> None:
        first = trace.TraceRun("tutor", question="一")
        first.context(system="规范", messages=[{"role": "user", "content": "问题"}])
        first.update(turns=2)
        first.finish("failed", answer="部分", error="超时")
        second = trace.TraceRun("tutor", question="二")
        second.finish("succeeded", answer="完成")
        first.assess({"verdict": "skipped", "skip_reason": "incomplete_execution"})
        rows = trace.read_traces("tutor.jsonl")
        self.assertEqual([r["question"] for r in rows], ["二", "一"])
        self.assertEqual(rows[1]["turns"], 2)
        self.assertTrue(rows[1]["versions"]["context_hash"])
        self.assertTrue((settings.data_dir / "eval-context" / f"{first.id}.json").exists())

    def test_exception_and_cancellation_are_terminal(self) -> None:
        for exc, status in ((RuntimeError("broken"), "failed"), (SystemExit(1), "cancelled")):

            @trace.observed("prep")
            def broken(error: BaseException = exc) -> None:
                trace.update_run(turns=3)
                raise error

            with self.assertRaises(type(exc)):
                broken()
            self.assertEqual(trace.read_traces("prep.jsonl")[0]["status"], status)
        self.assertEqual(len(trace.read_traces("prep.jsonl")), 2)

    def test_both_batch_model_errors_are_recorded(self) -> None:
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = TimeoutError("timeout")
        # 重试退避真睡(20/40/60/80s):测试只验证"最终抛出",patch 掉等待。
        with patch.object(research, "_sleep_backoff", lambda _s: None):
            with patch.object(research, "get_llm_client", return_value=client):
                with self.assertRaises(TimeoutError):
                    research._loop("prompt", lambda d, fetched: [], "topic", "framework")
        with patch.object(prep, "get_llm_client", return_value=client):
            with self.assertRaises(TimeoutError):
                prep.run_prep({"topic": "topic", "subtopic": "sub", "groups": []})
        for stage in ("research", "prep"):
            row = trace.read_traces(f"{stage}.jsonl")[0]
            # research 侧重试守卫耗尽 MAX_TURNS 才抛(turns=16);prep 侧无 retry,首轮抛(turns=1)。
            expected_turns = research.MAX_TURNS if stage == "research" else 1
            self.assertEqual((row["status"], row["turns"]), ("failed", expected_turns))
            self.assertIn("context_hash", row["versions"])

    def test_legacy_unknown_and_abandoned_process_interrupted(self) -> None:
        (settings.traces_dir / "tutor.jsonl").write_text(
            'bad\n[]\nnull\n{"answer":"旧答案","grounded":true}\n'
        )
        trace.TraceRun("tutor")
        with patch.object(trace, "_alive", return_value=False):
            rows = trace.read_traces("tutor.jsonl")
        self.assertEqual(rows[0]["status"], "interrupted")
        self.assertEqual(rows[1]["status"], "unknown")
        self.assertNotIn("grounded", rows[1])

    def chat_patches(self) -> ExitStack:
        stack = ExitStack()
        for name, value in (
            ("student_course_map", ""),
            ("mastered_concepts", []),
            ("ensure_session", "mock-session"),
            ("session_state_note", None),
        ):
            stack.enter_context(patch.object(chat, name, return_value=value))
        return stack

    def test_failed_sse_persists_partial_without_judge(self) -> None:
        def broken(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
            yield {"type": "iteration", "turns": 1}
            yield {"type": "delta", "text": "半截答案"}
            raise TimeoutError("模型超时")

        app = FastAPI()
        app.include_router(chat.router)
        with (
            self.chat_patches(),
            patch.object(chat, "run_tutor", side_effect=broken),
            patch.object(chat, "evaluate_answer") as judge,
            TestClient(app) as client,
        ):
            response = client.post("/api/v1/chat", json={"course_id": "course", "question": "问题"})
        self.assertIn("event: error", response.text)
        row = trace.read_traces("tutor.jsonl")[0]
        self.assertEqual((row["status"], row["answer"]), ("failed", "半截答案"))
        judge.assert_not_called()

    def test_closed_stream_records_cancel(self) -> None:
        with self.chat_patches():
            response = chat.chat(ChatRequest(course_id="course", question="问题"))

        async def close_stream() -> None:
            iterator = cast(AsyncGenerator[str, None], response.body_iterator)
            await anext(iterator)
            await iterator.aclose()

        asyncio.run(close_stream())
        self.assertEqual(trace.read_traces("tutor.jsonl")[0]["status"], "cancelled")

    def test_risky_answers_cannot_skip_judge_by_citing_or_searching(self) -> None:
        for calls, violations in (
            ([], ["第99节不存在"]),
            ([{"name": "web_search", "error": "failed"}], []),
        ):
            with patch.object(
                self_eval, "_judge", return_value={"verdict": "unsupported"}
            ) as judge:
                ev = self_eval.evaluate_answer(
                    "问题", "课件第99节", calls, "材料", guard_violations=violations
                )
            self.assertEqual(ev["verdict"], "unsupported")
            judge.assert_called_once()

    def test_successful_notes_are_evidence_failed_search_is_not(self) -> None:
        calls = [
            {"name": "read_notes", "result": "笔记依据"},
            {"name": "web_search", "error": "失败", "result": "错误页"},
        ]
        with patch.object(self_eval, "_judge", return_value={"verdict": "partial"}) as judge:
            self_eval.evaluate_answer("问题", "长" * 201, calls, "课件", context="旧问题")
        evidence = judge.call_args.args[2]
        self.assertIn("笔记依据", evidence)
        self.assertIn("旧问题", evidence)
        self.assertNotIn("错误页", evidence)

    def test_sampling_and_failed_judge_have_explicit_reasons(self) -> None:
        with patch.object(self_eval, "_judge", return_value={"verdict": "uncertain"}):
            a = self_eval.evaluate_answer("小问题", "短答", [], "材料")
            b = self_eval.evaluate_answer("小问题", "短答", [], "材料")
        self.assertEqual(a["verdict"], b["verdict"])
        self.assertEqual(a.get("skip_reason"), b.get("skip_reason"))
        with patch.object(self_eval, "_judge", side_effect=TimeoutError):
            ev = self_eval.evaluate_answer("问题", "长" * 201, [], "材料")
        self.assertEqual(ev["skip_reason"], "judge_error")

    def test_pending_lessons_need_review_including_legacy(self) -> None:
        (settings.data_dir / "agent_lessons.md").write_text(
            "# 教训\n<!-- 注释 -->\n- [待审] 旧候选\n- 人工规则\n", encoding="utf-8"
        )
        lessons.propose_lesson("run", "新候选", {"question": "问题"}, source="user")
        lessons.propose_lesson("test", "模拟候选", {}, source="test")
        self.assertEqual(len(lessons.list_lessons()), 2)
        self.assertEqual(lessons.approved_lessons(), "- 人工规则")
        lessons.review_lesson("run", "approved", "审核修正后")
        self.assertIn("审核修正后", lessons.approved_lessons())
        lessons.review_lesson("run", "rejected")
        self.assertNotIn("审核修正后", lessons.approved_lessons())

    def test_metrics_denominators_and_source_filters_all_stages(self) -> None:
        run = trace.TraceRun("tutor")
        trace.trace_tutor(
            course_id="course",
            page_id="s1",
            question="问题",
            answer="课件第99节",
            tool_calls=[{"name": "web_search", "error": "失败"}],
            elapsed_s=1,
            guard_violations=["不存在"],
            run=run,
        )
        run.assess({"version": trace.EVAL_VERSION, "verdict": "unsupported"})
        for stage in ("tutor", "grade", "prep", "research"):
            test = trace.TraceRun(stage, source="test")
            test.finish("failed", verdict="fail")
        result = eval_routes.summary()
        self.assertEqual(result["asks"], 1)
        self.assertEqual(result["quality"]["support_rate_pct"], 0)
        self.assertEqual(result["quality"]["coverage_pct"], 100)
        self.assertEqual(result["quality"]["valid_citation_pct"], 0)
        self.assertEqual(result["verdict_counts"], {})
        self.assertEqual(result["stages"]["research"]["total"], 0)
        self.assertEqual(eval_routes.summary(True)["stages"]["research"]["total"], 1)

    def test_empty_rates_null_but_grade_only_visible(self) -> None:
        trace.trace_grade(course_id="course", page_id="q1", verdict="fail", source="user")
        result = eval_routes.summary()
        self.assertIsNone(result["quality"]["support_rate_pct"])
        self.assertIsNone(result["quality"]["coverage_pct"])
        self.assertEqual(result["verdict_counts"], {"fail": 1})

    def test_repeats_separate_courses_unknown_context_not_comparable(self) -> None:
        for cid in ("a", "a", "b"):
            trace.trace_tutor(
                course_id=cid,
                page_id="s1",
                question="同问？",
                answer="答",
                tool_calls=[],
                elapsed_s=1,
            )
        groups = eval_routes.repeats()["repeats"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 2)
        self.assertFalse(groups[0]["comparable"])

    def test_offline_checker_missing_outputs_and_unreviewed_are_not_passes(self) -> None:
        from scripts.eval_agent import _CASES, evaluate, rule_errors

        cases = json.loads(_CASES.read_text(encoding="utf-8"))
        for case in cases:
            self.assertEqual(rule_errors(case, case["reference"]), [])
            self.assertTrue(rule_errors(case, case["counterexample"]))
        missing = evaluate(cases, [])
        self.assertEqual(missing["rule_passed"], 0)
        records = [
            {
                "case_id": c["id"],
                "output": c["reference"],
                "versions": {
                    "model": "fixture",
                    "prompt_hash": "fixture",
                    "context_hash": "fixture",
                    "code_hash": "fixture",
                    "input_hash": trace.digest(c["input"]),
                },
            }
            for c in cases
        ]
        unreviewed = evaluate(cases, records)
        self.assertEqual(unreviewed["rule_passed"], len(cases))
        self.assertEqual(unreviewed["semantic_passed"], 0)
        self.assertEqual(unreviewed["unreviewed"], len(cases))

    def test_execution_is_saved_before_judge_and_judge_failure_keeps_it(self) -> None:
        app = FastAPI()
        app.include_router(chat.router)

        def judge(*args: Any, **kwargs: Any) -> dict[str, Any]:
            row = trace.read_traces("tutor.jsonl")[0]
            self.assertEqual(row["status"], "succeeded")
            self.assertEqual(row["answer"], "真实答案")
            raise TimeoutError("裁判超时")

        events = [{"type": "final", "answer": "真实答案", "tool_calls": []}]
        with (
            self.chat_patches(),
            patch.object(chat, "run_tutor", return_value=iter(events)),
            patch.object(chat, "evaluate_answer", side_effect=judge),
            patch("builtins.print"),
            TestClient(app) as client,
        ):
            response = client.post("/api/v1/chat", json={"course_id": "course", "question": "问题"})
        self.assertIn("event: done", response.text)
        rows = trace.read_traces("tutor.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "succeeded")
        self.assertEqual(rows[0]["self_eval"]["skip_reason"], "assessment_error")
        self.assertEqual(eval_routes.summary()["quality"]["skip_reasons"], {"assessment_error": 1})

    def test_migration_merges_lifecycle_rows_by_run_id(self) -> None:
        rec = {
            "run_id": "one-attempt",
            "course_id": "course",
            "page_id": "q1",
            "verdict": "pass",
            "answer": "变化",
        }
        self.legacy([{**rec, "event": "progress"}, {**rec, "event": "finished"}])
        self.assertEqual(len(learning_store.grade_history("course")), 1)

    def test_grade_test_request_does_not_schedule_mastery(self) -> None:
        from app.services import mastery

        app = FastAPI()
        app.include_router(chat.router)
        with (
            patch.object(chat, "grade_recitation", return_value={"verdict": "pass"}) as grade,
            patch.object(mastery, "record_grade") as schedule,
            TestClient(app) as client,
        ):
            response = client.post(
                "/api/v1/grade",
                json={
                    "course_id": "course",
                    "page_id": "q1",
                    "answer": "模拟回答",
                    "source": "test",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(grade.call_args.kwargs["source"], "test")
        schedule.assert_not_called()

    def test_late_exception_overrides_provisional_success_and_soft_failure_is_kept(self) -> None:
        @trace.observed("prep")
        def late_error() -> None:
            trace.trace_prep(ok=True)
            raise OSError("收尾失败")

        with self.assertRaises(OSError):
            late_error()
        self.assertEqual(trace.read_traces("prep.jsonl")[0]["status"], "failed")

        @trace.observed("prep")
        def soft_fail() -> dict[str, Any]:
            trace.trace_prep(ok=False, error="预算耗尽")
            return {"ok": False}

        soft_fail()
        self.assertEqual(trace.read_traces("prep.jsonl")[0]["status"], "failed")

    def test_asgi_disconnect_is_recorded_while_model_thread_still_waits(self) -> None:
        import threading

        from starlette.types import Message, Scope

        entered, release = threading.Event(), threading.Event()

        def waiting(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
            entered.set()
            if not release.wait(timeout=3):
                raise TimeoutError("测试线程未释放")
            yield {"type": "delta", "text": "迟来的答案"}
            yield {"type": "final", "answer": "迟来的答案", "tool_calls": []}

        async def serve() -> None:
            async def receive() -> Message:
                while not entered.is_set():
                    await asyncio.sleep(0.001)
                return {"type": "http.disconnect"}

            async def send(message: Message) -> None:
                pass

            scope: Scope = {"type": "http", "asgi": {"spec_version": "2.3"}}
            task = asyncio.create_task(response(scope, receive, send))
            try:
                for _ in range(100):
                    rows = trace.read_traces("tutor.jsonl")
                    if rows and rows[0]["status"] == "cancelled":
                        break
                    await asyncio.sleep(0.005)
                self.assertEqual(rows[0]["status"], "cancelled")
                self.assertFalse(release.is_set())
            finally:
                release.set()
                await asyncio.wait_for(task, timeout=2)

        # SSE 延迟消费:替身必须一直覆盖到响应执行结束,不能只覆盖构造响应。
        with self.chat_patches(), patch.object(chat, "run_tutor", side_effect=waiting):
            response = chat.chat(ChatRequest(course_id="course", question="问题"))
            asyncio.run(serve())
        self.assertEqual(len(trace.read_traces("tutor.jsonl")), 1)
        self.assertEqual(trace.read_traces("tutor.jsonl")[0]["status"], "cancelled")

    def test_cost_estimate_uses_model_iterations_and_excludes_failed_test_runs(self) -> None:
        from app.services.estimate import _stage_stats
        for status, source, turns in (("succeeded", "user", 2), ("failed", "user", 90),
                                      ("succeeded", "test", 90)):
            run = trace.TraceRun("prep", source=source)
            run.update(ok=True, turns=turns, tool_calls=[{"name": "one"}] * 8)
            run.finish(status)
        stats = _stage_stats("prep.jsonl")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["calls"], 2)  # type: ignore[index]
        self.assertEqual(stats["n"], 1)  # type: ignore[index]
