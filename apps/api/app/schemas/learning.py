"""Schemas:学习进度与笔记写回(P3·N2)——类型从 OpenAPI 生成,前端不手写。"""

from __future__ import annotations

from typing import Literal

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


class CumulativeItem(BaseModel):
    """书末综合复测卷的一道题(T3):定位信息 + 题面,提交走现有 /grade 链。

    page_id 即 quiz 块 id——前端拿 (course_id, page_id) 直接 POST /api/v1/grade,
    与阅读器复述卡同一入参形态;pass_rule 是出题人写的判分标准(批改端作通过标准)。
    """

    course_id: str
    course_title: str
    section_id: str  # 节 id
    section_no: int  # 节序(1 起算),深链 /read/:id?section=N 回读对应节用
    section_heading: str
    page_id: str
    question: str
    hint: str | None = None
    pass_rule: str | None = None
    mastery: float | None = None  # 当前掌握度;None=从未测过
    due: bool = False  # 复习已到期未测(薄弱优先的第一梯队)
    fresh_pass: bool = False  # 全书读完之后已重新 pass 过


class CumulativePaper(BaseModel):
    """书末综合复测组卷(T3):一本书全部课程读完后的邀请状态 + 抽样卷。

    status: not_ready=书没读完(前端不显横幅) / available=邀请复测 /
    completed=本轮综合复测已通过(横幅不再自动出,可重测但明确标注)。
    """

    status: Literal["not_ready", "available", "completed"]
    topic: str
    total_checkpoints: int  # 全书检查点总数
    passed_count: int  # 卷内「读完之后已 pass」的题数
    items: list[CumulativeItem]
