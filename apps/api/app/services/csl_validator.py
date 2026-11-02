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
    CodeContent,
    Course,
    CourseV2,
    DiagramBlock,
    FlashcardsBlock,
    FormulaContent,
    ParagraphBlock,
    QuizBlock,
    QuizContent,
    TableBlock,
    TableContent,
)

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


def validate_course(d: dict[str, Any]) -> dict[str, Any]:
    """校验一份课件(dict 形态)。顶层 version==2 走书页规则,否则页/句规则。

    返回 {"ok": bool, "errors": [...], "warnings": [...], "summary": str}。
    JSON/结构错也归入 errors(不抛)——循环里模型拿到的永远是可读反馈。
    """
    if isinstance(d, dict) and d.get("version") == 2:
        return _validate_v2(d)
    return _validate_v1(d)


def _validate_v1(d: dict[str, Any]) -> dict[str, Any]:
    try:
        course = Course.model_validate(d)
    except ValidationError as e:
        return {
            "ok": False,
            "errors": _parse_errors(e),
            "warnings": [],
            "summary": f"结构错误 {len(e.errors())} 处,未进入规则校验",
        }

    errors: list[str] = []
    warnings: list[str] = []

    # ---- 课件级 + 先修依赖(v1/v2 同一套) ----
    _meta_checks(
        course.id, course.title, course.scenario,
        course.meta.source_notes, course.meta.depends_on, errors, warnings,
    )
    if course.scenario in ("自学", "复习") and not any(p.checkpoint for p in course.pages):
        errors.append(f"场景为「{course.scenario}」但没有任何复述检查点")

    seen_ids: set[str] = set()
    for i, page in enumerate(course.pages, 1):
        where = f"第{i}页 {page.id}"
        if page.id in seen_ids:
            errors.append(f"{where}: 页 id 重复(播放器按 id 定位)")
        seen_ids.add(page.id)

        # ---- 讲稿 ----
        n = len(page.script)
        if n == 0:
            errors.append(f"{where}: 讲稿为空")
        for si, s in enumerate(page.script, 1):
            if not s.text.strip():
                errors.append(f"{where}: 第{si}句讲稿是空文本")
            if not s.audio:
                warnings.append(f"{where}: 第{si}句无音频路径(TTS 编译前属正常)")

        # ---- 动画:越界 + 讲到什么亮什么 ----
        for f in page.fragments:
            if not 0 <= f.with_sentence < n:
                errors.append(
                    f"{where}: fragment({f.effect},{f.target}) 的 with_sentence={f.with_sentence} "
                    f"越界——0 起算,该页讲稿 {n} 句,合法范围 0~{n - 1}"
                )
        if page.content.kind in _REVEAL_KINDS and not page.fragments:
            errors.append(
                f"{where}: {page.content.kind} 页型零 fragment——内容生来逐步揭示,"
                f"整页一次亮违背「讲到什么亮什么」;应给每个揭示单元挂 with_sentence"
            )

        # ---- 各页型内容非空(Pydantic 只查类型,不查空列表;isinstance 才能收窄 union)----
        c = page.content
        if isinstance(c, FormulaContent) and not c.items:
            errors.append(f"{where}: formula 页 items 为空")
        if isinstance(c, CodeContent) and not c.lines:
            errors.append(f"{where}: code 页 lines 为空")
        if isinstance(c, TableContent) and not c.rows:
            errors.append(f"{where}: table 页 rows 为空")
        if isinstance(c, QuizContent) and not c.questions:
            errors.append(f"{where}: quiz 页 questions 为空")

        # ---- 检查点质量提示 ----
        if page.checkpoint and not page.checkpoint.pass_rule:
            warnings.append(f"{where}: 检查点缺 pass_rule,批改只能凭感觉(建议写通过标准)")

    ok = not errors
    cp = sum(1 for p in course.pages if p.checkpoint)
    sents = sum(len(p.script) for p in course.pages)
    summary = (
        f"{course.id}: {len(course.pages)} 页 / {sents} 句 / {cp} 检查点 / {course.scenario}"
        if ok
        else f"error {len(errors)} 处 · warning {len(warnings)} 处,按上面逐条修"
    )
    return {"ok": ok, "errors": errors, "warnings": warnings, "summary": summary}


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


def _validate_v2(d: dict[str, Any]) -> dict[str, Any]:
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
