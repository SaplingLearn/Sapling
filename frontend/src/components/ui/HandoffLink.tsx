"use client";
import React from "react";
import Link from "next/link";
import type { HandoffCta } from "@/lib/learningHandoffs";

// One link for every hand-off between surfaces (Tutor ↔ Study ↔ Quiz ↔ Tree;
// Tutor redesign phase 2). It is always a real next/link: client navigation,
// a URL on hover, and cmd/ctrl/shift/middle-click opening a new tab or window
// — which a raw <a> (a full reload) or a router.push button (no new tab)
// each lose. `onNavigate` takes a plain left click only, for a surface that
// plays its exit first (the Study hub's fade, `useToolNav.leaveTo`).
//
// - variant: primary | secondary (default) — the .btn shapes, as <Button>;
//            text — the bare text link (`btn--link`);
//            plain — no button class, for a surface with its own link style.
// - size:    sm | md (default).

type Variant = "primary" | "secondary" | "text" | "plain";

export type HandoffLinkProps = Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  variant?: Variant;
  size?: "sm" | "md";
  testId?: string;
  /** Takes a plain left click (e.g. to animate out, then navigate). */
  onNavigate?: (href: string) => void;
};

/** A left click with no modifier: the only click a surface may take over. */
export function isPlainClick(e: React.MouseEvent): boolean {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

function linkClass(variant: Variant, size: "sm" | "md", className?: string): string | undefined {
  const cls = [
    variant !== "plain" && "btn",
    variant === "primary" && "btn--primary",
    variant === "text" && "btn--link",
    variant !== "plain" && size === "sm" && "btn--sm",
    className,
  ].filter(Boolean).join(" ");
  return cls || undefined;
}

export const HandoffLink = React.forwardRef<HTMLAnchorElement, HandoffLinkProps>(function HandoffLink(
  { href, variant = "secondary", size = "md", testId, onNavigate, className, onClick, children, ...rest },
  ref,
) {
  return (
    <Link
      ref={ref}
      href={href}
      data-testid={testId}
      className={linkClass(variant, size, className)}
      {...rest}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented || !onNavigate || !isPlainClick(e)) return;
        e.preventDefault();
        onNavigate(href);
      }}
    >
      {children}
    </Link>
  );
});

/** A hand-off from `lib/learningHandoffs.ts`, as its link: its label, href
 *  and test id; `testId` overrides the id where one surface shows it twice. */
export function CtaLink({ cta, testId, ...props }: { cta: HandoffCta } & Omit<HandoffLinkProps, "href" | "children">) {
  return <HandoffLink href={cta.href} testId={testId ?? cta.testId} {...props}>{cta.label}</HandoffLink>;
}
