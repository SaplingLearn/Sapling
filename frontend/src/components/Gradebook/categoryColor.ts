// Deterministic per-category color picker. Hashes the category NAME (not id)
// so the assigned color survives schema churn — if a category is deleted and
// recreated mid-semester with the same name, the bar segment keeps its color.
// Hash uses djb2; result mods into the brand color palette.

export const CATEGORY_PALETTE = [
  "var(--c-crimson)",
  "var(--c-rust)",
  "var(--c-amber)",
  "var(--c-brown)",
  "var(--c-sage)",
  "var(--c-teal)",
  "var(--c-sky)",
  "var(--c-plum)",
  "var(--c-magenta)",
  "var(--c-rose)",
];

export function categoryColor(name: string): string {
  const key = name.trim().toLowerCase();
  let h = 5381;
  for (let i = 0; i < key.length; i++) h = ((h << 5) + h + key.charCodeAt(i)) | 0;
  return CATEGORY_PALETTE[(h >>> 0) % CATEGORY_PALETTE.length];
}
