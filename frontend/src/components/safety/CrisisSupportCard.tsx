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
 *
 * While a card is on screen, in either form and on any surface, it holds the
 * shell's feedback prompts (lib/feedbackPacing.ts), so no survey opens over it.
 */

import React, { useCallback, useId, useRef, useState } from "react";
import Dialog from "../Dialog";
import { useFeedbackHold } from "@/lib/feedbackPacing";
import { crisisSupportIn, type CrisisSupport, type CrisisSupportAction } from "@/lib/crisisSupport";
import styles from "./CrisisSupportCard.module.css";

/**
 * A resource link opens in a new tab when it is a web page; tel:/sms: links
 * hand off to the phone app instead. The hrefs are the payload's (the copy
 * lives in backend/services/crisis_support_copy.py), never configuration.
 */
const WEB_PROTOCOL = "https:";

function isWebPage(href: string): boolean {
  try {
    return new URL(href).protocol === WEB_PROTOCOL;
  } catch {
    return false;
  }
}

function ActionLink({ action }: { action: CrisisSupportAction }) {
  // Web pages open in a new tab without a referrer; tel:/sms: hand off to
  // the phone app and never navigate away from the student's work.
  const external = isWebPage(action.href);
  return (
    <a
      href={action.href}
      className={styles.action}
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
  bare = false,
}: {
  support: CrisisSupport;
  /** Renders the payload's dismiss button (the dialog's way back). */
  onDismiss?: () => void;
  titleId?: string;
  /** No border of its own: a dialog frames it. */
  bare?: boolean;
}) {
  const autoId = useId();
  const headingId = titleId ?? autoId;
  // No feedback survey over the card: held while it is mounted.
  useFeedbackHold(true);
  return (
    <section
      data-testid="crisis-support-card"
      aria-labelledby={headingId}
      className={bare ? `${styles.card} ${styles.bare}` : styles.card}
    >
      <h3 id={headingId} className={styles.title}>
        {support.title}
      </h3>
      {support.intro.map((p, i) => (
        <p key={i} className={styles.para}>{p}</p>
      ))}
      {support.resources_heading && (
        <p className={styles.resourcesHeading}>
          {support.resources_heading}
        </p>
      )}
      <ul className={styles.resources}>
        {support.resources.map((r) => (
          <li key={r.id} data-testid={`crisis-support-resource-${r.id}`}>
            <div className={styles.resourceName}>{r.name}</div>
            <div className={styles.resourceDetail}>{r.detail}</div>
            {r.actions.length > 0 && (
              <div className={styles.actions}>
                {r.actions.map((a) => <ActionLink key={a.href} action={a} />)}
              </div>
            )}
          </li>
        ))}
      </ul>
      {support.closing.map((p, i) => (
        <p key={i} className={i === 0 ? styles.closingFirst : styles.closing}>{p}</p>
      ))}
      {onDismiss && support.dismiss_label && (
        <div className={styles.footer}>
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
      <CrisisSupportCard support={support} onDismiss={onClose} titleId={titleId} bare />
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
