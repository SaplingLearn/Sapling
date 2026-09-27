"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { useUser } from "@/context/UserContext";

type Entry = { href: string; label: string; icon: string };

const SECTIONS: { label: string; items: Entry[] }[] = [
  {
    label: "Learn",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "home" },
      { href: "/learn",     label: "Tutor",     icon: "brain" },
      { href: "/quiz",      label: "Quiz",      icon: "flask" },
      { href: "/tree",      label: "Tree",      icon: "tree" },
      { href: "/study",     label: "Study",     icon: "bolt" },
    ],
  },
  {
    label: "Organize",
    items: [
      { href: "/library",  label: "Library",  icon: "book" },
      { href: "/calendar", label: "Calendar", icon: "cal" },
    ],
  },
  {
    label: "Community",
    items: [
      { href: "/social",       label: "Social",       icon: "users" },
      { href: "/achievements", label: "Achievements", icon: "trophy" },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/gradebook",      label: "Grades",         icon: "star" },
      { href: "/notetaker",      label: "Notetaker",      icon: "pencil" },
      { href: "/course-planner", label: "Course Planner", icon: "planner" },
    ],
  },
];

export const SIDE_NAV_EXPANDED = 232;
export const SIDE_NAV_COLLAPSED = 64;
const COLLAPSE_KEY = "sapling_sidenav_collapsed";

/* Row rhythm. 44px is the WCAG comfort target and this rail used to sit there,
   but a desktop-only sidebar carrying 12 destinations reads as a wall at that
   pitch. 38px is the dense-desktop value: still above the 36px floor we hold
   ourselves to on a pointer-first surface, and ~15% tighter per row once the
   1px gap is counted. Never take NAV_ITEM_MIN_HEIGHT below 36. */
const NAV_ITEM_MIN_HEIGHT = 38;
/** The floor the comment above forbids going under. Named so the clamp that
 *  enforces it cannot drift from the rule that states it. */
const NAV_ITEM_FLOOR = 36;
const NAV_GAP = 1;

/* Every vertical measurement in the rail, expressed as `clamp(floor, vh, the
   value it had)`.

   The rail is `height: 100vh` with `overflowY: auto`, and its content came to
   912px. That fits a 1080p screen with the bookmarks bar turned off and
   essentially nothing else: measured against real post-chrome viewports, it
   scrolled by 100px on a MacBook 14, 234px on a MacBook 13, and 314px on a
   1366x768 laptop with a bookmarks bar. A rail that scrolls is a rail whose
   last destinations are invisible, and this one hides Settings and the
   account block down there.

   So the rows hold their pitch until the window gets short and then give it
   up down to — never past — the 36px floor above. Everything that is not a
   row (the brand block, the group headers, the separators, the account
   padding) gives up proportionally more, because whitespace degrades more
   gracefully than a touch target does. */
const NAV_ITEM_H = `clamp(${NAV_ITEM_FLOOR}px, 4.3vh, ${NAV_ITEM_MIN_HEIGHT}px)`;
/** The account row, which is chrome rather than a destination. */
const ACCOUNT_H = "clamp(34px, 4.9vh, 44px)";
/** Gap above a group header. The single largest non-row cost: four of them. */
const HEAD_TOP = "clamp(3px, 2.2vh, 20px)";
const HEAD_TOP_N = "clamp(3px, 2.4vh, 22px)";
const HEAD_BOT = "clamp(2px, 1.1vh, 10px)";
const RAIL_PAD_Y = "clamp(6px, 1.4vh, 16px)";

/* Horizontal inset shared by every horizontal rule in the rail — the collapsed
   group separators and the Settings/Admin rule — so they read as one line
   family instead of three different indents. */
const RULE_INSET = 8;

/* Active/hover surfaces.
 *
 * A plain highlight, the way it always was — just not in the old colour. The
 * selected row is a flat `--sap-100` fill (the soft end of the green scale)
 * where it used to be `--bg-soft`, so the marker reads as green against the
 * rail's warm `--bg-subtle` ground instead of as another shade of cream. No
 * rail, no hue on the label, nothing else: the fill IS the treatment, and at
 * 38px on a 4px radius it is a smaller one than the 44px slab it replaces.
 *
 * Hover inherits the fill that active gave up. `--bg-soft` is one step off the
 * ground and neutral, so it is unmistakably the weaker, transient state and
 * cannot be confused with the green of a selection.
 *
 * Both are palette tokens rather than mixes, so they move with the scale. */
const NAV_ACTIVE_BG = "var(--sap-100)";
const NAV_HOVER_BG = "var(--bg-soft)";

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  return pathname === href || pathname.startsWith(href + "/");
}

function useCollapsed(): [boolean, (v: boolean) => void] {
  const [collapsed, setCollapsed] = React.useState(false);
  React.useEffect(() => {
    try { setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1"); } catch {}
  }, []);
  const update = (v: boolean) => {
    setCollapsed(v);
    try { localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0"); } catch {}
  };
  return [collapsed, update];
}

export function SideNav() {
  const pathname = usePathname() || "/";
  const { userName, avatarUrl, isAdmin, isAuthenticated } = useUser();
  const [collapsed, setCollapsed] = useCollapsed();

  const width = collapsed ? SIDE_NAV_COLLAPSED : SIDE_NAV_EXPANDED;

  return (
    <aside
      role="navigation"
      aria-label="Primary"
      // Hook for the pre-hydration mobile guard in globals.css (#110).
      data-app-sidenav=""
      style={{
        width,
        minWidth: width,
        height: "100vh",
        borderRight: "1px solid var(--border)",
        background: "var(--bg-subtle)",
        padding: collapsed ? `${RAIL_PAD_Y} 6px` : `${RAIL_PAD_Y} 10px`,
        display: "flex",
        flexDirection: "column",
        gap: NAV_GAP,
        overflowY: "auto",
        overflowX: "hidden",
        transition: "width var(--dur) var(--ease), min-width var(--dur) var(--ease), padding var(--dur) var(--ease)",
      }}
    >
      {/* Logo */}
      <Link
        href="/dashboard"
        aria-label="Sapling — home"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "flex-start",
          gap: 2,
          padding: collapsed ? "2px 0 clamp(4px, 1.6vh, 14px)" : "2px 8px clamp(4px, 1.6vh, 14px)",
          borderBottom: "1px solid var(--border)",
          marginBottom: 8,
          textDecoration: "none",
        }}
      >
        <img
          src="/sapling-icon.svg"
          alt="Sapling"
          width={32}
          height={32}
          decoding="async"
          style={{
            width: 32,
            height: 32,
            marginTop: -4,
            marginLeft: collapsed ? 0 : -2,
            marginRight: collapsed ? 0 : -4,
            alignSelf: "center",
            flexShrink: 0,
          }}
        />
        {!collapsed && (
          <div style={{ display: "flex", flexDirection: "column", gap: 1, alignItems: "flex-start" }}>
            <span
              style={{
                fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif",
                fontWeight: 700,
                fontSize: 20,
                color: "var(--brand-forest)",
                letterSpacing: "-0.02em",
                textShadow: "0 0 12px rgba(26, 92, 42, 0.2)",
                lineHeight: 1.1,
              }}
            >
              Sapling
            </span>
          </div>
        )}
      </Link>

      {SECTIONS.map((section, i) => (
        <React.Fragment key={section.label}>
          {!collapsed && (
            <div
              className="label-micro"
              /* Above: the first group needs its own value — it is the only
                 one introduced by the logo rule rather than by the group
                 before it, and inherits nothing from a preceding item.
                 Below: every header stands clear of the items it labels, so
                 the header reads as a heading and not as the first row. */
              style={{ padding: i === 0 ? `${HEAD_TOP} 10px ${HEAD_BOT}` : `${HEAD_TOP_N} 10px ${HEAD_BOT}` }}
            >
              {section.label}
            </div>
          )}
          {collapsed && i > 0 && (
            <div
              style={{ height: 1, background: "var(--border)", margin: `clamp(4px, 2.1vh, 18px) ${RULE_INSET}px ${HEAD_BOT}` }}
              aria-hidden
            />
          )}
          {section.items.map(item => (
            <NavLink
              key={item.href}
              entry={item}
              active={isActive(pathname, item.href)}
              collapsed={collapsed}
            />
          ))}
        </React.Fragment>
      ))}

      <div style={{ flex: 1 }} />

      {/* The one rule at the foot of the rail. It sits ABOVE the Settings +
          Admin pair (not between them, and not on the profile block), so the
          account-level items and the avatar below them read as a single
          cluster split off from the main nav. Same inset as the collapsed
          group rules above, so the two line up in the narrow state. */}
      <div
        style={{ height: 1, background: "var(--border)", margin: `${HEAD_BOT} ${RULE_INSET}px` }}
        aria-hidden
      />

      <NavLink
        entry={{ href: "/settings", label: "Settings", icon: "cog" }}
        active={isActive(pathname, "/settings")}
        collapsed={collapsed}
      />
      {isAdmin && (
        <NavLink
          entry={{ href: "/admin", label: "Admin", icon: "shield" }}
          active={isActive(pathname, "/admin")}
          collapsed={collapsed}
        />
      )}

      {/* The profile block carries no rule of its own — the one above Settings
          already opened this cluster, and a second hairline here would box the
          avatar in. */}
      {isAuthenticated && (
        <div style={{ padding: collapsed ? `${HEAD_BOT} 0 4px` : `${HEAD_BOT} 6px 4px` }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: collapsed ? 0 : 4,
              width: "100%",
            }}
          >
            <div
              title={collapsed ? (userName || "Account") : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flex: 1,
                minWidth: 0,
                padding: "6px 6px",
                borderRadius: "var(--r-sm)",
                textAlign: "left",
                justifyContent: collapsed ? "center" : "flex-start",
              }}
            >
              <Avatar name={userName || "?"} size={30} img={avatarUrl || undefined} />
              {!collapsed && (
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: "var(--text)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {userName || "You"}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Account</div>
                </div>
              )}
            </div>
            {!collapsed && (
              <button
                type="button"
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
                onClick={() => setCollapsed(true)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 44,
                  height: ACCOUNT_H,
                  flexShrink: 0,
                  borderRadius: "var(--r-sm)",
                  color: "var(--text-muted)",
                  transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-soft)";
                  e.currentTarget.style.color = "var(--text)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.color = "var(--text-muted)";
                }}
              >
                <Icon name="chev" size={12} />
              </button>
            )}
          </div>
          {collapsed && (
            <button
              type="button"
              aria-label="Expand sidebar"
              title="Expand sidebar"
              onClick={() => setCollapsed(false)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "100%",
                height: ACCOUNT_H,
                marginTop: 6,
                borderRadius: "var(--r-sm)",
                color: "var(--text-muted)",
                transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--bg-soft)";
                e.currentTarget.style.color = "var(--text)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = "var(--text-muted)";
              }}
            >
              <span style={{ display: "inline-flex", transform: "rotate(180deg)" }}>
                <Icon name="chev" size={12} />
              </span>
            </button>
          )}
        </div>
      )}
    </aside>
  );
}

function NavLink({ entry, active, collapsed }: { entry: Entry; active: boolean; collapsed: boolean }) {
  return (
    <Link
      href={entry.href}
      title={collapsed ? entry.label : undefined}
      aria-label={collapsed ? entry.label : undefined}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: collapsed ? "center" : "flex-start",
        gap: 10,
        // No explicit width: the rail is a flex column, so a row stretches to
        // the content box on its own and the margins below actually inset it.
        // `width: 100%` would have added to them and overflowed instead.
        minHeight: NAV_ITEM_H,
        // The pill is inset to the group header's own 10px, so its leading
        // edge lines up with "LEARN" rather than running to the rail's walls,
        // and it stops the same distance short on the right. The icon then
        // sits 12px inside that — which is what puts the destinations a step
        // in from the label they belong to.
        marginLeft: collapsed ? 0 : 10,
        marginRight: collapsed ? 0 : 10,
        padding: collapsed ? "6px 0" : "6px 12px",
        borderRadius: "var(--r-xs)",
        background: active ? NAV_ACTIVE_BG : "transparent",
        color: active ? "var(--text)" : "var(--text-dim)",
        fontWeight: active ? 600 : 400,
        fontSize: 13,
        transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
        textDecoration: "none",
      }}
      onMouseEnter={(e) => {
        if (active) return;
        e.currentTarget.style.background = NAV_HOVER_BG;
        e.currentTarget.style.color = "var(--text)";
      }}
      onMouseLeave={(e) => {
        if (active) return;
        e.currentTarget.style.background = "transparent";
        e.currentTarget.style.color = "var(--text-dim)";
      }}
    >
      <Icon name={entry.icon} size={15} />
      {!collapsed && <span style={{ flex: 1 }}>{entry.label}</span>}
    </Link>
  );
}

