"""原文定位、语义审查、课件引用和人工标签失效的离线回归。"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agent import prep, research
from app.core.config import settings
from app.schemas.csl import CourseV2
from app.services import evidence_review
from app.services.csl_validator import validate_course
from app.services.evidence import (
    fetch_error,
    locate_material,
    material_evidence,
    normalized_body,
    text_hash,
)
from scripts.audit_evidence import audit, exit_code

QUOTE = "Only incremental changes are appended; existing history is preserved."


def material_fixture() -> tuple[dict[str, Any], dict[str, str]]:
    sources: list[dict[str, Any]] = [
        {"id": i, "title": f"资料{i}", "url": f"https://example.org/{i}"} for i in (2, 5, 9)
    ]
    material: dict[str, Any] = {"topic": "状态管理", "subtopic": "增量更新", "sources": sources,
                "groups": [{"heading": "增量更新", "points": [
                    {"text": "只追加增量,保留历史。", "source_id": sources[i % 3]["id"],
                     "quote": QUOTE} for i in range(8)
                ]}]}
    pages = {str(s["url"]): f"[资料标题 | {s['url']}]\nContext before. {QUOTE}\nContext after."
             for s in sources}
    return material, pages


def text_reply(data: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(data))],
                           stop_reason="end_turn", usage=SimpleNamespace())


class EvidenceChainTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for key in ("data_dir", "courses_dir", "traces_dir", "kb_dir"):
            directory = Path(tmp.name) / key
            directory.mkdir()
            patcher = patch.object(settings, key, directory)
            patcher.start()
            self.addCleanup(patcher.stop)
        for module in (research, prep, evidence_review):
            guard = patch.object(module, "get_llm_client",
                                 side_effect=AssertionError("禁止未模拟模型调用"))
            guard.start()
            self.addCleanup(guard.stop)
        tty = patch.object(sys.stdin, "isatty", return_value=False)
        tty.start()
        self.addCleanup(tty.stop)
        self.raw, self.pages = material_fixture()
        self.material, errors = locate_material(self.raw, self.pages)
        self.assertEqual(errors, [])

    def course(self) -> dict[str, Any]:
        return {"id": "test", "title": "增量更新", "version": 2, "scenario": "自学",
                "meta": {"source_notes": ["fixture.json"],
                         "sources": copy.deepcopy(self.raw["sources"]),
                         "evidence": material_evidence(self.material)},
                "sections": [{"id": "s1", "heading": "增量",
                              "blocks": [{"type": "p", "text": "只追加变化,保留历史。",
                                          "evidence_ids": ["g1p1"]}]}]}

    def test_locates_real_body_and_preserves_source_identity_and_context(self) -> None:
        item = self.material["evidence"][0]
        body = normalized_body(self.pages[self.raw["sources"][0]["url"]])
        self.assertEqual(item["quote_status"], "matched")
        self.assertEqual(body[item["quote_start"]:item["quote_end"]], QUOTE)
        self.assertEqual(item["source_id"], 2)
        self.assertEqual(item["source_hash"], text_hash(body))
        self.assertEqual(item["support"], "unreviewed")
        self.assertIn("Context before", item["context"])

    def test_normalized_body_only_removes_a_standalone_fetch_header(self) -> None:
        quote = "A quotation near a Markdown link [reference](https://example.org/page)."
        self.assertEqual(
            normalized_body(f"[Page title | https://example.org/page]\n{quote}"), quote
        )
        # One-line extractors are common; the metadata parser must not mistake
        # a Markdown link's closing bracket for the end of the page header.
        self.assertEqual(normalized_body(f"[Page title | https://example.org/page] {quote}"),
                         f"[Page title | https://example.org/page] {quote}")

    def test_fabricated_quote_and_tool_header_cannot_be_evidence(self) -> None:
        for quote in ("This statement was never in the original document.",
                      "资料标题 | https://example.org/2"):
            candidate = copy.deepcopy(self.raw)
            candidate["groups"][0]["points"][0]["quote"] = quote
            _, errors = locate_material(candidate, self.pages)
            self.assertTrue(any("g1p1" in error for error in errors))

    def test_markdown_emphasis_does_not_break_verbatim_quote_matching(self) -> None:
        self.assertEqual(normalized_body("cost = unit_price * count; source_id"),
                         "cost = unit_price * count; source_id")
        candidate = copy.deepcopy(self.raw)
        candidate["groups"][0]["points"][0]["quote"] = (
            "Only incremental changes are appended; existing history is preserved."
        )
        pages = dict(self.pages)
        url = self.raw["sources"][0]["url"]
        pages[url] = pages[url].replace(
            "Only incremental changes are appended; existing history is preserved.",
            "**Only incremental changes are appended; existing history is preserved.**",
        )
        _, errors = locate_material(candidate, pages)
        self.assertFalse(errors)
        candidate["groups"][0]["points"][0]["quote"] = (
            "Only **incremental changes** are appended; existing history is preserved."
        )
        _, errors = locate_material(candidate, self.pages)
        self.assertFalse(errors)

    def test_cache_snapshot_tampering_rejected_and_changed_point_loses_old_review(self) -> None:
        self.material["evidence"][0].update(support="supported", reviewer="model:old")
        changed = copy.deepcopy(self.material)
        changed["source_snapshots"][self.raw["sources"][0]["url"]]["text"] += "tampered"
        with self.assertRaisesRegex(ValueError, "指纹"):
            material_evidence(changed)
        changed = copy.deepcopy(self.material)
        changed["groups"][0]["points"][0]["text"] = "全量覆盖历史。"
        item = material_evidence(changed)[0]
        self.assertEqual(item["support"], "unreviewed")
        self.assertIsNone(item["reviewer"])

    def test_recovered_snapshot_with_markdown_links_keeps_real_quote(self) -> None:
        raw = copy.deepcopy(self.raw)
        raw["groups"][0]["points"][0]["quote"] = QUOTE
        url = raw["sources"][0]["url"]
        pages = {key: value for key, value in self.pages.items()}
        pages[url] = (
            f"[Source | {url}]\nPrefix [linked text](https://example.org/linked). {QUOTE}"
        )
        material, errors = locate_material(raw, pages)
        self.assertEqual(errors, [])
        self.assertEqual(material_evidence(material)[0]["quote_status"], "matched")

    def test_legacy_material_cannot_self_declare_verified(self) -> None:
        self.raw["evidence"] = [{"id": "g1p1", "support": "supported"}]
        item = material_evidence(self.raw)[0]
        self.assertEqual((item["quote_status"], item["support"]), ("missing", "unreviewed"))

    def test_error_page_is_not_successful_fetch(self) -> None:
        for body in ("(抓取失败:timeout)", "", "[Error | https://example.org]\n403 Forbidden"):
            self.assertIsNotNone(fetch_error(body))
            _, errors = locate_material(self.raw, {url: body for url in self.pages})
            self.assertTrue(errors)

    def test_new_cache_rechecks_quotes_and_duplicate_source_ids_rejected(self) -> None:
        self.assertEqual(research.validate_material(self.material), [])
        self.material["groups"][0]["points"][0]["quote"] = "invented quote long enough"
        self.assertTrue(research.validate_material(self.material))
        self.raw["sources"][1]["id"] = 2
        self.assertTrue(any("唯一" in e for e in research.validate_material(self.raw)))

    def test_prep_persists_chain_and_rejects_unknown_or_unsupported_references(self) -> None:
        _, dispatch, _ = prep._make_tools(
            self.raw["sources"], evidence_items=material_evidence(self.material),
        )
        plan = [{"id": f"s{i}", "heading": f"节{i}", "has_quiz": False, "covers": ""}
                for i in range(1, 4)]
        dispatch["submit_plan"]({"sections": plan})
        dispatch["init_course"]({"id": "test", "title": "增量", "scenario": "自学",
                                 "source_notes": ["fixture.json"]})
        section = self.course()["sections"][0]
        bad = copy.deepcopy(section)
        bad["blocks"][0]["evidence_ids"] = ["invented"]
        self.assertIn("未写入", dispatch["write_section"]({"section": bad}))
        path = settings.courses_dir / "test.csl.json"
        self.assertEqual(json.loads(path.read_text())["sections"], [])
        dispatch["write_section"]({"section": section})
        course = json.loads(path.read_text())
        parsed = CourseV2.model_validate(course)
        self.assertEqual(parsed.sections[0].blocks[0].evidence_ids, ["g1p1"])
        self.assertEqual(parsed.meta.sources[0].id, 2)
        self.assertNotIn("source_snapshots", course["meta"])
        course["meta"]["evidence"][0]["support"] = "unsupported"
        path.write_text(json.dumps(course))
        self.assertIn("不受原文支持", dispatch["write_section"]({"section": section}))

    def test_old_course_stays_valid_and_duplicate_evidence_or_dangling_refs_fail(self) -> None:
        old = self.course()
        del old["meta"]["evidence"]
        del old["sections"][0]["blocks"][0]["evidence_ids"]
        self.assertTrue(validate_course(old)["ok"])
        duplicate = self.course()
        duplicate["meta"]["evidence"].append(duplicate["meta"]["evidence"][0])
        self.assertFalse(validate_course(duplicate)["ok"])
        dangling = self.course()
        dangling["sections"][0]["blocks"][0]["evidence_ids"] = ["missing"]
        self.assertFalse(validate_course(dangling)["ok"])

    def test_ambiguous_source_identity_and_unlocated_evidence_identity_are_rejected(self) -> None:
        for invalid_id in (2, 0, -1):
            course = self.course()
            course["meta"]["sources"][1]["id"] = invalid_id
            self.assertFalse(validate_course(course)["ok"])
        course = self.course()
        course["meta"]["evidence"][0]["source_id"] = None
        self.assertFalse(validate_course(course)["ok"])
        course = self.course()
        course["meta"]["evidence"][0]["id"] = " "
        self.assertFalse(validate_course(course)["ok"])

    def test_resumed_legacy_course_recovers_material_source_ids_by_url(self) -> None:
        _, dispatch, state = prep._make_tools(
            self.raw["sources"], evidence_items=material_evidence(self.material),
        )
        plan = [{"id": f"s{i}", "heading": f"节{i}", "has_quiz": False, "covers": ""}
                for i in range(1, 4)]
        state.update(course_id="test", plan=plan)
        course = self.course()
        course["meta"].pop("evidence")
        for source in course["meta"]["sources"]:
            source.pop("id")
        path = settings.courses_dir / "test.csl.json"
        path.write_text(json.dumps(course))
        dispatch["write_section"]({"section": self.course()["sections"][0]})
        restored = json.loads(path.read_text())
        self.assertEqual([s["id"] for s in restored["meta"]["sources"]], [2, 5, 9])
        self.assertTrue(validate_course(restored)["ok"])

    def test_course_review_does_not_inherit_material_success_and_uses_actual_block(self) -> None:
        course = self.course()
        course["meta"]["evidence"][0]["support"] = "supported"
        course["sections"][0]["blocks"][0]["text"] = "全量覆盖历史。"
        self.assertEqual(exit_code(audit(course)), 2)
        result = {"reviewer": "model:fixture", "items": [
            {"id": "s1:1", "verdict": "unsupported", "reason": "与保留历史相反"},
        ]}
        with patch("scripts.audit_evidence.review_claims", return_value=result) as judge:
            report = audit(course, use_model=True)
        self.assertEqual(exit_code(report), 1)
        self.assertIn("全量覆盖历史", judge.call_args.args[0][0]["text"])
        self.assertEqual(report["blocks"][0]["support"], "unreviewed")

    def test_human_labels_are_bound_to_actual_block_and_evidence(self) -> None:
        course = self.course()
        template = audit(course)["blocks"][0]["review_template"]
        label = dict(template, reviewer="reviewer", verdict="supported", reason="原文逐项支持")
        self.assertEqual(exit_code(audit(course, human_reviews=[label])), 0)
        course["sections"][0]["blocks"][0]["text"] = "改后的内容"
        self.assertEqual(exit_code(audit(course, human_reviews=[label])), 1)

    def test_table_caption_is_reviewed_and_changes_invalidate_human_label(self) -> None:
        course = self.course()
        course["sections"][0]["blocks"] = [{
            "type": "table", "header": ["策略", "行为"], "rows": [["增量", "追加"]],
            "caption": "已有历史始终保留", "evidence_ids": ["g1p1"],
        }]
        report = audit(course)
        self.assertIn("已有历史始终保留", report["blocks"][0]["text"])
        label = dict(report["blocks"][0]["review_template"], reviewer="reviewer",
                     verdict="supported", reason="支持表格与图注")
        self.assertEqual(exit_code(audit(course, human_reviews=[label])), 0)
        course["sections"][0]["blocks"][0]["caption"] = "已有历史全部删除"
        self.assertEqual(exit_code(audit(course, human_reviews=[label])), 1)

    def test_semantic_judge_timeout_or_duplicate_output_remains_unreviewed(self) -> None:
        claims = [{"id": "a", "text": "断言"}, {"id": "b", "text": "另一断言"}]
        client = MagicMock()
        client.with_options.return_value = client
        outputs: list[dict[str, Any]] = [
            {"items": [{"id": "a", "verdict": "supported", "reason": "支持"}] * 2},
            {"items": []},
        ]
        for output in outputs:
            client.messages.create.return_value = text_reply(output)
            with patch.object(evidence_review, "get_llm_client", return_value=client):
                result = evidence_review.review_claims(claims)
            self.assertTrue(all(i["verdict"] == "unreviewed" for i in result["items"]))
        client.messages.create.side_effect = TimeoutError
        with patch.object(evidence_review, "get_llm_client", return_value=client):
            result = evidence_review.review_claims(claims)
        self.assertEqual(result["error"], "TimeoutError")

    def test_review_checkpoint_recovers_only_completed_claims_after_interrupt(self) -> None:
        claims = [{"id": str(i), "text": f"断言{i}"} for i in range(5)]
        client = MagicMock()
        client.with_options.return_value = client
        completed = {"items": [{"id": str(i), "verdict": "supported", "reason": "支持"}
                               for i in range(4)]}
        client.messages.create.side_effect = [text_reply(completed), KeyboardInterrupt()]
        saved: list[dict[str, Any]] = []
        with patch.object(evidence_review, "get_llm_client", return_value=client):
            with self.assertRaises(KeyboardInterrupt):
                evidence_review.review_claims(claims, checkpoint=lambda r: saved.append(
                    copy.deepcopy(r)))
        self.assertEqual(len(saved[-1]["items"]), 4)
        client.messages.create.side_effect = None
        client.messages.create.reset_mock()
        client.messages.create.return_value = text_reply({"items": [
            {"id": "4", "verdict": "supported", "reason": "支持"}]})
        with patch.object(evidence_review, "get_llm_client", return_value=client):
            result = evidence_review.review_claims(claims, previous=saved[-1])
        self.assertEqual(client.messages.create.call_count, 1)
        payload = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertNotIn('"id": "0"', payload)
        self.assertTrue(all(i["verdict"] == "supported" for i in result["items"]))

    def test_review_reuse_invalidates_changed_claim_model_and_prompt(self) -> None:
        claims = [{"id": "a", "text": "原断言"}, {"id": "b", "text": "保留断言"}]
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.return_value = text_reply({"items": [
            {"id": cid, "verdict": "supported", "reason": "支持"} for cid in ("a", "b")]})
        with patch.object(evidence_review, "get_llm_client", return_value=client):
            previous = evidence_review.review_claims(claims)
            claims[0]["text"] = "改变断言"
            client.messages.create.reset_mock()
            evidence_review.review_claims(claims, previous=previous)
            payload = client.messages.create.call_args.kwargs["messages"][0]["content"]
            self.assertIn('"id": "a"', payload)
            self.assertNotIn('"id": "b"', payload)
            for key in ("reviewer", "prompt_hash"):
                invalid = {**previous, key: "changed"}
                client.messages.create.reset_mock()
                evidence_review.review_claims(claims, previous=invalid)
                payload = client.messages.create.call_args.kwargs["messages"][0]["content"]
                self.assertIn('"id": "b"', payload)

    def test_research_collects_actual_pages_rejects_forged_quote_and_records_review(self) -> None:
        calls = []
        for i, url in enumerate(self.pages):
            block = MagicMock()
            block.type, block.name = "tool_use", "fetch_page"
            block.id, block.input = str(i), {"url": url}
            block.model_dump.return_value = {"type": "tool_use", "name": "fetch_page",
                                            "id": str(i), "input": {"url": url}}
            calls.append(block)
        bad = copy.deepcopy(self.raw)
        bad["groups"][0]["points"][0]["quote"] = "invented quote long enough"
        bad["evidence"] = [{"id": "fake", "support": "supported"}]
        client = MagicMock()
        client.with_options.return_value = client
        client.messages.create.side_effect = [
            SimpleNamespace(content=calls, stop_reason="tool_use", usage=SimpleNamespace()),
            text_reply(bad), text_reply(self.raw),
        ]
        reviewed = {"reviewer": "model:fixture", "items": [
            {"id": f"g1p{i}", "verdict": "partial", "reason": "待核对适用条件"}
            for i in range(1, 9)
        ]}
        with (patch.object(research, "get_llm_client", return_value=client),
              patch.object(research, "_execute",
                           side_effect=lambda name, args: self.pages[args["url"]]),
              patch.object(research, "review_claims", return_value=reviewed),
              patch.object(research, "MAX_TURNS", 4)):
            result = research._loop("prompt", research.validate_material, "状态", "material:增量",
                                    source="test")
        self.assertEqual(client.messages.create.call_args.kwargs["max_tokens"], 32768)
        self.assertEqual(result["evidence_version"], 1)
        self.assertEqual(result["evidence"][0]["support"], "partial")
        self.assertEqual(len(result["source_snapshots"]), 3)
        self.assertIn("quote 不在", str(client.messages.create.call_args.kwargs["messages"]))
        self.assertEqual(material_evidence(result)[0]["quote_status"], "matched")


if __name__ == "__main__":
    unittest.main()
