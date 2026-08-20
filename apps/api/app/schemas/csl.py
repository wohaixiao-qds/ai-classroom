"""CSL（Courseware Markup Language）课件格式定义。

CSL 是课件的唯一事实源（JSON）：备课 Agent 产出它，编译器消费它
（生成音频、前端课件页）。Markdown 仅作人读预览导出，不参与流程。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------- 公共部分 ----------


class Sentence(BaseModel):
    """讲稿中的一句。一句 = 一个 TTS 音频文件 = 一次 fragment 步进。"""

    text: str
    audio: str | None = None  # TTS 产物路径，T2 阶段回填


class Fragment(BaseModel):
    """一个动画步进单元：讲稿第 with_sentence 句**开讲时**触发本动画。

    时序原则「讲到什么,亮什么」:元素在提到它的那句话开始时出现,
    而不是念完才出现。一句可带多个 fragment(如公式五项一起弹出)。
    """

    effect: str = "fade"  # 前端动画类名：fade / pop / rise / coderise ...
    target: str | None = None  # 作用目标选择器（页内元素 id），None=整页
    with_sentence: int  # 挂在第几句讲稿上(从 0 计,句开讲时触发)


class Checkpoint(BaseModel):
    """复述检查点：自学模式下页面讲完自动暂停，学员复述通过才继续。"""

    question: str  # 复述问题，如「用一句话说说三者谁大谁小」
    hint: str | None = None
    pass_rule: str | None = None  # 给批改 Agent 的通过标准描述


# ---------- 各页型内容 ----------


class CoverContent(BaseModel):
    kind: Literal["cover"] = "cover"
    equation: str | None = None  # 封面公式，如 "agent = LLM + harness"
    meta: list[tuple[str, str]] = []  # [(标签, 值)]，如 [("讲师", "AI 老师")]


class FormulaContent(BaseModel):
    kind: Literal["formula"] = "formula"
    items: list[str]  # 逐项弹出的公式元素，如 ["agent", "=", "LLM", "+", "harness"]
    conclusion: str  # 公式下方的大字结论


class DiagramContent(BaseModel):
    kind: Literal["diagram"] = "diagram"
    asset: str  # SVG 文件名（备课阶段产出，存 courses/assets/）
    legend: list[LegendItem] = []  # 图例：与 SVG 部件一一对应


class LegendItem(BaseModel):
    label: str
    color: str  # 设计 token 颜色
    note: str


class DuoContent(BaseModel):
    kind: Literal["duo"] = "duo"
    left: DuoCard
    right: DuoCard


class DuoCard(BaseModel):
    title: str
    tag: str  # 小标签，如「静态 · 菜单」
    body: str  # 支持简单 **加粗** 语法


class CodeContent(BaseModel):
    kind: Literal["code"] = "code"
    language: str = "python"
    lines: list[CodeLine]  # 逐行浮现，与讲稿句对齐
    note: str | None = None  # 代码下方结论


class CodeLine(BaseModel):
    code: str
    comment: str | None = None  # 行尾注释，如「决策 → LLM」
    highlight: str | None = None  # 高亮角色：llm / harness


class TableContent(BaseModel):
    kind: Literal["table"] = "table"
    headers: list[str]
    rows: list[list[str]]  # 每行依次浮现
    note: str | None = None


class QuizContent(BaseModel):
    kind: Literal["quiz"] = "quiz"
    questions: list[str]  # 依次滑入的自测题


_ContentUnion = (
    CoverContent | FormulaContent | DiagramContent
    | DuoContent | CodeContent | TableContent | QuizContent
)

PageContent = Annotated[_ContentUnion, Field(discriminator="kind")]


# ---------- 页与课程 ----------


class Page(BaseModel):
    id: str  # 页内唯一标识，如 "p2-formula"
    eyebrow: str | None = None  # 页眉小标（蓝色字）
    title: str | None = None
    content: PageContent
    script: list[Sentence]  # 本页讲稿（TTS 逐句）
    fragments: list[Fragment] = []  # 动画步进（数量应与 script 对齐）
    checkpoint: Checkpoint | None = None  # 自学版才有


class CourseMeta(BaseModel):
    source_notes: list[str] = []  # 来源笔记（知识库文件名），溯源用
    duration_min: int | None = None
    version: int = 1


class Course(BaseModel):
    """一份 CSL 课件 = 一个 .csl.json 文件。"""

    id: str  # 如 "harness-01"
    title: str
    scenario: Literal["自学", "复习", "对外"]  # 决定模板行为的场景标记
    meta: CourseMeta
    pages: list[Page]

    def page(self, page_id: str) -> Page:
        for p in self.pages:
            if p.id == page_id:
                return p
        raise KeyError(f"page not found: {page_id}")
