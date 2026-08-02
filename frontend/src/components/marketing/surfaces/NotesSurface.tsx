/**
 * Bento tile — the Notetaker (#344 step 2).
 *
 * Recreates `(shell)/notetaker`: the display-font title (its placeholder is
 * "Untitled note"), the Spectral body the editor sets at 15px/1.7, and the
 * right rail's "Linked concepts" card — one row per concept, each an inset pill
 * carrying an 8px mastery dot, the concept name, and the mastery word in mono
 * uppercase. That rail is the tile's whole point: a note in Sapling is attached
 * to the graph, which is what makes it a Notetaker and not a text box.
 */
import { StateDot, SurfaceFrame } from './Surface';
import type { MasteryTier } from '../graph/courseGraphs';

const LINKED: Array<{ label: string; tier: MasteryTier; word: string }> = [
  { label: 'Eigenvalues', tier: 'struggling', word: 'Struggling' },
  { label: 'Determinant', tier: 'unexplored', word: 'Unexplored' },
  { label: 'Matrices', tier: 'learning', word: 'Learning' },
];

export default function NotesSurface() {
  return (
    <SurfaceFrame testId="landing-surface-notes" title="Notetaker" meta="MA 242 · 2h ago">
      <span className="landing-surface-notetitle">Week 4 — eigen-everything</span>
      <p className="landing-surface-prose">
        λ is the scale factor; v is the direction that survives the transformation intact. So
        det(A − λI) = 0 is really just &ldquo;find the λ that collapses the matrix&rdquo;. Ask about
        repeated roots before the midterm.
      </p>

      <span className="landing-surface-label">Linked concepts</span>
      {LINKED.map((c) => (
        <span key={c.label} className="landing-surface-linkrow">
          <StateDot tier={c.tier} />
          <span className="landing-surface-name">{c.label}</span>
          <span className="landing-surface-mono">{c.word}</span>
        </span>
      ))}
    </SurfaceFrame>
  );
}
