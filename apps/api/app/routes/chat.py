"""答疑路由:POST /api/v1/chat (SSE)。

SSE 约定(按项目规范):事件信封 {type,data,id};心跳;前置校验(校验失败
返回普通 422,不进入流)。
事件类型: tool_call(老师正在查) / answer(最终回答) / done(收尾) / error。
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.tutor import course_text_of, run_tutor, trace
from app.schemas.chat import ChatRequest, GradeRequest
from app.services.grader import grade_recitation

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _sse(event_type: str, data: dict, eid: int) -> str:
    return f"id: {eid}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    # 前置校验:课件必须存在,否则 404(流开始前)
    try:
        course_text = course_text_of(req.course_id)
    except FileNotFoundError:
        raise HTTPException(404, f"课件不存在: {req.course_id}") from None

    history = [{"role": m.role, "content": m.content} for m in req.history]

    def gen():
        eid = 0
        yield ": heartbeat-setup\n\n"
        t0 = time.perf_counter()
        try:
            # v1: 循环整体跑完再回放工具事件+答案(真流式留 P4)
            answer, tool_calls = run_tutor(req.question, history, course_text, req.current_page)
            for tc in tool_calls:
                eid += 1
                yield _sse("tool_call", tc, eid)
            eid += 1
            yield _sse("answer", {"text": answer}, eid)
            trace(req.question, tool_calls, answer, time.perf_counter() - t0)
            eid += 1
            yield _sse("done", {"tool_calls": len(tool_calls)}, eid)
        except Exception as e:  # noqa: BLE001 流内错误用 error 事件(头已发出,无法再改状态码)
            eid += 1
            yield _sse("error", {"message": str(e)}, eid)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/grade")
def grade(req: GradeRequest) -> dict:
    try:
        return grade_recitation(req.course_id, req.page_id, req.answer)
    except KeyError as e:
        raise HTTPException(404, str(e)) from None
    except json.JSONDecodeError:
        raise HTTPException(502, "批改返回格式异常,请重试") from None
    except Exception as e:  # noqa: BLE001 LLM 认证/网络等,给可读信息
        raise HTTPException(502, f"批改服务暂不可用: {e}") from None
