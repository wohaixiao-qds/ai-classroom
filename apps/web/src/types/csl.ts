// CSL 课件类型（与 apps/api/app/schemas/csl.py 镜像）
// 为何手写不走 gen-types(2026-08-24 定,取代原 T5 TODO):课件不经 HTTP 端点
// (前端直接读静态 /courses/*.csl.json),无 OpenAPI 可生成;CSL 是稳定的作者态
// 契约。后端 schemas/csl.py 一变,记得同步改这份镜像。
// gen-types 已覆盖走 HTTP 的契约:见 types/api.gen.ts(catalog/sessions)。

export type Scenario = "自学" | "复习" | "对外";

export interface Sentence {
  text: string;
  audio: string | null;
}

export interface Fragment {
  effect: string; // fade/pop/rise/coderise/rowIn/quizIn/...
  target: string | null;
  with_sentence: number; // 挂在第几句讲稿上(句开讲时触发)
}

export interface Checkpoint {
  question: string;
  hint: string | null;
  pass_rule: string | null;
}

export type PageContent =
  | { kind: "cover"; equation: string | null; meta: [string, string][] }
  | { kind: "formula"; items: string[]; conclusion: string; derived: string | null }
  | { kind: "diagram"; asset: string; legend: LegendItem[] }
  | { kind: "duo"; left: DuoCard; right: DuoCard }
  | { kind: "code"; language: string; lines: CodeLine[]; note: string | null }
  | { kind: "table"; headers: string[]; rows: string[][]; note: string | null }
  | { kind: "quiz"; questions: string[] };

export interface LegendItem {
  label: string;
  color: string;
  note: string;
}

export interface DuoCard {
  title: string;
  tag: string;
  body: string;
}

export interface CodeLine {
  code: string;
  comment: string | null;
  highlight: string | null;
}

export interface Page {
  id: string;
  eyebrow: string | null;
  title: string | null;
  content: PageContent;
  script: Sentence[];
  fragments: Fragment[];
  checkpoint: Checkpoint | null;
}

export interface SourceRef {
  /** 调研来源(有据可查链路终点;新课走找资料时填,复习课通常为空) */
  title: string;
  url: string;
}

export interface CourseDep {
  /** 先修依赖(学习顺序):开课前建议先学完的课。只作展示,不锁进入 */
  id: string;
  reason: string | null;
}

export interface Course {
  id: string;
  title: string;
  scenario: Scenario;
  meta: {
    source_notes: string[];
    sources?: SourceRef[];
    topic?: string | null; // 所属主题(课程库分组)
    depends_on?: CourseDep[]; // 先修依赖(root 课为空)
    duration_min: number | null;
    version: number;
  };
  pages: Page[];
}

// ---------- v2 书页模型(P6):节→块,与 schemas/csl.py CourseV2 镜像 ----------

export type Block =
  | { type: "p"; text: string }
  | { type: "diagram"; lang: "mermaid"; code: string; caption: string | null }
  | { type: "code"; language: string; code: string; caption: string | null }
  | { type: "table"; header: string[]; rows: string[][]; caption: string | null }
  | { type: "callout"; kind: "tip" | "warn" | "note"; text: string }
  | { type: "quiz"; id: string; question: string; hint: string | null; pass_rule: string | null }
  | { type: "flashcards"; cards: Flashcard[] };

export interface Flashcard {
  front: string;
  back: string;
}

export interface Section {
  /** 迁移课的节 id = 旧页 id(复习历史零映射成本) */
  id: string;
  heading: string;
  blocks: Block[];
  audio: { path: string } | null; // 留位(TTS 砍留位,暂恒 null)
}

export interface CourseV2 {
  id: string;
  title: string;
  scenario: Scenario;
  version: 2;
  meta: Course["meta"];
  sections: Section[];
}

/** 按顶层 version 分派(与后端 parse_course 同约定) */
export function parseCourse(d: unknown): Course | CourseV2 {
  const o = d as Record<string, unknown>;
  return o && o.version === 2 ? (d as CourseV2) : (d as Course);
}

export function isV2(c: Course | CourseV2): c is CourseV2 {
  return (c as CourseV2).version === 2;
}
