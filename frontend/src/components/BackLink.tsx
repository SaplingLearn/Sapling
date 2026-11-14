"use client";

import Link from "next/link";
import { Icon } from "./Icon";

/**
 * The back button of a page you reach FROM another one (the Study tools:
 * Quiz, Flashcards, Study Guide). One look and one place on all of them: an
 * outlined header button, LAST in the header's actions, so it is always the
 * control in the top right corner.
 *
 * A header has one of these, and it goes up one level: a tool's own screen
 * goes back to Study; a screen inside a tool (a flashcard review, the set
 * builder) goes back to that tool's home.
 *
 * With `href` it is a link, not `router.back()`: it names where it goes and
 * still works on a reload, a new tab, or a page opened from a bookmark, where
 * there is no history entry to go back to. With `onClick` it is a button, for
 * a step back inside one page.
 */
type BackLinkProps = {
  label: string;
  /** Overrides the accessible name (a link's is "Back to {label}", a
   *  button's is its label). */
  ariaLabel?: string;
} & ({ href: string; onClick?: undefined } | { onClick: () => void; href?: undefined });

const STYLE: React.CSSProperties = {
  height: 40, padding: "0 14px", gap: 6, fontSize: "var(--fs-md)", whiteSpace: "nowrap", flexShrink: 0,
};

export function BackLink({ label, ariaLabel, href, onClick }: BackLinkProps) {
  const inside = <><Icon name="chevron-left" size={12} /> {label}</>;
  if (href === undefined) {
    return (
      <button type="button" className="btn" data-testid="back-link" aria-label={ariaLabel} style={STYLE} onClick={onClick}>
        {inside}
      </button>
    );
  }
  return (
    <Link
      href={href}
      className="btn"
      data-testid="back-link"
      aria-label={ariaLabel ?? (label === "Back" ? "Back" : `Back to ${label}`)}
      style={STYLE}
    >
      {inside}
    </Link>
  );
}
