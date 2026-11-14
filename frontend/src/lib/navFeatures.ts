/**
 * The app shell's main-nav destinations — the ONE list both nav skins
 * (SideNav, TopNav) render — and the feature flag that can hide each (#620).
 *
 * A `flag` is a backend `hide_<feature>` flag (services/feature_flags.py
 * NAV_FEATURES): "on" hides the destination from both navs, and
 * NavFeatureGate sends its routes to /dashboard; the backend also 404s the
 * feature's own API (services/feature_flags.py NAV_FEATURE_API, #771), so a
 * page that calls another feature's endpoint must be listed as an exemption
 * there. Dashboard has no flag; it is
 * where a hidden feature's routes land. Pure data + string checks only.
 */
export type NavItem = { href: string; label: string; icon: string; flag?: string };
export type NavSection = { label: string; items: NavItem[] };

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Learn",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "home" },
      { href: "/learn",     label: "Tutor",     icon: "clover", flag: "hide_tutor" },
      { href: "/tree",      label: "Tree",      icon: "trees",  flag: "hide_tree" },
      { href: "/study",     label: "Study",     icon: "study",  flag: "hide_study" },
    ],
  },
  {
    label: "Organize",
    items: [
      { href: "/library",  label: "Library",  icon: "library", flag: "hide_library" },
      { href: "/calendar", label: "Calendar", icon: "calendar",  flag: "hide_calendar" },
    ],
  },
  {
    label: "Community",
    items: [
      { href: "/social",       label: "Social",       icon: "social",  flag: "hide_social" },
      { href: "/achievements", label: "Achievements", icon: "achievements", flag: "hide_achievements" },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/gradebook",      label: "Grades",         icon: "star",    flag: "hide_grades" },
      { href: "/notetaker",      label: "Notetaker",      icon: "pencil",  flag: "hide_notetaker" },
      { href: "/course-planner", label: "Course Planner", icon: "planner", flag: "hide_course_planner" },
    ],
  },
];

/**
 * Flagged features that are NOT their own nav row: they live inside another
 * destination (Quiz is reached from Study since #753) but keep a `hide_*`
 * flag that hides their pages. `section` is the nav group they belong to, so
 * the admin flags tab files them there.
 */
export type NestedNavFeature = { href: string; label: string; flag: string; section: string };
export const NESTED_NAV_FEATURES: NestedNavFeature[] = [
  { href: "/quiz", label: "Quiz", flag: "hide_quiz", section: "Learn" },
];

/**
 * Pages that belong to a nav destination but sit outside its path: Flashcards
 * is a Study tool served at /flashcards, not under /study. `owner` is the nav
 * row's href, and the page is gated by that row's flag, so hiding Study hides
 * it too. A feature with a hide flag of its own is a NESTED_NAV_FEATURES entry
 * instead. A new entry also needs lib/appRoutes.ts SHELL_PREFIXES (flags are
 * only loaded inside the shell) and, for a Study tool, lib/toolHrefs.ts
 * STUDY_TOOL_PATHS (what keeps Study selected in the nav); a test pins both.
 */
export type NavPathAlias = { path: string; owner: string };
export const NAV_PATH_ALIASES: NavPathAlias[] = [
  { path: "/flashcards", owner: "/study" },
];

/** Segment-boundary match: `/quiz` and `/quiz/x`, never `/quizzes`. */
function isAtOrBelow(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(href + "/");
}

/** The `hide_*` flag guarding `pathname` (segment-boundary match), or null. */
export function navFlagForPath(pathname: string | null | undefined): string | null {
  if (!pathname) return null;
  for (const item of NESTED_NAV_FEATURES) {
    if (isAtOrBelow(pathname, item.href)) return item.flag;
  }
  // An aliased page answers as the nav row that owns it.
  const alias = NAV_PATH_ALIASES.find((a) => isAtOrBelow(pathname, a.path));
  const path = alias ? alias.owner : pathname;
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (item.flag && isAtOrBelow(path, item.href)) return item.flag;
    }
  }
  return null;
}

/** NAV_SECTIONS without the hidden items; a section left empty is dropped. */
export function visibleNavSections(isHidden: (flag: string) => boolean): NavSection[] {
  return NAV_SECTIONS
    .map((s) => ({ ...s, items: s.items.filter((i) => !i.flag || !isHidden(i.flag)) }))
    .filter((s) => s.items.length > 0);
}
