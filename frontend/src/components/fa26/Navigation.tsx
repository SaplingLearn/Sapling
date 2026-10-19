"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { GitBranch, Settings } from "lucide-react";
import { useUser } from "@/context/UserContext";
import { useFlagMap } from "@/context/FlagsContext";
import { navFlagForPath } from "@/lib/navFeatures";
import { BOTANICAL_ASSETS, BotanicalIcon, SaplingWordmark, type BotanicalIconName } from "../sapling/BotanicalIcon";
import { DesignSprout } from "./DesignIcon";

type SidebarItem = { href: string; label: string; icon?: BotanicalIconName };

// The approved 01–04 Pen sidebar. Learn and Tutor remain two views of the
// same controller; both inherit the /learn destination's hide_tutor flag.
const PRIMARY: SidebarItem[] = [
  { href: "/dashboard", label: "Today", icon: "today" },
  { href: "/learn", label: "Learn", icon: "learn" },
  { href: "/tree", label: "Knowledge" },
  { href: "/library", label: "Library", icon: "library" },
  { href: "/learn?view=tutor", label: "Tutor", icon: "tutor" },
  { href: "/calendar", label: "Calendar", icon: "calendar" },
];

const MORE_TOOLS = [
  { href: "/quiz", label: "Quiz", testId: "quiz" },
  { href: "/study?mode=guide", label: "Study guides", testId: "study" },
  { href: "/study?mode=cards", label: "Flashcards", testId: "flashcards" },
  { href: "/notetaker", label: "Notes", testId: "notetaker" },
  { href: "/gradebook", label: "Grades", testId: "gradebook" },
  { href: "/course-planner", label: "Course planner", testId: "course-planner" },
  { href: "/achievements", label: "Achievements", testId: "achievements" },
  { href: "/social", label: "Community", testId: "social" },
];

function SidebarBrand() {
  return <Link href="/dashboard" className="fa26-brand" aria-label="Sapling home">
    <SaplingWordmark width={150} decorative />
    <span className="fa26-brand-mobile"><DesignSprout /></span>
  </Link>;
}

// The query-aware active state needs its own boundary for statically rendered
// routes. Keep the rail's width while Next resolves the client URL; flagged
// links are never exposed by a loading fallback.
export function Navigation() {
  return <Suspense fallback={<aside className="fa26-navigation" aria-label="Primary navigation" aria-busy="true"><SidebarBrand /></aside>}>
    <SidebarNavigation />
  </Suspense>;
}

function SidebarNavigation() {
  const pathname = usePathname() || "/dashboard";
  const searchParams = useSearchParams();
  const tutorView = searchParams?.get("view") === "tutor";
  const { userName, isAdmin } = useUser();
  const { flags, ready } = useFlagMap();
  const visible = (href: string) => {
    const flag = navFlagForPath(href.split("?")[0]);
    return !flag || (ready && flags[flag] !== "on");
  };
  const [moreOpen, setMoreOpen] = React.useState(false);
  const trigger = React.useRef<HTMLButtonElement>(null);
  const more = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!moreOpen) return;
    more.current?.querySelector<HTMLAnchorElement>("a")?.focus();
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
  const active = (href: string) => {
    if (href === "/learn" || href === "/learn?view=tutor") {
      return (pathname === "/learn" || pathname.startsWith("/learn/")) && (href.includes("?") === tutorView);
    }
    return pathname === href || pathname.startsWith(href + "/");
  };
  const destination = (href: string) => {
    if (pathname !== "/learn" || (href !== "/learn" && href !== "/learn?view=tutor")) return href;
    // Switching views is not a new course/session choice. Keep the same
    // resume/course/deep-link context, just as the in-screen view control does.
    const params = new URLSearchParams(searchParams?.toString());
    if (href.includes("?")) params.set("view", "tutor");
    else params.delete("view");
    return `/learn${params.size ? `?${params}` : ""}`;
  };
  const accountName = userName?.trim() || "Your account";
  return <aside className="fa26-navigation" aria-label="Primary navigation">
    <SidebarBrand />
    <p className="fa26-workspace-label">Your workspace</p>
    <nav aria-label="Primary" className="fa26-primary-nav">
      <div className="fa26-nav-group">
        {PRIMARY.filter(item => visible(item.href)).map(item => <Link key={item.href} href={destination(item.href)} aria-label={item.label} title={item.label}
          data-testid={`nav-link-${item.href.includes("?") ? "tutor" : item.href.slice(1)}`} aria-current={active(item.href) ? "page" : undefined} className="fa26-nav-item">
          {item.icon ? <BotanicalIcon name={item.icon} size={22} style={{ height: BOTANICAL_ASSETS[item.icon].height }} /> : <GitBranch size={22} aria-hidden="true" />}
          <span className="fa26-nav-label">{item.label}</span>
        </Link>)}
      </div>
    </nav>
    <div className="fa26-sidebar-footer">
      <Link href="/settings" className="fa26-nav-item fa26-settings-link" data-testid="nav-link-settings" aria-current={active("/settings") ? "page" : undefined}>
        <Settings size={20} aria-hidden="true" /><span className="fa26-nav-label">Settings</span>
      </Link>
      <div className="fa26-profile">
        <button ref={trigger} type="button" className="fa26-profile-button" aria-label="Account and more tools"
          aria-expanded={moreOpen} aria-controls="fa26-more-tools" onClick={() => setMoreOpen(!moreOpen)}>
          <span className="fa26-profile-initial" aria-hidden="true">{accountName.charAt(0).toUpperCase()}</span>
          <span className="fa26-profile-copy"><strong>{accountName}</strong><span>Personal workspace</span></span>
        </button>
        {moreOpen && <div ref={more} id="fa26-more-tools" className="fa26-more-tools" role="region" aria-label="More tools">
          <strong>{accountName}</strong>
          {[...MORE_TOOLS, ...(isAdmin ? [{ href: "/admin", label: "Admin", testId: "admin" }] : [])]
            .filter(item => visible(item.href))
            .map(item => <Link key={item.href} href={item.href} data-testid={`nav-link-${item.testId}`} onClick={() => setMoreOpen(false)}>{item.label}</Link>)}
        </div>}
      </div>
    </div>
  </aside>;
}

export function StudyNavigation({ active, onSelect }: { active?: "guide" | "cards"; onSelect?: (value: "guide" | "cards") => void }) {
  return <nav className="fa26-study-tabs" aria-label="Study tools">
    <Link href="/quiz" aria-current={!active ? "page" : undefined}>Quiz</Link>
    {([{ mode: "cards", label: "Flashcards" }, { mode: "guide", label: "Study Guides" }] as const).map(tab => onSelect
      ? <button type="button" key={tab.mode} aria-pressed={active === tab.mode} onClick={() => onSelect(tab.mode)}>{tab.label}</button>
      : <Link key={tab.mode} href={`/study?mode=${tab.mode}`} aria-current={active === tab.mode ? "page" : undefined}>{tab.label}</Link>)}
  </nav>;
}
