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
