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

from app.schemas.csl import (
    CodeContent,
    Course,
    FormulaContent,
    QuizContent,
    TableContent,
)

# 这些页型的内容生来就该逐步揭示(模板定义),零 fragment = 整页一次性亮,
# 违背「讲到什么亮什么」——机械可查,故为 error。封面/图解除外。
_REVEAL_KINDS = {"formula", "code", "table", "duo", "quiz"}


def _parse_errors(e: ValidationError) -> list[str]:
    """把 Pydantic 报错翻成「第N页 …」可定位反馈(loc 里的 pages 下标 → 页号)。"""
    out: list[str] = []
    for err in e.errors():
        loc = err["loc"]
        page_no = None
        if len(loc) >= 2 and loc[0] == "pages" and isinstance(loc[1], int):
            page_no = loc[1] + 1  # Pydantic 下标从 0,页号从 1
        field = ".".join(str(x) for x in loc)
        where = f"第{page_no}页 " if page_no else ""
        out.append(f"{where}字段 {field}: {err['msg']}")
    return out


def validate_course(d: dict[str, Any]) -> dict[str, Any]:
    """校验一份课件( dict 形态,来自 write_csl 落盘后读回或文件解析)。

    返回 {"ok": bool, "errors": [...], "warnings": [...], "summary": str}。
    JSON/结构错也归入 errors(不抛)——循环里模型拿到的永远是可读反馈。
    """
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

    # ---- 课件级 ----
    if not course.id.strip():
        errors.append("课件 id 为空(课表/播放器路由都靠它)")
    if not course.title.strip():
        errors.append("课件 title 为空")
    if not course.meta.source_notes:
        errors.append("meta.source_notes 为空——课表靠它把笔记归入「在学的」,必须写回笔记路径")
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
                    f"{where}: fragment({f.effect},{f.target}) 挂在第 {f.with_sentence} 句,"
                    f"但讲稿只有 {n} 句"
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
