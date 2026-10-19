/**
 * The app shell's main-nav destinations — the ONE list every nav skin
 * renders (the shell's desktop sidebar, `fa26/Sidebar.tsx`, through
 * SIDEBAR_PRIMARY + SIDEBAR_MORE below; the legacy SideNav/TopNav directly) —
 * and the feature flag that can hide each (#620).
 *
 * A `flag` is a backend `hide_<feature>` flag (services/feature_flags.py
 * NAV_FEATURES): "on" hides the destination from every nav, and
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

/* ── The desktop sidebar (Pen nav) ─────────────────────────────────────────
 * The approved Pen sidebar shows six destinations. Each one NAMES a
 * NAV_SECTIONS destination by href, so its hide_ flag still comes from the one
 * list above; everything the Pen does not show lands in the sidebar's "More"
 * group (SIDEBAR_MORE), so no destination is ever dropped.
 *
 * Learn and Tutor are two views of the ONE /learn route (LoopLearn's
 * `?view=tutor`): Tutor exists only while the `tutor_view` flag is on, and both
 * hide with /learn's `hide_tutor`. */

/** LoopLearn's tutor view flag (services/feature_flags.py REGISTRY). */
export const TUTOR_VIEW_FLAG = "tutor_view";
export const TUTOR_VIEW_HREF = "/learn?view=tutor";

export type SidebarIcon = "today" | "learn" | "knowledge" | "library" | "tutor" | "calendar";
export type SidebarEntry = {
  /** Stable key: the active-state id and the pill's target. */
  key: string;
  href: string;
  label: string;
  icon: SidebarIcon;
  testid: string;
  /** The hide_ flag, read off the NAV_SECTIONS destination it names. */
  flag?: string;
  /** A flag that must be "on" for the entry to exist at all. */
  requires?: string;
};

const destination = (href: string): NavItem => {
  const item = NAV_SECTIONS.flatMap((s) => s.items).find((i) => i.href === href);
  if (!item) throw new Error(`navFeatures: ${href} is not a NAV_SECTIONS destination`);
  return item;
};

/** Pen order (Today renamed Home, 2026-10-19): Home, Learn, Knowledge, Library, Tutor, Calendar. The testids
 *  keep the `nav-link-<route>` convention E2E already asserts on. */
export const SIDEBAR_PRIMARY: SidebarEntry[] = [
  { key: "dashboard", href: "/dashboard", label: "Home", icon: "today", testid: "nav-link-dashboard" },
  { key: "learn", href: "/learn", label: "Learn", icon: "learn", testid: "nav-link-learn", flag: destination("/learn").flag },
  { key: "tree", href: "/tree", label: "Knowledge", icon: "knowledge", testid: "nav-link-tree", flag: destination("/tree").flag },
  { key: "library", href: "/library", label: "Library", icon: "library", testid: "nav-link-library", flag: destination("/library").flag },
  {
    key: "tutor-view", href: TUTOR_VIEW_HREF, label: "Tutor", icon: "tutor", testid: "nav-link-tutor-view",
    flag: destination("/learn").flag, requires: TUTOR_VIEW_FLAG,
  },
  { key: "calendar", href: "/calendar", label: "Calendar", icon: "calendar", testid: "nav-link-calendar", flag: destination("/calendar").flag },
];

/** Every NAV_SECTIONS destination the Pen sidebar does not show, in nav order. */
export const SIDEBAR_MORE: NavItem[] = NAV_SECTIONS
  .flatMap((s) => s.items)
  .filter((i) => !SIDEBAR_PRIMARY.some((p) => p.href === i.href));

const under = (pathname: string, href: string) => pathname === href || pathname.startsWith(href + "/");

/**
 * The key of the ONE sidebar entry that is the current page, or null.
 * `/learn` is Tutor when `?view=tutor` and the tutor view is offered, else
 * Learn. Other routes match their destination (segment boundary), then
 * Settings and Admin; anything else (a profile page, say) matches nothing.
 */
export function sidebarActiveKey(
  pathname: string | null | undefined,
  view: string | null | undefined,
  tutorOffered: boolean,
): string | null {
  if (!pathname) return null;
  if (under(pathname, "/learn")) return tutorOffered && view === "tutor" ? "tutor-view" : "learn";
  for (const e of SIDEBAR_PRIMARY) if (under(pathname, e.href)) return e.key;
  for (const i of SIDEBAR_MORE) if (under(pathname, i.href)) return i.href.slice(1);
  for (const href of ["/settings", "/admin"]) if (under(pathname, href)) return href.slice(1);
  return null;
}
