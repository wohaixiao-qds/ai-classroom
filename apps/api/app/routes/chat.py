"""答疑路由:POST /api/v1/chat (SSE)。

SSE 约定(按项目规范):事件信封 {type,data,id};心跳;前置校验(校验失败
返回普通 404,不进入流)。
事件类型: thinking(思考片段) / tool_call(老师正在查) / delta(答案流式片段) / done(收尾) / error。
"""

from __future__ import annotations

import json
import time
import traceback
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.agent.tutor import course_text_of, run_tutor
from app.core.config import settings
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
from app.services.catalog import mastered_concepts, session_state_note, student_course_map
from app.services.citation_guard import course_index_of, verify_citations
from app.services.grader import grade_recitation
from app.services.reteach_guard import detect_reteach
from app.services.self_eval import evaluate_answer

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _sse(event_type: str, data: dict, eid: int) -> str:
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

    # A6 答案自评 + 落 trace 是「事后账」:done 先发、裁判流结束后后台跑。
    # 之前裁判挡在 done 之前——5.3 思考常开后裁判一次动辄几十秒,前端答案已
    # 流完却收不到 done、流不关 → 按钮一直停在「停止」(没输出但像还在生成)。
    trace_job: dict[str, Any] = {}

    def _after_stream() -> None:
        ev = trace_job
        if not ev:
            return  # 流内报错没到 final:与旧行为一致,不落 trace
        try:
            verdict = evaluate_answer(
                ev["question"], ev["answer"], ev["tool_calls"], ev["course_text"]
            )
            trace_tutor(
                course_id=req.course_id,
                page_id=req.current_page,
                question=ev["question"],
                answer=ev["answer"],
                tool_calls=ev["tool_calls"],
                elapsed_s=ev["elapsed_s"],
                usage=ev.get("usage"),
                soft_landed=ev.get("soft_landed", False),
                truncated=ev.get("truncated", False),
                source=req.source,
                self_eval=verdict,
                guard_violations=ev.get("guard_violations", []),
                reteach=detect_reteach(ev["answer"], mastered),
            )
            # 经验级 memory:自评抓到编造 → 自动记一条候选进教训账本(带待审标,
            # 人定期清理;删行=撤销教训)。只有 fabricated 记,partial 噪音大不记
            v = (verdict or {}).get("verdict")
            if v == "fabricated":
                lp = settings.data_dir / "agent_lessons.md"
                lp.parent.mkdir(parents=True, exist_ok=True)
                reason = (verdict or {}).get("reason", "")[:80]
                with lp.open("a", encoding="utf-8") as f:
                    f.write(
                        f"- [待审] 问题「{ev['question'][:60]}」我曾编造无据内容"
                        f"({reason})——这类问题先声明「课件没讲、我不确定」再答\n"
                    )
                print(f"[chat] 自评判 fabricated,已记教训账本候选: {lp}", flush=True)
        except Exception:  # noqa: BLE001 后台账失败只留日志,不影响已交付的答案
            print(f"[chat] 自评/trace 后台任务失败:\n{traceback.format_exc()}", flush=True)

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
                course_map=course_map,
                mastered_terms=mastered,
                state_note=state_note,
            ):
                eid += 1
                if ev["type"] == "tool_call":
                    yield _sse("tool_call", {"name": ev["name"], "args": ev["args"]}, eid)
                elif ev["type"] == "thinking":
                    yield _sse("thinking", {"text": ev["text"]}, eid)
                elif ev["type"] == "delta":
                    yield _sse("delta", {"text": ev["text"]}, eid)
                elif ev["type"] == "final":
                    # 规则级门禁(假引用拦截):纯文本校验毫秒级,放 done 前;
                    # 流式体验不受损——答案照常流完,违规紧跟着补正 delta
                    violations = verify_citations(ev["answer"], course_index)
                    if violations:
                        eid += 1
                        yield _sse(
                            "delta",
                            {
                                "text": "\n\n⚠ **更正**:上文的引用经校验有误——"
                                + ";".join(violations)
                                + "。相关说法请以课件原文为准。"
                            },
                            eid,
                        )
                    yield _sse("done", {"tool_calls": len(ev["tool_calls"])}, eid)
                    # 裁判数据留给后台任务;elapsed 在 final 时刻取,tutor 耗时不含裁判时长
                    trace_job.update(
                        question=req.question,
                        answer=ev["answer"],
                        tool_calls=ev["tool_calls"],
                        elapsed_s=time.perf_counter() - t0,
                        guard_violations=violations,
                        usage=ev.get("usage"),
                        soft_landed=ev.get("soft_landed", False),
                        truncated=ev.get("truncated", False),
                        course_text=course_text,
                    )
        except Exception as e:  # noqa: BLE001 流内错误用 error 事件(头已发出,无法再改状态码)
            eid += 1
            yield _sse("error", {"message": str(e)}, eid)

    return StreamingResponse(
        gen(), media_type="text/event-stream", background=BackgroundTask(_after_stream)
    )


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
