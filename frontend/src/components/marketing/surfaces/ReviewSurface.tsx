/**
 * Band 3 — the Study screen's spaced review (#344 step 2).
 *
 * Recreates `screens/Study.tsx` in flashcards mode: the `Card {i} of {n}`
 * counter with the topic in mono on the right, the 6px progress track, the
 * flipped card (its `label-micro` face label over display-font text), and the
 * rating trio — Forgot / Hard / Easy — which is the product's actual
 * spaced-repetition verdict UI.
 *
 * Two deliberate divergences from the shipped screen, both required by the
 * brand guide rather than chosen for looks:
 *
 *  - **No emoji.** The real rating buttons lead with 🙈 / 🤔 / ✨; "no emoji in
 *    chrome" is a hard line, so the tone is carried by the pill tint instead.
 *  - **The interval legend is added.** Today the app schedules server-side and
 *    prints no interval anywhere in the frontend. The band's claim is "knows
 *    what to review, and when", and a rating trio with no visible consequence
 *    makes only the first half of it. The `Next review` line states what each
 *    rating buys — honest to the behaviour, and the one element that makes this
 *    surface unmistakably a spaced-repetition product rather than a quiz.
 *
 * The pill text stays `--text` and the colour lives in the tint + border: at
 * 11–12px, `--warn` on this paper is 4.28:1, under the 4.5:1 AA bar for small
 * text, and non-text contrast only has to clear 3:1.
 */
import type { CSSProperties } from 'react';

import { SurfaceFrame, SurfaceRule } from './Surface';

const RATINGS = [
  { label: 'Forgot', key: '1', tone: 'var(--state-struggle)', due: '10 min' },
  { label: 'Hard', key: '2', tone: 'var(--state-progress)', due: '1 day' },
  { label: 'Easy', key: '3', tone: 'var(--state-mastery)', due: '4 days' },
];

/** Card 7 of 12 — the fill the real 6px progress track would show. */
const PROGRESS_PCT = 58;

export default function ReviewSurface() {
  return (
    <SurfaceFrame testId="landing-surface-review" title="Study" meta="Spaced review">
      <span className="landing-surface-headrow">
        <span className="landing-surface-sub">Card 7 of 12</span>
        <span className="landing-surface-mono">MA 242 · Eigenvalues</span>
      </span>

      <span className="landing-surface-track" aria-hidden>
        <span className="landing-surface-fill" style={{ width: `${PROGRESS_PCT}%` }} />
      </span>

      <span className="landing-surface-card">
        <span className="landing-surface-label">Back</span>
        <span className="landing-surface-cardtext">
          det(A − λI) = 0 — the λ that makes A − λI collapse.
        </span>
      </span>

      <span className="landing-surface-ratings">
        {RATINGS.map((r) => (
          <span key={r.label} className="landing-surface-rate" style={{ '--tone': r.tone } as CSSProperties}>
            {r.label}
            <span className="landing-surface-ratekey">{r.key}</span>
          </span>
        ))}
      </span>

      <SurfaceRule />
      <span className="landing-surface-headrow">
        <span className="landing-surface-label">Next review</span>
        <span className="landing-surface-mono">
          {RATINGS.map((r) => `${r.label} ${r.due}`).join('  ·  ')}
        </span>
      </span>
    </SurfaceFrame>
  );
}
