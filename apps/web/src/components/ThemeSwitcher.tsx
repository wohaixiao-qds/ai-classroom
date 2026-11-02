import { Check, Palette } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

type ThemeId = "a" | "b" | "c";

const THEMES: { id: ThemeId; label: string }[] = [
  { id: "a", label: "石墨琥珀" },
  { id: "b", label: "墨蓝青" },
  { id: "c", label: "暖纸橙" },
];

const KEY = "classroom-theme";

/** 配色切换(A4 收纳):三主题收进一个下拉,Shell 顶栏与课堂页共用。
 *  写到 <html data-theme>,localStorage 持久化。默认 B(墨蓝青) */
export function ThemeSwitcher() {
  const [theme, setTheme] = useState<ThemeId>(() => {
    const saved = localStorage.getItem(KEY);
    return saved === "a" || saved === "b" || saved === "c" ? saved : "b";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const current = THEMES.find((t) => t.id === theme)?.label ?? "主题";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="rounded-full text-muted-foreground" title="切换配色">
          <Palette size={13} />
          {current}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {THEMES.map((t) => (
          <DropdownMenuItem key={t.id} onClick={() => setTheme(t.id)}>
            <Check size={13} className={theme === t.id ? "text-primary" : "opacity-0"} />
            {t.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
