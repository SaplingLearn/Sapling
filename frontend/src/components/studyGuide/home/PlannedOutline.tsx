import { Skeleton } from "@/components/Skeleton";

import { SpaceBar } from "../shared/SpaceBar";
import { tierFill, tierLabel, tierText } from "../shared/tiers";
import m from "./newGuide.module.css";
import type { PlanState } from "./usePlan";

/**
 * What the guide will cover for the choices as they stand: each planned
 * section with its mastery colour and share, and how long it reads.
 * `ready` is false while there is no class and material to plan for.
 */
export function PlannedOutline({ ready, state }: { ready: boolean; state: PlanState }) {
  return (
    <section className={m.outline} aria-label="Planned outline" aria-busy={state.loading} data-testid="guide-new-outline">
      <span className="label-micro">Planned outline</span>
      <OutlineBody ready={ready} state={state} />
    </section>
  );
}

function OutlineBody({ ready, state }: { ready: boolean; state: PlanState }) {
  if (!ready) return <p className={m.outlineNote}>Pick at least one material to see the outline.</p>;
  if (state.failed) return <p className={m.outlineNote}>Couldn&apos;t plan the outline. You can still generate the guide.</p>;
  const plan = state.plan;
  if (!plan) return <OutlineSkeleton />;
  if (plan.sections.length === 0) return <p className={m.outlineNote}>Nothing to outline from these materials yet.</p>;
  return (
    <div className={m.outlineBody} data-stale={state.loading || undefined}>
      <SpaceBar bars={plan.sections} />
      <ol className={m.sections}>
        {plan.sections.map((section, i) => (
          <li key={`${i}-${section.title}`} className={m.section} data-testid={`guide-new-outline-section-${i}`} data-tier={section.tier}>
            <span className={m.swatch} style={{ background: tierFill(section.tier) }} aria-hidden="true" />
            <span className={m.sectionText}>
              <span className={m.sectionTitle}>{section.title}</span>
              <span className={m.sectionTier} style={{ color: tierText(section.tier) }}>{tierLabel(section.tier)}</span>
            </span>
            <span className={m.share}>{section.weight}%</span>
          </li>
        ))}
      </ol>
      <p className={m.minutes} data-testid="guide-new-outline-minutes">about {plan.minutes} min</p>
      <p className={m.outlineNote}>The written guide may merge or rename sections.</p>
    </div>
  );
}

function OutlineSkeleton() {
  return (
    <div className={m.outlineBody} aria-hidden="true">
      <Skeleton height={12} radius="var(--r-xs)" />
      <Skeleton width="80%" height={14} />
      <Skeleton width="65%" height={14} />
      <Skeleton width="72%" height={14} />
    </div>
  );
}
