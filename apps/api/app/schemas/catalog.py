"""Schemas:课表(四泳道)接口的响应/请求模型(前端类型从 OpenAPI 生成,不手写)。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CourseItem(BaseModel):
    """在学的:已出课件(点击进课堂,带断点续播)。"""

    id: str
    title: str
    pages: int
    checkpoints: int
    topic: str | None = None  # 所属主题(课程库分组;旧课由 source_notes 实时推导)


class NoteItem(BaseModel):
    """能学的:有笔记但还没出课(点击触发备课 = P2 入口,本轮只记意图)。"""

    title: str  # 笔记文件名(去扩展名)
    path: str  # vault 相对路径,如 Agent/harness/03-Runtime/终止条件.md
    area: str  # 所属层级,如 "Agent / harness / Runtime"
    requested: bool = False  # 是否已请求备课
    status: str | None = None  # M5 执行态:running/done/failed(None=未请求)


class TodoItem(BaseModel):
    """想学的:待探清单里未打勾项(点击触发调研 = P3 入口,本轮只记意图)。"""

    title: str
    area: str
    hint: str | None = None
    requested: bool = False  # 是否已请求调研
    status: str | None = None  # M5 执行态


class SparkItem(BaseModel):
    """刚冒出的:学习中暴露的衍生候选(来源:trace 里 web_search 触发=课件未覆盖)。"""

    question: str
    key: str  # 归一化问题,作确认/忽略动作的 target
    page_id: str | None = None
    detail: str | None = None  # 当时联网搜的关键词
    confirmed: bool = False  # 是否已确认(值得单独学)


class Catalog(BaseModel):
    """课表四泳道。"""

    learning: list[CourseItem]
    notes: list[NoteItem]
    todo: list[TodoItem]
    sparks: list[SparkItem]


ActionKind = Literal["confirm_spark", "dismiss_spark", "request_prep", "request_research"]


class CatalogAction(BaseModel):
    """课表点击动作(Option B:只记意图,不造 P2/P3 逻辑)。"""

    kind: ActionKind
    target: str  # spark.key / note.path / todo.title
    label: str | None = None  # 展示用原文


class ActionResult(BaseModel):
    kind: str
    target: str
    status: str  # confirmed / dismissed / queued / running
    detail: str | None = None  # 后台执行时的日志路径/产出课件 id
