/**
 * Bento tile — the Gradebook (#344 step 2).
 *
 * Recreates the `/gradebook` course page: the course card's big display-font
 * letter grade next to the percentage that `percentColor` tints, then the
 * assignment list — a Spectral title, the `Due MM/DD/YYYY` mono line, the
 * points-earned / points-possible pair, and the category grouping.
 *
 * Colour rules, which shape the markup here more than the layout does:
 *
 *  - The 3.4rem letter grade is display-size, so WCAG treats it as large text
 *    (3:1) and it can carry `--grade-a` (#3a7d4e → 4.56:1) directly.
 *  - The per-row letter cannot. `--grade-b` (#a88020) is 3.39:1 on this paper,
 *    fine as a hairline or a dot (non-text, 3:1) and not fine as a glyph. So a
 *    row's pill keeps `--text` lettering and carries its grade band in the
 *    border and dot instead. The colour is still doing the state work; it is
 *    just not doing it *as text*.
 *
 * The real course card also paints a coloured band in the course's own hue.
 * Dropped here for the same reason the room avatars are neutral: identity
 * colour next to grade colour makes the grade colour stop meaning anything.
 */
import { SurfaceFrame, SurfaceRule } from './Surface';
import type { CSSProperties } from 'react';

const ROWS = [
  { title: 'Problem Set 6', due: 'Due 04/21/2026', earned: '18', possible: '20', letter: 'A', grade: 'var(--grade-a)' },
  { title: 'Midterm 1', due: 'Due 03/09/2026', earned: '84', possible: '100', letter: 'B', grade: 'var(--grade-b)' },
  { title: 'Quiz 4', due: 'Due 02/27/2026', earned: '9', possible: '10', letter: 'A', grade: 'var(--grade-a)' },
];

export default function GradebookSurface() {
  return (
    <SurfaceFrame testId="landing-surface-gradebook" title="Gradebook" meta="MA 242 · Fall 2025">
      <span className="landing-surface-headrow">
        <span className="landing-surface-grade">
          <span className="landing-surface-letter">A−</span>
          <span className="landing-surface-stack">
            <span className="landing-surface-pct">91.4%</span>
            <span className="landing-surface-mono">12 of 14 graded</span>
          </span>
        </span>
        <span className="landing-surface-mono">Term GPA 3.62</span>
      </span>

      <SurfaceRule />
      <span className="landing-surface-label">Assignments</span>

      {ROWS.map((r) => (
        <span key={r.title} className="landing-surface-gradebookrow">
          <span className="landing-surface-stack">
            <span className="landing-surface-assignment">{r.title}</span>
            <span className="landing-surface-mono">{r.due}</span>
          </span>
          <span className="landing-surface-points">
            {r.earned}
            <span className="landing-surface-slash"> / {r.possible}</span>
          </span>
          <span className="landing-surface-gradepill" style={{ '--grade': r.grade } as CSSProperties}>
            {r.letter}
          </span>
        </span>
      ))}
    </SurfaceFrame>
  );
}
