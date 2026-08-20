// CSL 课件类型（与 apps/api/app/schemas/csl.py 镜像）
// TODO(T5): FastAPI 就绪后,本文件替换为 packages/api-types 的 OpenAPI 生成产物,删除手写副本

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

export interface Course {
  id: string;
  title: string;
  scenario: Scenario;
  meta: { source_notes: string[]; duration_min: number | null; version: number };
  pages: Page[];
}
