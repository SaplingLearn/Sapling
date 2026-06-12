// Canonical Sapling brand green ("forest"). Single source of truth.
//
// The CSS custom property `--brand-forest` in globals.css carries the same
// value and is preferred in CSS / DOM-style / SVG-attribute sinks where
// `var()` resolves. This constant exists for the rare NON-CSS sinks where
// `var(--brand-forest)` would NOT resolve and a concrete hex is required:
//   - framer-motion color interpolation (`animate={{ fill: ... }}`), which
//     parses the value into RGBA channels to tween.
//   - hex-alpha string concatenation (e.g. `${BRAND_FOREST}55`).
// Keep this byte-identical to `--brand-forest`.
export const BRAND_FOREST = "#1B6C42";
