"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import problems from "@/data/problems.json";
import ThemeToggle from "@/app/theme-toggle";

const FAVORITES_KEY = "leetplusplus:starred-problems";

const difficultyStyle: Record<string, string> = {
  Easy: "text-emerald-800 bg-emerald-50",
  Medium: "text-amber-800 bg-amber-50",
  Hard: "text-rose-800 bg-rose-50",
};

export default function ProblemsPage() {
  const [starredIds, setStarredIds] = useState<string[]>([]);
  const [favoritesLoaded, setFavoritesLoaded] = useState(false);

  useEffect(() => {
    try {
      const saved: unknown = JSON.parse(window.localStorage.getItem(FAVORITES_KEY) ?? "[]");
      if (Array.isArray(saved) && saved.every((id): id is string => typeof id === "string")) {
        setStarredIds(saved);
      }
    } catch (error) {
      console.error("Could not load starred problems.", error);
    }
    setFavoritesLoaded(true);
  }, []);

  useEffect(() => {
    if (!favoritesLoaded) return;
    try {
      window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(starredIds));
    } catch (error) {
      console.error("Could not save starred problems.", error);
    }
  }, [favoritesLoaded, starredIds]);

  function toggleStar(problemId: string) {
    setStarredIds((current) => current.includes(problemId)
      ? current.filter((id) => id !== problemId)
      : [...current, problemId]);
  }

  return (
    <main className="min-h-screen bg-[#f7f8f5]">
      <header className="border-b border-stone-200">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Link href="/" className="text-lg font-bold tracking-tight text-[#17211d]">
            leet<span className="text-emerald-700">++</span>
          </Link>
          <div className="flex items-center gap-4">
            <span className="text-sm text-stone-500">Practice set</span>
            <ThemeToggle />
          </div>
        </div>
      </header>
      <section className="mx-auto max-w-6xl px-6 py-12">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">Choose a problem</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[#17211d]">Practice set</h1>
        <ul className="mt-8 divide-y divide-stone-200 border-y border-stone-200">
          {problems.map((problem) => (
            <li key={problem.id} className="group flex items-stretch transition hover:bg-white/60">
              <Link
                href={`/problems/${problem.id}`}
                className="flex min-w-0 flex-1 items-center gap-3 px-3 py-3"
              >
                <h2 className="truncate text-base font-semibold text-[#17211d] group-hover:text-emerald-800">{problem.title}</h2>
                <span className={`shrink-0 rounded px-2 py-1 text-xs font-medium ${difficultyStyle[problem.difficulty]}`}>
                  {problem.difficulty}
                </span>
                <span className="hidden min-w-0 truncate text-xs text-stone-500 sm:block">
                  {problem.patterns.join(" · ")}
                </span>
              </Link>
              <button
                type="button"
                onClick={() => toggleStar(problem.id)}
                aria-label={`${starredIds.includes(problem.id) ? "Unstar" : "Star"} ${problem.title}`}
                aria-pressed={starredIds.includes(problem.id)}
                className="flex w-12 shrink-0 items-center justify-center text-2xl text-amber-600 transition hover:bg-amber-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill={starredIds.includes(problem.id) ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
                  <path strokeLinecap="round" strokeLinejoin="round" d="m12 3 2.7 5.47 6.03.88-4.36 4.25 1.03 6.01L12 16.77l-5.4 2.84 1.03-6.01-4.36-4.25 6.03-.88L12 3Z" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}