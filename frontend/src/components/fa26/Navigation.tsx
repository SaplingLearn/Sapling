"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useFlagMap } from "@/context/FlagsContext";
import { navFlagForPath } from "@/lib/navFeatures";
import { useIsMobile } from "@/lib/useIsMobile";
import { DesignIcon, DesignSprout } from "./DesignIcon";
import { Sidebar } from "./Sidebar";

const PRIMARY = [
  { href: "/dashboard", label: "Dashboard", icon: "home" },
  { href: "/library", label: "Library", icon: "library" },
  { href: "/quiz", label: "Study", icon: "study" },
  { href: "/learn", label: "Clov", icon: "clov" },
];
const SECONDARY = [
  { href: "/tree", label: "Knowledge Map", icon: "tree" },
  { href: "/calendar", label: "Calendar", icon: "calendar" },
  { href: "/notetaker", label: "Notes", icon: "notes" },
];

/**
 * The shell's navigation: the Pen sidebar on desktop, #727's compact rail on
 * a phone (below useIsMobile's 768px, the same edge as the CSS switch).
 *
 * Both are rendered and CSS shows exactly one at every width, so the server
 * render is already right on a phone and nothing jumps at hydration. Only the
 * shown one carries data-testids, so an E2E locator never matches two
 * elements (before hydration the desktop one has them, the server's guess).
 */
export function Navigation() {
  const phone = useIsMobile();
  return <>
    <Sidebar testids={!phone} />
    <PhoneRail testids={phone} />
  </>;
}

/** #727's compact rail, kept unchanged as the phone navigation. */
export function PhoneRail({ testids = true }: { testids?: boolean }) {
  const pathname = usePathname() || "/dashboard";
  const { userName, isAdmin } = useUser();
  // #620 hide_<feature> flags, keyed by destination through lib/navFeatures
  // (the same table NavFeatureGate redirects on). Flagged destinations wait for
  // the flags to load so a hidden feature never flashes into the nav.
  const { flags, ready } = useFlagMap();
  const visible = (href: string) => {
    const flag = navFlagForPath(href);
    return !flag || (ready && flags[flag] !== "on");
  };
  const [moreOpen, setMoreOpen] = React.useState(false);
  const trigger = React.useRef<HTMLButtonElement>(null);
  const more = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!moreOpen) return;
    const close = (event: PointerEvent) => {
      if (!more.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setMoreOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMoreOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [moreOpen]);
  const active = (href: string) => href === "/quiz"
    ? ["/quiz", "/study", "/flashcards"].some(path => pathname === path || pathname.startsWith(path + "/"))
    : pathname === href || pathname.startsWith(href + "/");
  return <aside className="fa26-navigation" aria-label="Primary navigation">
    <Link href="/dashboard" className="fa26-brand" aria-label="Sapling home"><DesignSprout /></Link>
    <nav aria-label="Primary">
      {[PRIMARY, SECONDARY].map((group, index) => <div className="fa26-nav-group" key={index}>
        {group.filter(item => visible(item.href)).map(item => <Link key={item.href} href={item.href} aria-label={item.label} title={item.label}
          data-testid={testids ? `nav-link-${item.href.slice(1)}` : undefined} aria-current={active(item.href) ? "page" : undefined} className="fa26-nav-item">
          <DesignIcon name={item.icon} /><span className="fa26-nav-label">{item.label}</span>
        </Link>)}
      </div>)}
    </nav>
    <div className="fa26-profile">
      <button ref={trigger} type="button" className="fa26-profile-button" aria-label="Account and more tools"
        aria-expanded={moreOpen} aria-controls="fa26-more-tools" onClick={() => setMoreOpen(!moreOpen)}>
        {userName?.trim().charAt(0).toUpperCase() || "S"}
      </button>
      {moreOpen && <div ref={more} id="fa26-more-tools" className="fa26-more-tools">
        <strong>{userName || "Your account"}</strong>
        {[{ href: "/settings", label: "Settings" }, { href: "/gradebook", label: "Grades" },
          { href: "/course-planner", label: "Course planner" }, { href: "/achievements", label: "Achievements" },
          { href: "/social", label: "Community" }, ...(isAdmin ? [{ href: "/admin", label: "Admin" }] : [])]
          .filter(item => visible(item.href))
          .map(item => <Link key={item.href} href={item.href} data-testid={testids ? `nav-link-${item.href.slice(1)}` : undefined} onClick={() => setMoreOpen(false)}>{item.label}</Link>)}
      </div>}
    </div>
  </aside>;
}

export function StudyNavigation({ active, onSelect }: { active?: "guide" | "cards"; onSelect?: (value: "guide" | "cards") => void }) {
  return <nav className="fa26-study-tabs" aria-label="Study tools">
    <Link href="/quiz" aria-current={!active ? "page" : undefined}>Quiz</Link>
    {([{ mode: "guide", label: "Study Guide" }, { mode: "cards", label: "Flashcards" }] as const).map(tab => onSelect
      ? <button type="button" key={tab.mode} aria-pressed={active === tab.mode} onClick={() => onSelect(tab.mode)}>{tab.label}</button>
      : <Link key={tab.mode} href={`/study?mode=${tab.mode}`} aria-current={active === tab.mode ? "page" : undefined}>{tab.label}</Link>)}
  </nav>;
}
