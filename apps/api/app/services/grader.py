"""复述批改:单次 LLM 调用(无工具,不进循环)。

输入: 复述文本 + 该节内容 + 检查点的 pass_rule(T1 埋好的通过标准)
输出: 百分制 score + pass/fail(score≥70 过;<70 需重学或问 AI 老师后再复述)
      + gaps 错因列表(T2 错因结构化:机器可读,落 learning_grades 供复习卡/答疑消费)
      + 🎯 精准版对照(无论分数都给,pass 时作为「更完整的说法」→ 落笔记)。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.learning_store import record_result
from app.core.llm import get_llm_client
from app.core.prompts import GRADE_OUTPUT_SPEC, parse_json_reply
from app.core.trace import current_run, observed, run_context, trace_grade, update_run

GRADE_PROMPT = (
    """你是学习督导,批改学员对刚学内容的复述,并给出百分制评分。

本节讲过的内容:
{page_content}

通过标准(出题人写的):
{pass_rule}

学员的复述:
{answer}

"""
    + GRADE_OUTPUT_SPEC  # 产出规范(含标尺)在 core/prompts.py——后续批改排版改版动那里
)

# 同步批改场景:中转间歇 502/坏 JSON 常见,最多试 3 次(1.5s 递增退避)
_ATTEMPTS = 3
# 产出规范的上限:最多 4 条缺失点(T2 错因结构化,防模型超发刷屏)
_MAX_GAPS = 4


def _normalize_gaps(value: Any) -> list[str]:
    """错因结构化(T2):把模型输出的 gaps 归一成非空字符串列表。

    旧格式输出无 gaps / 字段不是数组 / 含空白项一律容忍——视为空列表,
    批改主流程(score/verdict/comment)不受影响;超上限截断。
    """
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for g in value:
        text = str(g).strip()
        if text:
            items.append(text)
    return items[:_MAX_GAPS]


def _locate_v2(d: dict[str, Any], page_id: str) -> tuple[dict[str, Any], str]:
    """v2 书页:按节 id 或 quiz 块 id 定位。返回 (定位到的 quiz 块, 节内容文本)。"""
    for sec in d.get("sections", []):
        quizzes = [b for b in sec.get("blocks", []) if b.get("type") == "quiz"]
        hit = next((q for q in quizzes if q.get("id") == page_id), None)
        if hit is None and sec.get("id") == page_id and quizzes:
            hit = quizzes[0]  # 按节 id 来的:取该节第一个测验
        if hit is None:
            continue
        parts = [f"## {sec.get('heading', '')}"]
        for b in sec.get("blocks", []):
            bt = b.get("type")
            if bt in ("p", "callout"):
                parts.append(str(b.get("text", "")))
            elif bt == "code":
                parts.append(f"```\n{b.get('code', '')}\n```")
            elif bt == "table":
                rows = [b.get("header", []), *b.get("rows", [])]
                parts.extend("|".join(map(str, row)) for row in rows)
        return hit, "\n".join(parts)
    msg = f"节/测验不存在: {page_id}"
    raise KeyError(msg)


@observed("grade")
def grade_recitation(
    course_id: str,
    page_id: str,
    answer: str,
    *,
    tutored: bool = False,
    source: str = "user",
) -> dict[str, Any]:
    """批改一次复述,返回 {score, verdict, comment, precise}。

    tutored=学员已在答疑里学过一轮:判分以「核心概念说清」为主,保底 70。
    """
    p: Path = settings.courses_dir / f"{course_id}.csl.json"
    d: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    if d.get("version") == 2:
        cp, page_content = _locate_v2(d, page_id)
    else:
        page = next((x for x in d["pages"] if x["id"] == page_id), None)
        if page is None:
            msg = f"页不存在: {page_id}"
            raise KeyError(msg)
        cp = page.get("checkpoint")
        if not cp:
            msg = f"该页没有检查点: {page_id}"
            raise KeyError(msg)
        page_content = "\n".join(f"- {s['text']}" for s in page["script"])

    client = get_llm_client()
    prompt = GRADE_PROMPT.format(
        page_content=page_content,
        pass_rule=cp.get("pass_rule") or "核心概念说清即可",
        answer=answer,
    )
    run_context(prompt=prompt, tools=[], parameters={"max_tokens": 16384})
    update_run(answer=answer, tutored=tutored, source=source)
    t0 = time.perf_counter()
    resp = None
    last_err: Exception | None = None
    for attempt in range(_ATTEMPTS):
        update_run(turns=attempt + 1)
        # 中转间歇 502/坏 JSON 常见:学员坐在弹层里等,一次坏响应就 502 太脆
        try:
            resp = client.messages.create(
                model=settings.llm_model,
                # 思考模型的思考块也吃 max_tokens 预算:小值被思考烧光→零文本
                # (5.3 思考更肥:8192 档是按 4.6 校的,全站切 5.3 后同提 16384)
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
            )
            update_run(usage={
                "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
            })
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    if resp is None:
        msg = f"批改 LLM 三次均失败: {last_err}"
        raise RuntimeError(msg)
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise RuntimeError(
            f"模型零文本输出(stop={resp.stop_reason}, "
            f"blocks={[b.type for b in resp.content]})——多为思考块吃尽预算"
        )
    result = parse_json_reply(text)  # 围栏/前置废话已容忍;坏 JSON/非对象 → None
    if result is None:
        msg = "批改返回格式异常: 不是可解析的 JSON 对象"
        raise RuntimeError(msg)
    # 错因结构化(T2):gaps 平行提取(缺哪几条),旧格式无此字段 → 空列表
    result["gaps"] = _normalize_gaps(result.get("gaps"))
    # 百分制判分:score≥70 过,<70 需重学/答疑后再复述;tutored 保底 70
    try:
        score = max(0, min(100, int(result.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    raw_score = score
    if tutored:
        score = max(score, 70)  # 已在答疑里学过一轮:核心说清即过
    result["score"] = score
    result["verdict"] = "pass" if score >= 70 else "fail"
    result["raw_score"] = raw_score
    result["tutored"] = tutored
    run = current_run()
    # Runtime 先保存结果;观测或裁判失败不能抹掉已交付的学习状态。
    record_result(course_id, page_id, answer, result, source=source,
                  run_id=run.id if run else None)
    trace_grade(
        course_id=course_id,
        page_id=page_id,
        answer=answer,
        verdict=result["verdict"],
        comment=result.get("comment", ""),
        elapsed_s=time.perf_counter() - t0,
        score=score,
        precise=str(result.get("precise", "")),
        raw_score=raw_score,
        tutored=tutored,
        source=source,
    )
    return result
