/**
 * Plain-language labels for the admin Feature flags tab (#620).
 *
 * The flag store speaks in variants ("off"/"on", variants[0] = off). For the
 * `hide_*` nav flags "on" HIDES the feature, which is backwards for anyone
 * reading a visibility switch, so the UI only ever says Visible / Hidden.
 * Any other flag keeps its own variant names. Pure functions only.
 */
import type { AdminFlag, FlagRule } from "@/lib/api";
import { NAV_SECTIONS, NESTED_NAV_FEATURES } from "@/lib/navFeatures";

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
  const nested = NESTED_NAV_FEATURES.find((item) => item.flag === key);
  if (nested) return { title: nested.label, group: nested.section, hideFlag: true };
  return { title: humanize(key), group: OTHER_GROUP, hideFlag: false };
}

/** Flags grouped in nav order (Learn, Organize, …), anything else last. */
export function groupFlags(flags: AdminFlag[]): { group: string; flags: AdminFlag[] }[] {
  const order = [...NAV_SECTIONS.map((s) => s.label), OTHER_GROUP];
  // Section rows first, then nested features in their declared order.
  const navOrder = [
    ...NAV_SECTIONS.flatMap((s) => s.items.map((i) => i.flag)),
    ...NESTED_NAV_FEATURES.map((n) => n.flag),
  ].filter(Boolean);
  const groups = new Map<string, AdminFlag[]>();
  for (const f of flags) {
    // A group the tab doesn't render (a nested feature naming a section that
    // was renamed, say) falls back to Other instead of vanishing.
    const meta = flagMeta(f.key).group;
    const g = order.includes(meta) ? meta : OTHER_GROUP;
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

/** Why a rule decided, in words (the part after "On: "), or null for a step this
 *  UI does not know. */
function ruleClause(r: FlagRule, roleName: (id: string) => string | undefined): string | null {
  switch (r.step) {
    case "user": return "this student has their own override";
    case "role": return `from the ${roleName(r.detail) ?? r.detail} role override`;
    case "rollout": return `they're in the ${r.detail} rollout`;
    case "default": return "the default for everyone";
    case "env_override": return `forced by the ${r.detail} environment variable`;
    case "fail_closed": return `fell back to off (${r.detail})`;
    // #866 K24: the learning loop's gate over its own flags (learning/gate.py)
    case "kill_switch": return `the ${r.detail} kill switch turns the learning loop off for everyone`;
    default: return null;
  }
}

/** The explain endpoint's answer, in words. `roleName` maps a role id. A
 *  learning-loop flag the loop is off for names what turned the loop off for
 *  them (#866 K24). */
export function explainPhrase(
  flag: AdminFlag,
  r: FlagRule,
  roleName: (id: string) => string | undefined,
): string {
  const v = variantLabel(flag, r.variant);
  if (r.step === "requires") {
    const needs = flagMeta(r.master?.key ?? r.detail).title;
    const why = r.master ? ruleClause(r.master, roleName) : null;
    return why ? `${v}: needs ${needs}, which is off for them — ${why}` : `${v}: needs ${needs} on`;
  }
  const why = ruleClause(r, roleName);
  return why ? `${v}: ${why}` : `${v} (${r.step}${r.detail ? `: ${r.detail}` : ""})`;
}

/** #866 K24: a row whose answer for everyone the server decides above its
 *  stored settings — the chip's words and its tooltip — or null. */
export function forcedNote(flag: AdminFlag): { chip: string; tip: string } | null {
  const f = flag.forced;
  if (!f) return null;
  const v = variantLabel(flag, f.variant);
  const tail = "whatever is set here; a change here applies once that is lifted.";
  if (f.step === "kill_switch") {
    return { chip: "Kill switch on", tip: `${v} for every student: the server's ${f.detail} kill switch turns the learning loop off, ${tail}` };
  }
  if (f.step === "requires") {
    const needs = flagMeta(f.master?.key ?? f.detail).title;
    return { chip: `${needs} off`, tip: `${v} for every student: it needs ${needs}, which the server's ${f.master?.detail ?? "settings"} forces off, ${tail}` };
  }
  return { chip: "Set on the server", tip: `${v} for every student: the server's ${f.detail} environment variable forces it, ${tail}` };
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
