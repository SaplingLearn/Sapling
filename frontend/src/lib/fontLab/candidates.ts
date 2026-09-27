/**
 * Font Lab candidate lists.
 *
 * Deliberately NOT reasoned from Sapling's shipped identity (Spectral /
 * Playfair / DM Sans / JetBrains Mono — see `lib/landing/fonts.ts` and
 * `app/layout.tsx`). A first pass here started from "what fits the existing
 * organic/editorial story" and kept landing on the same handful of faces
 * every AI-generated brand reaches for right now (Fraunces, Inter, Space
 * Grotesk, Plus Jakarta Sans...) — which defeats the point of a comparison.
 * This list is a blind pass instead: each role spans genuinely different
 * structural families (old-style vs. slab vs. decorative serif; grotesque vs.
 * geometric vs. humanist sans) with almost no overlap with the shipped faces
 * or with each other, so the choice gets made by looking at the live rail,
 * not by a rationale written in advance. The one exception per role is the
 * shipped incumbent, kept only so "Reset to shipped fonts" has something to
 * reset to.
 *
 * Every family here is served by Google Fonts and is loaded on demand — see
 * `useGoogleFonts.ts` — never bundled, so the picker never pays for a face
 * nobody has previewed yet.
 */

export type FontRole = "heading" | "body" | "label" | "subtitle";

export type FontGeneric = "serif" | "sans-serif" | "monospace";

export type FontCandidate = {
  /** Google Fonts family name, exactly as the API expects it. */
  family: string;
  /** css2 axis spec appended after the family, e.g. "wght@400;600;700". */
  axes: string;
  /** The weight actually used for the live preview. */
  previewWeight: number;
  italic?: boolean;
  /** Last-resort keyword for the CSS stack — this family's actual shape, not a role default. */
  generic: FontGeneric;
  /** One line, purely descriptive — what it looks like, not why it "fits". */
  note: string;
  /** Marks the family already shipping elsewhere in the product. */
  incumbent?: boolean;
};

export const ROLES: { id: FontRole; label: string; blurb: string }[] = [
  {
    id: "heading",
    label: "Heading",
    blurb: "The wordmark and page titles.",
  },
  {
    id: "body",
    label: "Regular",
    blurb: "Nav labels, buttons, running UI text. Has to hold up at 13px in a narrow rail.",
  },
  {
    id: "label",
    label: "Section label",
    blurb: "Tracked uppercase group headers — LEARN, ORGANIZE. Small and loud on purpose.",
  },
  {
    id: "subtitle",
    label: "Subtitle",
    blurb: "Secondary text riding under a heading or name — a quieter, second voice.",
  },
];

export const CANDIDATES: Record<FontRole, FontCandidate[]> = {
  heading: [
    {
      family: "Spectral",
      axes: "wght@400;600;700",
      previewWeight: 700,
      generic: "serif",
      incumbent: true,
      note: "Shipped today. Warm old-style serif, low contrast.",
    },
    {
      family: "Besley",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Sturdy transitional serif with sharp, slightly modern spurs.",
    },
    {
      family: "Yeseva One",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Bold decorative serif, thick curves — closer to a poster than a UI.",
    },
    {
      family: "Rozha One",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Sharp, angular bracket serifs. Unusual, a little severe.",
    },
    {
      family: "Old Standard TT",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Classic 19th-century academic-text serif. Dense, formal.",
    },
    {
      family: "Unna",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Slightly quirky slab-leaning serif with heavy ink traps.",
    },
    {
      family: "Bevan",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Heavy slab serif built for posters. Loud, industrial.",
    },
    {
      family: "Special Elite",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Worn typewriter face. Distressed, deliberately imperfect strokes.",
    },
    {
      family: "Big Shoulders Display",
      axes: "wght@400;700;900",
      previewWeight: 700,
      generic: "serif",
      note: "Condensed architectural slab, inspired by Chicago ironwork lettering.",
    },
    {
      family: "Gelasio",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Georgia-shaped metric-compatible serif. Plain, screen-tuned.",
    },
    {
      family: "Marcellus",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Cool, austere classical-inscription serif. Single weight, no italic.",
    },
    {
      family: "Vollkorn",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Sturdy book serif with a soft, slightly rustic texture.",
    },
    {
      family: "Zilla Slab",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Warm, humanist slab serif. Rounded, approachable weight.",
    },
  ],
  body: [
    {
      family: "DM Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      incumbent: true,
      note: "Shipped today. Geometric, low-drama grotesque.",
    },
    {
      family: "Schibsted Grotesk",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Newsroom grotesque with open apertures and a distinct lowercase g.",
    },
    {
      family: "Familjen Grotesk",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Swedish grotesque with quirky ligatures and a tight, dry texture.",
    },
    {
      family: "Bricolage Grotesque",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Variable display grotesque with expressive, uneven stroke contrast.",
    },
    {
      family: "Onest",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Rounded, soft geometric sans with a friendly, low-contrast rhythm.",
    },
    {
      family: "Gabarito",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Wide, confident geometric sans built for headline-weight UI.",
    },
    {
      family: "Instrument Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Crisp grotesque sibling of Instrument Serif. Neutral, precise.",
    },
    {
      family: "Gantari",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Rounder terminals, slightly wider counters than a typical grotesque.",
    },
    {
      family: "Jost",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Futura-style geometric sans — circular bowls, high x-height.",
    },
    {
      family: "Urbanist",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Thin-stroked geometric sans, airy and wide-set.",
    },
    {
      family: "Lexend",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Designed for reading proficiency — wide, even, deliberately plain.",
    },
    {
      family: "Wix Madefor Text",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Compact, tightly-spaced grotesque built for dense UI copy.",
    },
    {
      family: "Be Vietnam Pro",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      generic: "sans-serif",
      note: "Rounded grotesque with a slightly larger, chunkier lowercase.",
    },
  ],
  label: [
    {
      family: "JetBrains Mono",
      axes: "wght@400;500;600",
      previewWeight: 500,
      generic: "monospace",
      incumbent: true,
      note: "Shipped today. Coder-mono, reads as 'system status'.",
    },
    {
      family: "Fragment Mono",
      axes: "wght@400",
      previewWeight: 400,
      generic: "monospace",
      note: "Distinctive ligature-heavy mono with unusual curved terminals.",
    },
    {
      family: "Spline Sans Mono",
      axes: "wght@400;500;600",
      previewWeight: 500,
      generic: "monospace",
      note: "Rounded, soft-edged mono — friendlier than a typical code font.",
    },
    {
      family: "Syne Mono",
      axes: "wght@400",
      previewWeight: 400,
      generic: "monospace",
      note: "Wide, squarish experimental mono with an architectural feel.",
    },
    {
      family: "Share Tech Mono",
      axes: "wght@400",
      previewWeight: 400,
      generic: "monospace",
      note: "Retro terminal-green mono energy without actually being green.",
    },
    {
      family: "Cutive Mono",
      axes: "wght@400",
      previewWeight: 400,
      generic: "monospace",
      note: "Typewriter-styled mono — serif-ish slab feet on every letter.",
    },
    {
      family: "B612 Mono",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "monospace",
      note: "Designed for aircraft cockpit displays — extreme-legibility mono.",
    },
    {
      family: "Anonymous Pro",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "monospace",
      note: "Plain, sturdy coder mono. Deliberately unremarkable.",
    },
    {
      family: "Victor Mono",
      axes: "wght@400;600",
      previewWeight: 600,
      generic: "monospace",
      note: "Mono with cursive italics available — soft, slightly narrow uprights.",
    },
    {
      family: "Fira Code",
      axes: "wght@400;500;600",
      previewWeight: 500,
      generic: "monospace",
      note: "Ligature-rich coder mono, slightly rounder than JetBrains Mono.",
    },
    {
      family: "Ubuntu Mono",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "monospace",
      note: "Distinctly humanist mono — Ubuntu's rounded system-font DNA.",
    },
    {
      family: "Zilla Slab Highlight",
      axes: "wght@400;700",
      previewWeight: 700,
      generic: "serif",
      note: "Not a mono at all — a bold display slab meant for short bursts. Wild card.",
    },
    {
      family: "PT Mono",
      axes: "wght@400",
      previewWeight: 400,
      generic: "monospace",
      note: "Dense, narrow Cyrillic-heritage mono. Tighter tracking than most.",
    },
  ],
  subtitle: [
    {
      family: "DM Sans",
      axes: "wght@400",
      previewWeight: 400,
      generic: "sans-serif",
      incumbent: true,
      note: "Shipped today: same sans as body, upright, just lighter/smaller.",
    },
    {
      family: "Vollkorn",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Rustic book-serif italic, paired here with its own heading option.",
    },
    {
      family: "Bitter",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Slab-leaning italic — sturdier than a typical caption serif.",
    },
    {
      family: "Besley",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Sharp transitional-serif italic, same family as its heading option.",
    },
    {
      family: "Old Standard TT",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Dense academic-text italic — reads like a footnote.",
    },
    {
      family: "Gelasio",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Georgia-shaped italic — plain, screen-tuned, unremarkable on purpose.",
    },
    {
      family: "Unna",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Quirky ink-trap italic, a softer cousin of its heading option.",
    },
    {
      family: "Piazzolla",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Warm variable-serif italic with real personality in the curves.",
    },
    {
      family: "Literata",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Google's own reading-serif italic — humane, screen-optimized.",
    },
    {
      family: "Domine",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Upright only (no italic cut exists) — bold, chunky heading-style serif used quiet and small instead.",
    },
    {
      family: "Zilla Slab",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      generic: "serif",
      note: "Humanist slab italic, same family as its heading option.",
    },
    {
      family: "Marcellus",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Upright only — cool, classical, sits very still on the page.",
    },
    {
      family: "Special Elite",
      axes: "wght@400",
      previewWeight: 400,
      generic: "serif",
      note: "Upright only — worn typewriter voice, like a hand-typed annotation.",
    },
  ],
};

export const DEFAULT_SELECTION: Record<FontRole, string> = {
  heading: "Spectral",
  body: "DM Sans",
  label: "JetBrains Mono",
  subtitle: "DM Sans",
};
