import {
  Code,
  Image as ImageIcon,
  CircleHelp,
  Clapperboard,
  FileText,
  Scale,
  Sigma,
  Table,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** 课件页型 → 图标(详情页大纲 + 课堂页边栏共用一份,lucide 统一,替代散落的 emoji) */
const KIND_ICON: Record<string, LucideIcon> = {
  cover: Clapperboard,
  formula: Sigma,
  diagram: ImageIcon,
  duo: Scale,
  code: Code,
  table: Table,
  quiz: CircleHelp,
};

export function KindIcon({ kind, size = 13 }: { kind: string; size?: number }) {
  const Icon = KIND_ICON[kind] ?? FileText;
  return <Icon size={size} className="shrink-0" />;
}
