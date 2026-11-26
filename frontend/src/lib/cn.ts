import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/* tailwind-merge has to know Sapling's theme names (src/styles/theme.css),
   or it can't tell `text-md` (a font size) from `text-text-dim` (a colour)
   and would drop one of them as a "conflict". Keep these lists in step with
   theme.css; cn.test.ts pins the cases that matter. */
const FONT_SIZES = ["2xs", "xs", "sm", "md", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl"];
const RADII = ["xs", "sm", "md", "lg", "xl"];
const SHADOWS = ["sm", "md", "lg", "inset"];
const FONTS = ["sans", "serif", "display", "code"];

const merge = extendTailwindMerge({
  override: {
    // Sapling's font sizes carry no line height, so text-md must not drop an
    // earlier leading-[1.6] (tailwind-merge's default assumes it does).
    conflictingClassGroups: { "font-size": [] },
    theme: {
      text: FONT_SIZES,
      radius: RADII,
      shadow: SHADOWS,
      font: FONTS,
    },
  },
});

/** Join class names, dropping falsy ones; a later Tailwind class wins over an
 *  earlier one for the same property (`cn("p-2", props.className)`). */
export function cn(...inputs: ClassValue[]): string {
  return merge(clsx(inputs));
}
