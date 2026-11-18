"""假引用门禁(2026-11-18,规则级 tool):确定性校验答案里的引用,对不上即拦截补正。

课件铁律「要可靠就别指望模型自觉」的落地:prompt 是求自觉,这里是门禁。
校验两类(纯文本、零 LLM、毫秒级):
1. 「课件第N节/页」→ course_text 里必须真有 `[第N节]`/`[第N页]` 标记
   (course_text_of 的产出格式,节号天然权威)
2. `[1][2]` 来源标号 → 答案里实际列出的 http 链接数必须 ≥ 最大标号
   (教学规范:标号必须在末尾来源清单里对得上)

用法:答案完成后扫一遍,违规→补正消息(delta 追加)+ trace 记 guard_violations。
流式体验不受损(照常流完再补正),与「缓冲预检」的取舍见当日记账。
"""

from __future__ import annotations

import re

_CITE_RE = re.compile(r"课件第\s*(\d+)\s*([节页])")
_REF_RE = re.compile(r"\[(\d+)\]")
_URL_RE = re.compile(r"https?://\S+")


def _unit_count(course_text: str, unit: str) -> int:
    return len(re.findall(rf"\[第\d+{unit}\]", course_text))


def verify_citations(answer: str, course_text: str) -> list[str]:
    """返回违规清单(空=通过)。每条一句话,直接进补正文案。"""
    violations: list[str] = []
    seen: set[str] = set()
    for m in _CITE_RE.finditer(answer):
        n, unit = m.groups()
        key = f"{n}{unit}"
        if key in seen:
            continue
        seen.add(key)
        if f"[第{n}{unit}]" not in course_text:
            total = _unit_count(course_text, unit)
            violations.append(
                f"「课件第{n}{unit}」不存在(本课共 {total} 个{unit})"
                + (f",同主题内容在第 1~{total} {unit}内" if total else "")
            )
    refs = [int(x) for x in _REF_RE.findall(answer)]
    if refs:
        n_urls = len(_URL_RE.findall(answer))
        if max(refs) > n_urls:
            violations.append(
                f"来源标号 [{max(refs)}] 对不上实际列出的链接({n_urls} 条)——该标号无来源"
            )
    return violations
