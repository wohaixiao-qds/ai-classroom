import { NavLink, Outlet } from "react-router-dom";
import { ThemeSwitcher } from "../features/player/ThemeSwitcher";

/** 带顶栏的外壳(课表/观测用);课堂页沉浸不套这层 */
export function Shell() {
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1 rounded-full text-sm transition-colors ${
      isActive ? "bg-(--accent) font-medium text-(--bg)" : "muted hover:text-(--text)"
    }`;
  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-6 border-b border-(--line) px-6 py-3">
        <span className="font-bold">AI 教室</span>
        <nav className="flex gap-1">
          <NavLink to="/" className={link} end>
            课表
          </NavLink>
          <NavLink to="/eval" className={link}>
            观测
          </NavLink>
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
