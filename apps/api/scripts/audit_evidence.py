"""只读审阅课件的原文证据链。默认不调用模型、不写课件或学习库。

--model 对实际课件块另做语义审查(收费),不沿用原料要点的评分。
--reviews 导入具名人工审查,哈希绑定当前块和证据,内容变化后旧标签失效。
退出码 0=全部块已人工确认,1=结构错误/明确不支持,2=仍有未审或仅模型判定。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.trace import digest
from app.services.csl_validator import validate_course
from app.services.evidence import course_evidence_report
from app.services.evidence_review import review_claims


def audit(
    course: dict[str, Any], *, use_model: bool = False,
    human_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validation = validate_course(course)
    if not validation["ok"]:
        return {"course_id": course.get("id"), "errors": validation["errors"], "blocks": [],
                "semantic_status": "unreviewed"}
    report = course_evidence_report(course)
    blocks = report["blocks"]
    if use_model:
        review = review_claims([
            {"id": b["id"], "text": b["text"], "evidence": b["evidence"]}
            for b in blocks if b["evidence"]
        ])
        by_id = {item["id"]: item for item in review["items"]}
        for block in blocks:
            if item := by_id.get(block["id"]):
                block.update(model_support=item["verdict"], model_reason=item["reason"])
        report["model_review"] = review
    ids = [r.get("id") for r in human_reviews or []]
    if len(set(ids)) != len(ids):
        report["errors"].append("人工审查存在重复块 id")
    known = {b["id"] for b in blocks}
    for rid in ids:
        if rid not in known:
            report["errors"].append(f"人工审查指向不存在的块:{rid}")
    by_id = {r.get("id"): r for r in human_reviews or []}
    for block in blocks:
        fingerprint = digest({"text": block["text"], "evidence": block["evidence"]})
        block["review_template"] = {
            "id": block["id"], "reviewer": "", "input_hash": fingerprint,
            "verdict": "unreviewed", "reason": "",
        }
        if label := by_id.get(block["id"]):
            if (label.get("input_hash") != fingerprint
                or not isinstance(label.get("reviewer"), str) or not label["reviewer"].strip()
                or label.get("verdict") not in ("supported", "unsupported", "not_applicable")
                or not isinstance(label.get("reason"), str) or not label["reason"].strip()):
                report["errors"].append(f"{block['id']} 人工标签缺项或已因内容变化失效")
            else:
                block.update(support=label["verdict"], reason=label["reason"],
                             reviewer=label["reviewer"])
    report["semantic_status"] = (
        "human_reviewed" if blocks and all(b["support"] in ("supported", "not_applicable")
                                           for b in blocks) else "unreviewed"
    )
    return report


def exit_code(report: dict[str, Any]) -> int:
    if report["errors"] or any(
        b.get("support") == "unsupported" or b.get("model_support") == "unsupported"
        for b in report["blocks"]
    ):
        return 1
    return 0 if report["semantic_status"] == "human_reviewed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("course", type=Path)
    parser.add_argument("--model", action="store_true", help="调用当前配置模型审查课件块")
    parser.add_argument("--reviews", type=Path, help="具名人工标签 JSON 数组")
    args = parser.parse_args()
    try:
        course = json.loads(args.course.read_text(encoding="utf-8"))
        reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else []
        if not isinstance(course, dict) or not isinstance(reviews, list) or any(
            not isinstance(r, dict) for r in reviews
        ):
            raise ValueError("课件须为对象,人工标签须为对象数组")
        report = audit(course, use_model=args.model, human_reviews=reviews)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"输入无效:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
