import type { SectionBar } from "@/lib/studyGuide/types";

import s from "./SpaceBar.module.css";
import { tierFill, tierLabel, tierText } from "./tiers";

/** The section that gets the most room, or null for a guide with none. */
export function widestBar(bars: SectionBar[]): SectionBar | null {
  return bars.reduce<SectionBar | null>(
    (widest, bar) => (widest && widest.weight >= bar.weight ? widest : bar),
    null,
  );
}

function describe(bars: SectionBar[]): string {
  const parts = bars.map(bar => `${bar.title} ${bar.weight}%, ${tierLabel(bar.tier)}`);
  return `Share of the guide per section: ${parts.join("; ")}`;
}

/** How a guide spends its space: one segment per section, coloured by mastery. */
export function SpaceBar({ bars, legend = false }: { bars: SectionBar[]; legend?: boolean }) {
  if (bars.length === 0) return null;
  return (
    <div className={s.wrap} data-testid="guide-space-bar">
      <div className={s.bar} role="img" aria-label={describe(bars)}>
        {bars.map((bar, i) => (
          <span
            key={`${i}-${bar.title}`}
            className={s.segment}
            style={{ flexGrow: Math.max(bar.weight, 1), background: tierFill(bar.tier) }}
          />
        ))}
      </div>
      {legend && (
        <ul className={s.legend}>
          {bars.map((bar, i) => (
            <li key={`${i}-${bar.title}`} style={{ color: tierText(bar.tier) }}>
              <span className={s.swatch} style={{ background: tierFill(bar.tier) }} aria-hidden="true" />
              {bar.title} · {tierLabel(bar.tier)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
