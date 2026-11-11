import type { Cosmetic, UserProfile, UserRole } from "@/lib/types";

export type StudyGroup = { label: string; values: string[] };

/** The hero's background: a banner tint only when the banner has an asset. */
export function heroBackground(banner: Cosmetic | undefined): string {
  return banner?.asset_url
    ? `linear-gradient(135deg, color-mix(in oklab, ${banner.css_value || "var(--accent)"} 35%, var(--bg-panel)) 0%, var(--bg-panel) 100%)`
    : "var(--bg-panel)";
}

/** A copy of the roles, highest `display_priority` first (missing = 0). */
export function sortRolesByPriority(roles: UserRole[] | undefined): UserRole[] {
  return [...(roles || [])].sort(
    (a, b) => (b.role.display_priority || 0) - (a.role.display_priority || 0),
  );
}

/** The non-empty "Majors" / "Minors" groups, in that order. */
export function studiesOf(profile: Pick<UserProfile, "majors" | "minors">): StudyGroup[] {
  return [
    profile.majors?.length && { label: "Majors", values: profile.majors },
    profile.minors?.length && { label: "Minors", values: profile.minors },
  ].filter(Boolean) as StudyGroup[];
}

/** The metric strip shows once either the streak or the session count is known. */
export function hasStatsStrip(stats: Partial<UserProfile["stats"]>): boolean {
  return stats.streak_count !== undefined || stats.session_count !== undefined;
}

/** A profile with no (or empty) stats is one the viewer may not see. */
export function isPrivateProfile(stats: UserProfile["stats"] | undefined): boolean {
  return stats === undefined || Object.keys(stats || {}).length === 0;
}

/** `https://www.example.com/me` → `example.com/me`; an unparsable URL as-is. */
export function prettyUrl(url: string) {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "") + (u.pathname !== "/" ? u.pathname : "");
  } catch {
    return url;
  }
}
