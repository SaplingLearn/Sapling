/**
 * A journal post's artwork, at any size.
 *
 * Two posts ship photographs; the rest are illustrated with a drawn motif
 * taken from what the article actually argues — the forgetting curve for the
 * spacing piece, a verdict list for TeachBack, a syllabus becoming a calendar
 * for the ingest release. Before #601 those rendered an empty tinted panel on
 * /news and the article pages showed no artwork at all.
 *
 * The same component serves the landing card (~243px), the /news card
 * (~330px) and the article hero (~880px), which is a 3.6x magnification of
 * the same 243-unit drawing. Strokes take that happily; text does not — at
 * card size the labels are 7.5px, at hero they came out bigger than the
 * article's own body copy. So text is the one thing that does not scale
 * with the box: the plate label is a fixed-size span outside the SVG, and
 * in-drawing labels shrink in user units via `variant="hero"`.
 *
 * Callers supply the box: absolutely fills a `position: relative` parent,
 * cropping to whatever aspect ratio that parent sets.
 */

import Image from 'next/image';

import type { ArticleArt as Art, ArtMotif } from '@/lib/landing/journalArticles';

const GROUND = 'radial-gradient(ellipse 80% 70% at 45% 45%, #EAF1EC 0%, #E2ECE5 60%, #D8E5DD 100%)';

/** Mastery-tier palette, shared with the landing acts. */
const GREEN = '#0E9E5A';
const GREEN_DEEP = '#0C5638';
const GREEN_MID = '#4FA574';
const AMBER = '#C89B5E';
const CORAL = '#E27A63';
const INK = '#4A5D53';
const MUTED = '#61726A';
const PAPER = '#FDFCF9';
const HAIRLINE = 'rgba(18,32,26,0.12)';

function Frame({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ position: 'absolute', inset: 0, background: GROUND }}>
      <svg width="100%" height="100%" viewBox="0 0 243 158" preserveAspectRatio="xMidYMid slice">
        {children}
      </svg>
      <span
        style={{
          position: 'absolute',
          left: '5%',
          top: '6%',
          fontFamily: "'JetBrains Mono',monospace",
          fontSize: 9.5,
          letterSpacing: '0.18em',
          color: GREEN_DEEP,
        }}
      >
        {label}
      </span>
    </div>
  );
}

/** Concepts, prerequisite edges, and a mastery arc on each node. */
function GraphMotif({ ls }: MotifProps) {
  return (
    <Frame label="CS 112 · KNOWLEDGE GRAPH">
      <line x1="118" y1="76" x2="62" y2="44" stroke="rgba(12,86,56,0.3)" />
      <line x1="118" y1="76" x2="54" y2="108" stroke="rgba(12,86,56,0.3)" />
      <line x1="118" y1="76" x2="182" y2="50" stroke="rgba(12,86,56,0.3)" />
      <line x1="118" y1="76" x2="176" y2="116" stroke="rgba(12,86,56,0.2)" />
      <line x1="62" y1="44" x2="182" y2="50" stroke="rgba(12,86,56,0.12)" />
      <line x1="54" y1="108" x2="176" y2="116" stroke="rgba(12,86,56,0.12)" />
      {/* each node's ring arc is its mastery, drawn from 12 o'clock */}
      <circle cx="118" cy="76" r="15" fill="none" stroke={HAIRLINE} strokeWidth="2.6" />
      <circle cx="118" cy="76" r="15" fill="none" stroke={GREEN} strokeWidth="2.6" strokeLinecap="round" strokeDasharray="58 94" transform="rotate(-90 118 76)" />
      <circle cx="118" cy="76" r="9" fill={GREEN} />
      <text x="118" y="79" textAnchor="middle" fontFamily="JetBrains Mono" fontSize={7 * ls} fill="#061710">112</text>
      <circle cx="62" cy="44" r="10" fill="none" stroke={HAIRLINE} strokeWidth="2.2" />
      <circle cx="62" cy="44" r="10" fill="none" stroke={GREEN_MID} strokeWidth="2.2" strokeLinecap="round" strokeDasharray="38 25" transform="rotate(-90 62 44)" />
      <circle cx="62" cy="44" r="5.5" fill={GREEN_MID} />
      <text x="62" y="26" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={INK}>Trees</text>
      <circle cx="54" cy="108" r="10" fill="none" stroke={HAIRLINE} strokeWidth="2.2" />
      <circle cx="54" cy="108" r="10" fill="none" stroke={GREEN} strokeWidth="2.2" strokeLinecap="round" strokeDasharray="55 8" transform="rotate(-90 54 108)" />
      <circle cx="54" cy="108" r="5.5" fill={GREEN} />
      <text x="54" y="130" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={INK}>Sorting</text>
      <circle cx="182" cy="50" r="10" fill="none" stroke={HAIRLINE} strokeWidth="2.2" />
      <circle cx="182" cy="50" r="10" fill="none" stroke={CORAL} strokeWidth="2.2" strokeLinecap="round" strokeDasharray="16 47" transform="rotate(-90 182 50)" />
      <circle cx="182" cy="50" r="5" fill={CORAL} />
      <text x="182" y="32" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={INK}>Recursion</text>
      <circle cx="176" cy="116" r="9" fill="none" stroke="rgba(18,32,26,0.10)" strokeWidth="2" />
      <circle cx="176" cy="116" r="4.5" fill="#9a9a9a" />
      <text x="176" y="137" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={MUTED}>DP</text>
    </Frame>
  );
}

/**
 * The forgetting curve, restored at each shipped interval — and, dotted, the
 * decay you keep if nobody reviews. Each successive decay is shallower,
 * which is the whole argument of the article.
 */
function SpacingMotif({ ls }: MotifProps) {
  return (
    <Frame label="SPACED REVIEW · INTERVALS">
      <line x1="22" y1="118" x2="226" y2="118" stroke="rgba(12,86,56,0.18)" />
      <path d="M76 90C120 108 170 114 220 116" fill="none" stroke={MUTED} strokeWidth="1.1" strokeDasharray="2 3" opacity="0.45" />
      <path d="M30 36C46 74 62 86 76 90" fill="none" stroke={GREEN_DEEP} strokeWidth="2" strokeLinecap="round" opacity="0.85" />
      <path d="M76 34C96 62 116 72 138 76" fill="none" stroke={GREEN_DEEP} strokeWidth="2" strokeLinecap="round" opacity="0.85" />
      <path d="M138 31C168 44 196 52 220 56" fill="none" stroke={GREEN_DEEP} strokeWidth="2" strokeLinecap="round" opacity="0.85" />
      {/* the review itself: recall snaps retention back to the top */}
      <path d="M76 90V36" stroke={GREEN} strokeWidth="1.6" strokeDasharray="3 2.5" />
      <path d="M138 76V33" stroke={GREEN} strokeWidth="1.6" strokeDasharray="3 2.5" />
      <circle cx="76" cy="34" r="3.6" fill={GREEN} />
      <circle cx="138" cy="31" r="3.6" fill={GREEN} />
      <circle cx="30" cy="36" r="3.2" fill={GREEN_MID} />
      <circle cx="220" cy="56" r="3.2" fill={GREEN_MID} />
      <line x1="76" y1="118" x2="76" y2="124" stroke="rgba(12,86,56,0.35)" />
      <line x1="138" y1="118" x2="138" y2="124" stroke="rgba(12,86,56,0.35)" />
      <line x1="220" y1="118" x2="220" y2="124" stroke="rgba(12,86,56,0.35)" />
      <text x="76" y="135" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={INK}>10 min</text>
      <text x="138" y="135" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={INK}>1 day</text>
      <text x="218" y="135" textAnchor="middle" fontFamily="DM Sans" fontSize={7.5 * ls} fill={INK}>4 days</text>
    </Frame>
  );
}

/** You explain; the verdict comes back a piece at a time. */
function TeachBackMotif({ ls }: MotifProps) {
  const rows = [
    { y: 46, tint: 'rgba(14,158,90,0.14)', stroke: GREEN, mark: 'M-3 0 -0.8 2.4 3.2 -2.4', label: 'Covered' },
    { y: 71, tint: 'rgba(200,155,94,0.16)', stroke: AMBER, mark: 'M-3.2 0.8C-2 -1.6 -1 -1.6 0 0S2 1.6 3.2 -0.8', label: 'Vague' },
    { y: 96, tint: 'rgba(226,122,99,0.14)', stroke: CORAL, mark: 'M-2.6 -2.6 2.6 2.6M2.6 -2.6 -2.6 2.6', label: 'Missing' },
  ];
  return (
    <Frame label="TEACHBACK · THE VERDICT">
      <rect x="18" y="34" width="112" height="64" rx="12" fill={PAPER} stroke={HAIRLINE} />
      <path d="M34 97V110L49 97Z" fill={PAPER} stroke={HAIRLINE} strokeLinejoin="round" />
      <rect x="31" y="48" width="84" height="4.6" rx="2.3" fill="rgba(12,86,56,0.18)" />
      <rect x="31" y="60" width="72" height="4.6" rx="2.3" fill="rgba(12,86,56,0.18)" />
      <rect x="31" y="72" width="86" height="4.6" rx="2.3" fill="rgba(12,86,56,0.18)" />
      <rect x="31" y="84" width="45" height="4.6" rx="2.3" fill="rgba(12,86,56,0.10)" />
      <line x1="143" y1="34" x2="143" y2="112" stroke="rgba(12,86,56,0.14)" />
      {rows.map((row) => (
        <g key={row.label}>
          <circle cx="160" cy={row.y} r="8" fill={row.tint} />
          <path d={row.mark} transform={`translate(160 ${row.y})`} fill="none" stroke={row.stroke} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          <text x="175" y={row.y + 3} fontFamily="DM Sans" fontSize={8.5 * ls} fill={INK}>{row.label}</text>
        </g>
      ))}
    </Frame>
  );
}

/** One document in; a dated semester out. */
function SyllabusMotif() {
  const cells = Array.from({ length: 24 }, (_, i) => ({
    x: 136 + (i % 6) * 14,
    y: 56 + Math.floor(i / 6) * 14,
  }));
  const marked: Record<number, string> = { 4: CORAL, 9: AMBER, 16: GREEN, 21: GREEN };
  return (
    <Frame label="SYLLABUS · ONE UPLOAD">
      <rect x="26" y="38" width="62" height="80" rx="6" fill={PAPER} stroke={HAIRLINE} />
      <path d="M76 38 88 50H76Z" fill="rgba(12,86,56,0.10)" />
      <rect x="36" y="52" width="28" height="4.4" rx="2.2" fill="rgba(12,86,56,0.30)" />
      <rect x="36" y="66" width="42" height="3.6" rx="1.8" fill="rgba(12,86,56,0.16)" />
      <rect x="36" y="76" width="36" height="3.6" rx="1.8" fill="rgba(12,86,56,0.16)" />
      <rect x="36" y="86" width="44" height="3.6" rx="1.8" fill="rgba(12,86,56,0.16)" />
      <rect x="36" y="96" width="30" height="3.6" rx="1.8" fill="rgba(12,86,56,0.16)" />
      <path d="M99 78H119" stroke={GREEN_DEEP} strokeWidth="1.6" strokeLinecap="round" opacity="0.6" />
      <path d="M114 73 120 78 114 83" fill="none" stroke={GREEN_DEEP} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <line key={i} x1={136 + i * 14} y1="46" x2={146 + i * 14} y2="46" stroke="rgba(12,86,56,0.25)" strokeWidth="1.4" strokeLinecap="round" />
      ))}
      {cells.map((cell, i) => (
        <rect key={i} x={cell.x} y={cell.y} width="10" height="10" rx="2.4" fill={marked[i] ?? 'rgba(18,32,26,0.07)'} />
      ))}
    </Frame>
  );
}

/**
 * The team's own map: linked notes, each carrying how settled it is. The
 * states are the article's point — a shared map is only trustworthy if it
 * admits which parts nobody has confirmed yet.
 */
function CanopyMotif({ ls }: MotifProps) {
  const states = [
    { y: 52, tint: 'rgba(14,158,90,0.16)', dot: GREEN, label: 'Live' },
    { y: 80, tint: 'rgba(200,155,94,0.18)', dot: AMBER, label: 'Staged' },
    { y: 108, tint: 'rgba(18,32,26,0.08)', dot: '#9a9a9a', label: 'Draft' },
  ];
  return (
    <Frame label="CANOPY · THE SHARED MAP">
      {/* links are drawn first, so the opaque cards leave them showing in the gaps */}
      <line x1="42" y1="46" x2="104" y2="72" stroke="rgba(12,86,56,0.30)" />
      <line x1="42" y1="46" x2="46" y2="112" stroke="rgba(12,86,56,0.30)" />
      <line x1="104" y1="72" x2="46" y2="112" stroke="rgba(12,86,56,0.18)" />
      <line x1="46" y1="112" x2="84" y2="117" stroke="rgba(12,86,56,0.20)" strokeDasharray="3 3" />
      {/* two settled entries */}
      <rect x="20" y="32" width="44" height="28" rx="6" fill={PAPER} stroke={HAIRLINE} />
      <rect x="26" y="39" width="24" height="3.2" rx="1.6" fill="rgba(12,86,56,0.30)" />
      <rect x="26" y="46" width="30" height="2.8" rx="1.4" fill="rgba(12,86,56,0.16)" />
      <rect x="26" y="52" width="18" height="2.8" rx="1.4" fill="rgba(12,86,56,0.16)" />
      <circle cx="57" cy="38" r="2.6" fill={GREEN} />
      <rect x="82" y="58" width="44" height="28" rx="6" fill={PAPER} stroke={HAIRLINE} />
      <rect x="88" y="65" width="26" height="3.2" rx="1.6" fill="rgba(12,86,56,0.30)" />
      <rect x="88" y="72" width="30" height="2.8" rx="1.4" fill="rgba(12,86,56,0.16)" />
      <rect x="88" y="78" width="20" height="2.8" rx="1.4" fill="rgba(12,86,56,0.16)" />
      <circle cx="119" cy="64" r="2.6" fill={GREEN} />
      {/* one staged: written, not yet confirmed by a person */}
      <rect x="24" y="98" width="44" height="28" rx="6" fill={PAPER} stroke="rgba(200,155,94,0.8)" strokeDasharray="3.5 2.5" />
      <rect x="30" y="105" width="24" height="3.2" rx="1.6" fill="rgba(200,155,94,0.55)" />
      <rect x="30" y="112" width="28" height="2.8" rx="1.4" fill="rgba(12,86,56,0.14)" />
      <circle cx="61" cy="104" r="2.6" fill={AMBER} />
      {/* and one still an open question */}
      <rect x="84" y="106" width="40" height="26" rx="5" fill="none" stroke="rgba(18,32,26,0.22)" strokeDasharray="3 3" />
      <rect x="90" y="118" width="20" height="2.6" rx="1.3" fill="rgba(18,32,26,0.12)" />
      <rect x="90" y="124" width="13" height="2.6" rx="1.3" fill="rgba(18,32,26,0.10)" />
      <circle cx="117" cy="112" r="2.4" fill="#9a9a9a" />
      <line x1="140" y1="32" x2="140" y2="134" stroke="rgba(12,86,56,0.14)" />
      {states.map((state) => (
        <g key={state.label}>
          <circle cx="157" cy={state.y} r="7.5" fill={state.tint} />
          <circle cx="157" cy={state.y} r="3" fill={state.dot} />
          <text x="172" y={state.y + 3} fontFamily="DM Sans" fontSize={8.5 * ls} fill={INK}>{state.label}</text>
        </g>
      ))}
    </Frame>
  );
}

/** Label scale in viewBox units: 1 at card size, halved for the hero. */
interface MotifProps {
  ls: number;
}

const MOTIFS: Record<ArtMotif, (props: MotifProps) => React.JSX.Element> = {
  graph: GraphMotif,
  spacing: SpacingMotif,
  teachback: TeachBackMotif,
  syllabus: SyllabusMotif,
  canopy: CanopyMotif,
};

export function ArticleArt({
  art,
  sizes,
  priority = false,
  variant = 'card',
}: {
  art: Art;
  /** Passed through to next/image for photo posts. */
  sizes?: string;
  priority?: boolean;
  /** `hero` shrinks in-drawing labels to suit the magnified box. */
  variant?: 'card' | 'hero';
}) {
  if (art.kind === 'photo') {
    return <Image src={art.src} alt="" fill sizes={sizes} priority={priority} style={{ objectFit: 'cover' }} />;
  }
  const Motif = MOTIFS[art.motif];
  return <Motif ls={variant === 'hero' ? 0.52 : 1} />;
}
