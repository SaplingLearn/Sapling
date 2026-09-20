import type { CSSProperties } from "react";

/**
 * Bind the course accent for a subtree — R-1's one styling exemption ("binding
 * a CSS custom property to runtime data"), collected here so quiz home has a
 * single auditable site for it.
 *
 * `QuizScreen` already sets `--quiz-accent` on `.quiz-root`, which covers
 * everything in the page tree. The two dialogs do NOT live in that tree:
 * `Dialog` portals its panel to `document.body`, where the accent would fall
 * all the way back to `var(--accent)` and the segmented underlines would paint
 * in the app's green instead of the course's colour. Re-binding it on the
 * dialog root is what keeps a portalled panel looking like the screen it came
 * from.
 */
export function accentStyle(color: string | null | undefined): CSSProperties | undefined {
  return color ? ({ "--quiz-accent": color } as CSSProperties) : undefined;
}
