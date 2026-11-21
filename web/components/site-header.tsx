import Link from "next/link";
import { formatDate, formatIstDateTime } from "@/lib/format";

const NAV = [
  { href: "/", label: "Area managers" },
  { href: "/follow-up", label: "Follow-up" },
  { href: "/data-issues", label: "Data issues" },
  { href: "/method", label: "How it's checked" },
];

export function SiteHeader({
  generatedAt,
  asOf,
  developmentData,
}: {
  generatedAt: string | null;
  asOf: string | null;
  developmentData: boolean;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 shadow-[0_1px_0_var(--line)] backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      {developmentData ? (
        <p className="bg-warn-bg px-4 py-2 text-center text-sm font-semibold text-warn-ink">
          Development sample data. These are not real stores or real figures.
        </p>
      ) : null}
      <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 pt-2 sm:px-6 sm:pt-3">
        <Link href="/" className="text-lg font-semibold tracking-tight no-underline">
          Store Coach
        </Link>
        <nav aria-label="Main" className="-mx-2 flex flex-wrap text-sm sm:text-[0.95rem]">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-md px-2 py-1.5 font-medium underline decoration-line decoration-2 hover:bg-paper hover:decoration-ink active:bg-line sm:py-2"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
      <p className="mx-auto w-full max-w-3xl px-4 pb-2 text-xs text-muted sm:px-6 sm:pb-3 sm:text-sm">
        {generatedAt && asOf ? (
          <>
            Engine last ran {formatIstDateTime(generatedAt)}. Data up to {formatDate(asOf)}.
          </>
        ) : (
          <>No engine run has been published yet.</>
        )}
      </p>
    </header>
  );
}
