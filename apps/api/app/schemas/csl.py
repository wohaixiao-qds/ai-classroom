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


class SourceRef(BaseModel):
    """调研来源(有据可查链路的终点):网页 → 原料(带源) → 课件 meta.sources。"""

    title: str
    url: str


class CourseDep(BaseModel):
    """先修依赖(学习顺序):这门课开课之前建议先学完的课。人工/备课 agent 写,
    课表「下一步学」与课程库「建议先学」都从这里读;只作展示,不锁进入。"""

    id: str  # 先修课的课件 id(如 "harness-01")
    reason: str | None = None  # 一句话:为什么先学它


class CourseMeta(BaseModel):
    source_notes: list[str] = []  # 来源笔记（知识库文件名），溯源用
    sources: list[SourceRef] = []  # 调研来源(新课走找资料时带;复习课通常为空)
    topic: str | None = None  # 所属主题(备课 harness 从材料确定性写入;课程库分组用)
    depends_on: list[CourseDep] = []  # 先修依赖(学习顺序;root 课为空)
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

    def quiz_lookup(self) -> dict[str, tuple[int, str, str]]:
        """{页id: (页序, 标题, 问题)} —— 批改/复习按 id 定位检查点。"""
        out: dict[str, tuple[int, str, str]] = {}
        for i, p in enumerate(self.pages, 1):
            if p.checkpoint:
                out[p.id] = (i, p.title or p.eyebrow or p.id, p.checkpoint.question)
        return out

    def flash_lookup(self) -> dict[str, tuple[int, str, str]]:
        """v1 无闪卡,恒空(与 CourseV2 同接口,消费方免 isinstance)。"""
        return {}

    @property
    def unit_count(self) -> int:
        return len(self.pages)

    @property
    def checkpoint_count(self) -> int:
        return sum(1 for p in self.pages if p.checkpoint)


# ---------- v2 书页模型(P6):节→块,文字+插图,滚动阅读 ----------
# 设计见 docs/P6执行计划.md 第二节。与 v1 并存直至 M3 备课翻版:
# 顶层 "version": 2 是唯一格式标记(meta.version 是 v1 历史遗留,不作数)。


class ParagraphBlock(BaseModel):
    """书面 prose 段落;支持 **加粗** 与 `行内代码`。"""

    type: Literal["p"] = "p"
    text: str


class DiagramBlock(BaseModel):
    """mermaid 示意图(P6 插图):前端渲染失败降级为代码块。"""

    type: Literal["diagram"] = "diagram"
    lang: Literal["mermaid"] = "mermaid"
    code: str
    caption: str | None = None


class CodeBlock(BaseModel):
    type: Literal["code"] = "code"
    language: str = "text"
    code: str
    caption: str | None = None


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    header: list[str]
    rows: list[list[str]]
    caption: str | None = None


class CalloutBlock(BaseModel):
    type: Literal["callout"] = "callout"
    kind: Literal["tip", "warn", "note"] = "note"
    text: str


class QuizBlock(BaseModel):
    """复述检查点(原 v1 page.checkpoint)或自测题,内嵌节末。"""

    type: Literal["quiz"] = "quiz"
    id: str  # 课内唯一,如 "s3-cp";批改/复习按它定位
    question: str
    hint: str | None = None
    pass_rule: str | None = None


class Flashcard(BaseModel):
    front: str
    back: str


class FlashcardsBlock(BaseModel):
    """闪卡(P5·T5 并入):复习队列的消费单元。"""

    type: Literal["flashcards"] = "flashcards"
    cards: list[Flashcard]


_BlockUnion = (
    ParagraphBlock | DiagramBlock | CodeBlock | TableBlock
    | CalloutBlock | QuizBlock | FlashcardsBlock
)

Block = Annotated[_BlockUnion, Field(discriminator="type")]


class SectionAudio(BaseModel):
    """段级朗读留位(P6 拍板:TTS 先砍不加,字段位留给未来)。"""

    path: str


class Section(BaseModel):
    """书页的一节:标题 + 有序块列表。一节 ≈ 原 v1 一页的容量。"""

    id: str  # 迁移时沿用旧页 id(批改/复习历史零映射成本)
    heading: str
    blocks: list[Block]
    audio: SectionAudio | None = None


class CourseV2(BaseModel):
    """v2 书页课件:滚动文章形态,文字+插图,检查点/闪卡内嵌。"""

    id: str
    title: str
    scenario: Literal["自学", "复习", "对外"]
    version: Literal[2] = 2  # 顶层格式标记
    meta: CourseMeta
    sections: list[Section]

    def section(self, section_id: str) -> Section:
        for s in self.sections:
            if s.id == section_id:
                return s
        raise KeyError(f"section not found: {section_id}")

    def quiz_lookup(self) -> dict[str, tuple[int, str, str]]:
        """{quiz块id 或 节id: (节序, 标题, 问题)} —— 兼容按节/按块两种定位。"""
        out: dict[str, tuple[int, str, str]] = {}
        for i, s in enumerate(self.sections, 1):
            for b in s.blocks:
                if isinstance(b, QuizBlock):
                    out[b.id] = (i, s.heading, b.question)
            first = next(
                (b for b in s.blocks if isinstance(b, QuizBlock)), None
            )
            if first is not None and s.id not in out:
                out[s.id] = (i, s.heading, first.question)
        return out

    @property
    def unit_count(self) -> int:
        return len(self.sections)

    @property
    def checkpoint_count(self) -> int:
        return sum(
            1 for s in self.sections for b in s.blocks if isinstance(b, QuizBlock)
        )

    def flash_lookup(self) -> dict[str, tuple[int, str, str]]:
        """{闪卡块id: (节序, 节标题, 首卡正面)} —— 闪卡 id 渲染期合成:<节id>-fc<序>。"""
        out: dict[str, tuple[int, str, str]] = {}
        for i, s in enumerate(self.sections, 1):
            j = 0
            for b in s.blocks:
                if isinstance(b, FlashcardsBlock):
                    front = b.cards[0].front if b.cards else ""
                    out[f"{s.id}-fc{j}"] = (i, s.heading, front)
                    j += 1
        return out


AnyCourse = Course | CourseV2


def parse_course(text: str) -> AnyCourse:
    """按顶层 version 分派装载(v1 无顶层 version 字段)。目录扫描/复习/课表统一走这里。"""
    import json

    d = json.loads(text)
    if isinstance(d, dict) and d.get("version") == 2:
        return CourseV2.model_validate(d)
    return Course.model_validate(d)
