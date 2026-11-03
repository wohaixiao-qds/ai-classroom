"""答疑路由:POST /api/v1/chat (SSE)。

SSE 约定(按项目规范):事件信封 {type,data,id};心跳;前置校验(校验失败
返回普通 404,不进入流)。
事件类型: tool_call(老师正在查) / delta(答案流式片段) / done(收尾) / error。
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.tutor import course_text_of, run_tutor
from app.core.memory import ensure_session, list_sessions, new_session, session_history
from app.core.trace import read_traces, trace_tutor
from app.schemas.chat import (
    ChatRequest,
    FlashReportRequest,
    GradeRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionListResponse,
)
from app.services.grader import grade_recitation
from app.services.self_eval import evaluate_answer

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

    session_id = ensure_session(req.session_id, req.course_id)

    def gen():
        eid = 0
        yield ": heartbeat-setup\n\n"
        t0 = time.perf_counter()
        try:
            yield _sse("session", {"session_id": session_id}, 0)
            for ev in run_tutor(
                req.question,
                course_text,
                req.current_page,
                session_id=session_id,
                course_id=req.course_id,
                checkpoint=req.checkpoint.model_dump() if req.checkpoint else None,
            ):
                eid += 1
                if ev["type"] == "tool_call":
                    yield _sse("tool_call", {"name": ev["name"], "args": ev["args"]}, eid)
                elif ev["type"] == "delta":
                    yield _sse("delta", {"text": ev["text"]}, eid)
                elif ev["type"] == "final":
                    # A6 答案自评:仅可疑答案(长答+没引页+没调工具)才跑裁判,
                    # 结果进 trace。跑在流结束后 → 不挡学员(答案已 delta 流完)。
                    verdict = evaluate_answer(
                        req.question, ev["answer"], ev["tool_calls"], course_text
                    )
                    trace_tutor(
                        course_id=req.course_id,
                        page_id=req.current_page,
                        question=req.question,
                        answer=ev["answer"],
                        tool_calls=ev["tool_calls"],
                        elapsed_s=time.perf_counter() - t0,
                        usage=ev.get("usage"),
                        soft_landed=ev.get("soft_landed", False),
                        truncated=ev.get("truncated", False),
                        source=req.source,
                        self_eval=verdict,
                    )
                    yield _sse("done", {"tool_calls": len(ev["tool_calls"])}, eid)
        except Exception as e:  # noqa: BLE001 流内错误用 error 事件(头已发出,无法再改状态码)
            eid += 1
            yield _sse("error", {"message": str(e)}, eid)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/sessions", response_model=SessionListResponse)
def sessions(course_id: str) -> dict:
    """某课程的会话列表(A5 会话管理:切回历史对话)。"""
    return {"sessions": list_sessions(course_id)}


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def session_detail(session_id: str) -> dict:
    """会话历史(仅文本轮,给前端渲染)。"""
    return {"turns": session_history(session_id)}


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session(course_id: str) -> dict:
    """开一轮干净对话。"""
    return {"session_id": new_session(course_id)}


@router.post("/grade")
def grade(req: GradeRequest) -> dict:
    try:
        result = grade_recitation(
            req.course_id, req.page_id, req.answer, tutored=req.tutored
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from None
    except json.JSONDecodeError:
        raise HTTPException(502, "批改返回格式异常,请重试") from None
    except Exception as e:  # noqa: BLE001 LLM 认证/网络等,给可读信息
        raise HTTPException(502, f"批改服务暂不可用: {e}") from None
    # 批改成功 → 累积掌握度 + 推进复习档位(失败不影响批改结果返回)
    from app.services import mastery

    mastery.record_grade(req.course_id, req.page_id, result["verdict"])
    return result


@router.post("/flash/report")
def flash_report(req: FlashReportRequest) -> dict:
    """闪卡自评(M4):记得/忘了 → 同一套掌握度累积与间隔排期。无 LLM,纯回写。"""
    from app.services import mastery

    verdict = "pass" if req.remembered else "fail"
    mastery.record_grade(req.course_id, req.block_id, verdict)
    with mastery._conn() as c:
        row = c.execute(
            "SELECT mastery, next_review_at FROM checkpoint_mastery"
            " WHERE course_id=? AND page_id=?",
            (req.course_id, req.block_id),
        ).fetchone()
    return {
        "ok": True,
        "mastery": row["mastery"] if row else 0,
        "next_review_at": row["next_review_at"] if row else None,
    }


@router.get("/grade/last")
def grade_last(course_id: str, page_id: str) -> dict:
    """回查某检查点最近一次批改(通过态跨刷新展示用);没有则 {found: false}。"""
    for g in read_traces("grade.jsonl", limit=500):
        if g.get("course_id") == course_id and g.get("page_id") == page_id:
            return {
                "found": True,
                "verdict": g.get("verdict"),
                "score": g.get("score"),
                "comment": g.get("comment"),
                "precise": g.get("precise"),
                "answer": g.get("answer"),
            }
    return {"found": False}