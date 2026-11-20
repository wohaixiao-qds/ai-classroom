// 共享结构只由 Pydantic 生成;此文件保留稳定的 import 出口和前端视图函数。
import type { components } from "./csl.gen";

export type Course = components["schemas"]["Course"];
export type CourseV2 = components["schemas"]["CourseV2"];
export type Scenario = Course["scenario"];
export type Sentence = components["schemas"]["Sentence"];
export type Fragment = components["schemas"]["Fragment"];
export type Checkpoint = components["schemas"]["Checkpoint"];
export type Page = components["schemas"]["Page"];
export type PageContent = Page["content"];
export type LegendItem = components["schemas"]["LegendItem"];
export type DuoCard = components["schemas"]["DuoCard"];
export type CodeLine = components["schemas"]["CodeLine"];
export type SourceRef = components["schemas"]["SourceRef"];
export type CourseDep = components["schemas"]["CourseDep"];
export type EvidenceItem = components["schemas"]["EvidenceItem"];
export type Section = components["schemas"]["Section"];
export type Block = Section["blocks"][number];
export type Flashcard = components["schemas"]["Flashcard"];

/** 按顶层 version 分派(与后端 parse_course 同约定) */
export function parseCourse(d: unknown): Course | CourseV2 {
  const o = d as Record<string, unknown>;
  return o && o.version === 2 ? (d as CourseV2) : (d as Course);
}

export function isV2(c: Course | CourseV2): c is CourseV2 {
  return (c as CourseV2).version === 2;
}

/** 节/页统一视图:课表卡片与详情页不关心课件版本(P6 过渡期双版本) */
export interface UnitStat {
  id: string;
  title: string;
  hasCheckpoint: boolean;
  sentences: number;
  /** v1 页型(cover/formula/...);v2 节无此概念 */
  kind?: string;
}

export function courseUnits(c: Course | CourseV2): UnitStat[] {
  if (isV2(c))
    return c.sections.map((s) => ({
      id: s.id,
      title: s.heading,
      hasCheckpoint: s.blocks.some((b) => b.type === "quiz"),
      sentences: 0,
    }));
  return c.pages.map((p) => ({
    id: p.id,
    title: p.title || p.eyebrow || p.id,
    hasCheckpoint: !!p.checkpoint,
    sentences: p.script.length,
    kind: p.content.kind,
  }));
}

export type AnyCourse = components["schemas"]["AnyCourse"];
