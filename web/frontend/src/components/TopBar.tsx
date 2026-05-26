import clsx from "clsx";
import { BarChart3, Briefcase, Moon, RefreshCw, Search, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export type TabKey = "dashboard" | "lookup" | "portfolio";

interface Props {
  tab: TabKey;
  onTab: (t: TabKey) => void;
  loadedAt?: string;
  onRefresh: () => void;
  refreshing: boolean;
}

const TABS: { key: TabKey; label: string; icon: typeof BarChart3 }[] = [
  { key: "dashboard", label: "Dashboard", icon: BarChart3 },
  { key: "lookup", label: "Lookup", icon: Search },
  { key: "portfolio", label: "Portfolio", icon: Briefcase },
];

export function TopBar({ tab, onTab, loadedAt, onRefresh, refreshing }: Props) {
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    const sys = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const useDark = stored ? stored === "dark" : sys;
    document.documentElement.classList.toggle("dark", useDark);
    setDark(useDark);
  }, []);

  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
    setDark(next);
  };

  return (
    <header className="sticky top-0 z-30 backdrop-blur bg-white/80 dark:bg-zinc-950/80 border-b border-zinc-200 dark:border-zinc-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center gap-4">
        <div className="flex items-center gap-2 font-bold tracking-tight">
          <span className="text-lg">📊</span>
          <span className="hidden sm:inline">Portfolio Intelligence</span>
        </div>

        <nav className="ml-4 flex gap-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => onTab(t.key)}
                className={clsx(
                  "flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
                  active
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800",
                )}
              >
                <Icon size={15} />
                <span className="hidden sm:inline">{t.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {loadedAt && (
            <span className="hidden md:inline text-xs text-zinc-500">
              loaded {loadedAt}
            </span>
          )}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="btn-ghost text-xs"
            aria-label="Refresh"
          >
            <RefreshCw
              size={14}
              className={refreshing ? "animate-spin" : ""}
            />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <button
            onClick={toggle}
            className="btn-ghost text-xs"
            aria-label="Toggle theme"
          >
            {dark ? <Sun size={14} /> : <Moon size={14} />}
          </button>
        </div>
      </div>
    </header>
  );
}
