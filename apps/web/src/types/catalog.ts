/** 课表(四泳道)类型 —— 手写,镜像后端 app/schemas/catalog.py。
 *  注:gen-types(OpenAPI→TS)管线尚未接入,暂沿用手写约定(同 csl.ts);
 *  接入后本文件应由生成产物替代(边界铁律 2)。 */

export interface CourseItem {
  id: string;
  title: string;
  pages: number;
  checkpoints: number;
}

export interface NoteItem {
  title: string;
  path: string;
  area: string;
  requested: boolean;
}

export interface TodoItem {
  title: string;
  area: string;
  hint: string | null;
  requested: boolean;
}

export interface SparkItem {
  question: string;
  key: string;
  page_id: string | null;
  detail: string | null;
  confirmed: boolean;
}

export interface Catalog {
  learning: CourseItem[];
  notes: NoteItem[];
  todo: TodoItem[];
  sparks: SparkItem[];
}

export type ActionKind = "confirm_spark" | "dismiss_spark" | "request_prep" | "request_research";
