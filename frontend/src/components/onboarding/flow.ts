/**
 * The onboarding flow's fixed shape: six chapters over nine screens, the
 * choices on them, and the accounts the Connect step offers. Pure data, so
 * the screens, the draft and the tests share one definition.
 */

export const CHAPTERS = [
  "About you", "Your school", "Your courses", "Get to know Sapling", "Terms", "Connect your accounts",
] as const;

export const SCREENS = [
  { id: "name", ch: 0 }, { id: "birthday", ch: 0 }, { id: "school", ch: 1 }, { id: "courses", ch: 2 },
  { id: "tour", ch: 3 }, { id: "features", ch: 3 }, { id: "terms", ch: 4 }, { id: "privacy", ch: 4 },
  { id: "connect", ch: 5 },
] as const;

export type ScreenId = (typeof SCREENS)[number]["id"];
export const LAST = SCREENS.length - 1;

export function screenIndex(id: ScreenId): number {
  return SCREENS.findIndex(s => s.id === id);
}

export const YEARS = [
  ["freshman", "Freshman"], ["sophomore", "Sophomore"], ["junior", "Junior"],
  ["senior", "Senior"], ["graduate", "Graduate"], ["other", "Other"],
] as const;

export const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** Third field: logo height inside its tile, so logos match by visual area. */
export const OTHER_SCHOOLS = [
  ["Northeastern", "northeastern-t.png", "68%"], ["MIT", "mit-t.png", "56%"], ["Harvard", "harvard-t.png", "76%"],
  ["Boston College", "bc-t.png", "77%"], ["Tufts", "tufts-t.png", "51%"],
] as const;

/** Where a student can join the beta list (the landing's newsletter section). */
export const BETA_LIST_HREF = "/#newsletter";

export type ConnKey = "gradescope" | "gcal" | "blackboard" | "canvas" | "classroom";
export type ConnChoices = Partial<Record<ConnKey, boolean>>;

export interface Connection {
  key: ConnKey;
  name: string;
  icon: string;
  desc: string;
  /** The nav flag (#620) that hides the feature this account feeds. With it
   * on the option is left out (useHiddenConnections). */
  flag?: string;
  /**
   * What choosing it means, as [label, text] rows for the consent sheet.
   * Only the accounts Sapling can connect today have one; the rest are
   * "Coming soon". Nothing connects during onboarding itself: the choice is
   * carried out after the profile is saved (components/onboarding/profile.ts).
   */
  consent?: [string, string][];
}

export const CONNECTIONS: Connection[] = [
  {
    key: "gradescope", name: "Gradescope", icon: "gradescope.png", flag: "hide_grades",
    desc: "Assignments, due dates and grades into your Gradebook.",
    consent: [
      ["How", "After setup, your Gradebook opens and you sign in to Gradescope there."],
      ["Stores", "Assignment names and due dates. Scores are encrypted before they're saved."],
      ["Undo", "Disconnect any time in Settings → Connected accounts."],
    ],
  },
  {
    key: "gcal", name: "Google Calendar", icon: "gcal.webp", flag: "hide_calendar",
    desc: "Your events beside your deadlines.",
    consent: [
      ["How", "After setup, Google will ask for your permission. Nothing connects unless you allow it."],
      ["Uses", "Your events show on your Sapling calendar, and you can add your deadlines to Google Calendar."],
      ["Undo", "Disconnect any time on the Calendar page."],
    ],
  },
  { key: "blackboard", name: "Blackboard", icon: "blackboard.png", desc: "Materials, announcements and grades." },
  { key: "canvas", name: "Canvas", icon: "canvas.png", desc: "Materials, announcements and grades." },
  { key: "classroom", name: "Google Classroom", icon: "classroom.png", desc: "Materials, announcements and grades." },
];
