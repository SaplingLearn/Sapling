"use client";
import type { LoopCredit } from "@/lib/api";
import tutorStyles from "./tutor/tutor.module.css";

const VERDICT_COPY: Record<string, { title: string; note: string }> = {
  correct: { title: "Correct", note: "That answer counts toward this concept." },
  not_yet: { title: "Not yet", note: "The tutor's reply above shows what to fix." },
  idk: { title: "Not yet", note: "No problem — the tutor's reply above walks through it." },
};

/** #866 K07: what a correct answer earned (the server's `credit`, from the help
 *  used before it): help H1-H3 counts at a reduced weight, a worked example or a
 *  shown answer (H4-H6) not at all. Absent (an older server): the full line. */
const CREDIT_NOTE: Record<LoopCredit, string> = {
  full: VERDICT_COPY.correct.note,
  partial: "That answer counts partly toward this concept, because you used a hint.",
  none: "This one doesn't count toward the concept, because help was shown before you answered. Try the next one on your own.",
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
export function VerdictBanner({ verdict, concept, next, credit }: {
  verdict: string; concept: string | null; next?: string | null; credit?: LoopCredit | null;
}) {
  const known = VERDICT_COPY[verdict];
  const copy = known && verdict !== "not_yet" ? known : { ...VERDICT_COPY.not_yet, note: VERDICT_COPY.not_yet.note + notYetNext(next) };
  const yes = verdict === "correct";
  const note = yes && credit && CREDIT_NOTE[credit] ? CREDIT_NOTE[credit] : copy.note;
  return (
    <div data-testid="loop-verdict" data-verdict={verdict} data-credit={yes ? credit ?? undefined : undefined} className={`${yes ? tutorStyles.verdictYes : tutorStyles.verdictNo} fade-in`}>
      {concept && <span className="label-micro">{concept} · check</span>}
      <div style={{ font: "600 17px var(--font-display)", color: yes ? "var(--sap-600)" : "var(--warn)" }}>{copy.title}</div>
      <div style={{ fontSize: 14 }}>{note}</div>
    </div>
  );
}
