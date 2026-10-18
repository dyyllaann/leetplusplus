"use client";

import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [isDarkMode, setIsDarkMode] = useState(false);

  useEffect(() => {
    setIsDarkMode(document.documentElement.dataset.theme === "dark");
  }, []);

  function toggleTheme() {
    const nextIsDark = document.documentElement.dataset.theme !== "dark";
    document.documentElement.dataset.theme = nextIsDark ? "dark" : "light";
    window.localStorage.setItem("leetplusplus-theme", nextIsDark ? "dark" : "light");
    setIsDarkMode(nextIsDark);
  }

  return (
    <button
      type="button"
      aria-label={`Switch to ${isDarkMode ? "light" : "dark"} mode`}
      aria-pressed={isDarkMode}
      onClick={toggleTheme}
      className="rounded border border-stone-300 px-2 py-1.5 text-xs font-medium text-stone-700 hover:bg-white sm:px-3"
    >
      {isDarkMode ? "Light mode" : "Dark mode"}
    </button>
  );
}