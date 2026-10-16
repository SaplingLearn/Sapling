/**
 * Plain-language labels for the admin Feature flags tab (#620).
 *
 * The flag store speaks in variants ("off"/"on", variants[0] = off). For the
 * `hide_*` nav flags "on" HIDES the feature, which is backwards for anyone
 * reading a visibility switch, so the UI only ever says Visible / Hidden.
 * Any other flag keeps its own variant names. Pure functions only.
 */
import type { AdminFlag } from "@/lib/api";
import { NAV_SECTIONS } from "@/lib/navFeatures";

export type FlagMeta = { title: string; group: string; hideFlag: boolean };

export const OTHER_GROUP = "Other";

const humanize = (key: string) =>
  key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function flagMeta(key: string): FlagMeta {
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (item.flag === key) return { title: item.label, group: section.label, hideFlag: true };
    }
  }
  return { title: humanize(key), group: OTHER_GROUP, hideFlag: false };
}

/** Flags grouped in nav order (Learn, Organize, …), anything else last. */
export function groupFlags(flags: AdminFlag[]): { group: string; flags: AdminFlag[] }[] {
  const order = [...NAV_SECTIONS.map((s) => s.label), OTHER_GROUP];
  const navOrder = NAV_SECTIONS.flatMap((s) => s.items.map((i) => i.flag)).filter(Boolean);
  const groups = new Map<string, AdminFlag[]>();
  for (const f of flags) {
    const g = flagMeta(f.key).group;
    groups.set(g, [...(groups.get(g) ?? []), f]);
  }
  return order
    .filter((g) => groups.has(g))
    .map((g) => ({
      group: g,
      flags: (groups.get(g) ?? []).slice().sort((a, b) => {
        const ia = navOrder.indexOf(a.key);
        const ib = navOrder.indexOf(b.key);
        return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib) || a.key.localeCompare(b.key);
      }),
    }));
}

const isOffOn = (f: AdminFlag) => f.variants.length === 2 && f.variants[0] === "off" && f.variants[1] === "on";

export function variantLabel(flag: AdminFlag, variant: string): string {
  if (flagMeta(flag.key).hideFlag && isOffOn(flag)) return variant === "on" ? "Hidden" : "Visible";
  return humanize(variant);
}

/**
 * The list row's switch, or null for a flag with more than two variants.
 * For a hide flag the switch reads "Visible" (checked = shown); for any other
 * two-variant flag it reads "On" (checked = not the off variant).
 */
export function switchFor(flag: AdminFlag): { checked: boolean; variantWhen: (checked: boolean) => string } | null {
  if (flag.variants.length !== 2) return null;
  const [off, on] = flag.variants;
  if (flagMeta(flag.key).hideFlag && isOffOn(flag)) {
    return { checked: flag.default_variant === off, variantWhen: (c) => (c ? off : on) };
  }
  return { checked: flag.default_variant !== off, variantWhen: (c) => (c ? on : off) };
}

/** The variant a rollout serves when there's only one other choice. */
export function otherVariant(flag: AdminFlag, def: string): string | null {
  const rest = flag.variants.filter((v) => v !== def);
  return rest.length === 1 ? rest[0] : null;
}

/** "Hidden for 25% of students" — the rollout in words, or null at 0%. */
export function rolloutPhrase(flag: AdminFlag, pct: number, variant: string | null): string | null {
  if (pct <= 0 || !variant) return null;
  return `${variantLabel(flag, variant)} for ${pct}% of students`;
}

/**
 * What a default/rollout change does, in one sentence, before it's saved
 * (design spec §7: a change must state its scope before it applies).
 */
export function changeSummary(
  flag: AdminFlag,
  next: { def: string; pct: number; rv: string | null },
): string | null {
  const parts: string[] = [];
  const { title } = flagMeta(flag.key);
  if (next.def !== flag.default_variant) {
    parts.push(`${title} becomes ${variantLabel(flag, next.def)} for everyone`);
  }
  const before = rolloutPhrase(flag, flag.rollout_percent, flag.rollout_variant);
  const after = rolloutPhrase(flag, next.pct, next.rv);
  if (before !== after) {
    parts.push(after ? `rollout: ${after}` : "rollout ends");
  }
  if (parts.length === 0) return null;
  const overrides = flag.targets.length;
  const tail = overrides > 0
    ? ` ${overrides} override${overrides === 1 ? "" : "s"} still take${overrides === 1 ? "s" : ""} priority.`
    : "";
  const s = parts.join("; ");
  return `${s.charAt(0).toUpperCase()}${s.slice(1)}.${tail}`;
}

/** The explain endpoint's answer, in words. `roleName` maps a role id. */
export function explainPhrase(
  flag: AdminFlag,
  r: { variant: string; step: string; detail: string },
  roleName: (id: string) => string | undefined,
): string {
  const v = variantLabel(flag, r.variant);
  switch (r.step) {
    case "user": return `${v}: this student has their own override`;
    case "role": return `${v}: from the ${roleName(r.detail) ?? r.detail} role override`;
    case "rollout": return `${v}: they're in the ${r.detail} rollout`;
    case "default": return `${v}: the default for everyone`;
    case "env_override": return `${v}: forced by the ${r.detail} environment variable`;
    case "fail_closed": return `${v}: fell back to off (${r.detail})`;
    default: return `${v} (${r.step}${r.detail ? `: ${r.detail}` : ""})`;
  }
}

/** "3h ago" style, for the last-change column. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}
