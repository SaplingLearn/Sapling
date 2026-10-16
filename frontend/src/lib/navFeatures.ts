/**
 * The app shell's main-nav destinations — the ONE list both nav skins
 * (SideNav, TopNav) render — and the feature flag that can hide each (#620).
 *
 * A `flag` is a backend `hide_<feature>` flag (services/feature_flags.py
 * NAV_FEATURES): "on" hides the destination from both navs, and
 * NavFeatureGate sends its routes to /dashboard. Dashboard has no flag; it is
 * where a hidden feature's routes land. Pure data + string checks only.
 */
export type NavItem = { href: string; label: string; icon: string; flag?: string };
export type NavSection = { label: string; items: NavItem[] };

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Learn",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "home" },
      { href: "/learn",     label: "Tutor",     icon: "brain", flag: "hide_tutor" },
      { href: "/quiz",      label: "Quiz",      icon: "flask", flag: "hide_quiz" },
      { href: "/tree",      label: "Tree",      icon: "tree",  flag: "hide_tree" },
      { href: "/study",     label: "Study",     icon: "bolt",  flag: "hide_study" },
    ],
  },
  {
    label: "Organize",
    items: [
      { href: "/library",  label: "Library",  icon: "book", flag: "hide_library" },
      { href: "/calendar", label: "Calendar", icon: "cal",  flag: "hide_calendar" },
    ],
  },
  {
    label: "Community",
    items: [
      { href: "/social",       label: "Social",       icon: "users",  flag: "hide_social" },
      { href: "/achievements", label: "Achievements", icon: "trophy", flag: "hide_achievements" },
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

/** The `hide_*` flag guarding `pathname` (segment-boundary match), or null. */
export function navFlagForPath(pathname: string | null | undefined): string | null {
  if (!pathname) return null;
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (item.flag && (pathname === item.href || pathname.startsWith(item.href + "/"))) {
        return item.flag;
      }
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
