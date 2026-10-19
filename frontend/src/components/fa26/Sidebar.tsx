"use client";

import React, { Suspense, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ChevronDown, Ellipsis, GitBranch, Settings } from "lucide-react";
import { useUser } from "@/context/UserContext";
import { useFlagMap } from "@/context/FlagsContext";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import {
  SIDEBAR_MORE, SIDEBAR_PRIMARY, TUTOR_VIEW_FLAG, sidebarActiveKey,
  type SidebarEntry, type SidebarIcon,
} from "@/lib/navFeatures";
import { Icon } from "../Icon";
import { BOTANICAL_ASSETS, BotanicalIcon, SaplingWordmark, type BotanicalIconName } from "../sapling/BotanicalIcon";
import styles from "./Sidebar.module.css";

/** Remembers whether the "More" group is open (per browser, best effort). */
export const MORE_STORAGE_KEY = "sapling_nav_more_open";

/** The approved Pen nav exports. Knowledge has no approved vector (a recorded
 *  gap): the Pen frame draws Lucide's pre-1.0 git-branch, and the closest
 *  icon the app ships is lucide-react 1.x's redrawn GitBranch. */
const BOTANICAL: Partial<Record<SidebarIcon, BotanicalIconName>> = {
  today: "today", learn: "learn", library: "library", tutor: "tutor", calendar: "calendar",
};

function EntryIcon({ icon }: { icon: SidebarIcon }) {
  const name = BOTANICAL[icon];
  // Width-fitted at 22px with the authored height, as in the Pen frames
  // (Tutor's tree stands 27.7px tall, Today's house 16.6px).
  if (name) return <BotanicalIcon name={name} size={22} style={{ height: BOTANICAL_ASSETS[name].height }} />;
  return <GitBranch size={22} strokeWidth={1.75} aria-hidden="true" focusable="false" />;
}

/** Reads `?view=` in its own Suspense boundary: useSearchParams in the shell
 *  would otherwise opt every shell page out of static rendering. */
function ViewReader({ onView }: { onView: (view: string | null) => void }) {
  const view = useSearchParams().get("view");
  useEffect(() => { onView(view); }, [view, onView]);
  return null;
}

/* The More group's remembered state: localStorage when it works, this
   module's memory when it does not (private windows, blocked site data). */
let moreMemory: boolean | null = null;
const moreListeners = new Set<() => void>();
function readMoreOpen(): boolean {
  if (moreMemory !== null) return moreMemory;
  try { return window.localStorage.getItem(MORE_STORAGE_KEY) === "1"; } catch { return false; }
}
function writeMoreOpen(open: boolean) {
  moreMemory = open;
  try { window.localStorage.setItem(MORE_STORAGE_KEY, open ? "1" : "0"); } catch { /* storage blocked */ }
  moreListeners.forEach((listener) => listener());
}
function subscribeMore(listener: () => void) {
  moreListeners.add(listener);
  return () => { moreListeners.delete(listener); };
}
/** Test-only: forget this page's More state. */
export function __resetMoreStateForTests() { moreMemory = null; }

/**
 * The shell's desktop sidebar: the approved Pen nav (216px, sage panel,
 * wordmark, YOUR WORKSPACE, six botanical destinations, Settings and the
 * account row), plus a quiet "More" disclosure holding every other
 * destination so nothing is dropped. Below the phone breakpoint the shell
 * shows the compact rail instead (Navigation.tsx).
 *
 * Motion: ONE cream pill sits behind the active row and tweens its
 * translateY to the next active row. It is placed without a transition on
 * mount (and whenever it reappears), so only real route changes animate;
 * reduced motion makes every change instant (Sidebar.module.css).
 */
export function Sidebar({ testids = true }: { testids?: boolean }) {
  const pathname = usePathname() || "/dashboard";
  const { userName, isAdmin } = useUser();
  const { flags, ready: flagsReady } = useFlagMap();
  const [view, setView] = useState<string | null>(null);
  const tutorOffered = flags[TUTOR_VIEW_FLAG] === "on";
  const activeKey = sidebarActiveKey(pathname, view, tutorOffered);
  const tid = (id: string) => (testids ? id : undefined);

  // Flagged destinations wait for the flags, so a hidden feature never
  // flashes into the nav (the same rule NavFeatureGate redirects on).
  const visible = (flag?: string, requires?: string) =>
    (!flag || (flagsReady && flags[flag] !== "on")) && (!requires || (flagsReady && flags[requires] === "on"));
  const primary = SIDEBAR_PRIMARY.filter((e) => visible(e.flag, e.requires));
  const more = [
    ...SIDEBAR_MORE.filter((i) => visible(i.flag)).map((i) => ({ key: i.href.slice(1), href: i.href, label: i.label, icon: i.icon })),
    ...(isAdmin ? [{ key: "admin", href: "/admin", label: "Admin", icon: "shield" }] : []),
  ];
  const activeInMore = more.some((i) => i.key === activeKey);

  // More: closed by default and remembered per browser. A route that lives in
  // More opens it (until the student closes it again on that route).
  const storedOpen = useSyncExternalStore(subscribeMore, readMoreOpen, () => false);
  const [dismissedOn, setDismissedOn] = useState<string | null>(null);
  const forcedOpen = activeInMore && dismissedOn !== pathname;
  const moreOpen = forcedOpen || storedOpen;
  const setMore = (open: boolean) => {
    setDismissedOn(open ? null : pathname);
    writeMoreOpen(open);
  };
  const moreId = useId();
  const moreButton = useRef<HTMLButtonElement>(null);
  const onMoreKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    setMore(false);
    moreButton.current?.focus();
  };

  // The pill is driven straight on the DOM (it is animation state, not
  // React state): placed without a transition on mount and whenever it
  // reappears; transitions arm one frame after the first placement.
  const track = useRef<HTMLElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const [animated, setAnimated] = useState(false);
  // Reduced motion never arms the transitions (the stylesheet also zeroes them).
  const reducedMotion = usePrefersReducedMotion();
  const targetKey = activeInMore && !moreOpen ? null : activeKey;
  const place = useCallback(() => {
    const nav = track.current;
    const content = nav?.firstElementChild;
    const el = pill.current;
    if (!nav || !content || !el) return;
    const row = targetKey ? content.querySelector<HTMLElement>(`[data-nav-key="${targetKey}"]`) : null;
    if (!row) {
      delete el.dataset.shown;
      delete nav.dataset.pill;
      return;
    }
    // Relative to the scrolling content box the pill lives in, so a scrolled
    // track needs no correction.
    const y = Math.round(row.getBoundingClientRect().top - content.getBoundingClientRect().top);
    const transform = `translateY(${y}px)`;
    const wasShown = el.dataset.shown !== undefined;
    if (wasShown && el.style.transform === transform) return;
    if (wasShown) delete el.dataset.jump; else el.dataset.jump = "";
    el.style.transform = transform;
    el.dataset.shown = "";
    nav.dataset.pill = "";
  }, [targetKey]);
  const rowsKey = primary.map((e) => e.key).join() + "|" + more.map((i) => i.key).join();
  useLayoutEffect(() => { place(); }, [place, rowsKey]);
  useEffect(() => {
    const nav = track.current;
    if (!nav || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => place());
    observer.observe(nav);
    if (nav.firstElementChild) observer.observe(nav.firstElementChild);
    return () => observer.disconnect();
  }, [place]);
  useEffect(() => {
    let second = 0;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => setAnimated(true)); });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, []);

  const row = (entry: { key: string; href: string; label: string }, icon: React.ReactNode, testid: string | undefined) => {
    const current = entry.key === activeKey;
    return <li key={entry.key}>
      <Link href={entry.href} className={styles.item} data-nav-key={entry.key} data-testid={testid}
        aria-current={current ? "page" : undefined}>
        <span className={styles.icon}>{icon}</span>
        <span className={styles.label}>{entry.label}</span>
      </Link>
    </li>;
  };

  return <aside className={styles.sidebar} aria-label="Sidebar" data-testid={tid("app-sidebar")} data-animated={(animated && !reducedMotion) || undefined}>
    <Suspense fallback={null}><ViewReader onView={setView} /></Suspense>
    <Link href="/dashboard" className={styles.brand} aria-label="Sapling home">
      <SaplingWordmark width={150} decorative />
    </Link>
    <nav aria-label="Primary" className={styles.track} ref={track}>
      <div className={styles.content}>
        <span ref={pill} aria-hidden="true" data-testid={tid("nav-pill")} className={styles.pill} />
        <p className={styles.eyebrow}>Your workspace</p>
        <ul className={styles.list}>
          {primary.map((e: SidebarEntry) => row(e, <EntryIcon icon={e.icon} />, tid(e.testid)))}
        </ul>
        {more.length > 0 && <div className={styles.more}>
          <button ref={moreButton} type="button" className={`${styles.item} ${styles.moreButton}`}
            aria-expanded={moreOpen} aria-controls={moreId} data-testid={tid("nav-more")} onClick={() => setMore(!moreOpen)}>
            <span className={styles.icon}><Ellipsis size={22} strokeWidth={1.75} aria-hidden="true" focusable="false" /></span>
            <span className={styles.label}>More</span>
            <ChevronDown className={styles.chevron} size={18} strokeWidth={1.75} aria-hidden="true" focusable="false" />
          </button>
          <div id={moreId} className={styles.moreRegion} data-open={moreOpen || undefined} data-testid={tid("nav-more-region")}
            inert={!moreOpen} onKeyDown={onMoreKeyDown}>
            <div className={styles.moreInner}>
              <ul className={`${styles.list} ${styles.moreList}`} aria-label="More destinations">
                {more.map((i) => row(i, <Icon name={i.icon} size={20} />, tid(`nav-link-${i.key}`)))}
              </ul>
            </div>
          </div>
        </div>}
        <div className={styles.footer}>
          <ul className={styles.list}>
            {row({ key: "settings", href: "/settings", label: "Settings" },
              <Settings size={18} strokeWidth={1.75} aria-hidden="true" focusable="false" />, tid("nav-link-settings"))}
          </ul>
        </div>
      </div>
    </nav>
    <div className={styles.account} data-testid={tid("nav-account")}>
      <span className={styles.avatar} aria-hidden="true">{userName?.trim().charAt(0).toUpperCase() || "S"}</span>
      <span className={styles.who}>
        <strong>{userName || "Your account"}</strong>
        <small>Personal workspace</small>
      </span>
    </div>
  </aside>;
}
