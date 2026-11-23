"""CSL 课件校验(M1)—— 备课 agent 循环的终止判据,亦是人工审校前的机械闸。

设计(见 docs/P2执行计划 M1、设计方案 §二 四道闸之「校验器兜底」):
- 进程内可调(M2 循环用),CLI 只是薄壳(scripts/validate_csl.py)
- 反馈可执行:报「第X页 …」而非 traceback——模型看得懂才改得动
- 分级:error = 不过(Pydantic/结构/讲到什么亮什么的机械可查项);
  warning = 提示人工审校(不影响循环终止)
- 音频缺失是 warning 而非 error:生成期(M2)本来就没音频,M3 才回填
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.csl import (
    CalloutBlock,
    CodeBlock,
    CourseV2,
    DiagramBlock,
    FlashcardsBlock,
    ParagraphBlock,
    QuizBlock,
    TableBlock,
)
from app.services.evidence import course_evidence_report

# 这些页型的内容生来就该逐步揭示(模板定义),零 fragment = 整页一次性亮,
# 违背「讲到什么亮什么」——机械可查,故为 error。封面/图解除外。
_REVEAL_KINDS = {"formula", "code", "table", "duo", "quiz"}


def _parse_errors(e: ValidationError) -> list[str]:
    """把 Pydantic 报错翻成可定位反馈(v1 页 / v2 节;下标 → 1 起算序号)。"""
    out: list[str] = []
    unit_word = {"pages": "页", "sections": "节"}
    for err in e.errors():
        loc = err["loc"]
        unit_no = None
        if len(loc) >= 2 and loc[0] in unit_word and isinstance(loc[1], int):
            unit_no = loc[1] + 1  # Pydantic 下标从 0,序号从 1
        field = ".".join(str(x) for x in loc)
        where = f"第{unit_no}{unit_word.get(str(loc[0]) if loc else '', '页')} " if unit_no else ""
        out.append(f"{where}字段 {field}: {err['msg']}")
    return out


def _meta_checks(
    id_: str,
    title: str,
    scenario: str,
    source_notes: list[str],
    depends_on: list[Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    """课件级 + 先修依赖:v1/v2 同一套规则。"""
    if not id_.strip():
        errors.append("课件 id 为空(课表/播放器路由都靠它)")
    if not title.strip():
        errors.append("课件 title 为空")
    if not source_notes:
        errors.append("meta.source_notes 为空——课表靠它把笔记归入「在学的」,必须写回笔记路径")
    if scenario in ("自学", "复习") and not depends_on and id_ != "harness-01":
        # 学习路线鼓励链上,但 root/独立课合法 → 只提示不挡
        warnings.append("meta.depends_on 为空——若是独立入门课可忽略,否则建议链上先修")
    dep_ids = [d.id for d in depends_on]
    if id_ in dep_ids:
        errors.append("meta.depends_on 引用了课件自身(自依赖没有意义)")
    if len(dep_ids) != len(set(dep_ids)):
        errors.append("meta.depends_on 有重复项,只保留第一个并删掉多余")
    for dep in depends_on:
        if not dep.reason or not dep.reason.strip():
            warnings.append(
                f"meta.depends_on: 先修 {dep.id} 缺 reason——「为什么先学它」建议补一句"
            )
        if not (settings.courses_dir / f"{dep.id}.csl.json").exists():
            warnings.append(
                f"meta.depends_on: 先修课件 {dep.id} 不存在(尚未备课?先修仅作展示,不影响上课)"
            )


def validate_course(
    d: dict[str, Any], *, check_model_support: bool = True,
) -> dict[str, Any]:
    """校验一份课件(dict 形态)。顶层 version==2 走书页规则,否则页/句规则。

    返回 {"ok": bool, "errors": [...], "warnings": [...], "summary": str}。
    JSON/结构错也归入 errors(不抛)——循环里模型拿到的永远是可读反馈。
    """
    if isinstance(d, dict) and d.get("version") == 2:
        return _validate_v2(d, check_model_support=check_model_support)
    return _validate_v1(d)


def _validate_v1(d: dict[str, Any]) -> dict[str, Any]:
    """v1 已退役(P6 flip 后全量为 v2):只指路,不再做规则校验。"""
    return {
        "ok": False,
        "errors": [
            "v1 页/句课件已退役——请产出 v2 书页格式(节→块);"
            "存量迁移用 scripts/migrate_csl_v2.py"
        ],
        "warnings": [],
        "summary": "v1 已退役",
    }


# ---------- v2 书页规则(P6·M1) ----------

_BLOCK_NAMES = {
    "p": "段落",
    "diagram": "示意图",
    "code": "代码",
    "table": "表格",
    "callout": "提示框",
    "quiz": "测验",
    "flashcards": "闪卡",
}


def _validate_v2(d: dict[str, Any], *, check_model_support: bool = True) -> dict[str, Any]:
    try:
        course = CourseV2.model_validate(d)
    except ValidationError as e:
        return {
            "ok": False,
            "errors": _parse_errors(e),
            "warnings": [],
            "summary": f"结构错误 {len(e.errors())} 处,未进入规则校验",
        }

    errors: list[str] = []
    warnings: list[str] = []

    _meta_checks(
        course.id, course.title, course.scenario,
        course.meta.source_notes, course.meta.depends_on, errors, warnings,
    )
    evidence_ids = [e.id for e in course.meta.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("meta.evidence 证据 id 重复,每条要点必须有唯一身份")
    source_id_list = [s.id if s.id is not None else i
                      for i, s in enumerate(course.meta.sources, 1)]
    if any(sid <= 0 for sid in source_id_list) or len(source_id_list) != len(set(source_id_list)):
        errors.append("meta.sources 来源 id 必须是唯一的正整数(旧课无 id 时使用列表序号)")
    source_ids = set(source_id_list)
    for evidence in course.meta.evidence:
        if not evidence.id.strip() or not evidence.point.strip():
            errors.append("meta.evidence 的 id 与 point 不可为空")
        if evidence.source_id is not None and evidence.source_id not in source_ids:
            errors.append(f"证据 {evidence.id} 的来源[{evidence.source_id}]不在 meta.sources 中")
        if evidence.quote_status == "matched" and not (
            evidence.source_id is not None and evidence.quote
            and evidence.source_hash and evidence.context
            and evidence.quote in evidence.context
            and evidence.quote_start is not None and evidence.quote_start >= 0
            and evidence.quote_end == evidence.quote_start + len(evidence.quote)
        ):
            errors.append(f"证据 {evidence.id} 的摘录定位信息不完整或不一致")
    report = course_evidence_report(
        course.model_dump(), check_model_support=check_model_support,
    )
    errors.extend(report["errors"])
    if course.meta.evidence:
        missing = sum(e.quote_status != "matched" for e in course.meta.evidence)
        pending = sum(e.support != "supported" for e in course.meta.evidence)
        if missing or pending:
            warnings.append(f"证据待审: {missing} 条无可验证原文定位,"
                            f"{pending} 条未获模型完整支撑判定;模型判定仍需人工校准")
        unlinked = report["total_blocks"] - report["linked_blocks"]
        warnings.append(f"正文语义未审,另有 {unlinked} 块未关联原文证据"
                        "(申报 exemplary 的示例块除外);可用 audit_evidence.py 审阅")
    if not course.sections:
        errors.append("sections 为空——至少一节")

    n_quiz = 0
    quiz_ids: set[str] = set()
    for i, sec in enumerate(course.sections, 1):
        where = f"第{i}节 {sec.id}"
        if not sec.id.strip():
            errors.append(f"第{i}节: 节 id 为空")
        if not sec.heading.strip():
            errors.append(f"{where}: 标题为空")
        if not sec.blocks:
            errors.append(f"{where}: 零块——至少一段文字或一个块")

        for bi, b in enumerate(sec.blocks, 1):
            bwhere = f"{where} 第{bi}块({b.type}/{_BLOCK_NAMES[b.type]})"
            # G1 溯源硬闸:事实块必须挂证据;示例/类比/练习须写作时申报 exemplary。
            if isinstance(b, (ParagraphBlock, DiagramBlock, CodeBlock, TableBlock, CalloutBlock)) \
                    and not b.evidence_ids and not b.exemplary:
                errors.append(
                    f"{bwhere}: 事实块未关联证据且未申报 exemplary——知识点必须可溯源;"
                    '示例/类比/练习请显式写 "exemplary": true'
                )
            if isinstance(b, ParagraphBlock):
                if not b.text.strip():
                    errors.append(f"{bwhere}: 段落文本为空")
            elif isinstance(b, DiagramBlock):
                if not b.code.strip():
                    errors.append(f"{bwhere}: mermaid 源码为空")
            elif isinstance(b, CodeBlock):
                if not b.code.strip():
                    errors.append(f"{bwhere}: 代码为空")
            elif isinstance(b, TableBlock):
                if not b.rows:
                    errors.append(f"{bwhere}: 表格零行")
                if b.header and any(not str(h).strip() for h in b.header):
                    errors.append(f"{bwhere}: 表头有空单元格")
            elif isinstance(b, CalloutBlock):
                if not b.text.strip():
                    errors.append(f"{bwhere}: 提示框文本为空")
            elif isinstance(b, QuizBlock):
                n_quiz += 1
                if not b.id.strip():
                    errors.append(f"{bwhere}: 测验 id 为空(批改/复习按它定位)")
                elif b.id in quiz_ids:
                    errors.append(f"{bwhere}: 测验 id「{b.id}」重复(全课唯一)")
                quiz_ids.add(b.id)
                if not b.question.strip():
                    errors.append(f"{bwhere}: 问题是空文本")
                if not b.pass_rule:
                    warnings.append(f"{bwhere}: 缺 pass_rule,批改只能凭感觉(建议写通过标准)")
            elif isinstance(b, FlashcardsBlock):
                fronts: set[str] = set()
                for ci, card in enumerate(b.cards, 1):
                    if not card.front.strip() or not card.back.strip():
                        errors.append(f"{bwhere} 第{ci}张: front/back 有空文本")
                    if card.front in fronts:
                        errors.append(f"{bwhere} 第{ci}张: front 与同节重复")
                    fronts.add(card.front)

    if course.scenario in ("自学", "复习") and n_quiz < 3:
        # 配额是写作指引而非文件有效性:存量课(如 function-calling-stability 只有 2
        # 个检查点)是合法 v1 内容;备课循环在生成期盯住这条(prompt+人审)
        warnings.append(
            f"全课只有 {n_quiz} 个测验块——建议 ≥3 节带复述检查点(存量课可豁免)"
        )

    ok = not errors
    n_blocks = sum(len(s.blocks) for s in course.sections)
    summary = (
        f"{course.id}: {len(course.sections)} 节 / {n_blocks} 块 / {n_quiz} 测验 "
        f"/ {course.scenario}(v2 书页)"
        if ok
        else f"error {len(errors)} 处 · warning {len(warnings)} 处,按上面逐条修"
    )
    return {"ok": ok, "errors": errors, "warnings": warnings, "summary": summary}


def validate_course_json(text: str) -> dict[str, Any]:
    """从 JSON 文本校验(文件读回场景);JSON 本身坏了也归入 errors。"""
    import json

    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "errors": [f"JSON 解析失败: {e.msg}(第 {e.lineno} 行第 {e.colno} 列)"],
            "warnings": [],
            "summary": "JSON 本身不合法,先修格式",
        }
    return validate_course(d)
