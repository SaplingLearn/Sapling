"use client";

/**
 * Library → Tree / Quiz CTAs (W8.1). Renders the status line and deep links
 * from `libraryNext`; callers supply flag-resolved visibility.
 */

import Link from "next/link";
import type { LibraryNext } from "@/lib/libraryNext";

export function LibraryNextCtas({
  next,
  quizLabel = "Quiz these concepts",
  testIdPrefix = "library-next",
}: {
  next: LibraryNext;
  quizLabel?: string;
  testIdPrefix?: string;
}) {
  if (!next.statusLine && !next.treeHref && !next.quizHref) return null;

  return (
    <div
      data-testid={testIdPrefix}
      style={{
        marginTop: 10,
        padding: 12,
        borderRadius: "var(--r-sm)",
        border: "1px solid var(--border)",
        background: "var(--bg-panel)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {next.statusLine && (
        <div
          data-testid={`${testIdPrefix}-status`}
          style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.4 }}
        >
          {next.statusLine}
        </div>
      )}
      {(next.treeHref || next.quizHref) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {next.treeHref && (
            <Link
              data-testid={`${testIdPrefix}-tree`}
              href={next.treeHref}
              className="btn btn--sm btn--ghost"
            >
              Open Tree
            </Link>
          )}
          {next.quizHref && (
            <Link
              data-testid={`${testIdPrefix}-quiz`}
              href={next.quizHref}
              className="btn btn--sm btn--primary"
            >
              {quizLabel}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
