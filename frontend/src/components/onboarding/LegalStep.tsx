"use client";

/**
 * The Terms of Service and Privacy Policy screens. The document is the one
 * the public /terms and /privacy pages publish (lib/legal/documents.ts), and
 * its version is what the onboarding save says the student accepted. The box
 * can be ticked only once the student has scrolled to the end.
 */
import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { legalDateLabel, type LegalDocument, type LegalSection } from "@/lib/legal/documents";
import { ScreenHead } from "./ScreenHead";

function Clause({ section: s }: { section: LegalSection }) {
  return (
    <div className="ob-clause">
      <h2>{s.title}</h2>
      {s.body && (
        <p>
          {s.body}
          {s.link && <a href={s.link.href}>{s.link.label}</a>}
          {s.bodySuffix}
        </p>
      )}
      {s.list && <ul>{s.list.map(li => <li key={li}>{li}</li>)}</ul>}
      {s.subsections?.map(sub => (
        <div key={sub.label} className="ob-clause-sub">
          <p className="ob-clause-label">{sub.label}</p>
          <ul>{sub.list.map(li => <li key={li}>{li}</li>)}</ul>
        </div>
      ))}
      {s.highlights && (
        <ul>
          {s.highlights.map(h => <li key={h.label}><strong>{h.label}</strong> {h.text}</li>)}
        </ul>
      )}
      {s.bodyAfter && <p>{s.bodyAfter}</p>}
    </div>
  );
}

export function LegalStep({ doc, reachedEnd, agreed, notice, onReachEnd, onAgree }: {
  doc: LegalDocument;
  reachedEnd: boolean;
  agreed: boolean;
  notice?: React.ReactNode;
  onReachEnd: () => void;
  onAgree: (v: boolean) => void;
}) {
  const [pct, setPct] = useState(reachedEnd ? 1 : 0);
  const bodyRef = useRef<HTMLDivElement>(null);
  const hintId = useId();

  const measure = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    const room = el.scrollHeight - el.clientHeight;
    // A panel tall enough to show the whole document has nothing to scroll.
    const p = room <= 2 ? 1 : Math.min(1, el.scrollTop / room);
    setPct(p);
    if (p > 0.985 && !reachedEnd) onReachEnd();
  }, [reachedEnd, onReachEnd]);

  useEffect(() => {
    const frame = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", measure); };
  }, [measure]);

  return (
    <section className="ob-screen ob-screen--legal">
      <ScreenHead title={doc.title} notice={notice} />
      <div className="ob-legal">
        <div className="ob-panel ob-doc">
          <div className="ob-doc-progress" aria-hidden="true"><div style={{ width: `${Math.round(pct * 100)}%` }} /></div>
          <div
            ref={bodyRef}
            className="ob-doc-body"
            onScroll={measure}
            tabIndex={0}
            role="region"
            aria-label={doc.title}
            data-testid="onboarding-legal-body"
          >
            <div className="ob-doc-meta ob-doc-meta--top" data-testid="onboarding-legal-updated">
              Last updated: {legalDateLabel(doc.version)}
            </div>
            <p className="ob-doc-preamble">{doc.preamble}</p>
            {doc.sections.map(s => <Clause key={s.title} section={s} />)}
            <div className="ob-doc-meta ob-doc-meta--end">End of the {doc.title}</div>
          </div>
        </div>
        <button
          data-testid="onboarding-agree"
          className="ob-agree"
          role="checkbox"
          aria-checked={agreed}
          aria-describedby={reachedEnd ? undefined : hintId}
          disabled={!reachedEnd}
          onClick={() => onAgree(!agreed)}
        >
          <span className="ob-box" aria-hidden="true">{agreed ? "✓" : ""}</span>
          I agree to the {doc.title}
        </button>
        {!reachedEnd && (
          <p id={hintId} className="ob-agree-hint" data-testid="onboarding-agree-hint">
            Scroll to the end to accept.
          </p>
        )}
      </div>
    </section>
  );
}
