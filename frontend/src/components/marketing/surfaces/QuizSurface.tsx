/**
 * Band 2 — a live Adaptive Quizzes question (#344 step 2).
 *
 * Recreates `QuizPanel`'s `active` phase: the "Question {i} of {n}" micro-label
 * on the left, the difficulty chip on the right, the question at 16px, and the
 * `role="radiogroup"` answer grid with its `A.` mono prefix — selected option in
 * the accent border + accent-soft fill the panel actually paints.
 *
 * The one thing the real panel does NOT show is *why* this question is the one
 * you got, and that is precisely the band's claim. The footer strip states it in
 * the surface's own register: the last streak, and the difficulty the next
 * question moves to. Colour there is `--state-progress` — a status, not decor.
 *
 * Static: the options are `<div role="radio">`, not `<button>`s. The whole
 * surface is a picture of the product, there is nothing to click.
 */
import { StateDot, SurfaceFrame, SurfaceRule } from './Surface';

const OPTIONS = [
  { label: 'A', text: 'The angle that A rotates v through' },
  { label: 'B', text: 'The factor that A scales v by' },
  { label: 'C', text: 'The determinant of A' },
  { label: 'D', text: 'The rank of A' },
];

/** The option the student has picked but not yet submitted. */
const PICKED = 'B';

export default function QuizSurface() {
  return (
    <SurfaceFrame testId="landing-surface-quiz" title="Adaptive Quizzes" meta="Question 4 of 8">
      <span className="landing-surface-headrow">
        <span className="landing-surface-concept">
          <StateDot tier="struggling" />
          Eigenvalues
        </span>
        <span className="landing-surface-chip is-hard">Hard</span>
      </span>

      <p className="landing-surface-question">
        If A v = λ v for some non-zero v, what does λ tell you about what A does to v?
      </p>

      <span className="landing-surface-options" role="radiogroup" aria-label="Answer options">
        {OPTIONS.map((o) => {
          const picked = o.label === PICKED;
          return (
            <span
              key={o.label}
              role="radio"
              aria-checked={picked}
              aria-label={`${o.label}. ${o.text}`}
              className={`landing-surface-option${picked ? ' is-picked' : ''}`}
            >
              <span className="landing-surface-optionkey">{o.label}.</span>
              {o.text}
            </span>
          );
        })}
      </span>

      <SurfaceRule />
      <span className="landing-surface-headrow">
        <span className="landing-surface-footnote">3 right in a row on this concept</span>
        <span className="landing-surface-tune">Next question ↑ harder</span>
      </span>
    </SurfaceFrame>
  );
}
