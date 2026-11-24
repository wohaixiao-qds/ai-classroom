"""Schemas:学习进度与笔记写回(P3·N2)——类型从 OpenAPI 生成,前端不手写。"""

from __future__ import annotations

from pydantic import BaseModel


class CompletionState(BaseModel):
    done: bool
    checkpoints_total: int
    checkpoints_passed: int
    ready: bool  # 学完(进度到底+检查点全过)→ 允许写回


class TodoEdit(BaseModel):
    file: str
    old_line: str
    new_line: str


class NoteDraft(BaseModel):
    mode: str  # new / new-root / append
    title: str
    note_path: str
    content: str
    todo_edit: TodoEdit | None = None


class ApplyResult(BaseModel):
    written: bool
    note_path: str


class ReviewItem(BaseModel):
    """一条到期的复习卡:某个检查点该重测了。"""

    course_id: str
    course_title: str
    page_id: str
    page_title: str
    page_no: int  # 1 起算,前端 ?page= 深链直接用
    question: str  # 复述问题(卡片上直接展示)
    mastery: float  # 0~1,当前掌握度
    next_review_at: str
    overdue_days: int  # 逾期天数(0=今天到期)
    gaps: list[str] = []  # 最近一次带错因批改的缺失点(T2「上次漏了」);闪卡/旧数据为空


class ReviewDue(BaseModel):
    """今日复习清单 + 现役复习卡总数。"""

    items: list[ReviewItem]
    total: int
