"""重教门禁(观测期,2026-11-19 B 方案):检测答疑答案是否把已学概念当新概念重新教。

与 citation_guard 同思路——prompt(策略级)约束口吻不可靠,这里事后确定性扫描。
当前只观测记 trace(命中句式+概念),不拦截不补正;跑几天看命中/误伤率再定升级。

判据(窄口径防误伤):「定义引导词 + 已学概念词」连用——
  所谓X / X(是指 / X,是指 / X指的是 / X,即
正常使用(「就像你学过的 X 一样」「X 帮我们…」)不命中。
"""

from __future__ import annotations

import re


def detect_reteach(answer: str, mastered_terms: list[str]) -> list[str]:
    """返回命中清单(空=干净)。每条一句:「概念词 × 句式」。"""
    hits: list[str] = []
    for term in mastered_terms:
        if not term:
            continue
        esc = re.escape(term)
        patterns = [
            (f"所谓{esc}", "所谓X"),
            (rf"{esc}[(，,]\s*是指", "X(是指"),
            (rf"{esc}指的是", "X指的是"),
            (rf"{esc}[,，]即", "X,即"),
        ]
        for pat, label in patterns:
            if re.search(pat, answer):
                hits.append(f"{term} × {label}")
                break  # 同词多句式只记一次
    return hits
