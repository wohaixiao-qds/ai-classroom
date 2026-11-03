"""答疑 Agent —— 最小 harness 骨架的落地。

对照笔记《harness是什么》的最小骨架:
    while not done:                 ← run() 的 for+break
        resp = llm(messages)        ← client.messages.create (决策:LLM)
        cmd = parse(resp)           ← stop_reason/tool_use 解析 (解析:你写)
        result = execute(cmd)       ← execute_tool (执行:你写)
        messages.append(result)     ← tool_result 回填 (反馈:你写)
        done = check(result)        ← stop_reason != tool_use (终止:你写)

Scaffolding 部分:SYSTEM_PROMPT(教学风格+引用规范) 与 build_system(上下文组装,固定底料打缓存标记)。
Eval 部分:轨迹落盘见 trace()。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.agent.tools import TOOLS, execute_tool
from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.memory import append_turn, load_messages
from app.core.trace import trace_tutor

SYSTEM_PROMPT = """你是「AI 老师」,在学员学习课件时提供答疑。规则:

1. **课件优先**:问题能从课件内容回答的,基于课件答,注明「课件第N页」。
2. **课件之外**:涉及最新实践/版本/课件没讲的知识,用 web_search 查,
回答时用 [1][2] 标注来源,末尾列来源链接。
3. **学员学过的**:判断问题可能与学员已有笔记相关时,可用 read_notes 检索其知识库,衔接旧知识讲解。
4. **教学风格**:小步讲解、类比优先、宁少勿多;学员问概念时先给一句话核心,再按需展开,不一次灌完。
5. **回答显示在窄对话框**:少用标题和多级列表;短问题 1-3 句直接答;
确需分点用单层短横线列表,不嵌套;加粗只标关键词。像口头答疑,不是写文档。
6. **不瞎编**:查不到就说查不到,不编造来源。
"""

MAX_TURNS = 6  # 终止条件之二:防工具调用风暴


def build_system(course_text: str) -> list[dict]:
    """system 拆成多个 block,固定内容在前并打 cache_control 缓存标记。

    只放「每轮都不变」的:身份规范 + 课件全文。动态的当前页不进这里
    (它跟着对话走,见 run_tutor),否则前缀一变缓存全失效。
    """
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": f"## 课件全文\n{course_text}",
            "cache_control": {"type": "ephemeral"},  # 智谱不支持则被忽略,不报错
        },
    ]


def trace(question: str, tool_calls: list[dict], answer: str, elapsed: float) -> None:
    """已迁移到 app.core.trace.trace_tutor(带 course_id/page_id/引用页/usage)。

    保留薄壳仅为兼容旧调用;新代码请直接用 core.trace。
    """
    trace_tutor(
        course_id="",
        page_id=None,
        question=question,
        answer=answer,
        tool_calls=tool_calls,
        elapsed_s=elapsed,
    )


def run_tutor(
    question: str,
    course_text: str,
    current_page: str | None,
    *,
    session_id: str,
    course_id: str,
    checkpoint: dict[str, Any] | None = None,
) -> Iterator[dict]:
    """跑一轮答疑,以事件流产出(生成器)。

    记忆由本函数自己管(Runtime 层持有,不靠前端递纸条):
      开头 load_messages(session_id) 取历史(含工具块 → 追问时依据还在)
      结尾 append_turn 落盘本轮问答

    产出事件:
      {"type":"tool_call", ...}                     工具执行了(实时告诉前端在查)
      {"type":"delta","text":..}                    最终答案的一段 token(流式)
      {"type":"final","answer":..,"tool_calls":[..]} 收尾(给落轨迹用)
    工具轮的 token 不外发(那是模型思考要不要用工具);仅最终答案轮的文本逐段流式。
    """
    client = get_llm_client()
    # 动态状态(当前页/检查点联动)放进首条 user 消息,不污染可缓存的 system 前缀
    first_user = question
    if current_page:
        first_user = f"[我正在学第「{current_page}」页]\n\n{question}"
    if checkpoint:
        # 批改→答疑联动(P7 补):复述没过,老师拿全上下文做引导式解答
        first_user = (
            "[复述检查点没过,请引导式解答:先点破薄弱点,引导学员自己想通,"
            "不要直接给完整标准答案]\n"
            f"检查点问题:{checkpoint.get('question', '')}\n"
            f"通过标准:{checkpoint.get('pass_rule') or '核心概念说清即可'}\n"
            f"学员回答:{checkpoint.get('answer', '')}\n"
            f"判定:{checkpoint.get('verdict', 'warn')}\n\n"
            f"{question}"
        )
    history = load_messages(session_id)
    messages: list[dict] = [*history, {"role": "user", "content": first_user}]
    append_turn(session_id, course_id, "user", question, page_id=current_page)
    tool_calls: list[dict] = []
    usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0}

    for turn in range(MAX_TURNS):
        last_turn = turn == MAX_TURNS - 1
        # 兜底终止的「软着陆」:最后一轮不给工具,逼模型用已查到的信息收尾。
        if last_turn and isinstance(messages[-1].get("content"), list):
            messages[-1]["content"].append({
                "type": "text",
                "text": "(已达查询上限,请基于目前已掌握的信息尽力作答;仍不确定的部分如实说明。)",
            })

        # 流式调用:边收 token 边 yield,结束后取完整消息判 stop_reason
        answer_parts: list[str] = []
        with client.messages.stream(
            model=settings.llm_model,
            max_tokens=1024,
            system=build_system(course_text),
            messages=messages,
            tools=[] if last_turn else TOOLS,
        ) as stream:
            for text in stream.text_stream:
                answer_parts.append(text)
                yield {"type": "delta", "text": text}
            final = stream.get_final_message()

        # 累计 token 用量(观测:每问成本 + 缓存是否真命中)
        u = final.usage
        usage_total["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage_total["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        usage_total["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0

        if final.stop_reason != "tool_use":  # 终止:模型不再要工具
            answer = "".join(answer_parts)
            append_turn(session_id, course_id, "assistant", answer, page_id=current_page)
            yield {
                "type": "final",
                "answer": answer,
                "tool_calls": tool_calls,
                "usage": usage_total,
                "soft_landed": last_turn,  # 撞 MAX_TURNS 才收尾 = 查不到硬答
                "truncated": final.stop_reason == "max_tokens",
            }
            return

        # 工具轮:解析+执行+回填(此轮的 delta 是模型的思考文字,前端可忽略)
        assistant_blocks = [b.model_dump() for b in final.content]
        messages.append({"role": "assistant", "content": assistant_blocks})
        append_turn(session_id, course_id, "assistant", assistant_blocks, kind="tool_use")
        tool_results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            t0 = time.time()
            try:
                result = execute_tool(block.name, dict(block.input))
                err = None
            except Exception as e:  # noqa: BLE001 错误回收:工具炸了不拖垮循环
                result, err = f"(工具执行出错: {e})", str(e)
            tc = {
                "name": block.name, "args": dict(block.input),
                "ms": round((time.time() - t0) * 1000), "error": err,
            }
            tool_calls.append(tc)
            yield {"type": "tool_call", **tc}  # 实时:老师正在查
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
            )
        messages.append({"role": "user", "content": tool_results})
        append_turn(session_id, course_id, "user", tool_results, kind="tool_result")

    fallback = "(本轮信息有限,请换个更具体的问题再试)"
    append_turn(session_id, course_id, "assistant", fallback, page_id=current_page)
    yield {
        "type": "final",
        "answer": fallback,
        "tool_calls": tool_calls,
        "usage": usage_total,
        "soft_landed": True,
        "truncated": False,
    }


def course_text_of(course_id: str) -> str:
    """课件全文(答疑底料)。v2 书页:标题+每节 heading+各块文本;v1 旧格式兼容。"""
    p: Path = settings.courses_dir / f"{course_id}.csl.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    lines = [f"# {d['title']}"]
    if d.get("version") == 2:
        for i, sec in enumerate(d.get("sections", []), 1):
            lines.append(f"\n[第{i}节] {sec.get('heading', '')}")
            for b in sec.get("blocks", []):
                bt = b.get("type")
                if bt in ("p", "callout"):
                    lines.append(f"  {b.get('text', '')}")
                elif bt == "diagram":
                    lines.append(f"  [示意图] {b.get('caption') or ''}: {b.get('code', '')[:200]}")
                elif bt == "code":
                    lines.append(f"  [代码 {b.get('language', '')}]\n  {b.get('code', '')}")
                elif bt == "table":
                    rows = [b.get("header", []), *b.get("rows", [])]
                    lines.extend(f"  | {'|'.join(map(str, row))}" for row in rows)
                elif bt == "quiz":
                    rule = b.get("pass_rule") or "核心概念说清"
                    lines.append(f"  [检查点] {b.get('question', '')}(标准:{rule})")
        return "\n".join(lines)
    for i, page in enumerate(d["pages"], 1):
        lines.append(f"\n[第{i}页] {page.get('eyebrow') or ''} {page.get('title') or ''}")
        for s in page["script"]:
            lines.append(f"  {s['text']}")
    return "\n".join(lines)
