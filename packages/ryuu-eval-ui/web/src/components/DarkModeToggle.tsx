import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

function getInitial(): boolean {
  const stored = localStorage.getItem("ryuu-eval-dark");
  if (stored !== null) return stored === "true";
  return false; // default to light
}

export function useDarkMode() {
  const [dark, setDark] = useState(getInitial);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("ryuu-eval-dark", String(dark));
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}

export function DarkModeToggle() {
  const { dark, toggle } = useDarkMode();
  return (
    <button
      onClick={toggle}
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      className="p-1.5 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
    >
      {dark ? <Sun size={14} /> : <Moon size={14} />}
    </button>
  );
}
