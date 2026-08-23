/**
 * Band 1 — the Document Library ingest queue (#344 step 2).
 *
 * Recreates `DocumentUploadModal` at rest, mid-batch: the file rows with their
 * `28×36` doc tile, `{size} · {EXT}` meta line and status chip (`queued` /
 * `processing…` / `done` — the modal's own wording), then the extraction
 * result the modal prints underneath a finished row: a summary line plus the
 * concept chips that land on the graph.
 *
 * The concept chips carry mastery dots from `TIER_COLOR`, which is the whole
 * argument of the band: an upload is not a file in a folder, it is nodes on
 * your graph. Same tokens as the knowledge-graph section one viewport up.
 */
import { ConceptChip, StateDot, SurfaceFrame, SurfaceRule } from './Surface';
import type { MasteryTier } from '../graph/courseGraphs';

/** The modal's doc tile — a page glyph, drawn inline (no icon dependency). */
function DocGlyph() {
  return (
    <span aria-hidden className="landing-surface-doc">
      <svg viewBox="0 0 16 20" width="13" height="16" fill="none" aria-hidden>
        <path
          d="M2.5 1.5h7.2L14 5.8v12.7H2.5z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
        <path d="M9.5 1.7v4.3H14" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="M5 10h6M5 13h6M5 16h3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    </span>
  );
}

type UploadStatus = 'done' | 'processing' | 'queued';

const FILES: Array<{ name: string; meta: string; status: UploadStatus; label: string }> = [
  { name: 'MA242_syllabus.pdf', meta: '0.4 MB · PDF', status: 'done', label: 'done' },
  { name: 'linear_algebra_ch3.pdf', meta: '2.8 MB · PDF', status: 'processing', label: 'processing…' },
  { name: 'lecture_wk4.pptx', meta: '6.1 MB · PPTX', status: 'queued', label: 'queued' },
];

const CONCEPTS: Array<{ label: string; tier: MasteryTier }> = [
  { label: 'Vector Spaces', tier: 'mastered' },
  { label: 'Matrices', tier: 'learning' },
  { label: 'Eigenvalues', tier: 'struggling' },
  { label: 'Determinant', tier: 'unexplored' },
];

export default function UploadSurface() {
  return (
    <SurfaceFrame testId="landing-surface-upload" title="Document Library" meta="3 files queued">
      {FILES.map((f) => (
        <div key={f.name} className="landing-surface-row">
          <DocGlyph />
          <span className="landing-surface-stack">
            <span className="landing-surface-name">{f.name}</span>
            <span className="landing-surface-sub">{f.meta}</span>
          </span>
          <span className={`landing-surface-status is-${f.status}`}>{f.label}</span>
        </div>
      ))}

      {/* The extraction readout the modal prints under a finished row. */}
      <SurfaceRule />
      <span className="landing-surface-label">Concepts extracted</span>
      <p className="landing-surface-note">
        Syllabus read: 19 concepts mapped onto MA 242, 4 of them new.
      </p>
      <span className="landing-surface-chiprow">
        {CONCEPTS.map((c) => (
          <ConceptChip key={c.label} label={c.label} tier={c.tier} />
        ))}
        <span className="landing-surface-chip is-count">+15</span>
      </span>

      {/* The graph is where they land — say so in the surface's own voice. */}
      <span className="landing-surface-footnote">
        <StateDot tier="mastered" />
        Linked to your MA 242 graph
      </span>
    </SurfaceFrame>
  );
}
