export default function Home() {
  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="mx-auto max-w-6xl px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold">Geeta Complex</h1>
          <nav className="text-sm text-slate-600 space-x-4">
            <a href="/admin" className="hover:underline">Admin</a>
            <a href="/catalog" className="hover:underline">Catalog</a>
            <a href="/pos" className="hover:underline">POS</a>
          </nav>
        </div>
      </header>
      <section className="mx-auto max-w-6xl px-4 py-8">
        <h2 className="text-lg font-medium">Welcome 👋</h2>
        <p className="mt-2 text-slate-600">Day 1: set up UI + a simple product list.</p>
      </section>
    </main>
  );
}
