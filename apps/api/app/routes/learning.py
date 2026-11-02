"""学习生命周期路由(P3·N2):进度上报/完成判定 + 笔记草稿/确认落盘 + 复习队列。

写回闸门:ready(学完)才允许 draft/apply——「学完才写回」是机制不是自觉。
复习:批改结果在 /grade 里累积进 checkpoint_mastery,这里只读到期的。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.progress import completion, mark_done
from app.schemas.learning import ApplyResult, CompletionState, NoteDraft, ReviewDue, TodoEdit
from app.services.mastery import due_reviews
from app.services.note_writer import apply_draft, build_draft

router = APIRouter(prefix="/api/v1", tags=["learning"])

# 草稿缓存:确认的必须是预览过的那份(LLM 非确定性,重生成会得到不同文本)
_DRAFT_CACHE: dict[str, dict[str, Any]] = {}


@router.post("/progress/{course_id}/done", response_model=CompletionState)
def report_done(course_id: str) -> CompletionState:
    """播放引擎到达课程自然终点时上报(幂等),顺手返回完成态(前端弹邀请用)。"""
    mark_done(course_id)
    return completion(course_id)


@router.get("/progress/{course_id}", response_model=CompletionState)
def get_completion(course_id: str) -> CompletionState:
    return completion(course_id)


def _require_ready(course_id: str) -> None:
    st = completion(course_id)
    if not st.ready:
        missing = []
        if not st.done:
            missing.append("还没播放到最后一页")
        if st.checkpoints_passed < st.checkpoints_total:
            missing.append(f"检查点通过 {st.checkpoints_passed}/{st.checkpoints_total}")
        raise HTTPException(409, "还没学完,暂不写回:" + ";".join(missing))


@router.post("/notes/draft/{course_id}", response_model=NoteDraft)
def note_draft(course_id: str) -> NoteDraft:
    """生成写回草稿(预览用,不落盘)。学完才放行。"""
    _require_ready(course_id)
    try:
        d = build_draft(course_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    _DRAFT_CACHE[course_id] = d
    te = d.get("todo_edit")
    todo = TodoEdit(file=te[0].name, old_line=te[1], new_line=te[2]) if te else None
    return NoteDraft(
        mode=d["mode"],
        title=d["title"],
        note_path=d["note_path"],
        content=d["content"],
        todo_edit=todo,
    )


@router.post("/notes/apply/{course_id}", response_model=ApplyResult)
def note_apply(course_id: str) -> ApplyResult:
    """确认落盘——写的是缓存里预览过的那份;没有缓存(过期/重启)则现生成。"""
    _require_ready(course_id)
    d = _DRAFT_CACHE.get(course_id)
    if d is None:
        d = build_draft(course_id)
    apply_draft(d)
    _DRAFT_CACHE.pop(course_id, None)
    return ApplyResult(written=True, note_path=d["note_path"])


@router.get("/review/due", response_model=ReviewDue)
def review_due() -> ReviewDue:
    """今日到期复习卡(进课堂重测,批改后自动排下一次)。"""
    return due_reviews()
