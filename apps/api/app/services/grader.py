"""复述批改:单次 LLM 调用(无工具,不进循环)。

输入: 复述文本 + 该节内容 + 检查点的 pass_rule(T1 埋好的通过标准)
输出: 百分制 score + pass/fail(score≥70 过;<70 需重学或问 AI 老师后再复述)
      + 🎯 精准版对照(无论分数都给,pass 时作为「更完整的说法」→ 落笔记)。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.trace import trace_grade

GRADE_PROMPT = """你是学习督导,批改学员对刚学内容的复述,并给出百分制评分。

本节讲过的内容:
{page_content}

通过标准(出题人写的):
{pass_rule}

学员的复述:
{answer}

按 JSON 输出(不要其他内容):
{{"score": 0~100 的整数,
  "comment": "一两句点评:对在哪/缺在哪",
  "precise": "标准表述——分数再高也给,pass 时作为「更完整的说法」"}}

评分标尺:
- 85~100:核心关系/步骤全对,细节小瑕疵不扣
- 70~84:核心说清,个别小漏不扣
- 40~69:方向对但漏了关键一半,或踩了标准里点名的坑
- 0~39:说反了/完全没说到点子上

判定尺度(服务端按 score≥70 判过):
- 70 以上:核心说清即过,措辞小瑕疵不扣
- 70 以下:漏关键或说反——学员会先问 AI 老师再重新复述"""

# 同步批改场景:中转间歇 502/坏 JSON 常见,最多试 3 次(1.5s 递增退避)
_ATTEMPTS = 3


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


def grade_recitation(
    course_id: str,
    page_id: str,
    answer: str,
    *,
    tutored: bool = False,
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
    t0 = time.perf_counter()
    resp = None
    last_err: Exception | None = None
    for attempt in range(_ATTEMPTS):
        # 中转间歇 502/坏 JSON 常见:学员坐在弹层里等,一次坏响应就 502 太脆
        try:
            resp = client.messages.create(
                model=settings.llm_model,
                # 思考模型的思考块也吃 max_tokens 预算:小值被思考烧光→零文本
                # (实测 1024 间歇性触发;与 prep/归位 8192 同档)
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
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
    # 模型偶尔裹 ```json```,剥掉
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        result: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as e:
        msg = f"批改返回格式异常: {e}"
        raise RuntimeError(msg) from None
    # 百分制判分:score≥70 过,<70 需重学/答疑后再复述;tutored 保底 70
    try:
        score = max(0, min(100, int(result.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    if tutored:
        score = max(score, 70)  # 已在答疑里学过一轮:核心说清即过
    result["score"] = score
    result["verdict"] = "pass" if score >= 70 else "fail"
    trace_grade(
        course_id=course_id,
        page_id=page_id,
        answer=answer,
        verdict=result["verdict"],
        comment=result.get("comment", ""),
        elapsed_s=time.perf_counter() - t0,
        score=score,
        precise=str(result.get("precise", "")),
    )
    return result
