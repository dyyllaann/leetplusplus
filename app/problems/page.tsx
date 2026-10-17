import Link from "next/link";
import problems from "@/data/problems.json";

const difficultyStyle: Record<string, string> = {
  Easy: "text-emerald-800 bg-emerald-50",
  Medium: "text-amber-800 bg-amber-50",
  Hard: "text-rose-800 bg-rose-50",
};

export default function ProblemsPage() {
  return (
    <main className="min-h-screen bg-[#f7f8f5]">
      <header className="border-b border-stone-200">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Link href="/" className="text-lg font-bold tracking-tight text-[#17211d]">
            leet<span className="text-emerald-700">++</span>
          </Link>
          <span className="text-sm text-stone-500">Practice set</span>
        </div>
      </header>
      <section className="mx-auto max-w-6xl px-6 py-12">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">Choose a problem</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[#17211d]">Practice set</h1>
        <ul className="mt-8 divide-y divide-stone-200 border-y border-stone-200">
          {problems.map((problem) => (
            <li key={problem.id}>
              <Link
                href={`/problems/${problem.id}`}
                className="group grid gap-3 py-5 transition hover:bg-white/60 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-3"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-lg font-semibold text-[#17211d] group-hover:text-emerald-800">{problem.title}</h2>
                    <span className={`rounded px-2 py-1 text-xs font-medium ${difficultyStyle[problem.difficulty]}`}>
                      {problem.difficulty}
                    </span>
                  </div>
                  <p className="mt-1 max-w-2xl text-sm leading-6 text-stone-600">{problem.summary}</p>
                  <ul className="mt-3 flex flex-wrap gap-2" aria-label="Patterns">
                    {problem.patterns.map((pattern) => (
                      <li key={pattern} className="border border-stone-300 px-2 py-1 text-xs text-stone-600">
                        {pattern}
                      </li>
                    ))}
                  </ul>
                </div>
                <span className="text-sm font-medium text-emerald-800">Open <span aria-hidden="true">-&gt;</span></span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}