"use client";

/**
 * First-run onboarding, ported from the Claude Design handoff
 * ("Sapling Onboarding", Paper theme). Six chapters over nine screens:
 * name, birthday → school → year + courses → two-page tour → Terms + Privacy
 * → connect accounts, over an animated node graph that grows a cluster per
 * finished chapter. Ends with the "Welcome to Sapling" outro and a white
 * hand-off into the app.
 *
 * Kept from the previous screen: the per-account draft (#757), the 409
 * "already onboarded" hand-off, the local-seed hold redirect (#715), and the
 * real catalog search + profile submit.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import {
  calendarAuthUrl,
  onboardingCoursesSearch,
  submitOnboardingProfile,
  updateSettings,
  type OnboardingCourse,
} from "@/lib/api";
import type { UserSettings } from "@/lib/types";
import { onboardingRedirect } from "@/lib/localSeed";
import SignInModal from "@/components/marketing/SignInModal";
import { SAPLING_WORDMARK_SRC } from "@/components/SaplingWordmark";
import { statusOf } from "@/lib/errorMessage";
import { OnboardingGraph, type GraphPhase, type GraphZoom } from "@/components/onboarding/OnboardingGraph";
import { setGraphStage } from "@/components/onboarding/chapterLayer";
import { CakeArt, FEATURES, TourArt } from "@/components/onboarding/illustrations";
import { LEGAL_UPDATED, PRIVACY, TERMS } from "@/components/onboarding/legalCopy";
import "@/components/onboarding/onboarding.css";

const CHAPTERS = ["About you", "Your school", "Your courses", "Get to know Sapling", "Terms", "Connect your accounts"];

const SCREENS = [
  { id: "name", ch: 0 }, { id: "birthday", ch: 0 }, { id: "school", ch: 1 }, { id: "courses", ch: 2 },
  { id: "tour", ch: 3 }, { id: "features", ch: 3 }, { id: "terms", ch: 4 }, { id: "privacy", ch: 4 },
  { id: "connect", ch: 5 },
] as const;
type ScreenId = (typeof SCREENS)[number]["id"];
const LAST = SCREENS.length - 1;

const YEARS = [
  ["freshman", "Freshman"], ["sophomore", "Sophomore"], ["junior", "Junior"],
  ["senior", "Senior"], ["graduate", "Graduate"], ["other", "Other"],
] as const;

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// Third field: logo height inside its tile, so logos match by visual area.
const OTHER_SCHOOLS = [
  ["Northeastern", "northeastern-t.png", "68%"], ["MIT", "mit-t.png", "56%"], ["Harvard", "harvard-t.png", "76%"],
  ["Boston College", "bc-t.png", "77%"], ["Tufts", "tufts-t.png", "51%"],
] as const;

type ConnKey = "gradescope" | "gcal" | "blackboard" | "canvas" | "classroom";
const CONNECTIONS: { key: ConnKey; name: string; icon: string; desc: string; reads?: string }[] = [
  { key: "gradescope", name: "Gradescope", icon: "gradescope.png", desc: "Assignments, due dates and grades into your Gradebook.", reads: "Assignments, due dates and grades for your enrolled courses." },
  { key: "gcal", name: "Google Calendar", icon: "gcal.webp", desc: "Deadlines in, study blocks out.", reads: "Your calendar events, so I can place study blocks around them." },
  { key: "blackboard", name: "Blackboard", icon: "blackboard.png", desc: "Materials, announcements and grades." },
  { key: "canvas", name: "Canvas", icon: "canvas.png", desc: "Materials, announcements and grades." },
  { key: "classroom", name: "Google Classroom", icon: "classroom.png", desc: "Materials, announcements and grades." },
];

// Intro / outro beats from the handoff, in ms.
const INTRO_TEXT_IN = 450, INTRO_TEXT_OUT = 1900, INTRO_DONE = 2550;
const OUTRO_TEXT_IN = 1400, OUTRO_TEXT_OUT = 3050, OUTRO_WHITE = 3450, OUTRO_HANDOFF = 4250;

/** The pre-#757 key, shared by every account on the browser: one student's
 * half-finished draft prefilled the next one's form. Never read; dropped. */
const LEGACY_DRAFT_KEY = "sapling_onboarding_draft";

/** The draft lives per account (#757). */
export function onboardingDraftKey(userId: string): string {
  return `${LEGACY_DRAFT_KEY}:${userId}`;
}

interface Draft {
  name: string;
  dobM: string;
  dobD: string;
  dobY: string;
  school: "" | "bu";
  year: string;
  courses: OnboardingCourse[];
  termsEnd: boolean;
  termsOk: boolean;
  privEnd: boolean;
  privOk: boolean;
  conn: Partial<Record<ConnKey, boolean>>;
  screen: number;
  /** Finished chapter indexes; each one grows a cluster on the graph. */
  done: number[];
}

const EMPTY_DRAFT: Draft = {
  name: "", dobM: "", dobD: "", dobY: "", school: "", year: "", courses: [],
  termsEnd: false, termsOk: false, privEnd: false, privOk: false, conn: {}, screen: 0, done: [],
};

function loadDraft(userId: string): Draft | null {
  if (typeof window === "undefined") return null;
  try {
    localStorage.removeItem(LEGACY_DRAFT_KEY);
    const raw = localStorage.getItem(onboardingDraftKey(userId));
    if (!raw) return null;
    const d = { ...EMPTY_DRAFT, ...JSON.parse(raw) } as Draft;
    // A draft from the previous onboarding shape (step/first_name) is not resumable.
    if (!Number.isInteger(d.screen) || d.screen < 0 || d.screen > LAST || !Array.isArray(d.courses)) return null;
    return d;
  } catch {
    return null;
  }
}

/** Draft owner for someone who hasn't signed in yet (the landing takeover).
 * Signing in adopts it: carried over in place, or picked up by /onboarding
 * after a same-tab sign-in redirect. */
export const GUEST_OWNER = "guest";

function clearDraft(userId: string) {
  try { localStorage.removeItem(onboardingDraftKey(userId)); } catch {}
}

export function ageOn(today: Date, m: string, d: string, y: string): number | null {
  if (!m || !d || !y) return null;
  let a = today.getFullYear() - Number(y);
  const month = today.getMonth() + 1;
  if (month < Number(m) || (month === Number(m) && today.getDate() < Number(d))) a--;
  return a;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

type Phase = GraphPhase;

export function Onboarding({ takeover = false }: {
  /** Played over the landing from Get Started. Everyone is treated as a new
   * student: no sign-in needed until Finish, and no local-seed redirect. */
  takeover?: boolean;
} = {}) {
  const router = useRouter();
  const { userId, userName, userReady, isAuthenticated, signOut } = useUser();
  const toast = useToast();
  // Whose answers these are: the account, or (takeover only) a guest.
  const owner = userId || (takeover && userReady && !isAuthenticated ? GUEST_OWNER : "");
  const guest = owner === GUEST_OWNER;
  const [signInOpen, setSignInOpen] = useState(false);
  /** Set when a guest hits Finish; the save runs once sign-in lands. */
  const finishAfterSignIn = useRef(false);
  const ownerRef = useRef<string>("");
  const signedIn = useRef(false);

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  // Whose draft is in state. Saving only when it matches the signed-in user
  // keeps one account's answers from being written under another's key in
  // the render between a user switch and the re-hydrate.
  const [hydratedFor, setHydratedFor] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [zoom, setZoom] = useState<GraphZoom>("rest");
  const [introText, setIntroText] = useState(false);
  const [outroText, setOutroText] = useState(false);
  const [whiteout, setWhiteout] = useState(false);
  const [consent, setConsent] = useState<ConnKey | null>(null);
  const [notified, setNotified] = useState<Partial<Record<ConnKey, boolean>>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);
  useEffect(() => clearTimers, [clearTimers]);

  // #715: on a local backend this account is getting (or has) the sample
  // dataset; the hold screen waits for it and moves on to the dashboard.
  useEffect(() => {
    if (takeover) return;
    let cancelled = false;
    void onboardingRedirect().then(route => { if (route && !cancelled) router.replace(route); });
    return () => { cancelled = true; };
  }, [router, takeover]);

  useEffect(() => {
    if (takeover || !userReady) return;
    if (!isAuthenticated) router.replace("/");
  }, [takeover, userReady, isAuthenticated, router]);

  // Hydrate once per owner, then either resume (no intro) or play the intro.
  useEffect(() => {
    if (!owner) return;
    const previous = ownerRef.current;
    ownerRef.current = owner;
    if (previous === GUEST_OWNER && owner !== GUEST_OWNER) {
      // The guest just signed in: their answers are already on screen, so
      // they carry over in place (the save effect rewrites them under the
      // account's key) instead of reloading and replaying the intro.
      clearDraft(GUEST_OWNER);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHydratedFor(owner);
      return;
    }
    let saved = loadDraft(owner);
    if (!saved && owner !== GUEST_OWNER) {
      // A guest who signed in through a same-tab redirect lands here.
      saved = loadDraft(GUEST_OWNER);
      if (saved) clearDraft(GUEST_OWNER);
    }
    const googleFirst = guest ? "" : (userName || "").split(" ")[0] || "";
    // Syncing from localStorage (an external store) into state is this
    // effect's whole job; it runs once per owner.
    setDraft(saved ? { ...saved, name: saved.name || googleFirst } : { ...EMPTY_DRAFT, name: googleFirst });
    setHydratedFor(owner);
    clearTimers();
    if (saved && saved.screen > 0) {
      setZoom("active");
      setPhase("active");
    } else if (prefersReducedMotion()) {
      setPhase("active");
    } else {
      setPhase("out");
      timers.current = [
        setTimeout(() => setIntroText(true), INTRO_TEXT_IN),
        setTimeout(() => { setIntroText(false); setZoom("active"); }, INTRO_TEXT_OUT),
        setTimeout(() => setPhase("active"), INTRO_DONE),
      ];
    }
  }, [owner, guest, userName, clearTimers]);

  useEffect(() => {
    if (!hydratedFor || hydratedFor !== owner) return;
    try { localStorage.setItem(onboardingDraftKey(hydratedFor), JSON.stringify(draft)); } catch {}
  }, [draft, hydratedFor, owner]);

  // UI scale: shrinks on small screens, grows only slightly on large ones.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const apply = () => {
      const z = Math.max(0.7, Math.min(1.15, Math.min(window.innerWidth / 1440, window.innerHeight / 900)));
      el.style.setProperty("--uiz", String(z));
    };
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, []);

  // Over the landing, the mark keeps the exact box the landing navbar drew it
  // in, so Get Started's zoom never moves or resizes it. The navbar centres
  // its logo against the taller Sign In / Get Started row, so the offset is
  // measured rather than assumed; the navbar stays mounted under the veil, so
  // it can be re-measured on resize. Without it the CSS fallback applies.
  const [markBox, setMarkBox] = useState<{ top: number; left: number; width: number } | null>(null);
  useEffect(() => {
    if (!takeover) return;
    const measure = () => {
      const mark = document.querySelector<HTMLElement>(".ld-nav-mark");
      if (!mark) return;
      // The navbar's entry animation only translates Y, so its box is exact
      // horizontally; the vertical offset comes from layout instead, which a
      // click during that animation can't skew. The navbar is fixed at top 0,
      // so the summed offsets are the viewport position.
      const r = mark.getBoundingClientRect();
      let top = 0;
      for (let el: HTMLElement | null = mark; el; el = el.offsetParent as HTMLElement | null) top += el.offsetTop;
      if (r.width > 0) setMarkBox({ top, left: r.left, width: r.width });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [takeover]);

  // Over the landing, the landing hero's own canvas is the graph: hand it the
  // camera and chapter state instead of drawing a second one.
  const stageChapter = SCREENS[draft.screen].ch;
  useEffect(() => {
    if (!takeover) return;
    setGraphStage({ active: true, phase, zoom, activeChapter: stageChapter, completed: draft.done });
  }, [takeover, phase, zoom, stageChapter, draft.done]);
  useEffect(() => {
    if (!takeover) return;
    return () => setGraphStage({ active: false, phase: "idle", zoom: "rest", activeChapter: 0, completed: [] });
  }, [takeover]);

  const set = useCallback(<K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }));
  }, []);

  const screen = SCREENS[draft.screen];
  const id: ScreenId = screen.id;
  const age = ageOn(new Date(), draft.dobM, draft.dobD, draft.dobY);
  const blocked = age !== null && age < 13;
  const minor = age !== null && age >= 13 && age < 18;

  const canNext = useMemo(() => {
    if (phase !== "active") return false;
    switch (id) {
      case "name": return draft.name.trim().length > 0;
      case "birthday": return age !== null && age >= 13;
      case "school": return draft.school === "bu";
      case "courses": return !!draft.year && draft.courses.length > 0;
      case "terms": return draft.termsOk;
      case "privacy": return draft.privOk;
      default: return true;
    }
  }, [phase, id, draft, age]);

  const abortOutro = useCallback((message: string) => {
    clearTimers();
    setOutroText(false);
    setWhiteout(false);
    setZoom("active");
    setPhase("active");
    toast.error(message);
  }, [clearTimers, toast]);

  /** Saves the profile; resolves to where the hand-off goes, or rejects. */
  const save = useCallback(async (): Promise<string> => {
    if (!userId) throw new Error("Not signed in.");
    const lastName = (userName || "").split(" ").slice(1).join(" ");
    try {
      await submitOnboardingProfile({
        user_id: userId,
        first_name: draft.name.trim(),
        last_name: lastName,
        year: draft.year,
        course_ids: draft.courses.map(c => c.id),
      });
    } catch (err) {
      // #757: this account already finished onboarding (another tab, or a
      // stale page); the server keeps the profile it has. Nothing to save.
      if (statusOf(err) === 409) { clearDraft(userId); return "/dashboard"; }
      throw err;
    }
    if (minor) {
      // The birthday screen promises under-18s start with sharing off.
      const patch = { profile_visibility: "private", share_class_context: false } as Partial<UserSettings>;
      await updateSettings(userId, patch).catch(() => {
        toast.info("We couldn't switch sharing off for you. You can do it in Settings.");
      });
    }
    clearDraft(userId);
    if (draft.conn.gcal) return calendarAuthUrl(userId);
    if (draft.conn.gradescope) return "/gradebook";
    return "/dashboard";
  }, [userId, userName, draft, minor, toast]);

  const go = useCallback((dest: string) => {
    if (/^https?:\/\//.test(dest)) window.location.href = dest;
    else router.replace(dest);
  }, [router]);

  const finish = useCallback(() => {
    if (guest) {
      // Saving needs an account: sign in (or create one) first, then the
      // save and the outro carry on from here.
      finishAfterSignIn.current = true;
      setSignInOpen(true);
      return;
    }
    clearTimers();
    setDraft(prev => ({ ...prev, done: Array.from(new Set([...prev.done, screen.ch])) }));
    setPhase("complete");
    setZoom("active");
    let failed = false;
    const saving = save();
    saving.catch(err => {
      failed = true;
      abortOutro(err instanceof Error ? err.message : "Failed to save your profile. Please try again.");
    });
    if (prefersReducedMotion()) {
      void saving.then(dest => { if (!failed) go(dest); }, () => {});
      return;
    }
    timers.current = [
      setTimeout(() => setOutroText(true), OUTRO_TEXT_IN),
      setTimeout(() => { setOutroText(false); setZoom("outro"); }, OUTRO_TEXT_OUT),
      setTimeout(() => setWhiteout(true), OUTRO_WHITE),
      setTimeout(() => { void saving.then(dest => { if (!failed) go(dest); }, () => {}); }, OUTRO_HANDOFF),
    ];
  }, [guest, clearTimers, screen.ch, save, abortOutro, go]);

  // A guest who signed in from Finish: their answers have been adopted by the
  // account (hydratedFor), so the save can run now.
  useEffect(() => {
    if (!finishAfterSignIn.current || guest || !userId || hydratedFor !== userId) return;
    finishAfterSignIn.current = false;
    // Reacting to the sign-in (an external event) is the point: this starts
    // the save + outro the guest asked for with Finish.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    finish();
  }, [guest, userId, hydratedFor, finish]);

  const next = useCallback(() => {
    if (!canNext) return;
    if (draft.screen === LAST) { finish(); return; }
    setDraft(prev => {
      const ni = prev.screen + 1;
      const ch = SCREENS[prev.screen].ch;
      const done = SCREENS[ni].ch !== ch && !prev.done.includes(ch) ? [...prev.done, ch] : prev.done;
      return { ...prev, screen: ni, done };
    });
  }, [canNext, draft.screen, finish]);

  const back = useCallback(() => {
    if (consent) { setConsent(null); return; }
    if (phase !== "active" || draft.screen === 0) return;
    set("screen", draft.screen - 1);
  }, [consent, phase, draft.screen, set]);

  const leave = useCallback(async () => {
    if (owner) clearDraft(owner);
    if (!guest) await signOut();
    // Over the landing, a full reload is what takes the takeover down.
    if (takeover) window.location.assign("/");
    else router.replace("/");
  }, [owner, guest, takeover, signOut, router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName || "";
      if (e.key === "Enter") {
        if (/^(BUTTON|A|SELECT|TEXTAREA)$/.test(tag) || consent) return;
        e.preventDefault();
        next();
      } else if (e.key === "Escape") {
        e.preventDefault();
        back();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, back, consent]);

  const active = phase === "active";
  const legal = screen.ch === 4;
  const primaryLabel = id === "features" ? "Read the terms" : id === "connect" ? "Finish" : "Next";
  const consentDef = CONNECTIONS.find(c => c.key === consent);

  return (
    <div ref={rootRef} className={`ob-root${takeover ? " ob-root--takeover" : ""}`} data-testid="onboarding-gate">
      {!takeover && <div className="ob-beam" />}
      {!takeover && <OnboardingGraph phase={phase} zoom={zoom} activeChapter={screen.ch} completed={draft.done} />}
      <div className="ob-scrim" aria-hidden="true" style={{ opacity: phase === "idle" || (phase === "out" && zoom === "rest") ? 0 : 1 }} />

      <div className="ob-logo" style={markBox ? { top: markBox.top, left: markBox.left } : undefined}>
        <img src={SAPLING_WORDMARK_SRC} alt="Sapling" style={markBox ? { width: markBox.width, height: "auto" } : undefined} />
      </div>

      <div
        className="ob-content"
        style={{ opacity: active ? 1 : 0, pointerEvents: active ? "auto" : "none" }}
        aria-hidden={!active}
      >
        <div className={`ob-scroll${id === "features" ? " ob-scroll--wide" : ""}${legal ? " ob-scroll--legal" : ""}`}>
          <div className="ob-zoom">
            {id === "name" && (
              <section key="name" className="ob-screen ob-screen--roomy">
                <h1 className="ob-h1">First, what should I call you?</h1>
                <div className="ob-body">
                  <img src="/onboarding/name-character.svg" alt="" className="ob-character" />
                  <input
                    data-testid="onboarding-name"
                    className="ob-input ob-input--name"
                    value={draft.name}
                    onChange={e => set("name", e.target.value)}
                    aria-label="Your name"
                    placeholder="Your first name"
                    autoFocus
                  />
                  {!guest && <p className="ob-note">From your Google account. Change it if you go by something else.</p>}
                </div>
              </section>
            )}

            {id === "birthday" && (
              <section key="birthday" className="ob-screen ob-screen--roomy">
                <h1 className="ob-h1">When&apos;s your birthday?</h1>
                <div className="ob-body" style={{ gap: 24 }}>
                  <CakeArt />
                  {!blocked && (
                    <div className="ob-dob">
                      <DobSelect label="Month" value={draft.dobM} width={170} onChange={v => set("dobM", v)}
                        options={MONTHS.map((m, i) => [String(i + 1), m])} />
                      <DobSelect label="Day" value={draft.dobD} width={100} onChange={v => set("dobD", v)}
                        options={Array.from({ length: 31 }, (_, i) => [String(i + 1), String(i + 1)])} />
                      <DobSelect label="Year" value={draft.dobY} width={120} onChange={v => set("dobY", v)}
                        options={yearOptions()} />
                    </div>
                  )}
                  {minor && (
                    <div className="ob-bubble">
                      Since you&apos;re under 18, class sharing and study-room invites start switched off. You can change them later.
                    </div>
                  )}
                  {blocked && (
                    <div className="ob-panel ob-blocked" role="alert">
                      <div className="ob-blocked-title">Sapling is for students 13 and up.</div>
                      <div className="ob-blocked-body">We haven&apos;t saved anything you entered. We&apos;d love to see you again when you&apos;re older.</div>
                      <button data-testid="onboarding-dob-fix" className="ob-textlink" onClick={() => set("dobY", "")}>I made a mistake</button>
                    </div>
                  )}
                </div>
              </section>
            )}

            {id === "school" && (
              <section key="school" className="ob-screen">
                <h1 className="ob-h1">Where do you study?</h1>
                <p className="ob-sub">Tap your school&apos;s logo.</p>
                <div className="ob-body" style={{ gap: 18 }}>
                  <div className="ob-schools">
                    <button
                      data-testid="onboarding-school-bu"
                      className="ob-school"
                      aria-pressed={draft.school === "bu"}
                      onClick={() => set("school", "bu")}
                    >
                      <div className="ob-school-logo"><img src="/onboarding/schools/bu-t.png" alt="" style={{ height: "52%", width: "auto", maxWidth: "90%" }} /></div>
                      Boston University
                    </button>
                    {OTHER_SCHOOLS.map(([name, logo, h]) => (
                      <div key={name} className="ob-school ob-school--soon" aria-disabled="true">
                        <div className="ob-school-logo"><img src={`/onboarding/schools/${logo}`} alt="" style={{ height: h, width: "auto", maxWidth: "100%" }} /></div>
                        {name}
                        <span className="ob-soon">Coming soon</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {id === "courses" && (
              <section key="courses" className="ob-screen">
                <h1 className="ob-h1">What are you taking this term?</h1>
                <p className="ob-sub">Pick your year and add at least one course. Each one grows its own branch.</p>
                <CourseStep
                  year={draft.year}
                  courses={draft.courses}
                  onYear={v => set("year", v)}
                  onCourses={v => set("courses", v)}
                />
              </section>
            )}

            {id === "tour" && (
              <section key="tour" className="ob-screen">
                <h1 className="ob-h1">Your notes become a map.</h1>
                <p className="ob-sub">Drop syllabi, slides or notes into the library, and Sapling extracts the concepts intelligently.</p>
                <div className="ob-body"><TourArt /></div>
              </section>
            )}

            {id === "features" && (
              <section key="features" className="ob-screen">
                <h1 className="ob-h1">More than a map.</h1>
                <p className="ob-sub">Everything you upload also powers these.</p>
                <div className="ob-body">
                  <div className="ob-features">
                    {FEATURES.map(f => (
                      <div key={f.caption} className="ob-feature">{f.art}<span>{f.caption}</span></div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {legal && (
              <LegalStep
                key={id}
                kind={id === "terms" ? "terms" : "privacy"}
                reachedEnd={id === "terms" ? draft.termsEnd : draft.privEnd}
                agreed={id === "terms" ? draft.termsOk : draft.privOk}
                onReachEnd={() => set(id === "terms" ? "termsEnd" : "privEnd", true)}
                onAgree={v => set(id === "terms" ? "termsOk" : "privOk", v)}
              />
            )}

            {id === "connect" && (
              <section key="connect" className="ob-screen">
                <h1 className="ob-h1">Connect your accounts</h1>
                <p className="ob-sub">Bring your deadlines and grades in. Every one is optional.</p>
                <div className="ob-connect-wrap">
                  <div className="ob-connect">
                    {CONNECTIONS.map(c => {
                      const built = !!c.reads;
                      const on = built ? !!draft.conn[c.key] : !!notified[c.key];
                      const label = built ? (on ? "Connected ✓" : "Connect") : on ? "We'll let you know" : "Notify me";
                      return (
                        <div key={c.key} className="ob-panel ob-conn">
                          <div className="ob-conn-icon" aria-hidden="true"><img src={`/onboarding/icons/${c.icon}`} alt="" /></div>
                          <div className="ob-conn-text">
                            <span className="ob-conn-name">{c.name}</span>
                            <span className="ob-conn-desc">{c.desc}</span>
                          </div>
                          <button
                            data-testid={`onboarding-connect-${c.key}`}
                            className={`ob-pill${on ? " ob-pill--on" : built ? " ob-pill--primary" : ""}`}
                            aria-label={`${label}: ${c.name}`}
                            onClick={() => {
                              if (on) return;
                              if (built) setConsent(c.key);
                              else setNotified(prev => ({ ...prev, [c.key]: true }));
                            }}
                          >
                            {label}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>
            )}
          </div>
        </div>

        <div className="ob-actions">
          <button data-testid="onboarding-continue" className="ob-primary" disabled={!canNext} onClick={next}>
            {primaryLabel}
          </button>
          <div className="ob-secondaries">
            {id === "connect" && <button data-testid="onboarding-skip" className="ob-secondary" onClick={next}>Skip for now</button>}
            {id === "birthday" && blocked && <button data-testid="onboarding-sign-out" className="ob-secondary" onClick={() => void leave()}>Sign out</button>}
          </div>
        </div>
      </div>

      <div className="ob-progress" style={{ opacity: active ? 1 : 0 }} aria-label="Onboarding progress">
        {CHAPTERS.map((label, i) => {
          const total = SCREENS.filter(s => s.ch === i).length;
          const pos = SCREENS.slice(0, draft.screen + 1).filter(s => s.ch === i).length;
          const current = screen.ch === i;
          const done = draft.done.includes(i);
          const fill = current ? Math.max(8, ((pos - 0.5) / total) * 100) : done ? 100 : 0;
          return (
            <div key={label} className="ob-chapter" aria-current={current ? "step" : undefined}>
              <div className="ob-chapter-label">{current ? label : done ? "✓" : ""}</div>
              <div className="ob-chapter-bar"><div style={{ width: `${fill}%` }} /></div>
            </div>
          );
        })}
      </div>

      <div className="ob-keys" style={{ opacity: active ? 1 : 0 }}>
        <button data-testid="onboarding-next-key" className="ob-key" onClick={next} tabIndex={-1}><kbd>Enter</kbd>Next</button>
        <button data-testid="onboarding-back" className="ob-key" onClick={back} tabIndex={-1}><kbd>Esc</kbd>Back</button>
      </div>

      {consentDef && (
        <div className="ob-sheet-backdrop" onClick={() => setConsent(null)}>
          <div className="ob-sheet" role="dialog" aria-modal="true" aria-labelledby="ob-consent-title" onClick={e => e.stopPropagation()}>
            <div className="ob-sheet-grip" />
            <h2 id="ob-consent-title" className="ob-sheet-title">Connect {consentDef.name}</h2>
            <div className="ob-sheet-rows">
              <div className="ob-sheet-row"><b>READS</b><span>{consentDef.reads}</span></div>
              <div className="ob-sheet-row"><b>STORES</b><span>Only what it syncs, encrypted before it&apos;s saved.</span></div>
              <div className="ob-sheet-row"><b>UNDO</b><span>Disconnect any time in Settings → Connections.</span></div>
            </div>
            <div className="ob-sheet-actions">
              <button
                data-testid="onboarding-consent-continue"
                className="ob-sheet-go"
                autoFocus
                onClick={() => { set("conn", { ...draft.conn, [consentDef.key]: true }); setConsent(null); }}
              >
                Continue
              </button>
              <button data-testid="onboarding-consent-cancel" className="ob-sheet-cancel" onClick={() => setConsent(null)}>Not now</button>
            </div>
          </div>
        </div>
      )}

      {phase !== "idle" && (
        <div className="ob-moment ob-moment--intro" style={{ opacity: introText ? 1 : 0 }} aria-hidden={!introText}>
          <div className="ob-moment-glow" />
          <p className="ob-intro-text">Let&apos;s Learn About You...</p>
        </div>
      )}
      {phase === "complete" && (
        <div className="ob-moment ob-moment--outro" style={{ opacity: outroText ? 1 : 0 }} aria-live="polite">
          <div className="ob-moment-glow" />
          <p className="ob-welcome">
            <span>Welcome to</span>
            <img src={SAPLING_WORDMARK_SRC} alt="Sapling" />
          </p>
        </div>
      )}
      <SignInModal
        open={signInOpen}
        // The modal calls onSignedIn and then onClose; only a close without a
        // sign-in (dismissed, failed) drops the pending save.
        onClose={() => {
          setSignInOpen(false);
          if (!signedIn.current) finishAfterSignIn.current = false;
          signedIn.current = false;
        }}
        onSignedIn={() => { signedIn.current = true; finishAfterSignIn.current = true; }}
      />
      <div className="ob-whiteout" style={{ opacity: whiteout ? 1 : 0, pointerEvents: whiteout ? "auto" : "none" }} />
    </div>
  );
}

function yearOptions(): [string, string][] {
  const thisYear = new Date().getFullYear();
  return Array.from({ length: 70 }, (_, i) => [String(thisYear - i), String(thisYear - i)]);
}

function DobSelect({ label, value, options, width, onChange }: {
  label: string; value: string; options: [string, string][]; width: number; onChange: (v: string) => void;
}) {
  return (
    <select
      data-testid={`onboarding-dob-${label.toLowerCase()}`}
      className="ob-select"
      aria-label={label}
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{ minWidth: width }}
    >
      <option value="">{label}</option>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

function CourseStep({ year, courses, onYear, onCourses }: {
  year: string;
  courses: OnboardingCourse[];
  onYear: (v: string) => void;
  onCourses: (v: OnboardingCourse[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OnboardingCourse[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      onboardingCoursesSearch(query.trim())
        .then(r => { if (!cancelled) setResults(r.courses ?? []); })
        .catch(() => { if (!cancelled) setResults([]); })
        .finally(() => { if (!cancelled) setLoaded(true); });
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
  }, [query]);

  const picked = new Set(courses.map(c => c.id));
  const toggle = (c: OnboardingCourse) =>
    onCourses(picked.has(c.id) ? courses.filter(x => x.id !== c.id) : [...courses, c]);
  const shown = results;

  return (
    <div className="ob-courses">
      <div className="ob-label">Your year</div>
      <div className="ob-years">
        {YEARS.map(([v, l]) => (
          <button key={v} data-testid={`onboarding-year-${v}`} className="ob-choice" aria-pressed={year === v} onClick={() => onYear(v)}>
            {l}
          </button>
        ))}
      </div>
      <div className="ob-label ob-label--gap">Your courses</div>
      <input
        data-testid="onboarding-course-search"
        className="ob-input ob-input--search"
        value={query}
        onChange={e => setQuery(e.target.value)}
        aria-label="Search courses"
        placeholder="Search by code or name, like CS 111"
      />
      {courses.length > 0 && (
        <div className="ob-chips">
          {courses.map(c => (
            <button
              key={c.id}
              data-testid={`onboarding-course-remove-${c.id}`}
              className="ob-chip"
              aria-label={`Remove ${c.course_code}`}
              onClick={() => toggle(c)}
            >
              {c.course_code}<span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      )}
      <div className="ob-label" style={{ paddingTop: 4 }}>{query.trim() ? "Matches" : "Popular at Boston University"}</div>
      <div className="ob-panel ob-results">
        {shown.map(c => {
          const added = picked.has(c.id);
          return (
            <button
              key={c.id}
              data-testid={`onboarding-course-result-${c.id}`}
              className="ob-result"
              aria-pressed={added}
              onClick={() => toggle(c)}
            >
              <span className="ob-result-code">{c.course_code}</span>
              <span className="ob-result-name">{c.course_name}</span>
              <span className="ob-result-action">{added ? "Added ✓" : "Add"}</span>
            </button>
          );
        })}
        {loaded && shown.length === 0 && (
          <div className="ob-empty">No matches yet. Try the course code, like &quot;MA 123&quot;.</div>
        )}
      </div>
    </div>
  );
}

function LegalStep({ kind, reachedEnd, agreed, onReachEnd, onAgree }: {
  kind: "terms" | "privacy";
  reachedEnd: boolean;
  agreed: boolean;
  onReachEnd: () => void;
  onAgree: (v: boolean) => void;
}) {
  const [pct, setPct] = useState(reachedEnd ? 1 : 0);
  const bodyRef = useRef<HTMLDivElement>(null);
  const name = kind === "terms" ? "Terms of Service" : "Privacy Policy";
  const clauses = kind === "terms" ? TERMS : PRIVACY;

  const measure = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    const room = el.scrollHeight - el.clientHeight;
    // A panel tall enough to show the whole document has nothing to scroll.
    const p = room <= 2 ? 1 : Math.min(1, el.scrollTop / room);
    setPct(p);
    if (p > 0.985 && !reachedEnd) onReachEnd();
  }, [reachedEnd, onReachEnd]);

  useEffect(() => {
    const frame = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", measure); };
  }, [measure]);

  return (
    <section className="ob-screen ob-screen--legal">
      <h1 className="ob-h1">{name}</h1>
      <div className="ob-legal">
        <div className="ob-panel ob-doc">
          <div className="ob-doc-progress"><div style={{ width: `${Math.round(pct * 100)}%` }} /></div>
          <div ref={bodyRef} className="ob-doc-body" onScroll={measure} tabIndex={0} aria-label={name} data-testid="onboarding-legal-body">
            <div className="ob-doc-meta ob-doc-meta--top">Last updated: {LEGAL_UPDATED}</div>
            {clauses.map(c => (
              <div key={c.title} className="ob-clause">
                <h2>{c.title}</h2>
                <p>{c.body}</p>
                {c.list && <ul>{c.list.map(li => <li key={li}>{li}</li>)}</ul>}
                {c.after && <p>{c.after}</p>}
              </div>
            ))}
            <div className="ob-doc-meta ob-doc-meta--end">End of the {name}</div>
          </div>
        </div>
        <button
          data-testid="onboarding-agree"
          className="ob-agree"
          role="checkbox"
          aria-checked={agreed}
          disabled={!reachedEnd}
          title={reachedEnd ? undefined : "Scroll to the end to accept."}
          onClick={() => onAgree(!agreed)}
        >
          <span className="ob-box" aria-hidden="true">{agreed ? "✓" : ""}</span>
          {kind === "terms" ? "I agree to the Terms of Service" : "I agree to the Privacy Policy"}
        </button>
      </div>
    </section>
  );
}
