import { Activity, GraduationCap, Wand2 } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { ThemeSwitcher } from "../components/ThemeSwitcher";
import { cn } from "../lib/utils";

/** 学习台与课程库合二为一(2026-11-17 拍板):课程库升级为学习主页(今日横条+封面继续读),
 *  学习台退役(/ 重定向 /courses)。导航三项:学习/生成中心/观测。 */
const NAV = [
  { to: "/courses", label: "学习", icon: GraduationCap, end: false },
  { to: "/studio", label: "生成中心", icon: Wand2, end: false },
  { to: "/eval", label: "观测", icon: Activity, end: false },
];
export function Shell() {
  const link = ({ isActive }: { isActive: boolean }) =>
    cn(
      "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
      isActive
        ? "bg-primary/15 font-medium text-primary"
        : "text-muted-foreground hover:bg-accent hover:text-foreground",
    );
  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-8 border-b border-border px-6 py-3">
        <span className="flex items-center gap-2 font-bold tracking-wide">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary/15 text-primary">
            <GraduationCap size={16} />
          </span>
          AI 教室
        </span>
        <nav className="flex gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} className={link} end={end} viewTransition>
              <Icon size={14} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto">
          <ThemeSwitcher />
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
