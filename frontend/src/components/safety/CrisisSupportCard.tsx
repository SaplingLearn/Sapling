"use client";

/**
 * The crisis-support card (docs/safety/crisis-support.md): a calm card with
 * crisis resources, shown INSTEAD of a tutor reply or an AI result when the
 * backend's crisis screen fired on what the student typed, or BESIDE a notes
 * action's result when the note itself matched. Not an error: no red, no
 * alert role, no "something went wrong". Every string comes from the
 * payload — the wording lives in backend/services/crisis_support_copy.py
 * alone.
 *
 * `CrisisSupportCard` sits in a conversation (ChatPanel, the quiz's Ask
 * panel); `CrisisSupportDialog` shows it over a surface that has no
 * conversation to put it in (a session start, a note action, an answer box).
 */

import React, { useCallback, useId, useRef, useState } from "react";
import Dialog from "../Dialog";
import { crisisSupportIn, type CrisisSupport, type CrisisSupportAction } from "@/lib/crisisSupport";
import { cn } from "@/lib/cn";

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
      className="bg-info-soft border border-[rgba(62,_111,_138,_0.28)] rounded-lg py-4.5 px-5 text-text font-sans text-base leading-[1.6]" style={{ ...style }}
    >
      <h3 id={headingId} className="mt-0 mx-0 mb-2 text-lg font-bold text-text">
        {support.title}
      </h3>
      {support.intro.map((p, i) => (
        <p key={i} className="mt-0 mx-0 mb-2">{p}</p>
      ))}
      {support.resources_heading && (
        <p className="mt-3 mx-0 mb-1.5 text-base font-semibold text-info">
          {support.resources_heading}
        </p>
      )}
      <ul className="list-none m-0 p-0 flex flex-col gap-2.5">
        {support.resources.map((r) => (
          <li key={r.id} data-testid={`crisis-support-resource-${r.id}`}>
            <div className="font-bold">{r.name}</div>
            <div className="text-text-dim">{r.detail}</div>
            {r.actions.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {r.actions.map((a) => <ActionLink key={a.href} action={a} />)}
              </div>
            )}
          </li>
        ))}
      </ul>
      {support.closing.map((p, i) => (
        <p key={i} className={cn(i === 0 ? "mt-3.5 mx-0 mb-0" : "mt-2 mx-0 mb-0")}>{p}</p>
      ))}
      {onDismiss && support.dismiss_label && (
        <div className="mt-4 flex justify-end">
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
 * normal handling; render `dialog` once in the surface. `afterClose` runs
 * once the student closes the card (a result shown alongside it that leaves
 * the page, like opening the tutor, waits for that). A card that arrives
 * while one is showing replaces it, but every `afterClose` still pending
 * runs, in order, when the student closes it.
 */
export function useCrisisSupport() {
  const [support, setSupport] = useState<CrisisSupport | null>(null);
  const afterCloseRef = useRef<Array<() => void>>([]);
  const intercept = useCallback((response: unknown, afterClose?: () => void): boolean => {
    const found = crisisSupportIn(response);
    if (found) {
      if (afterClose) afterCloseRef.current.push(afterClose);
      setSupport(found);
    }
    return found !== null;
  }, []);
  const close = useCallback(() => {
    setSupport(null);
    const pending = afterCloseRef.current;
    afterCloseRef.current = [];
    for (const then of pending) then();
  }, []);
  const dialog = <CrisisSupportDialog support={support} onClose={close} />;
  return { intercept, dialog, support };
}
