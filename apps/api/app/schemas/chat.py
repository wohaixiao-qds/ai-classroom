"""Schemas:答疑接口的请求/响应模型(前端类型将从 OpenAPI 生成,替代手写)。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    course_id: str  # 课件 id,如 "harness-01"
    current_page: str | None = None  # 学员当前页 id,回答可贴着进度
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = []  # 最近几轮,前端负责截断


class GradeRequest(BaseModel):
    course_id: str
    page_id: str
    answer: str = Field(min_length=1, max_length=2000)
