/**
 * Capitalise the first letter of a raw value ("common" -> "Common",
 * "lecture notes" -> "Lecture notes") for display.
 *
 * Labels used to be forced to ALL CAPS by CSS, which hid that many of them
 * render lowercase enum values straight from the API. Sentence case is the
 * house style now, so those values pass through here instead.
 */
export function sentenceCase(value: string | null | undefined): string {
  if (!value) return "";
  return value.charAt(0).toUpperCase() + value.slice(1);
}
