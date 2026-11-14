"use client";

/**
 * The crisis-support card (docs/safety/crisis-support.md): a calm card with
 * crisis resources, shown INSTEAD of a tutor reply or an AI result when the
 * backend's crisis screen fired. Not an error: no red, no alert role, no
 * "something went wrong". Every string comes from the payload — the wording
 * lives in backend/services/crisis_support_copy.py alone.
 *
 * `CrisisSupportCard` sits in a conversation (ChatPanel, the quiz's Ask
 * panel); `CrisisSupportDialog` shows it over a surface that has no
 * conversation to put it in (a session start, a note action, an answer box).
 */

import React, { useCallback, useId, useState } from "react";
import Dialog from "../Dialog";
import { crisisSupportIn, type CrisisSupport, type CrisisSupportAction } from "@/lib/crisisSupport";

const CARD: React.CSSProperties = {
  background: "var(--info-soft)",
  border: "1px solid rgba(62, 111, 138, 0.28)",
  borderRadius: "var(--r-lg)",
  padding: "18px 20px",
  color: "var(--text)",
  fontFamily: "var(--font-sans)",
  fontSize: 14,
  lineHeight: 1.6,
};

const ACTION: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minHeight: 32,
  padding: "4px 12px",
  borderRadius: 999,
  border: "1px solid rgba(62, 111, 138, 0.35)",
  background: "var(--bg-panel)",
  color: "var(--info)",
  fontWeight: 600,
  fontSize: 13,
  textDecoration: "none",
};

function ActionLink({ action }: { action: CrisisSupportAction }) {
  // https pages open in a new tab without a referrer; tel:/sms: hand off to
  // the phone app and never navigate away from the student's work.
  const external = action.href.toLowerCase().startsWith("https://");
  return (
    <a
      href={action.href}
      style={ACTION}
      data-testid="crisis-support-action"
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
    >
      {action.label}
    </a>
  );
}

export function CrisisSupportCard({
  support,
  onDismiss,
  titleId,
  style,
}: {
  support: CrisisSupport;
  /** Renders the payload's dismiss button (the dialog's way back). */
  onDismiss?: () => void;
  titleId?: string;
  style?: React.CSSProperties;
}) {
  const autoId = useId();
  const headingId = titleId ?? autoId;
  return (
    <section
      data-testid="crisis-support-card"
      aria-labelledby={headingId}
      style={{ ...CARD, ...style }}
    >
      <h3 id={headingId} style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 700, color: "var(--text)" }}>
        {support.title}
      </h3>
      {support.intro.map((p, i) => (
        <p key={i} style={{ margin: "0 0 8px" }}>{p}</p>
      ))}
      {support.resources_heading && (
        <p style={{ margin: "12px 0 6px", fontSize: 12, fontWeight: 600, color: "var(--info)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {support.resources_heading}
        </p>
      )}
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        {support.resources.map((r) => (
          <li key={r.id} data-testid={`crisis-support-resource-${r.id}`}>
            <div style={{ fontWeight: 700 }}>{r.name}</div>
            <div style={{ color: "var(--text-dim)" }}>{r.detail}</div>
            {r.actions.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                {r.actions.map((a) => <ActionLink key={a.href} action={a} />)}
              </div>
            )}
          </li>
        ))}
      </ul>
      {support.closing.map((p, i) => (
        <p key={i} style={{ margin: i === 0 ? "14px 0 0" : "8px 0 0" }}>{p}</p>
      ))}
      {onDismiss && support.dismiss_label && (
        <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
          <button type="button" className="btn btn--sm" data-testid="crisis-support-dismiss" onClick={onDismiss}>
            {support.dismiss_label}
          </button>
        </div>
      )}
    </section>
  );
}

export function CrisisSupportDialog({
  support,
  onClose,
}: {
  support: CrisisSupport | null;
  onClose: () => void;
}) {
  const titleId = useId();
  if (!support) return null;
  return (
    <Dialog open onClose={onClose} labelledBy={titleId} showCloseButton={false} padding="0" size="md">
      <CrisisSupportCard support={support} onDismiss={onClose} titleId={titleId} style={{ border: "none" }} />
    </Dialog>
  );
}

/**
 * For a surface with no conversation: `intercept(response)` shows the card
 * (and returns true) when the response carries one, so the caller stops its
 * normal handling; render `dialog` once in the surface.
 */
export function useCrisisSupport() {
  const [support, setSupport] = useState<CrisisSupport | null>(null);
  const intercept = useCallback((response: unknown): boolean => {
    const found = crisisSupportIn(response);
    if (found) setSupport(found);
    return found !== null;
  }, []);
  const close = useCallback(() => setSupport(null), []);
  const dialog = <CrisisSupportDialog support={support} onClose={close} />;
  return { intercept, dialog, support };
}
