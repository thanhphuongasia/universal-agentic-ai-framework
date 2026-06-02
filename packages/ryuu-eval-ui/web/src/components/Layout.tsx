import { NavLink, Outlet } from "react-router-dom";
import { LayoutDashboard, FlaskConical, GitCompare, ClipboardCheck } from "lucide-react";
import { DarkModeToggle } from "@/components/DarkModeToggle";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ProjectSwitcher } from "@/components/ProjectSwitcher";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/suites", label: "Suites", icon: FlaskConical },
  { to: "/compare", label: "Compare", icon: GitCompare },
  { to: "/oracle-review", label: "Golden Dataset", icon: ClipboardCheck },
];

export function Layout() {
  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 border-r border-gray-200 dark:border-gray-800 flex flex-col">
        <div className="px-4 py-4 border-b border-gray-200 dark:border-gray-800">
          <span className="font-semibold text-sm tracking-wide text-purple-600 dark:text-purple-400">
            Eval Testing System
          </span>
        </div>

        {/* Project switcher */}
        <div className="pt-2 border-b border-gray-200 dark:border-gray-800">
          <div className="px-3 pb-1 text-[10px] font-medium text-gray-400 uppercase tracking-wider">
            Project
          </div>
          <ProjectSwitcher />
        </div>

        <nav className="flex-1 p-2 space-y-0.5">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 font-medium"
                    : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
                }`
              }
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <span className="text-xs text-gray-400">v0.2.0</span>
          <DarkModeToggle />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}
