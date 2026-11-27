"use client";

/**
 * Library → Tree / Quiz CTAs (W8.1). Renders the status line and deep links
 * from `libraryNext`; callers supply flag-resolved visibility.
 */

import Link from "next/link";
import type { LibraryNext } from "@/lib/libraryNext";
import styles from "./LibraryNextCtas.module.css";

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
      className={styles.card}
    >
      {next.statusLine && (
        <div
          data-testid={`${testIdPrefix}-status`}
          className={styles.status}
        >
          {next.statusLine}
        </div>
      )}
      {(next.treeHref || next.quizHref) && (
        <div className={styles.actions}>
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
