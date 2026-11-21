import Link from "next/link";

export default function NotFound() {
  return (
    <section className="rounded-lg border border-line bg-surface p-6">
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-3 text-muted">
        There is no area manager or store at this address in the latest engine run.
      </p>
      <p className="mt-4">
        <Link href="/" className="font-semibold underline decoration-line decoration-2 hover:decoration-ink">
          Go to the list of area managers
        </Link>
      </p>
    </section>
  );
}
