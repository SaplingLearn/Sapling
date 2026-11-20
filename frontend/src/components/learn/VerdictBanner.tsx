"use client";
import tutorStyles from "./tutor/tutor.module.css";

const VERDICT_COPY: Record<string, { title: string; note: string }> = {
  correct: { title: "Correct", note: "That answer counts toward this concept." },
  not_yet: { title: "Not yet", note: "The tutor's reply above shows what to fix." },
  idk: { title: "Not yet", note: "No problem — the tutor's reply above walks through it." },
};

/** What a "Not yet" says comes next (#866 K08): another check on the same
 *  idea, unless the plan has moved on (`next`, `nextAfterVerdict`). */
function notYetNext(next: string | null | undefined): string {
  if (next === undefined) return " Try another one on the same idea.";
  return next ? ` Next up: ${next}.` : "";
}

/** Wireframe T9: the graded check's verdict, above the tutor's feedback.
 *  `next`: where the plan went after this grade — absent while the next check
 *  stays on this concept, the next concept's name, or null when none is left. */
export function VerdictBanner({ verdict, concept, next }: { verdict: string; concept: string | null; next?: string | null }) {
  const known = VERDICT_COPY[verdict];
  const copy = known && verdict !== "not_yet" ? known : { ...VERDICT_COPY.not_yet, note: VERDICT_COPY.not_yet.note + notYetNext(next) };
  const yes = verdict === "correct";
  return (
    <div data-testid="loop-verdict" data-verdict={verdict} className={`${yes ? tutorStyles.verdictYes : tutorStyles.verdictNo} fade-in`}>
      {concept && <span className="label-micro">{concept} · check</span>}
      <div style={{ font: "600 17px var(--font-display)", color: yes ? "var(--sap-600)" : "var(--warn)" }}>{copy.title}</div>
      <div style={{ fontSize: 14 }}>{copy.note}</div>
    </div>
  );
}
