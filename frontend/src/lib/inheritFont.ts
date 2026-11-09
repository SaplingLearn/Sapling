import type { CSSProperties } from "react";

/**
 * `font: inherit` spelled as longhands. React warns (and can mis-style on
 * rerender) when the `font` shorthand sits next to a `fontWeight`/`fontSize`
 * that changes between renders. Spread this where `font: "inherit"` would go;
 * key order gives the same override semantics as the shorthand.
 */
export const INHERIT_FONT: CSSProperties = {
  fontFamily: "inherit",
  fontSize: "inherit",
  fontWeight: "inherit",
  fontStyle: "inherit",
  lineHeight: "inherit",
};
