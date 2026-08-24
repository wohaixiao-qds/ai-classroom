/** 课表类型 —— 从 OpenAPI 生成产物(api.gen.ts)派生,不再手写(边界铁律 2)。
 *
 *  重新生成:后端起在 :8100 后运行 `pnpm gen-types`(拉 /openapi.json)。
 *  历史:B1 阶段这些是手写的;接上 gen-types 管线后改为派生,后端 schema 变更前端自动跟随。
 */
import type { components } from "./api.gen";

type Schemas = components["schemas"];

export type CourseItem = Schemas["CourseItem"];
export type NoteItem = Schemas["NoteItem"];
export type TodoItem = Schemas["TodoItem"];
export type SparkItem = Schemas["SparkItem"];
export type Catalog = Schemas["Catalog"];
export type ActionKind = Schemas["CatalogAction"]["kind"];
