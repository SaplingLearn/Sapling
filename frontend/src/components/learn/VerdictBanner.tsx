"use client";
import type { LoopCredit, LoopCreditReason } from "@/lib/loopCredit";
import tutorStyles from "./tutor/tutor.module.css";

const VERDICT_COPY: Record<string, { title: string; note: string }> = {
  correct: { title: "Correct", note: "That answer counts toward this concept." },
  not_yet: { title: "Not yet", note: "The tutor's reply above shows what to fix." },
  idk: { title: "Not yet", note: "No problem — the tutor's reply above walks through it." },
};

/** #866 K07: what a correct answer earned (the server's `credit`, the weight
 *  its evidence was journaled at): a reduced weight says what reduced it
 *  (`credit_reasons`), a worked example or a shown answer (H4-H6) means none.
 *  Absent (an older server): the full line. */
const REASON_CLAUSE: Record<LoopCreditReason, string> = {
  hint: "you used a hint",
  recheck: "this idea was already checked, or its answer shown, earlier this session",
  low_confidence: "the tutor couldn't be fully sure how to read it",
  multi_concept: "it tests more than one concept at once",
};

function joinClauses(parts: string[]): string {
  return parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

export function creditNote(credit: LoopCredit, reasons: LoopCreditReason[] = []): string {
  if (credit === "full") return VERDICT_COPY.correct.note;
  if (credit === "none") {
    return "This one doesn't count toward the concept, because help was shown before you answered. Try the next one on your own.";
  }
  const why = joinClauses(reasons.filter((r) => REASON_CLAUSE[r]).map((r) => REASON_CLAUSE[r]));
  return why ? `That answer counts partly toward this concept, because ${why}.` : "That answer counts partly toward this concept.";
}

/** What a "Not yet" says comes next (#866 K08): another check on the same
 *  idea, unless the plan has moved on (`next`, `nextAfterVerdict`). */
function notYetNext(next: string | null | undefined): string {
  if (next === undefined) return " Try another one on the same idea.";
  return next ? ` Next up: ${next}.` : "";
}

/** Wireframe T9: the graded check's verdict, above the tutor's feedback.
 *  `next`: where the plan went after this grade — absent while the next check
 *  stays on this concept, the next concept's name, or null when none is left. */
export function VerdictBanner({ verdict, concept, next, credit, reasons }: {
  verdict: string; concept: string | null; next?: string | null; credit?: LoopCredit | null; reasons?: LoopCreditReason[];
}) {
  const known = VERDICT_COPY[verdict];
  const copy = known && verdict !== "not_yet" ? known : { ...VERDICT_COPY.not_yet, note: VERDICT_COPY.not_yet.note + notYetNext(next) };
  const yes = verdict === "correct";
  const note = yes && (credit === "full" || credit === "partial" || credit === "none") ? creditNote(credit, reasons) : copy.note;
  return (
    <div data-testid="loop-verdict" data-verdict={verdict} data-credit={yes ? credit ?? undefined : undefined} className={`${yes ? tutorStyles.verdictYes : tutorStyles.verdictNo} fade-in`}>
      {concept && <span className="label-micro">{concept} · check</span>}
      <div style={{ font: "600 17px var(--font-display)", color: yes ? "var(--sap-600)" : "var(--warn)" }}>{copy.title}</div>
      <div style={{ fontSize: 14 }}>{note}</div>
    </div>
  );
}
