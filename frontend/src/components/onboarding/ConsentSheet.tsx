"use client";

/**
 * What connecting an account means, before the student chooses it. Choosing
 * records the choice only: the account connects after the profile is saved.
 * A modal sheet: focus moves in, Tab stays inside, Esc or the backdrop
 * closes it, and focus goes back to the button that opened it (the shared
 * overlay behaviour from components/Dialog).
 */
import React from "react";
import { useOverlayBehaviour } from "@/components/Dialog";
import type { Connection } from "./flow";

export function ConsentSheet({ connection, onConfirm, onClose }: {
  connection: Connection;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { panelRef, onKeyDown } = useOverlayBehaviour({ open: true, onClose });
  return (
    <div className="ob-sheet-backdrop" onClick={onClose} onKeyDown={onKeyDown}>
      <div
        ref={panelRef}
        className="ob-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ob-consent-title"
        data-testid="onboarding-consent"
        onClick={e => e.stopPropagation()}
      >
        <div className="ob-sheet-grip" aria-hidden="true" />
        <h2 id="ob-consent-title" className="ob-sheet-title">Connect {connection.name}</h2>
        <dl className="ob-sheet-rows">
          {(connection.consent ?? []).map(([label, text]) => (
            <div key={label} className="ob-sheet-row">
              <dt>{label}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
        <div className="ob-sheet-actions">
          <button data-testid="onboarding-consent-continue" className="ob-sheet-go" onClick={onConfirm}>
            Connect after setup
          </button>
          <button data-testid="onboarding-consent-cancel" className="ob-sheet-cancel" onClick={onClose}>
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
