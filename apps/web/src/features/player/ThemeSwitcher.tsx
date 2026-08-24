import { useEffect, useRef, useState } from "react";
import { Palette } from "lucide-react";

type ThemeId = "a" | "b" | "c";

const THEMES: { id: ThemeId; label: string }[] = [
  { id: "a", label: "石墨琥珀" },
  { id: "b", label: "墨蓝青" },
  { id: "c", label: "暖纸橙" },
];

const KEY = "classroom-theme";

/** 配色切换(A4 收纳):三主题收进一个 pill 菜单,不再常驻三按钮。
 *  写到 <html data-theme>,localStorage 持久化。默认 B(墨蓝青) */
export function ThemeSwitcher() {
  const [theme, setTheme] = useState<ThemeId>(() => {
    const saved = localStorage.getItem(KEY);
    return saved === "a" || saved === "b" || saved === "c" ? saved : "b";
  });
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(KEY, theme);
  }, [theme]);

  // 点外面收起
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const current = THEMES.find((t) => t.id === theme)?.label ?? "主题";

  return (
    <div ref={boxRef} className="relative text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className="muted flex items-center gap-1.5 rounded-full border border-(--line) px-3 py-1.5 hover:text-(--text)"
        title="切换配色"
      >
        <Palette size={13} />
        {current}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 flex flex-col gap-1 rounded-lg border border-(--line) bg-(--surface) p-1.5 shadow-lg">
          {THEMES.map((t) => (
            <button
              key={t.id}
              onClick={() => {
                setTheme(t.id);
                setOpen(false);
              }}
              className={`rounded-md px-3 py-1.5 text-left transition-colors ${
                theme === t.id
                  ? "bg-(--accent) font-medium text-(--bg)"
                  : "muted hover:bg-(--surface2) hover:text-(--text)"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
