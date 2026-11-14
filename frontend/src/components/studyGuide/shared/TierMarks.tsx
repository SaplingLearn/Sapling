import type { Tier } from "@/lib/studyGuide/types";

import s from "./pieces.module.css";
import { tierFill, tierLabel, tierText } from "./tiers";

/** The small square in a mastery tier's colour. The label beside it says the tier. */
export function TierSwatch({ tier }: { tier: Tier }) {
  return <span className={s.swatch} style={{ background: tierFill(tier) }} aria-hidden="true" />;
}

/** "Struggling", "Mastered"…, in the tier's text colour. */
export function TierLabel({ tier }: { tier: Tier }) {
  return <span className={s.tierLabel} style={{ color: tierText(tier) }}>{tierLabel(tier)}</span>;
}
