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
    session_id: str | None = None  # 会话 id;缺省则后端新建(记忆归后端,前端不递历史)
    source: str = "user"  # user=真实使用 / test=调试(观测统计默认只算 user)


class GradeRequest(BaseModel):
    course_id: str
    page_id: str
    answer: str = Field(min_length=1, max_length=2000)


class SessionInfo(BaseModel):
    """会话列表项(A5 历史对话)。"""

    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    asks: int


class SessionTurn(BaseModel):
    """会话详情里的一轮(仅文本轮,给前端渲染)。"""

    role: str
    content: str
    ts: str


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo]


class SessionDetailResponse(BaseModel):
    turns: list[SessionTurn]


class SessionCreateResponse(BaseModel):
    session_id: str
