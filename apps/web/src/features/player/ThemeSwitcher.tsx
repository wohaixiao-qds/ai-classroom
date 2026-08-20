import { useEffect, useState } from "react";

type ThemeId = "a" | "b" | "c";

const THEMES: { id: ThemeId; label: string }[] = [
  { id: "a", label: "石墨琥珀" },
  { id: "b", label: "墨蓝青" },
  { id: "c", label: "暖纸橙" },
];

const KEY = "classroom-theme";

/** 三套配色切换:写到 <html data-theme>,localStorage 持久化。默认 B(墨蓝青) */
export function ThemeSwitcher() {
  const [theme, setTheme] = useState<ThemeId>(() => {
    const saved = localStorage.getItem(KEY);
    return saved === "a" || saved === "b" || saved === "c" ? saved : "b";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(KEY, theme);
  }, [theme]);

  return (
    <div className="fixed top-4 right-4 z-50 flex gap-1 rounded-full border border-(--line) bg-(--surface) px-2 py-1 text-xs">
      {THEMES.map((t) => (
        <button
          key={t.id}
          onClick={() => setTheme(t.id)}
          className={`rounded-full px-3 py-1 transition-colors ${
            theme === t.id ? "bg-(--accent) font-medium text-(--bg)" : "muted hover:text-(--text)"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
