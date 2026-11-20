"""离线固定用例评测:只读指定输出,不调用模型、不导入学习状态。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.research import validate_framework, validate_material
from app.core.trace import digest
from app.services.citation_guard import verify_citations
from app.services.csl_validator import validate_course

_CASES = Path(__file__).resolve().parent.parent / "evals" / "cases.json"


def rule_errors(case: dict[str, Any], output: dict[str, Any]) -> list[str]:
    if not isinstance(output, dict):
        return ["输出必须为对象"]
    try:
        return _rules(case, output)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return [f"输出结构无效: {type(exc).__name__}"]


def _rules(case: dict[str, Any], output: dict[str, Any]) -> list[str]:
    agent, expect = case["agent"], case["expect"]
    errors = []
    if agent == "tutor":
        answer = str(output.get("answer", ""))
        if not answer.strip():
            errors.append("没有回答")
        errors += verify_citations(answer, case["input"]["course_index"])
        for term in expect.get("required_terms", []):
            if term not in answer:
                errors.append(f"缺少关键表述: {term}")
        for term in expect.get("forbidden_terms", []):
            if term in answer:
                errors.append(f"出现禁止表述: {term}")
        for call in output.get("tool_calls", []):
            if call.get("name") not in ("web_search", "read_notes"):
                errors.append(f"工具越权: {call.get('name')}")
    elif agent == "research":
        errors += validate_framework(output)
        if any(
            any(word in str(c.get("goal", "")) for word in ("了解", "熟悉"))
            for c in output.get("courses", [])
        ):
            errors.append("学习目标不可验证")
    elif agent == "material":
        errors += validate_material(output, set(case["input"]["fetched"]))
    elif agent == "prep":
        errors += validate_course(output)["errors"]
        quizzes = [
            b
            for s in output.get("sections", [])
            for b in s.get("blocks", [])
            if b.get("type") == "quiz"
        ]
        if len(quizzes) < expect["min_quizzes"] or any(not q.get("pass_rule") for q in quizzes):
            errors.append("测验不足或缺少明确通过标准")
    elif agent == "grade":
        raw, score = output.get("raw_score"), output.get("score")
        if (
            not isinstance(raw, int)
            or not expect["raw_score_range"][0] <= raw <= expect["raw_score_range"][1]
        ):
            errors.append("原始分不在人工标注范围")
        effective = max(raw, 70) if isinstance(raw, int) and case["input"].get("tutored") else raw
        if score != effective or not isinstance(score, int) or not 0 <= score <= 100:
            errors.append("应用分与辅导保底规则不一致")
        if output.get("verdict") != expect["verdict"]:
            errors.append("判定与预期不一致")
    else:
        errors.append(f"未知 agent: {agent}")
    return errors


def evaluate(cases: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {r["case_id"]: r for r in records}
    items = []
    for case in cases:
        record = by_id.get(case["id"])
        if not record:
            items.append(
                {
                    "case_id": case["id"],
                    "rules": "failed",
                    "errors": ["缺少输出"],
                    "semantic": "unreviewed",
                }
            )
            continue
        output = record.get("output", {})
        errors = rule_errors(case, output)
        versions = record.get("versions", {})
        for key in ("model", "prompt_hash", "context_hash", "code_hash"):
            if not versions.get(key):
                errors.append(f"缺少版本字段: {key}")
        if versions.get("input_hash") != digest(case["input"]):
            errors.append("输入哈希不匹配固定用例")
        review = record.get("human_review", {})
        labels = review.get("checks", {})
        valid_review = (
            bool(review.get("reviewer"))
            and review.get("output_hash") == digest(output)
            and all(isinstance(labels.get(k), bool) for k in case["rubric"])
        )
        semantic = (
            ("passed" if all(labels[k] for k in case["rubric"]) else "failed")
            if valid_review
            else "unreviewed"
        )
        items.append(
            {
                "case_id": case["id"],
                "rules": "failed" if errors else "passed",
                "errors": errors,
                "semantic": semantic,
                "versions": versions,
                "review_template": {
                    "reviewer": "",
                    "output_hash": digest(output),
                    "checks": dict.fromkeys(case["rubric"]),
                },
            }
        )
    return {
        "dataset": "classroom-eval-v1",
        "dataset_hash": digest(cases),
        "cases": items,
        "rule_passed": sum(r["rules"] == "passed" for r in items),
        "semantic_passed": sum(r["semantic"] == "passed" for r in items),
        "unreviewed": sum(r["semantic"] == "unreviewed" for r in items),
        "total": len(cases),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--outputs", type=Path, help="逐行 JSON:{case_id,output,versions,human_review?}"
    )
    ap.add_argument("--self-check", action="store_true", help="验证参考答案和反例,不代表模型成绩")
    args = ap.parse_args()
    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    if args.self_check:
        failures = [
            c["id"]
            for c in cases
            if rule_errors(c, c["reference"]) or not rule_errors(c, c["counterexample"])
        ]
        print(
            json.dumps(
                {
                    "mode": "checker-self-check",
                    "total": len(cases),
                    "failures": failures,
                    "model_evaluated": False,
                },
                ensure_ascii=False,
            )
        )
        return bool(failures)
    if args.outputs is None:
        ap.error("必须指定 --outputs 或 --self-check")
    try:
        records = [
            json.loads(line)
            for line in args.outputs.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        ids = [r["case_id"] for r in records]
        if len(set(ids)) != len(ids) or set(ids) - {c["id"] for c in cases}:
            raise ValueError("case_id 重复或不在固定用例中")
        report = evaluate(cases, records)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"输入无效: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["rule_passed"] != report["total"] or any(
        c["semantic"] == "failed" for c in report["cases"]
    ):
        return 1
    return 2 if report["unreviewed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
