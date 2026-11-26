/**
 * W4 Stage 2 trust chrome (claim AR): short visible labels + honest tooltips.
 * Present only when the server already sent the signal — never invents cites
 * or a second verifier. No "trust the AI" framing.
 */

export const MATERIALS_GROUNDED_LABEL = "Grounded in your materials";
/** Hover / a11y detail: passages were in the prompt, not a decorative cite list. */
export const MATERIALS_GROUNDED_HINT =
  "This turn used passages from your uploaded course materials — check anything important against the source.";

export const TRUST_CHROME_STYLE = {
  fontFamily: "var(--font-sans)",
  fontSize: 12,
  color: "var(--text-muted)",
} as const;
