"""复述批改:单次 LLM 调用(无工具,不进循环)。

输入: 复述文本 + 该页讲稿/内容 + 检查点的 pass_rule(T1 埋好的通过标准)
输出: ✅(过) / ⚠️(大体对,需补正) / ❌(没说清,重述) + 🎯 精准版对照。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.trace import trace_grade

GRADE_PROMPT = """你是学习督导,批改学员对刚学内容的复述。严格但鼓励。

本页讲过的内容:
{page_content}

通过标准(出题人写的):
{pass_rule}

学员的复述:
{answer}

按 JSON 输出(不要输出其他内容):
{{"verdict": "pass|warn|fail",
  "comment": "一两句点评,指出对在哪/缺在哪",
  "precise": "若非 pass,给出该复述应有的准确表述(纯内容,不要写「精准版」等任何标签)"}}

判定尺度:
- pass: 核心关系/区分说清了,措辞小瑕疵不扣
- warn: 方向对但漏了关键一半,或踩了标准里点名的坑 → 给精准版
- fail: 关系说反/完全没说到点子上
"""


def grade_recitation(course_id: str, page_id: str, answer: str) -> dict:
    """批改一次复述,返回 {verdict, comment, precise}。"""
    p: Path = settings.courses_dir / f"{course_id}.csl.json"
    d = json.loads(p.read_text(encoding="utf-8"))
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
    resp = client.messages.create(
        model=settings.llm_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    # 模型偶尔裹 ```json```,剥掉
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    result = json.loads(text)
    if result.get("verdict") not in ("pass", "warn", "fail"):
        result["verdict"] = "warn"
    trace_grade(
        course_id=course_id,
        page_id=page_id,
        answer=answer,
        verdict=result["verdict"],
        comment=result.get("comment", ""),
        elapsed_s=time.perf_counter() - t0,
    )
    return result
