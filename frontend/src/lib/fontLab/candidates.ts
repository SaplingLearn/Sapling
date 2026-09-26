/**
 * Font Lab candidate lists.
 *
 * Sapling's shipped identity (see `lib/landing/fonts.ts` and `app/layout.tsx`)
 * is an editorial serif (Spectral / Playfair) over a clean UI sans (DM Sans),
 * with JetBrains Mono for tracked micro-labels and Caveat as a one-off
 * annotation hand. That is the brief every candidate below was picked
 * against: organic and a little literary at display size (a sapling is a
 * living thing, not a SaaS logomark), unfussy and legible at 13px in a
 * 232px-wide rail, and never a face so "neutral" it could belong to any
 * dashboard on earth (Roboto/Arial-class defaults are excluded on purpose).
 *
 * Every family here is served by Google Fonts and is loaded on demand — see
 * `useGoogleFonts.ts` — never bundled, so the picker never pays for a face
 * nobody has previewed yet.
 */

export type FontRole = "heading" | "body" | "label" | "subtitle";

export type FontCandidate = {
  /** Google Fonts family name, exactly as the API expects it. */
  family: string;
  /** css2 axis spec appended after the family, e.g. "wght@400;600;700". */
  axes: string;
  /** The weight actually used for the live preview. */
  previewWeight: number;
  italic?: boolean;
  /** One line: why this face earns a slot for this role. Critique, not hype. */
  note: string;
  /** Marks the family already shipping elsewhere in the product. */
  incumbent?: boolean;
};

export const ROLES: { id: FontRole; label: string; blurb: string }[] = [
  {
    id: "heading",
    label: "Heading",
    blurb: "The wordmark and page titles. Where Sapling gets to look like a plant, not a tool.",
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
      incumbent: true,
      note: "Current wordmark face. Warm old-style serif, low contrast — reads as grown, not drawn.",
    },
    {
      family: "Playfair Display",
      axes: "wght@400;600;700",
      previewWeight: 700,
      incumbent: true,
      note: "Current body-serif's display cousin. High contrast, sharper and more fashion-editorial.",
    },
    {
      family: "Fraunces",
      axes: "wght@400;600;700",
      previewWeight: 700,
      note: "Best fit in the list: a soft, wet-ink serif built for exactly this 'organic but refined' brief.",
    },
    {
      family: "Newsreader",
      axes: "wght@400;600;700",
      previewWeight: 600,
      note: "Quiet, journalistic serif. Reads calmer than Spectral — a safe, slightly duller alternative.",
    },
    {
      family: "Lora",
      axes: "wght@400;600;700",
      previewWeight: 600,
      note: "Well-worn text serif with brushed curves. Friendly, a little generic at large sizes.",
    },
    {
      family: "Source Serif 4",
      axes: "wght@400;600;700",
      previewWeight: 700,
      note: "Sturdy, workmanlike serif. Trustworthy but flatter personality than Fraunces or Spectral.",
    },
    {
      family: "Cormorant Garamond",
      axes: "wght@400;600;700",
      previewWeight: 600,
      note: "Elegant and very thin-stroked. Beautiful at 32px, too fragile for a 20px sidebar wordmark.",
    },
    {
      family: "Crimson Pro",
      axes: "wght@400;600;700",
      previewWeight: 600,
      note: "Classic book serif. Solid default energy — doesn't say 'growth' the way Fraunces does.",
    },
    {
      family: "Petrona",
      axes: "wght@400;600;700",
      previewWeight: 600,
      note: "Contemporary serif with a soft, slightly rounded texture. Underused, worth a look.",
    },
    {
      family: "Domine",
      axes: "wght@400;600;700",
      previewWeight: 700,
      note: "Bold, chunky serif built for headings. Reads sturdy and a bit plain next to organic options.",
    },
    {
      family: "Bitter",
      axes: "wght@400;600;700",
      previewWeight: 700,
      note: "Slab-leaning serif, confident at small sizes. Feels more 'editorial tech blog' than botanical.",
    },
    {
      family: "Piazzolla",
      axes: "wght@400;600;700",
      previewWeight: 600,
      note: "Warm variable serif with real personality in the curves. Close Fraunces alternative.",
    },
    {
      family: "Literata",
      axes: "wght@400;600;700",
      previewWeight: 700,
      note: "Google's own reading serif — humane, screen-optimized. Safe, well-tested, a bit corporate.",
    },
  ],
  body: [
    {
      family: "DM Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      incumbent: true,
      note: "Current UI face. Geometric but warm, low-drama at 13px — hard to beat as the daily driver.",
    },
    {
      family: "Inter",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "The default of every dashboard built in the last five years. Excellent, but says nothing.",
    },
    {
      family: "Manrope",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Slightly rounder, friendlier take on the geometric-grotesk family. Good DM Sans cousin.",
    },
    {
      family: "Public Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "USWDS's workhorse. Extremely legible, extremely neutral — leans bureaucratic, not botanical.",
    },
    {
      family: "Work Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Humanist, a touch narrower than DM Sans. Reads slightly more editorial, less 'app'.",
    },
    {
      family: "Karla",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Quirky, grotesk with soft terminals. Has more character than most options but less polish.",
    },
    {
      family: "IBM Plex Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Technical and precise. Fits the mono sibling well but reads corporate-engineering, not growth.",
    },
    {
      family: "Sora",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Rounder, softer geometric sans. Friendly, slightly younger-brand feel than DM Sans.",
    },
    {
      family: "Figtree",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Very close relative of DM Sans — rounder terminals, marginally warmer. Safe swap.",
    },
    {
      family: "Outfit",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Geometric with tighter apertures. Reads more 'startup wordmark' than 'body text at 13px'.",
    },
    {
      family: "Albert Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Neutral grotesk, closer to Helvetica's descendants. Clean but the least distinctive here.",
    },
    {
      family: "Plus Jakarta Sans",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Popular geometric sans with a bit of swagger in the italics. Slightly wide for a narrow rail.",
    },
    {
      family: "Hanken Grotesk",
      axes: "wght@400;500;600;700",
      previewWeight: 500,
      note: "Compact, no-nonsense grotesk. Sets tight, which helps in a 232px column — under-used, worth testing.",
    },
  ],
  label: [
    {
      family: "JetBrains Mono",
      axes: "wght@400;500;600",
      previewWeight: 500,
      incumbent: true,
      note: "Current label face. Reads as 'system status', which suits a tracked group header well.",
    },
    {
      family: "Space Grotesk",
      axes: "wght@400;500;600",
      previewWeight: 500,
      note: "Not a mono, but the squarish grotesk cousin of Space Mono. Reads techy without going full code.",
    },
    {
      family: "IBM Plex Mono",
      axes: "wght@400;500;600",
      previewWeight: 500,
      note: "Sibling of Plex Sans. Slightly narrower than JetBrains, a touch more 'terminal'.",
    },
    {
      family: "Space Mono",
      axes: "wght@400;700",
      previewWeight: 700,
      note: "Quirky, wide-set mono with real personality. Loud at all-caps — good if labels want to pop more.",
    },
    {
      family: "Archivo",
      axes: "wght@500;600;700",
      previewWeight: 600,
      note: "Grotesk, not mono — trades the 'code' association for a bolder, more poster-like caps set.",
    },
    {
      family: "Archivo Narrow",
      axes: "wght@500;600;700",
      previewWeight: 600,
      note: "Condensed grotesk. Lets a label pack more tracking into the same width — worth testing at 10px.",
    },
    {
      family: "DM Mono",
      axes: "wght@400;500",
      previewWeight: 500,
      note: "DM Sans's mono sibling — pairs cleanly if body also goes DM Sans. Quieter than JetBrains.",
    },
    {
      family: "Red Hat Mono",
      axes: "wght@400;500",
      previewWeight: 500,
      note: "Clean, slightly geometric mono. Under-the-radar, reads a bit more 'dashboard', less 'IDE'.",
    },
    {
      family: "Azeret Mono",
      axes: "wght@400;500;600",
      previewWeight: 500,
      note: "Distinctive ligature-heavy mono. More visual flavor than most, risks feeling gimmicky at 10px.",
    },
    {
      family: "Chivo Mono",
      axes: "wght@400;500;600",
      previewWeight: 500,
      note: "Grotesk-flavored mono, wide apertures. Sets a hair looser than JetBrains — easier at tiny sizes.",
    },
    {
      family: "Martian Mono",
      axes: "wght@400;500",
      previewWeight: 500,
      note: "Chunky, retro-computing mono. Strong personality but possibly too costume-y for a nav label.",
    },
    {
      family: "Overpass Mono",
      axes: "wght@400;600",
      previewWeight: 600,
      note: "Highway-signage mono heritage. Sturdy and legible, a bit heavier-set than the others.",
    },
    {
      family: "Roboto Mono",
      axes: "wght@400;500",
      previewWeight: 500,
      note: "The default mono. Perfectly fine, contributes nothing to Sapling's voice — control sample.",
    },
  ],
  subtitle: [
    {
      family: "DM Sans",
      axes: "wght@400",
      previewWeight: 400,
      italic: true,
      incumbent: true,
      note: "Current approach: same sans as body, just lighter/smaller. Coherent, but doesn't feel 'secondary'.",
    },
    {
      family: "Spectral",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "The heading serif's italic. Gives subtitles an editorial 'aside' voice without adding a new family.",
    },
    {
      family: "Newsreader",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Soft, quiet italic — reads like a caption in a printed book. Excellent restraint.",
    },
    {
      family: "Source Serif 4",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Sturdier italic, less swash than Newsreader. Good if subtitles need to stay legible at 11px.",
    },
    {
      family: "Lora",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Warm, slightly bouncy italic. Friendly, though a touch informal for account-level metadata.",
    },
    {
      family: "Crimson Pro",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Classic book italic. Tasteful, if a little sleepy — very safe choice.",
    },
    {
      family: "Instrument Serif",
      axes: "ital@1",
      previewWeight: 400,
      italic: true,
      note: "High-contrast display italic. Gorgeous as a one-off flourish, too loud repeated on every card.",
    },
    {
      family: "Libre Baskerville",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Sturdy, screen-tuned Baskerville italic. Reads a bit more 'legal document' than 'app caption'.",
    },
    {
      family: "STIX Two Text",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Academic-journal italic. Fits the tutoring/knowledge-graph subject matter conceptually.",
    },
    {
      family: "Petrona",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Soft companion to its own heading candidate above — pairs the two roles from one family.",
    },
    {
      family: "Noto Serif",
      axes: "ital,wght@1,400",
      previewWeight: 400,
      italic: true,
      note: "Extremely neutral italic. Reliable fallback-grade choice, no real point of view.",
    },
    {
      family: "Karla",
      axes: "ital@1",
      previewWeight: 400,
      italic: true,
      note: "Sans italic instead of serif — keeps subtitle in the UI-sans family, just slanted and lighter.",
    },
    {
      family: "Work Sans",
      axes: "ital@1",
      previewWeight: 400,
      italic: true,
      note: "Another sans-italic route. Slightly narrower than Karla, reads calmer next to DM Sans body.",
    },
  ],
};

export const DEFAULT_SELECTION: Record<FontRole, string> = {
  heading: "Spectral",
  body: "DM Sans",
  label: "JetBrains Mono",
  subtitle: "DM Sans",
};
