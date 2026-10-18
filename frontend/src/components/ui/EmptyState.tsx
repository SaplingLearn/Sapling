"use client";
import React from "react";
import { Icon } from "@/components/Icon";

/**
 * EmptyState — "there's nothing here yet, and here's the way out" (#537).
 *
 * Promoted from the private component inside `screens/Gradebook/Landing.tsx`,
 * which was the only real empty state in the app; the quiz's two ("add a
 * course", "your tree is empty") would otherwise have been the second and
 * third one-off. Landing now imports this.
 *
 * `size="hero"` is Landing's treatment — a display-scale title that owns a
 * whole blank screen. `md` (the default) is the in-page version the quiz uses.
 * An empty state is never a dead end: `action` is the way out, and callers are
 * expected to supply one.
 */
export interface EmptyStateProps {
  title: string;
  body?: string;
  /** A link out, or any control the caller would rather build itself. */
  action?: { label: string; href: string } | React.ReactNode;
  /** Mono/uppercase line above the title. */
  eyebrow?: string;
  /** Name from `components/Icon`. */
  icon?: string;
  size?: "md" | "hero";
  testid?: string;
}

function isHrefAction(a: EmptyStateProps["action"]): a is { label: string; href: string } {
  return (
    typeof a === "object" &&
    a !== null &&
    "href" in a &&
    typeof (a as { href?: unknown }).href === "string"
  );
}

export function EmptyState({
  title,
  body,
  action,
  eyebrow,
  icon,
  size = "md",
  testid,
}: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state--${size}`} data-testid={testid}>
      {icon && (
        <span className="empty-state__icon" aria-hidden="true">
          <Icon name={icon} size={size === "hero" ? 28 : 20} />
        </span>
      )}
      {eyebrow && <div className="empty-state__eyebrow label-micro">{eyebrow}</div>}
      <h2 className="empty-state__title h-serif">{title}</h2>
      {body && <p className="empty-state__body body-serif">{body}</p>}
      {action && (
        <div className="empty-state__action">
          {isHrefAction(action) ? (
            <a className="btn btn--primary" href={action.href}>
              {action.label}
            </a>
          ) : (
            action
          )}
        </div>
      )}
    </div>
  );
}
