"""答疑路由:POST /api/v1/chat (SSE)。

SSE 约定(按项目规范):事件信封 {type,data,id};心跳;前置校验(校验失败
返回普通 404,不进入流)。
事件类型: thinking(思考片段) / tool_call(老师正在查) / delta(答案流式片段) / done(收尾) / error。
"""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import AsyncIterator, Generator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import iterate_in_threadpool
from starlette.types import Message, Receive, Scope, Send

from app.agent.tutor import course_text_of, run_tutor
from app.core.learning_store import last_result
from app.core.lessons import propose_lesson
from app.core.memory import ensure_session, list_sessions, new_session, session_history
from app.core.trace import EVAL_VERSION, TraceRun, trace_tutor
from app.schemas.chat import (
    ChatRequest,
    FlashReportRequest,
    GradeRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionListResponse,
)
from app.services.catalog import mastered_concepts, session_state_note, student_course_map
from app.services.citation_guard import course_index_of, verify_citations
from app.services.grader import grade_recitation
from app.services.reteach_guard import detect_reteach
from app.services.self_eval import evaluate_answer

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _sse(event_type: str, data: dict[str, Any], eid: int) -> str:
    return f"id: {eid}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    # 前置校验:课件必须存在,否则 404(流开始前)。
    # 底料走节级窗口(当前节±相邻节+全课目录):全文 4~8k 每问全价,问题天然贴阅读位置
    try:
        course_text = course_text_of(req.course_id, section=req.current_page)
        # 引用合法性以完整章节结构为准,不能拿裁剪后的模型底料当作全课。
        course_index = course_index_of(req.course_id)
    except FileNotFoundError:
        raise HTTPException(404, f"课件不存在: {req.course_id}") from None
    # 课程地图与 course_text 同分工:路由层算好传入,agent 层不自己读盘
    course_map = student_course_map()
    # A 方案:已学概念词表(确定性抽取,贴在问题旁——「查地图」推理不再外包给模型)
    mastered = mastered_concepts(exclude_course_id=req.course_id)

    session_id = ensure_session(req.session_id, req.course_id)
    # 侧信道:会话中途进度增量(拉模式,每问现算 diff,变化才产出)
    state_note = session_state_note(session_id, req.course_id)

    # 执行轨迹先落,裁判随后补写;失败/断连也有同一个 run_id。
    run = TraceRun("tutor", course_id=req.course_id, page_id=req.current_page,
                   session_id=session_id, question=req.question, source=req.source)
    trace_job: dict[str, Any] = {
        "answer": "", "tool_calls": [], "usage": {}, "turns": 0,
        "guard_violations": [], "status": "running", "context": "",
    }
    # 即使上下文装配失败,仍有路由输入可复盘;正常运行会被实际 system/messages 覆盖。
    run.context(materials=course_text, course_map=course_map, mastered=mastered,
                state_note=state_note,
                checkpoint=req.checkpoint.model_dump() if req.checkpoint else None)

    def record(status: str, error: str | None = None) -> None:
        trace_job["status"] = status
        trace_tutor(
            course_id=req.course_id, page_id=req.current_page, question=req.question,
            answer=trace_job["answer"], tool_calls=trace_job["tool_calls"],
            elapsed_s=time.perf_counter() - run.started, usage=trace_job["usage"],
            turns=trace_job["turns"], source=req.source, status=status, error=error,
            guard_violations=trace_job["guard_violations"],
            reteach=detect_reteach(trace_job["answer"], mastered),
            soft_landed=trace_job.get("soft_landed", False),
            truncated=trace_job.get("truncated", False), run=run,
            self_eval={"version": EVAL_VERSION, "verdict": "skipped", "skip_reason": (
                "pending" if status == "succeeded" else "incomplete_execution")},
        )

    def _after_stream() -> None:
        if run.fields.get("status") != "succeeded":
            return
        try:
            verdict = evaluate_answer(
                req.question, trace_job["answer"], trace_job["tool_calls"], course_text,
                guard_violations=trace_job["guard_violations"], context=trace_job["context"],
            )
            run.assess(verdict or {"version": EVAL_VERSION, "verdict": "skipped",
                                   "skip_reason": "no_assessment"})
            if (verdict or {}).get("verdict") in ("unsupported", "partial"):
                propose_lesson(
                    run.id,
                    f"问题「{req.question[:80]}」的回答可能缺少证据。"
                    "同类问题先核对课件与工具返回,无法支撑的断言明确标为不确定。",
                    {"question": req.question, "answer": trace_job["answer"],
                     "assessment": verdict}, source=req.source,
                )
        except Exception:  # noqa: BLE001 后台评价失败不覆盖执行终态
            run.assess({"version": EVAL_VERSION, "verdict": "skipped",
                        "skip_reason": "assessment_error"})
            print(f"[chat] 评价后台任务失败:\n{traceback.format_exc()}", flush=True)

    def gen() -> Generator[str, None, None]:
        eid = 0
        last_saved = time.perf_counter()
        try:
            yield ": heartbeat-setup\n\n"
            yield _sse("session", {"session_id": session_id}, 0)
            for ev in run_tutor(
                req.question, course_text, req.current_page,
                session_id=session_id, course_id=req.course_id,
                checkpoint=req.checkpoint.model_dump() if req.checkpoint else None,
                course_map=course_map, mastered_terms=mastered, state_note=state_note,
            ):
                if run.finished:  # 浏览器已断连,下一次模型事件到达即停止继续调用。
                    return
                eid += 1
                if ev["type"] == "context":
                    run.context(**{k: v for k, v in ev.items() if k != "type"})
                    trace_job["context"] = json.dumps(ev["messages"], ensure_ascii=False)
                elif ev["type"] == "iteration":
                    trace_job["turns"] = ev["turns"]
                    run.update(turns=ev["turns"])
                elif ev["type"] == "usage":
                    trace_job["usage"] = ev["usage"]
                    run.update(usage=ev["usage"])
                elif ev["type"] == "tool_call":
                    trace_job["tool_calls"].append({k: v for k, v in ev.items() if k != "type"})
                    run.update(tool_calls=trace_job["tool_calls"])
                    yield _sse("tool_call", {"name": ev["name"], "args": ev["args"]}, eid)
                elif ev["type"] == "thinking":
                    yield _sse("thinking", {"text": ev["text"]}, eid)
                elif ev["type"] == "delta":
                    trace_job["answer"] += ev["text"]
                    if time.perf_counter() - last_saved >= 1:
                        run.update(answer=trace_job["answer"])
                        last_saved = time.perf_counter()
                    yield _sse("delta", {"text": ev["text"]}, eid)
                elif ev["type"] == "final":
                    trace_job.update({k: v for k, v in ev.items() if k != "type"})
                    violations = verify_citations(ev["answer"], course_index)
                    trace_job["guard_violations"] = violations
                    record("succeeded")  # 必须早于 done,裁判永远不挡用户收尾。
                    if violations:
                        eid += 1
                        yield _sse("delta", {
                            "text": "\n\n⚠ **更正**:上文的引用经校验有误——"
                            + ";".join(violations) + "。相关说法请以课件原文为准。",
                        }, eid)
                    yield _sse("done", {"tool_calls": len(ev["tool_calls"])}, eid)
                    return
            if not run.finished:
                record("failed", "答疑循环结束但没有 final")
                yield _sse("error", {"message": "答疑未完成,请重试"}, eid + 1)
        except Exception as exc:  # noqa: BLE001 流开始后用 SSE error
            if not run.finished:
                record("failed", f"{type(exc).__name__}: {exc}")
            yield _sse("error", {"message": str(exc)}, eid + 1)
        finally:
            if not run.finished:
                record("cancelled", "答疑流关闭")

    async def stream() -> AsyncIterator[str]:
        iterator = gen()
        try:
            async for chunk in iterate_in_threadpool(iterator):
                yield chunk
        finally:
            # Starlette 断连取消异步迭代时,同步模型调用可能仍在工作线程里等待。
            # 先记取消;线程返回下一事件时检测 run.finished,不再进入后续工具轮。
            if not run.finished:
                record("cancelled", "客户端断开连接")
            try:
                iterator.close()
            except ValueError:  # 工作线程仍在 next(),由其返回后自行退出。
                pass

    class TracedResponse(StreamingResponse):
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            async def watched_receive() -> Message:
                message = await receive()
                if message["type"] == "http.disconnect" and not run.finished:
                    record("cancelled", "客户端断开连接")
                return message

            try:
                await super().__call__(scope, watched_receive, send)
            finally:
                # 包住 ASGI 响应本身:send 失败时异步生成器不一定立即 close。
                if not run.finished:
                    record("cancelled", "响应连接已关闭")

    return TracedResponse(
        stream(), media_type="text/event-stream", background=BackgroundTask(_after_stream)
    )


@router.get("/sessions", response_model=SessionListResponse)
def sessions(course_id: str) -> dict[str, Any]:
    """某课程的会话列表(A5 会话管理:切回历史对话)。"""
    return {"sessions": list_sessions(course_id)}


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def session_detail(session_id: str) -> dict[str, Any]:
    """会话历史(仅文本轮,给前端渲染)。"""
    return {"turns": session_history(session_id)}


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session(course_id: str) -> dict[str, Any]:
    """开一轮干净对话。"""
    return {"session_id": new_session(course_id)}


@router.post("/grade")
def grade(req: GradeRequest) -> dict[str, Any]:
    try:
        result = grade_recitation(
            req.course_id, req.page_id, req.answer, tutored=req.tutored, source=req.source
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from None
    except json.JSONDecodeError:
        raise HTTPException(502, "批改返回格式异常,请重试") from None
    except Exception as e:  # noqa: BLE001 LLM 认证/网络等,给可读信息
        raise HTTPException(502, f"批改服务暂不可用: {e}") from None
    # 批改成功 → 累积掌握度 + 推进复习档位(失败不影响批改结果返回)
    from app.services import mastery

    if req.source == "user":
        mastery.record_grade(req.course_id, req.page_id, result["verdict"])
    return result


@router.post("/flash/report")
def flash_report(req: FlashReportRequest) -> dict[str, Any]:
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
def grade_last(course_id: str, page_id: str) -> dict[str, Any]:
    """回查某检查点最近一次批改(通过态跨刷新展示用);没有则 {found: false}。"""
    g = last_result(course_id, page_id)
    return {"found": True, **g} if g else {"found": False}
