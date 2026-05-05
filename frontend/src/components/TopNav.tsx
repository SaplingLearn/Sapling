"use client";

/**
 * Sapling top navigation.
 *
 * Replaces the vertical Sidebar with a minimal 56px sticky top bar —
 * matches the pre-revamp Navbar pattern. Top-level entries are grouped
 * (Learn / Organize / Community / Tools) and reveal sub-items on hover,
 * mirroring the SideNav's section structure but in horizontal form.
 *
 * Design decisions:
 *  - Group labels in the bar; hover/focus opens a small panel with the
 *    section's icon+label rows (same shape as SideNav rows so the two
 *    shells feel related, not parallel).
 *  - Active state on a GROUP = any child route matches. The group
 *    label goes weight 700 + `var(--text)`; inactive groups are dimmed.
 *  - Hover open is forgiving: a short close-delay (140ms) gives the
 *    cursor time to bridge from trigger to panel without flicker.
 *  - Click on a group label is also valid (keyboard / touch parity).
 *  - Mobile (≤768px) collapses everything into a hamburger that drops a
 *    panel grouped the same way.
 *  - Right-side cluster (settings / admin / avatar) unchanged.
 */

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";

type NavItem = { href: string; label: string; icon: string };
type NavGroup = { label: string; items: NavItem[] };

// Mirrors SideNav's SECTIONS verbatim. Kept duplicated rather than
// imported so the two shells stay independent — TopNav and SideNav are
// alternative skins, not parent/child, and the routing data is small
// enough that the duplication isn't a maintenance burden.
const GROUPS: NavGroup[] = [
  {
    label: "Learn",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "home"  },
      { href: "/learn",     label: "Tutor",     icon: "brain" },
      { href: "/quiz",      label: "Quiz",      icon: "flask" },
      { href: "/tree",      label: "Tree",      icon: "tree"  },
      { href: "/study",     label: "Study",     icon: "bolt"  },
    ],
  },
  {
    label: "Organize",
    items: [
      { href: "/library",  label: "Library",  icon: "book" },
      { href: "/calendar", label: "Calendar", icon: "cal"  },
    ],
  },
  {
    label: "Community",
    items: [
      { href: "/social",       label: "Social",       icon: "users"  },
      { href: "/achievements", label: "Achievements", icon: "trophy" },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/gradebook",      label: "Grades",         icon: "star"    },
      { href: "/notetaker",      label: "Notetaker",      icon: "pencil"  },
      { href: "/course-planner", label: "Course Planner", icon: "planner" },
    ],
  },
];

export const TOP_NAV_HEIGHT = 56;

function isActiveItem(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  return pathname === href || pathname.startsWith(href + "/");
}

function isActiveGroup(pathname: string, group: NavGroup): boolean {
  return group.items.some((item) => isActiveItem(pathname, item.href));
}

export function TopNav() {
  const pathname = usePathname() || "/";
  const { userName, avatarUrl, isAdmin, isAuthenticated } = useUser();
  const isMobile = useIsMobile();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const mobileRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (mobileRef.current && !mobileRef.current.contains(e.target as Node)) setMobileOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <nav
      role="navigation"
      aria-label="Primary"
      style={{
        height: TOP_NAV_HEIGHT,
        minHeight: TOP_NAV_HEIGHT,
        // --bg-topbar from the pre-revamp palette is a deliberately
        // greener tint than --bg-subtle so the nav reads as its own
        // surface without needing a border or shadow to announce it.
        background: "var(--bg-topbar)",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: isMobile ? 8 : 20,
        padding: isMobile ? "0 12px" : "0 20px",
        position: "sticky",
        top: 0,
        zIndex: 20,
      }}
    >
      {/* Mobile hamburger */}
      {isMobile && (
        <div ref={mobileRef} style={{ position: "relative" }}>
          <button
            aria-label="Navigation menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((o) => !o)}
            style={{
              padding: 6, display: "flex", flexDirection: "column", gap: 4,
              width: 28, alignItems: "center",
            }}
          >
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{
                  width: 18, height: 2, borderRadius: 1,
                  background: "var(--text-dim)",
                  transition: "transform var(--dur-fast) var(--ease), opacity var(--dur-fast) var(--ease)",
                  transform:
                    mobileOpen && i === 0 ? "rotate(45deg) translateY(4px)" :
                    mobileOpen && i === 2 ? "rotate(-45deg) translateY(-4px)" : "none",
                  opacity: mobileOpen && i === 1 ? 0 : 1,
                }}
              />
            ))}
          </button>
          {mobileOpen && <MobilePanel pathname={pathname} />}
        </div>
      )}

      {/* Logo — ported verbatim from the pre-revamp Navbar
          (main@929658f:frontend/src/components/Navbar.tsx:213-231):
          /sapling-icon.svg + Spectral "Sapling" with a soft green
          text-shadow. */}
      <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: "2px", textDecoration: "none" }}>
        <img
          src="/sapling-icon.svg"
          alt="Sapling"
          style={{
            width: "32px",
            height: "32px",
            marginTop: "-7px",
            marginBottom: "-3px",
            marginLeft: "-2px",
            marginRight: "-4px",
            alignSelf: "center",
            flexShrink: 0,
          }}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: "1px", alignItems: "center", textAlign: "center" }}>
          <span
            style={{
              fontFamily: "'Spectral', Georgia, serif",
              fontWeight: 700,
              fontSize: isMobile ? "17px" : "20px",
              color: "#1a5c2a",
              letterSpacing: "-0.02em",
              textShadow: "0 0 12px rgba(26, 92, 42, 0.2)",
              lineHeight: 1.1,
            }}
          >
            Sapling
          </span>
        </div>
      </Link>

      {/* Desktop group row — hover/focus reveals each group's items */}
      {!isMobile && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, flex: 1, minWidth: 0 }}>
          {GROUPS.map((g) => (
            <NavGroupTrigger key={g.label} group={g} pathname={pathname} />
          ))}
        </div>
      )}

      <div style={{ marginLeft: isMobile ? "auto" : 0, display: "flex", alignItems: "center", gap: 8 }}>
        {isAuthenticated && (
          <>
            <Link
              href="/settings"
              aria-label="Settings"
              title="Settings"
              style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 32, height: 32, borderRadius: "var(--r-sm)",
                color: pathname.startsWith("/settings") ? "var(--text)" : "var(--text-muted)",
                transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; e.currentTarget.style.color = "var(--text)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = pathname.startsWith("/settings") ? "var(--text)" : "var(--text-muted)"; }}
            >
              <Icon name="cog" size={16} />
            </Link>
            {isAdmin && (
              <Link
                href="/admin"
                aria-label="Admin"
                title="Admin"
                style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 32, height: 32, borderRadius: "var(--r-sm)",
                  color: pathname.startsWith("/admin") ? "var(--text)" : "var(--text-muted)",
                  transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; e.currentTarget.style.color = "var(--text)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = pathname.startsWith("/admin") ? "var(--text)" : "var(--text-muted)"; }}
              >
                <Icon name="shield" size={16} />
              </Link>
            )}
            <div
              aria-label={userName || "Account"}
              title={userName || "Account"}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: 3, borderRadius: "var(--r-full)",
              }}
            >
              <Avatar name={userName || "?"} size={30} img={avatarUrl || undefined} />
            </div>
          </>
        )}
      </div>
    </nav>
  );
}

/**
 * NavGroupTrigger — one of the four top-level group buttons.
 *
 * Hover (or focus) opens a panel anchored to the trigger; mouse-leave
 * with a short delay closes it. The delay (140ms) is deliberate: the
 * trigger and panel touch but a bare 0px gap can still flicker on
 * sub-pixel cursor moves, so we let the close animation tolerate
 * cursor jitter while the user travels from label to item.
 */
function NavGroupTrigger({ group, pathname }: { group: NavGroup; pathname: string }) {
  const active = isActiveGroup(pathname, group);
  const [open, setOpen] = React.useState(false);
  const closeTimer = React.useRef<number | null>(null);
  const wrapperRef = React.useRef<HTMLDivElement | null>(null);

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), 140);
  };

  // Cancel any pending close-timer if this component unmounts mid-flight
  // (e.g. route change while the dropdown is closing). Avoids a stray
  // setState on an unmounted component.
  React.useEffect(() => {
    return () => cancelClose();
  }, []);

  // Close when route changes (navigation triggered).
  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Click outside / Escape closes.
  React.useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div
      ref={wrapperRef}
      onMouseEnter={() => { cancelClose(); setOpen(true); }}
      onMouseLeave={scheduleClose}
      // Symmetric counterpart to onFocus opening the panel: when focus
      // leaves the wrapper entirely (Tab past the last item), close.
      // relatedTarget can be null when focus jumps to a non-focusable
      // surface or to another window — treat that as leaving too.
      onBlur={(e) => {
        const next = e.relatedTarget as Node | null;
        if (!wrapperRef.current || !next || !wrapperRef.current.contains(next)) {
          setOpen(false);
        }
      }}
      style={{ position: "relative" }}
    >
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onFocus={() => { cancelClose(); setOpen(true); }}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "6px 10px",
          borderRadius: "var(--r-sm)",
          fontSize: 13,
          fontWeight: active ? 700 : 500,
          color: active || open ? "var(--text)" : "var(--text-muted)",
          whiteSpace: "nowrap",
          transition: "color var(--dur-fast) var(--ease)",
          cursor: "pointer",
          background: "transparent",
          border: "none",
        }}
        onMouseEnter={(e) => {
          if (!active) e.currentTarget.style.color = "var(--text-dim)";
        }}
        onMouseLeave={(e) => {
          if (!active && !open) e.currentTarget.style.color = "var(--text-muted)";
        }}
      >
        {group.label}
        <span
          aria-hidden
          style={{
            display: "inline-flex",
            transition: "transform var(--dur-fast) var(--ease)",
            transform: open ? "rotate(180deg)" : "rotate(90deg)",
            color: "currentColor",
            opacity: 0.6,
            marginTop: 1,
          }}
        >
          <Icon name="chev" size={10} />
        </span>
      </button>

      {open && (
        <div
          aria-label={group.label}
          // Panel touches the trigger's bottom edge (no marginTop) so
          // cursor traversal stays within the wrapper's mouse-event
          // bounds. The 140ms close-delay is a separate forgiveness
          // mechanism; together they make the hover handoff reliable.
          //
          // No `role="menu"` here — that ARIA role implies arrow-key
          // navigation between items, which we don't implement. Linear
          // tab order through Links is the actual UX, so we leave the
          // semantics as "nav with links" rather than over-claim.
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            minWidth: 200,
            padding: 6,
            background: "var(--bg-panel)",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-md)",
            boxShadow: "var(--shadow-md)",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            zIndex: 100,
          }}
        >
          {group.items.map((item) => {
            const itemActive = isActiveItem(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: "var(--r-sm)",
                  background: itemActive ? "var(--bg-soft)" : "transparent",
                  color: itemActive ? "var(--text)" : "var(--text-dim)",
                  fontSize: 13,
                  fontWeight: itemActive ? 600 : 400,
                  textDecoration: "none",
                  transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-soft)";
                  e.currentTarget.style.color = "var(--text)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = itemActive ? "var(--bg-soft)" : "transparent";
                  e.currentTarget.style.color = itemActive ? "var(--text)" : "var(--text-dim)";
                }}
              >
                <Icon name={item.icon} size={15} />
                <span style={{ flex: 1 }}>{item.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MobilePanel({ pathname }: { pathname: string }) {
  return (
    <div
      style={{
        position: "absolute", top: "calc(100% + 6px)", left: 0,
        minWidth: 240, padding: "6px 0",
        background: "var(--bg-panel)", border: "1px solid var(--border)",
        borderRadius: "var(--r-md)", boxShadow: "var(--shadow-md)",
        zIndex: 100,
      }}
    >
      {GROUPS.map((g, i) => (
        <React.Fragment key={g.label}>
          {i > 0 && <div style={{ height: 1, background: "var(--border)", margin: "6px 8px" }} aria-hidden />}
          <div
            className="label-micro"
            style={{ padding: "8px 14px 4px" }}
          >
            {g.label}
          </div>
          {g.items.map((item) => {
            const itemActive = isActiveItem(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px",
                  fontSize: 14, fontWeight: itemActive ? 700 : 500,
                  color: itemActive ? "var(--text)" : "var(--text-dim)",
                  textDecoration: "none",
                  transition: "background var(--dur-fast) var(--ease)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                <Icon name={item.icon} size={15} />
                {item.label}
              </Link>
            );
          })}
        </React.Fragment>
      ))}
    </div>
  );
}
