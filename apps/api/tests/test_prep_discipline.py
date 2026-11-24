"""T1 备课纪律包(2026-11-24):测验反出千/先例后抽象挂载 + validator 来源标号闸,全离线。"""

from __future__ import annotations

import unittest
from typing import Any

from app.agent import prep
from app.core.prompts import QUIZ_FAIRNESS_RULE
from app.services.csl_validator import validate_course


def v2_course(
    sources: list[dict[str, Any]],
    blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """最小合法 v2 课(示例块走 exemplary 申报,不搭证据链);来源标号闸的载体。"""
    return {
        "id": "t1-discipline", "title": "备课纪律包", "version": 2, "scenario": "自学",
        "meta": {"source_notes": ["fixture.md"], "sources": sources},
        "sections": [{"id": "s1", "heading": "节一", "blocks": blocks or [
            {"type": "p", "text": "普通正文,不含来源标号。", "exemplary": True},
        ]}],
    }


def six_sources() -> list[dict[str, Any]]:
    return [{"title": f"资料{i}", "url": f"https://example.org/{i}"} for i in range(1, 7)]


def source_errors(result: dict[str, Any]) -> list[str]:
    return [e for e in result["errors"] if "来源清单" in e]


class PrepPromptDisciplineTests(unittest.TestCase):
    """T1.1/T1.2:两条 prompt 纪律进 _SHARED_STYLE,全量/续写两套 prompt 都拿到。"""

    def test_quiz_fairness_rule_mounted_into_full_prompt(self) -> None:
        prompt = prep.PREP_PROMPT.format(
            position="", material="", existing="", shared_style=prep._SHARED_STYLE,
        )
        self.assertIn(QUIZ_FAIRNESS_RULE, prompt)

    def test_resume_prompt_receives_same_shared_style(self) -> None:
        self.assertIn("{shared_style}", prep.RESUME_PROMPT)
        self.assertIn(QUIZ_FAIRNESS_RULE, prep._SHARED_STYLE)

    def test_quiz_fairness_covers_three_leak_channels(self) -> None:
        for needle in ("长度尽量接近", "随机分布", "格式差异"):
            self.assertIn(needle, QUIZ_FAIRNESS_RULE)

    def test_shared_style_has_example_first_discipline(self) -> None:
        idx = prep._SHARED_STYLE.find("先例后抽象")
        self.assertGreater(idx, -1)
        # 纪律行同时说明与 exemplary 申报机制的兼容关系(例子走申报,不引入无据事实)
        self.assertIn("exemplary", prep._SHARED_STYLE[idx : idx + 120])


class SourceRefGateTests(unittest.TestCase):
    """T1.3:正文「源[N]」必须落在 meta.sources 内;无来源清单的课跳过(老课兼容)。

    全库扫描(2026-11-24)10 门课 76 处标号零违例,故闸落 error 级(硬闸)。
    """

    def test_dangling_number_over_count_is_error(self) -> None:
        blocks = [
            {"type": "p", "text": "该机制由上游调度,细节见源[9]。", "exemplary": True},
            {"type": "callout", "kind": "tip",
             "text": "关键结论见源[9]和[10]。", "exemplary": True},
        ]
        r = validate_course(v2_course(six_sources(), blocks))
        errs = source_errors(r)
        self.assertEqual(len(errs), 3, r["errors"])  # 簇内两个标号(9,10)逐个判
        self.assertIn("第1块", errs[0])
        self.assertIn("「源[9]」超出来源清单(共6条)", errs[0])
        self.assertIn("删除该引用或补来源", errs[0])
        self.assertIn("第2块", errs[1])
        self.assertIn("「源[10]」超出来源清单(共6条)", errs[2])

    def test_within_range_and_all_prose_surfaces_pass(self) -> None:
        blocks: list[dict[str, Any]] = [
            {"type": "p", "text": "细节见源[2],对比见源[5]和[6]。", "exemplary": True},
            {"type": "table", "header": ["做法"], "rows": [["见源[3]"]],
             "caption": "对比表 源[4]", "exemplary": True},
            {"type": "quiz", "id": "s1-cp", "question": "复述源[2]讲的两步是什么?",
             "pass_rule": "答出两步名称与顺序"},
        ]
        r = validate_course(v2_course(six_sources(), blocks))
        self.assertEqual(source_errors(r), [], r["errors"])
        self.assertTrue(r["ok"])

    def test_no_sources_skips_gate(self) -> None:
        blocks = [{"type": "p", "text": "复习课没有来源清单,标号源[9]不拦。", "exemplary": True}]
        r = validate_course(v2_course([], blocks))
        self.assertEqual(source_errors(r), [], r["errors"])
        self.assertTrue(r["ok"])

    def test_explicit_source_ids_are_the_identity(self) -> None:
        # id 才是来源身份(阅读器锚点 src-{id}):标号必须命中 id 集,不只是 ≤ 数量
        sources = [{"id": 2, "title": "a", "url": "https://example.org/2"},
                   {"id": 5, "title": "b", "url": "https://example.org/5"}]
        blocks = [{"type": "p", "text": "命中 id 的源[5]没问题;源[1]数量内却无此身份。",
                   "exemplary": True}]
        r = validate_course(v2_course(sources, blocks))
        errs = source_errors(r)
        self.assertEqual(len(errs), 1, r["errors"])
        self.assertIn("「源[1]」不在来源清单(共2条)中", errs[0])


if __name__ == "__main__":
    unittest.main()
