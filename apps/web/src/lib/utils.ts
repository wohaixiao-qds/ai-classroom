import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** 合并条件类名并去重冲突的 Tailwind 类(shadcn 标配) */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
