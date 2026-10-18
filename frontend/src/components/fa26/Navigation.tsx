"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { DesignIcon, DesignSprout } from "./DesignIcon";

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

export function Navigation() {
  const pathname = usePathname() || "/dashboard";
  const { userName, isAdmin } = useUser();
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
        {group.map(item => <Link key={item.href} href={item.href} aria-label={item.label} title={item.label}
          aria-current={active(item.href) ? "page" : undefined} className="fa26-nav-item">
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
          .map(item => <Link key={item.href} href={item.href} onClick={() => setMoreOpen(false)}>{item.label}</Link>)}
      </div>}
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
