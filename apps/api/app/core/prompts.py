"""LLM 输出格式规范集中地(方案 A 提取)——两个职责:

1. **prompt 片段常量**:各调用点的输出排版/格式纪律,点单拼装进各自 prompt。
   改排版只动这里(单一事实源),拼装方需保持既有 prompt 字节不变
   (system 前缀缓存稳定 + 行为零漂移)。
2. **parse_json_reply**:「剥围栏→括号截取→loads→对象校验」的统一回复解析,
   替代 grader/self_eval/归位/research 四处手抄(提炼自 research._json_from_text)。

归位:app/core(§1.2 基础设施层),agent 与 services 双向可 import,无环。
"""

from __future__ import annotations

import json
from typing import Any

# ---- 通用格式纪律(各调用点统一口径) ----
JSON_OUTPUT_RULE = "按 JSON 输出(不要其他内容):"

# ---- 答疑(tutor)输出排版:窄框对话 + 引用规范(前端 linkifyCitations/linkifyUrls 与之配对) ----
CITE_COURSE_RULE = "1. **课件优先**:问题能从课件内容回答的,基于课件答,注明「课件第N页」。"
CITE_WEB_RULE = (
    "2. **课件之外**:涉及最新实践/版本/课件没讲的知识,用 web_search 查,\n"
    "回答时用 [1][2] 标注来源,末尾列来源链接。"
)
CHAT_NARROW_RULE = (
    "6. **回答显示在窄对话框**:少用标题和多级列表;短问题 1-3 句直接答;\n"
    "确需分点用单层短横线列表,不嵌套;加粗只标关键词。像口头答疑,不是写文档。"
)

# ---- 复述批改(grader)产出规范:score/comment/precise 的 JSON + 标尺 ----
# 后续批改排版改版在此单点改(2026-11 拍板,先提取后改版)
GRADE_OUTPUT_SPEC = (
    JSON_OUTPUT_RULE
    + "\n"
    + '{{"score": 0~100 的整数,\n'
    '  "comment": "恰好三行,每行一条(配结算环+分条展示):\\n'
    "✓ 对在哪——一条具体的,不空夸\\n"
    "✗ 缺在哪——一条最值得补的\\n"
    '→ 下一步——一句行动:怎么补/下次复述先想什么",\n'
    '  "precise": "标准表述——分数再高也给,pass 时作为「更完整的说法」"}}\n'
    "\n"
    "评分标尺:\n"
    "- 85~100:核心关系/步骤全对,细节小瑕疵不扣\n"
    "- 70~84:核心说清,个别小漏不扣\n"
    "- 40~69:方向对但漏了关键一半,或踩了标准里点名的坑\n"
    "- 0~39:说反了/完全没说到点子上\n"
    "\n"
    "判定尺度(服务端按 score≥70 判过):\n"
    "- 70 以上:核心说清即过,措辞小瑕疵不扣\n"
    "- 70 以下:漏关键或说反——学员会先问 AI 老师再重新复述"
)


def parse_json_reply(text: str) -> dict[str, Any] | None:
    """模型回复 → JSON 对象;容忍 ```json 围栏与前置废话(找 {…} 截取),
    零文本/坏 JSON/非对象一律返回 None,兜底语义由调用方定(重试/skipped/报错)。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").removeprefix("json").strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        d = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None
