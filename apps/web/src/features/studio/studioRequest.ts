import type { components } from "../../types/api.gen";

export type StudioJobFocus = Pick<components["schemas"]["JobSummary"], "kind" | "target">;

export async function studioRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(typeof data?.detail === "string" ? data.detail : `请求失败（HTTP ${response.status}）`);
  }
  return data as T;
}
