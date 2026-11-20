"use client";
import tutorStyles from "./tutor/tutor.module.css";

const VERDICT_COPY: Record<string, { title: string; note: string }> = {
  correct: { title: "Correct", note: "That answer counts toward this concept." },
  not_yet: { title: "Not yet", note: "The tutor's reply above shows what to fix. Try another one on the same idea." },
  idk: { title: "Not yet", note: "No problem — the tutor's reply above walks through it." },
};

/** Wireframe T9: the graded check's verdict, above the tutor's feedback. */
export function VerdictBanner({ verdict, concept }: { verdict: string; concept: string | null }) {
  const copy = VERDICT_COPY[verdict] ?? VERDICT_COPY.not_yet;
  const yes = verdict === "correct";
  return (
    <div data-testid="loop-verdict" data-verdict={verdict} className={`${yes ? tutorStyles.verdictYes : tutorStyles.verdictNo} fade-in`}>
      {concept && <span className="label-micro">{concept} · check</span>}
      <div style={{ font: "600 17px var(--font-display)", color: yes ? "var(--sap-600)" : "var(--warn)" }}>{copy.title}</div>
      <div style={{ fontSize: 14 }}>{copy.note}</div>
    </div>
  );
}
