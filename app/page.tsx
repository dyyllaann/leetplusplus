import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col bg-[#f7f8f5]">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6">
        <Link href="/" className="text-lg font-bold tracking-tight text-[#17211d]">
          leet<span className="text-emerald-700">++</span>
        </Link>
        <span className="text-xs font-medium uppercase tracking-[0.16em] text-stone-500">Whiteboard practice</span>
      </header>
      <section className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-6 pb-24">
        <p className="mb-5 text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">Think it through, out loud</p>
        <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight text-[#17211d] sm:text-6xl">
          Practice coding interviews on your whiteboard, with a coach that asks instead of answers.
        </h1>
        <Link
          href="/problems"
          className="mt-9 inline-flex w-fit items-center gap-3 rounded-md bg-[#174d3b] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#103c2e] focus:outline-none focus:ring-2 focus:ring-emerald-700 focus:ring-offset-2"
        >
          Start practicing <span aria-hidden="true">-&gt;</span>
        </Link>
      </section>
      <footer className="border-t border-stone-200 px-6 py-4 text-xs text-stone-500">
        <div className="mx-auto max-w-6xl">A quieter way to get interview-ready.</div>
      </footer>
    </main>
  );
}