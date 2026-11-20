/**
 * Where a tutor session was opened from, when it is not the Tutor itself, and
 * the request fields that say so. Moved out of `api.ts` (which re-exports the
 * types) when chat turns gained the quoted quiz question (#866 K12).
 */

/**
 * PKG-14 (spec §13 A99): a session opened ABOUT one quiz question (the quiz's
 * "Ask about this" panel). The question is named by its attempt and index; the
 * server resolves its identity from the attempt row and records the help, so
 * quiz evidence on that question earns no unassisted credit. On the loop path
 * the session starts teaching the quiz's concept (no probe).
 */
export interface QuizAskOrigin {
  attemptId: string;
  questionIndex: number;
}

/** #866 audit K01: a study guide's "Ask the tutor" (the rail's question box,
 *  a concept map's Ask). On the loop path the session skips the check-in and
 *  the plan and answers the question from the first turn, as a quiz ask does;
 *  the legacy path ignores it. */
export type GuideAskOrigin = { guide: true };
/** Where a tutor session was opened from, when it is not the Tutor itself. */
export type AskOrigin = QuizAskOrigin | GuideAskOrigin;

/** A session start's origin fields (`StartSessionBody.origin` and the quiz question). */
export const askOriginFields = (origin?: AskOrigin) =>
  !origin ? {} : 'guide' in origin ? { origin: 'guide_ask' as const }
    : { origin: 'quiz_ask' as const, quiz_attempt_id: origin.attemptId, quiz_question_index: origin.questionIndex };

/**
 * A chat turn that QUOTES the quiz question (#866 K12; `ChatBody.quiz_attempt_id`
 * and `quiz_question_index`): the Ask panel's first message, which carries the
 * question's stem, options and explanation. The server reads that question off
 * the student's own attempt, so a crisis phrase the question itself holds (a
 * patient's words in a nursing question) shows the crisis card BESIDE the
 * explanation instead of in place of it (docs/safety/crisis-support.md).
 */
export const quotedQuestionFields = (quote?: QuizAskOrigin) =>
  quote ? { quiz_attempt_id: quote.attemptId, quiz_question_index: quote.questionIndex } : {};
