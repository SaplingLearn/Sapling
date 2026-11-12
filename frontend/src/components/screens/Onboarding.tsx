"use client";

/**
 * First-run onboarding, ported from the Claude Design handoff ("Sapling
 * Onboarding", Paper theme). Six chapters over nine screens: name, birthday →
 * school → year + courses → two-page tour → Terms + Privacy → connect
 * accounts, over an animated node graph that grows a cluster per finished
 * chapter. Ends with the "Welcome to Sapling" outro and a white hand-off into
 * the app.
 *
 * Onboarding needs an account (owner decision, 2026-11-12: sign in first).
 * The middleware sends a signed-out visitor through sign-in and an onboarded
 * student to /dashboard; the app shell sends a student who hasn't finished
 * here. Kept from before: the per-account draft (#757, now expiring), the
 * local-seed hold redirect (#715), the real catalog search and profile save.
 *
 * The pieces live in components/onboarding/: the screens, the draft, the
 * save and its failures (profile.ts), and the intro/outro (useStage.ts).
 */
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import { onboardingRedirect } from "@/lib/localSeed";
import { PRIVACY, TERMS } from "@/lib/legal/documents";
import { SAPLING_WORDMARK_SRC } from "@/components/SaplingWordmark";
import { OnboardingGraph } from "@/components/onboarding/OnboardingGraph";
import type { GraphPhase, GraphZoom } from "@/components/onboarding/chapterLayer";
import { ageOn, isMinor, isUnder13, rememberUnder13, under13Remembered } from "@/components/onboarding/age";
import { CONNECTIONS, LAST, SCREENS, screenIndex, type ConnKey, type ScreenId } from "@/components/onboarding/flow";
import { EMPTY_DRAFT, advance, canAdvance, finished, type Draft } from "@/components/onboarding/draft";
import { useOnboardingDraft } from "@/components/onboarding/useOnboardingDraft";
import { useStage } from "@/components/onboarding/useStage";
import { useHiddenConnections, visibleChoices } from "@/components/onboarding/useHiddenConnections";
import { classifySaveError, handoffFor, saveProfile, type Handoff, type SaveFailure } from "@/components/onboarding/profile";
import {
  BirthdayScreen, ConnectScreen, FeaturesScreen, NameScreen, SchoolScreen, TourScreen, type Dob,
} from "@/components/onboarding/screens";
import { CourseStep } from "@/components/onboarding/CourseStep";
import { LegalStep } from "@/components/onboarding/LegalStep";
import { ConsentSheet } from "@/components/onboarding/ConsentSheet";
import { Actions, IntroMoment, KeyHints, OutroMoment, Progress, TopBar, Whiteout } from "@/components/onboarding/chrome";
import "@/components/onboarding/onboarding.css";

/** Where a signed-out visitor goes: the landing, with the sign-in box open. */
const SIGN_IN_ROUTE = "/?signin=1";

const PRIMARY_LABEL: Partial<Record<ScreenId, string>> = { features: "Read the terms", connect: "Finish" };

/** A save that sent the student back to fix something, shown on that screen. */
type NoticeKind = "courses" | "legal";
const NOTICE_SCREEN: Record<NoticeKind, ScreenId> = { courses: "courses", legal: "terms" };

function NoticeText({ kind }: { kind: NoticeKind }) {
  if (kind === "courses") {
    return (
      <>
        None of the courses you picked are in the catalog any more. Search again, or choose
        &ldquo;My courses aren&apos;t listed&rdquo;.
      </>
    );
  }
  return (
    <>
      The Terms of Service or Privacy Policy changed after this page opened. Reload to read the
      current version, then agree again.{" "}
      <button data-testid="onboarding-legal-reload" className="ob-textlink" onClick={() => window.location.reload()}>
        Reload
      </button>
    </>
  );
}

function ScreenBody({ draft: d, patch, blocked, minor, notice, hidden, onDob, onSignOut, onConnect }: {
  draft: Draft;
  patch: (p: Partial<Draft>) => void;
  blocked: boolean;
  minor: boolean;
  notice: NoticeKind | null;
  hidden: Set<ConnKey>;
  onDob: (dob: Dob) => void;
  onSignOut: () => void;
  onConnect: (key: ConnKey) => void;
}) {
  const id = SCREENS[d.screen].id;
  const noticeHere = notice && NOTICE_SCREEN[notice] === id ? <NoticeText kind={notice} /> : undefined;
  switch (id) {
    case "name":
      return <NameScreen name={d.name} onName={v => patch({ name: v })} />;
    case "birthday":
      return (
        <BirthdayScreen dob={{ m: d.dobM, d: d.dobD, y: d.dobY }} blocked={blocked} minor={minor} onDob={onDob} onSignOut={onSignOut} />
      );
    case "school":
      return <SchoolScreen school={d.school} onSchool={v => patch({ school: v })} onSignOut={onSignOut} />;
    case "courses":
      return (
        <CourseStep
          year={d.year}
          courses={d.courses}
          later={d.coursesLater}
          notice={noticeHere}
          onYear={v => patch({ year: v })}
          onCourses={v => patch({ courses: v, coursesLater: false })}
          onLater={() => patch({ courses: [], coursesLater: !d.coursesLater })}
        />
      );
    case "tour":
      return <TourScreen />;
    case "features":
      return <FeaturesScreen />;
    case "terms":
      return (
        <LegalStep
          key="terms" doc={TERMS} reachedEnd={d.termsEnd} agreed={d.termsOk} notice={noticeHere}
          onReachEnd={() => patch({ termsEnd: true })} onAgree={v => patch({ termsOk: v })}
        />
      );
    case "privacy":
      return (
        <LegalStep
          key="privacy" doc={PRIVACY} reachedEnd={d.privEnd} agreed={d.privOk}
          onReachEnd={() => patch({ privEnd: true })} onAgree={v => patch({ privOk: v })}
        />
      );
    case "connect":
      return (
        <ConnectScreen
          conn={d.conn}
          hidden={hidden}
          onConnect={onConnect}
          onRemove={key => patch({ conn: { ...d.conn, [key]: false } })}
        />
      );
  }
}

function scrollClass(id: ScreenId): string {
  const wide = id === "features" ? " ob-scroll--wide" : "";
  const legal = id === "terms" || id === "privacy" ? " ob-scroll--legal" : "";
  return `ob-scroll${wide}${legal}`;
}

function scrimOpacity(phase: GraphPhase, zoom: GraphZoom): number {
  return phase === "idle" || (phase === "out" && zoom === "rest") ? 0 : 1;
}

/** #715: on a local backend this account is getting (or has) the sample
 * dataset; the hold screen waits for it and moves on to the dashboard. */
function useLocalSeedRedirect(replace: (route: string) => void) {
  useEffect(() => {
    let cancelled = false;
    void onboardingRedirect().then(route => { if (route && !cancelled) replace(route); });
    return () => { cancelled = true; };
  }, [replace]);
}

/** UI scale: shrinks on small screens, grows only slightly on large ones. */
function useUiScale(rootRef: React.RefObject<HTMLDivElement | null>) {
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
  }, [rootRef]);
}

/** Enter is Next and Esc is Back, unless a control already used the key. */
function useOnboardingKeys(next: () => void, back: () => void, sheetOpen: boolean) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // An open dropdown's Enter or Esc, the course search's Enter, a dialog's Esc.
      if (e.defaultPrevented) return;
      if (e.key === "Enter") {
        const tag = (e.target as HTMLElement | null)?.tagName || "";
        if (/^(BUTTON|A|SELECT|TEXTAREA)$/.test(tag) || sheetOpen) return;
        e.preventDefault();
        next();
      } else if (e.key === "Escape") {
        e.preventDefault();
        back();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, back, sheetOpen]);
}

export function Onboarding() {
  const router = useRouter();
  const { userId, userName, userReady, isAuthenticated, signOut, refreshProfile, markOnboarded } = useUser();
  const toast = useToast();
  const { phase, zoom, introText, outroText, whiteout, enter, outro, abort } = useStage();
  const [ageGate, setAgeGate] = useState(false);
  const { draft, setDraft, patch, discard } = useOnboardingDraft(userId, userName, resumed => {
    setAgeGate(under13Remembered());
    enter(resumed);
  });
  const [consent, setConsent] = useState<ConnKey | null>(null);
  const [notice, setNotice] = useState<NoticeKind | null>(null);
  const [settingUp, setSettingUp] = useState(false);
  // Accounts whose feature is switched off for this student aren't offered.
  const { hidden, current: hiddenNow } = useHiddenConnections(userId);
  const leaving = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useLocalSeedRedirect(router.replace);
  useUiScale(rootRef);
  useEffect(() => {
    if (userReady && !isAuthenticated && !leaving.current) router.replace(SIGN_IN_ROUTE);
  }, [userReady, isAuthenticated, router]);

  const screen = SCREENS[draft.screen];
  const age = ageOn(new Date(), draft.dobM, draft.dobD, draft.dobY);
  const blocked = ageGate || isUnder13(age);
  const active = phase === "active";
  const canNext = active && canAdvance(screen.id, draft, age, blocked);

  // Each screen's heading takes focus as it arrives (and reads out the notice
  // it names), in a layout effect so nothing typed right after is lost.
  useLayoutEffect(() => {
    if (!active) return;
    contentRef.current?.querySelector<HTMLElement>("[data-screen-heading]")?.focus({ preventScroll: true });
  }, [active, draft.screen]);

  const go = useCallback((h: Handoff) => {
    // The calendar consent flow is a backend redirect: a full page load.
    if ("page" in h) window.location.assign(h.page);
    else router.replace(h.route);
  }, [router]);

  const recover = useCallback((failure: SaveFailure) => {
    if (failure.kind === "already") {
      // #757: finished in another tab or a stale page; the server keeps the
      // profile it has. Nothing to save, nothing to wait for.
      discard();
      markOnboarded();
      toast.info("Your account was already set up.");
      go({ route: "/dashboard" });
      return;
    }
    if (failure.kind === "not_approved") {
      go({ route: "/pending" });
      return;
    }
    abort();
    setSettingUp(false);
    if (failure.kind === "courses") {
      patch({ screen: screenIndex("courses"), courses: [], coursesLater: false });
      setNotice("courses");
    } else if (failure.kind === "legal") {
      patch({ screen: screenIndex("terms"), termsEnd: false, termsOk: false, privEnd: false, privOk: false });
      setNotice("legal");
    } else {
      toast.error(failure.message);
    }
  }, [abort, discard, go, markOnboarded, patch, toast]);

  const finish = useCallback((skipConnections: boolean) => {
    if (!userId || !active) return;
    // "Skip for now" finishes with nothing chosen.
    const final = finished(skipConnections ? { ...draft, conn: {} } : draft);
    setDraft(final);
    setNotice(null);
    setSettingUp(true);
    const saved = saveProfile({ userId, accountName: userName, draft: final, under18: isMinor(age) }).then(
      () => {
        discard();
        // The greeting and the nav show the name just chosen.
        void refreshProfile();
        return true;
      },
      (err: unknown) => {
        recover(classifySaveError(err));
        return false;
      },
    );
    outro(() => {
      void saved.then(ok => {
        if (!ok) return;
        // Before leaving: the shell would otherwise send a still-"new" student back here.
        markOnboarded();
        // A choice whose feature is switched off (since it was made) is dropped.
        go(handoffFor(userId, visibleChoices(final.conn, hiddenNow())));
      });
    });
  }, [userId, userName, active, draft, age, setDraft, discard, refreshProfile, recover, outro, markOnboarded, hiddenNow, go]);

  const next = useCallback(() => {
    if (!canNext) return;
    if (draft.screen === LAST) {
      finish(false);
      return;
    }
    setNotice(null);
    setDraft(advance);
  }, [canNext, draft.screen, finish, setDraft]);

  const back = useCallback(() => {
    if (consent) {
      setConsent(null);
      return;
    }
    if (!active || draft.screen === 0) return;
    setNotice(null);
    patch({ screen: draft.screen - 1 });
  }, [consent, active, draft.screen, patch]);

  const leave = useCallback(() => {
    leaving.current = true;
    discard();
    void signOut().catch(() => {}).finally(() => router.replace("/"));
  }, [discard, signOut, router]);

  const onDob = useCallback((dob: Dob) => {
    if (isUnder13(ageOn(new Date(), dob.m, dob.d, dob.y))) {
      // Remembered in this browser for a day (age.ts), and nothing the
      // student entered is kept, the birthday included.
      rememberUnder13();
      setAgeGate(true);
      setDraft(prev => ({ ...EMPTY_DRAFT, screen: prev.screen }));
      return;
    }
    patch({ dobM: dob.m, dobD: dob.d, dobY: dob.y });
  }, [patch, setDraft]);

  useOnboardingKeys(next, back, consent !== null);

  const consentDef = CONNECTIONS.find(c => c.key === consent);

  return (
    <div ref={rootRef} className="ob-root" data-testid="onboarding-gate">
      <div className="ob-beam" />
      <OnboardingGraph phase={phase} zoom={zoom} activeChapter={screen.ch} completed={draft.done} />
      <div className="ob-scrim" aria-hidden="true" style={{ opacity: scrimOpacity(phase, zoom) }} />

      <div className="ob-logo">
        <img src={SAPLING_WORDMARK_SRC} alt="Sapling" />
      </div>
      <TopBar active={active} onSignOut={leave} />

      <div
        ref={contentRef}
        className={`ob-content${active ? "" : " ob-content--hidden"}`}
        aria-hidden={!active}
        inert={!active || consentDef !== undefined}
      >
        <div className={scrollClass(screen.id)}>
          <div className="ob-zoom">
            <ScreenBody
              draft={draft}
              patch={patch}
              blocked={blocked}
              minor={isMinor(age)}
              notice={notice}
              hidden={hidden}
              onDob={onDob}
              onSignOut={leave}
              onConnect={setConsent}
            />
          </div>
        </div>
        <Actions
          label={PRIMARY_LABEL[screen.id] ?? "Next"}
          canNext={canNext}
          canBack={draft.screen > 0}
          onNext={next}
          onBack={back}
          onSkip={screen.id === "connect" ? () => finish(true) : undefined}
        />
      </div>

      <Progress active={active} screen={draft.screen} done={draft.done} />
      <KeyHints active={active} onNext={next} onBack={back} />

      {consentDef && (
        <ConsentSheet
          connection={consentDef}
          onConfirm={() => {
            patch({ conn: { ...draft.conn, [consentDef.key]: true } });
            setConsent(null);
          }}
          onClose={() => setConsent(null)}
        />
      )}

      <IntroMoment shown={introText} started={phase !== "idle"} />
      <OutroMoment shown={outroText} complete={phase === "complete"} />
      <Whiteout on={whiteout} settingUp={settingUp} />
    </div>
  );
}
