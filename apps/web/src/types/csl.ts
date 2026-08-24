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

export interface Course {
  id: string;
  title: string;
  scenario: Scenario;
  meta: {
    source_notes: string[];
    sources?: SourceRef[];
    topic?: string | null; // 所属主题(课程库分组)
    duration_min: number | null;
    version: number;
  };
  pages: Page[];
}
