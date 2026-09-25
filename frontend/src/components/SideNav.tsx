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
const NAV_GAP = 1;

/* Horizontal inset shared by every horizontal rule in the rail — the collapsed
   group separators and the Settings/Admin rule — so they read as one line
   family instead of three different indents. */
const RULE_INSET = 8;

/* Active/hover surfaces.
 *
 * A plain neutral highlight. The selected row is a flat `--bg-soft`
 * (`--ink-100`) fill — one step off the rail's warm `--bg-subtle` ground —
 * with the label in bold ink. The earlier `--sap-100` green read as a
 * washed-out tint against the cream rail, and `--ink-200` read as too heavy;
 * one step of the shell's own warm grey is enough once the label goes bold.
 * No rail, no hue on the label: the fill IS the treatment.
 *
 * Hover is the same colour at half strength, so it is unmistakably the
 * weaker, transient state and never reads as a second selection. */
const NAV_ACTIVE_BG = "var(--bg-soft)";
const NAV_HOVER_BG = "color-mix(in srgb, var(--bg-soft) 50%, transparent)";

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
        padding: collapsed ? "16px 6px" : "16px 10px",
        display: "flex",
        flexDirection: "column",
        gap: NAV_GAP,
        // The rail itself never scrolls: only the destinations region below
        // does, so the account footer stays pinned at the bottom.
        overflow: "hidden",
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
          padding: collapsed ? "2px 0 14px" : "2px 8px 14px",
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
                fontFamily: "'Spectral', Georgia, serif",
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

      {/* The destinations scroll on their own when the viewport is too short
          for them, with the scrollbar hidden (`scrollbarWidth` here, the
          WebKit pseudo-element in globals.css) — a 10px gutter in a 232px
          rail read as clutter, and wheel/trackpad/keyboard scrolling all
          still work. `minHeight: 0` is what lets a flex child shrink below
          its content and scroll at all. */}
      <div
        data-sidenav-scroll=""
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          overflowX: "hidden",
          scrollbarWidth: "none",
          display: "flex",
          flexDirection: "column",
          gap: NAV_GAP,
        }}
      >
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
              style={{ padding: i === 0 ? "20px 10px 10px" : "22px 10px 10px" }}
            >
              {section.label}
            </div>
          )}
          {collapsed && i > 0 && (
            <div
              style={{ height: 1, background: "var(--border)", margin: `18px ${RULE_INSET}px 10px` }}
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

      </div>

      {/* Collapse/expand sits just above the footer rule, pinned with it, and
          is built like a nav row: "‹ Collapse" in the wide rail, the bare
          chevron (pointing out) in the narrow one — the usual sidebar toggle.
          Same insets, padding and row height as NavLink so it lines up with
          the destinations above it. */}
      <button
        type="button"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : undefined}
        onClick={() => setCollapsed(!collapsed)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "flex-start",
          gap: 10,
          flexShrink: 0,
          minHeight: NAV_ITEM_MIN_HEIGHT,
          marginTop: 6,
          marginLeft: collapsed ? 0 : 10,
          marginRight: collapsed ? 0 : 10,
          padding: collapsed ? "6px 0" : "6px 12px",
          borderRadius: "var(--r-xs)",
          color: "var(--text-dim)",
          fontSize: 13,
          textAlign: "left",
          transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = NAV_HOVER_BG;
          e.currentTarget.style.color = "var(--text)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent";
          e.currentTarget.style.color = "var(--text-dim)";
        }}
      >
        <span
          style={{
            display: "inline-flex",
            width: 15,
            justifyContent: "center",
            transform: collapsed ? undefined : "rotate(180deg)",
          }}
        >
          <Icon name="chev" size={13} />
        </span>
        {!collapsed && <span style={{ flex: 1 }}>Collapse</span>}
      </button>

      {/* The account footer — Settings, Admin and the profile block — sits
          under one full-width rule, the same line as the logo's, so the pair
          frames the rail top and bottom and the account cluster reads as split
          off from the main nav. Pinned: it never scrolls with the list above. */}
      <div
        data-sidenav-footer=""
        style={{
          display: "flex",
          flexDirection: "column",
          gap: NAV_GAP,
          flexShrink: 0,
          marginTop: 4,
          paddingTop: 10,
          borderTop: "1px solid var(--border)",
        }}
      >
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

      {/* The profile block carries no rule of its own — the footer's rule
          already opened this cluster, and a second hairline here would box the
          avatar in. */}
      {isAuthenticated && (
        <div style={{ padding: collapsed ? "10px 0 4px" : "10px 6px 4px" }}>
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
          </div>
        </div>
      )}
      </div>
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
        minHeight: NAV_ITEM_MIN_HEIGHT,
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

