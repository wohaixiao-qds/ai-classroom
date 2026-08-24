"""答案自评(A6 · Eval 层)—— 事后审查答疑回答是否**有据**,单次 LLM 裁判(不进循环)。

设计(见 P1.5 §A6 对齐):
- 评估型:只判 + 记录,不重答(修正型留待后续)。
- 仅可疑才评(省 token):长答 + 没引课件页 + 全程没调工具 = 纯靠模型脑补、编造风险最高,
  才跑裁判。引了页 / 调了 read_notes / web_search = 查过真实来源 → 不评。
- 独立裁判:干净的单次调用,只喂 问题 + 材料 + 答案(不复用工具循环上下文,免自我偏袒 + 省 token)。
- 软着陆:任何异常 / 解析失败 → verdict=skipped,绝不影响已发给学员的答案。

复用 grader.py 的 LLM-judge 姿势,只是把枪口从「判学员复述」掉转到「判 agent 自己的答案」。
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.trace import cited_pages

SELF_EVAL_PROMPT = """你在审查「AI 老师」对学员问题的回答是否**有据**:
即回答内容是否被下列课件材料支撑,还是超出材料、像模型自己编的。

学员问题:
{question}

课件材料(老师能依据的全部内容):
{materials}

老师的回答:
{answer}

只按 JSON 输出(不要输出别的):
{{"verdict": "grounded|partial|fabricated", "reason": "一句话:哪部分有据 / 哪部分超出材料"}}

判定尺度:
- grounded: 回答都能在课件材料里找到依据(措辞不同不扣)
- partial: 大体有据,但夹带了材料里没有的具体断言
- fabricated: 主要内容在材料里找不到依据,像凭空生成
注:老师若坦诚说「课件没讲 / 查不到」这类免责,属诚实,不算编造。"""

_VERDICTS = ("grounded", "partial", "fabricated")


def _judge(question: str, answer: str, materials: str) -> dict[str, str]:
    client = get_llm_client()
    prompt = SELF_EVAL_PROMPT.format(question=question, materials=materials, answer=answer)
    resp = client.messages.create(
        model=settings.llm_model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):  # 模型偶尔裹 ```json```,剥掉(同 grader)
        text = text.strip("`").removeprefix("json").strip()
    result = json.loads(text)
    verdict = str(result.get("verdict", ""))
    if verdict not in _VERDICTS:
        verdict = "skipped"
    return {"verdict": verdict, "reason": str(result.get("reason", ""))[:200]}


def evaluate_answer(
    question: str,
    answer: str,
    tool_calls: list[dict[str, Any]],
    materials: str,
) -> dict[str, str] | None:
    """可疑才评。返回 {verdict, reason};不可疑(引了页 / 调过工具 / 短答)返回 None(不评、不花钱)。

    自评本身失败 → {"verdict":"skipped", ...},不抛,调用方无需处理异常。
    """
    if cited_pages(answer) or tool_calls or len(answer) <= 200:
        return None
    try:
        return _judge(question, answer, materials)
    except Exception as e:  # noqa: BLE001 自评失败绝不拖累已产出的答案
        return {"verdict": "skipped", "reason": f"自评未完成: {e}"}
