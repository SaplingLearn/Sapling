"use client";

import React, { Suspense, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ChevronDown, Ellipsis, GitBranch, PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";
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
/** Remembers whether the sidebar is collapsed to its icon rail. */
export const COLLAPSED_STORAGE_KEY = "sapling_nav_collapsed";

/** The approved Pen nav exports. Knowledge has no approved vector (a recorded
 *  gap): the Pen frame draws Lucide's pre-1.0 git-branch, and the closest
 *  icon the app ships is lucide-react 1.x's redrawn GitBranch. */
const BOTANICAL: Partial<Record<SidebarIcon, BotanicalIconName>> = {
  today: "today", learn: "learn", library: "library", tutor: "tutor", calendar: "calendar",
};

/** Row icon width, px (--nav-icon in Sidebar.module.css). */
const ICON = 18;

function EntryIcon({ icon }: { icon: SidebarIcon }) {
  const name = BOTANICAL[icon];
  // Width-fitted at 18px (down from the Pen's 22, at Andres's request) with
  // the authored aspect: Tutor's tree stands ~22.6px, Today's house ~13.6px.
  const { width, height } = name ? BOTANICAL_ASSETS[name] : { width: 1, height: 1 };
  if (name) return <BotanicalIcon name={name} size={ICON} style={{ height: (ICON * height) / width }} />;
  return <GitBranch size={ICON} strokeWidth={1.75} aria-hidden="true" focusable="false" />;
}

/** Reads the URL in its own Suspense boundary: useSearchParams in the shell
 *  would otherwise opt every shell page out of static rendering. */
function ViewReader({ onSearch }: { onSearch: (search: string) => void }) {
  const search = useSearchParams().toString();
  useEffect(() => { onSearch(search); }, [search, onSearch]);
  return null;
}

/* Remembered booleans (More open, sidebar collapsed): localStorage when it
   works, this module's memory when it does not (private windows, blocked
   site data). One tiny external store per key. */
function rememberedFlag(key: string) {
  let memory: boolean | null = null;
  const listeners = new Set<() => void>();
  return {
    read(): boolean {
      if (memory !== null) return memory;
      try { return window.localStorage.getItem(key) === "1"; } catch { return false; }
    },
    write(value: boolean) {
      memory = value;
      try { window.localStorage.setItem(key, value ? "1" : "0"); } catch { /* storage blocked */ }
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    reset() { memory = null; },
  };
}
const moreStore = rememberedFlag(MORE_STORAGE_KEY);
const collapsedStore = rememberedFlag(COLLAPSED_STORAGE_KEY);
const serverFalse = () => false;
/** Test-only: forget this page's remembered nav state. */
export function __resetMoreStateForTests() { moreStore.reset(); collapsedStore.reset(); }

/* Applies a remembered collapse before the first paint of a server-rendered
   page, so a collapsed sidebar never flashes open and shoves <main> over at
   hydration (React then owns the attribute; see suppressHydrationWarning). */
const PRE_PAINT_COLLAPSE = `(function(s){try{if(localStorage.getItem(${JSON.stringify(COLLAPSED_STORAGE_KEY)})==="1")s.parentElement.setAttribute("data-collapsed","")}catch(e){}})(document.currentScript)`;

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
  const [search, setSearch] = useState("");
  const view = new URLSearchParams(search).get("view");
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
  const storedOpen = useSyncExternalStore(moreStore.subscribe, moreStore.read, serverFalse);
  const [dismissedOn, setDismissedOn] = useState<string | null>(null);
  const forcedOpen = activeInMore && dismissedOn !== pathname;
  const moreOpen = forcedOpen || storedOpen;
  const setMore = (open: boolean) => {
    setDismissedOn(open ? null : pathname);
    moreStore.write(open);
  };
  const moreId = useId();
  const sidebarId = useId();

  // Collapse to an icon rail: default expanded, remembered per browser.
  const collapsed = useSyncExternalStore(collapsedStore.subscribe, collapsedStore.read, serverFalse);
  const toggleCollapsed = () => { setTip(null); collapsedStore.write(!collapsed); };
  // Collapsed rows show their label in a tooltip on hover and focus. It is
  // fixed-positioned so the rail's clipping never cuts it off; the rows carry
  // aria-labels, so it is decoration for sighted users only.
  const [tip, setTip] = useState<{ label: string; top: number; left: number } | null>(null);
  const showTip = (target: EventTarget | null) => {
    if (!collapsed) return;
    const el = target instanceof Element ? target.closest<HTMLElement>("[data-tip]") : null;
    if (!el) { setTip(null); return; }
    const r = el.getBoundingClientRect();
    setTip({ label: el.dataset.tip ?? "", top: r.top + r.height / 2, left: r.right + 10 });
  };
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

  const destination = (href: string) => {
    if (pathname !== "/learn" || (href !== "/learn" && href !== "/learn?view=tutor")) return href;
    // A sidebar view change keeps the active course/session and deep-link
    // context. Only the presentation changes, just as with the in-screen tabs.
    const params = new URLSearchParams(search);
    if (href.includes("?")) params.set("view", "tutor");
    else params.delete("view");
    return `/learn${params.size ? `?${params}` : ""}`;
  };

  const row = (entry: { key: string; href: string; label: string }, icon: React.ReactNode, testid: string | undefined) => {
    const current = entry.key === activeKey;
    return <li key={entry.key}>
      <Link href={destination(entry.href)} className={styles.item} data-nav-key={entry.key} data-testid={testid}
        aria-current={current ? "page" : undefined} aria-label={collapsed ? entry.label : undefined} data-tip={entry.label}>
        <span className={styles.icon}>{icon}</span>
        <span className={`${styles.label} ${styles.fade}`}>{entry.label}</span>
      </Link>
    </li>;
  };

  return <aside id={sidebarId} className={styles.sidebar} aria-label="Sidebar" data-testid={tid("app-sidebar")}
    data-animated={(animated && !reducedMotion) || undefined} data-collapsed={collapsed || undefined}
    suppressHydrationWarning
    onPointerOver={(e) => showTip(e.target)} onPointerLeave={() => setTip(null)}
    onFocus={(e) => showTip(e.target)} onBlur={() => setTip(null)}
    onKeyDown={(e) => { if (e.key === "Escape") setTip(null); }}>
    <script dangerouslySetInnerHTML={{ __html: PRE_PAINT_COLLAPSE }} />
    <Suspense fallback={null}><ViewReader onSearch={setSearch} /></Suspense>
    <div className={styles.header}>
      {/* No approved standalone Sapling mark ships in public/design/sapling,
          so the collapsed rail shows no logo rather than a drawn one. */}
      <Link href="/dashboard" className={`${styles.brand} ${styles.fade}`} aria-label="Sapling home">
        <SaplingWordmark width={112} decorative />
      </Link>
      <button type="button" className={styles.toggle} data-testid={tid("nav-collapse")}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} aria-controls={sidebarId}
        data-tip={collapsed ? "Expand sidebar" : undefined} onClick={toggleCollapsed}>
        {collapsed
          ? <PanelLeftOpen size={18} strokeWidth={1.75} aria-hidden="true" focusable="false" />
          : <PanelLeftClose size={18} strokeWidth={1.75} aria-hidden="true" focusable="false" />}
      </button>
    </div>
    <nav aria-label="Primary" className={styles.track} ref={track}>
      <div className={styles.content}>
        <span ref={pill} aria-hidden="true" data-testid={tid("nav-pill")} className={styles.pill} />
        <p className={`${styles.eyebrow} ${styles.fade}`}>Your workspace</p>
        <ul className={styles.list}>
          {primary.map((e: SidebarEntry) => row(e, <EntryIcon icon={e.icon} />, tid(e.testid)))}
        </ul>
        {more.length > 0 && <div className={styles.more}>
          <button ref={moreButton} type="button" className={`${styles.item} ${styles.moreButton}`}
            aria-expanded={moreOpen} aria-controls={moreId} data-testid={tid("nav-more")} onClick={() => setMore(!moreOpen)}
            aria-label={collapsed ? "More" : undefined} data-tip="More">
            <span className={styles.icon}><Ellipsis size={ICON} strokeWidth={1.75} aria-hidden="true" focusable="false" /></span>
            <span className={`${styles.label} ${styles.fade}`}>More</span>
            <span className={`${styles.chevronSlot} ${styles.fade}`}>
              <ChevronDown className={styles.chevron} size={16} strokeWidth={1.75} aria-hidden="true" focusable="false" />
            </span>
          </button>
          <div id={moreId} className={styles.moreRegion} data-open={moreOpen || undefined} data-testid={tid("nav-more-region")}
            inert={!moreOpen} onKeyDown={onMoreKeyDown}>
            <div className={styles.moreInner}>
              <ul className={`${styles.list} ${styles.moreList}`} aria-label="More destinations">
                {more.map((i) => row(i, <Icon name={i.icon} size={ICON} />, tid(`nav-link-${i.key}`)))}
              </ul>
            </div>
          </div>
        </div>}
        <div className={styles.footer}>
          <ul className={styles.list}>
            {row({ key: "settings", href: "/settings", label: "Settings" },
              <Settings size={ICON} strokeWidth={1.75} aria-hidden="true" focusable="false" />, tid("nav-link-settings"))}
          </ul>
        </div>
      </div>
    </nav>
    <div className={styles.account} data-testid={tid("nav-account")} title={collapsed ? userName || "Your account" : undefined}>
      <span className={styles.avatar} aria-hidden="true">{userName?.trim().charAt(0).toUpperCase() || "S"}</span>
      <span className={`${styles.who} ${styles.fade}`}>
        <strong>{userName || "Your account"}</strong>
        <small>Personal workspace</small>
      </span>
    </div>
    {collapsed && tip && <span className={styles.tip} data-testid={tid("nav-tip")} aria-hidden="true"
      style={{ top: tip.top, left: tip.left }}>{tip.label}</span>}
  </aside>;
}
