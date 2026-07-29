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
              padding: 6, display: "flex", flexDirection: "column", justifyContent: "center", gap: 4,
              minWidth: 44, minHeight: 44, alignItems: "center",
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
              color: "var(--brand-forest)",
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
      {!isMobile && <DesktopGroups pathname={pathname} />}

      <div style={{ marginLeft: isMobile ? "auto" : 0, display: "flex", alignItems: "center", gap: 8 }}>
        {isAuthenticated && (
          <>
            <Link
              href="/settings"
              aria-label="Settings"
              title="Settings"
              style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 44, height: 44, borderRadius: "var(--r-sm)",
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
                  width: 44, height: 44, borderRadius: "var(--r-sm)",
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
 * DesktopGroups — the horizontal row of group triggers.
 *
 * Owns a SINGLE `openIndex` for the whole row so that at most one group
 * panel is ever open. This is the fix for #320: previously each trigger
 * kept its own open-state and its own close-timer, so moving the cursor
 * from tab A to tab B cancelled only B's timer — A's 140ms timer kept
 * A's panel open, briefly showing two panels at once and leaving the
 * old one lingering. With a shared owner, entering any tab immediately
 * preempts whichever tab was open (openIndex is replaced synchronously),
 * so switching tabs closes the old panel with no delay.
 *
 * The 140ms close-delay is retained but now only applies when the cursor
 * leaves the row entirely (to empty space) — its original purpose: the
 * trigger and panel touch, but a bare 0px gap can still flicker on
 * sub-pixel cursor moves, so the delay tolerates jitter as the cursor
 * travels from label to item.
 */
function DesktopGroups({ pathname }: { pathname: string }) {
  const [openIndex, setOpenIndex] = React.useState<number | null>(null);
  const closeTimer = React.useRef<number | null>(null);

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  // Open a specific group, pre-empting any other open group and any
  // pending close. Because this replaces openIndex synchronously, the
  // previously-open panel closes the instant the cursor reaches a new
  // tab — no two panels can coexist.
  const openGroup = (i: number) => {
    cancelClose();
    setOpenIndex(i);
  };
  const closeNow = () => {
    cancelClose();
    setOpenIndex(null);
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpenIndex(null), 140);
  };

  // Cancel any pending close-timer on unmount (e.g. route change while
  // the dropdown is closing). Avoids a stray setState after unmount.
  React.useEffect(() => cancelClose, []);

  // Close when route changes (navigation triggered).
  React.useEffect(() => {
    closeNow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Click outside the row / Escape closes the open panel.
  React.useEffect(() => {
    if (openIndex === null) return;
    const onClick = (e: MouseEvent) => {
      // "Outside" means outside every trigger wrapper (+ its panel), NOT
      // outside rowRef: the row is flex:1 and stretches across the header's
      // blank strip, so a row-bounds check would swallow clicks in that dead
      // space and leave a keyboard-opened panel (no hover timer armed) stuck.
      const target = e.target as Element | null;
      if (!target?.closest?.("[data-nav-group]")) closeNow();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeNow();
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openIndex]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, flex: 1, minWidth: 0 }}>
      {GROUPS.map((g, i) => (
        <NavGroupTrigger
          key={g.label}
          group={g}
          pathname={pathname}
          open={openIndex === i}
          onOpen={() => openGroup(i)}
          onScheduleClose={scheduleClose}
          onClose={closeNow}
        />
      ))}
    </div>
  );
}

/**
 * NavGroupTrigger — one of the four top-level group buttons.
 *
 * Presentational + interaction only; the open-state lives in the parent
 * DesktopGroups so the row can enforce "at most one panel open" (#320).
 * Hover/focus asks the parent to open this group; mouse-leave asks it to
 * schedule a close; focus leaving the wrapper closes immediately.
 */
function NavGroupTrigger({
  group,
  pathname,
  open,
  onOpen,
  onScheduleClose,
  onClose,
}: {
  group: NavGroup;
  pathname: string;
  open: boolean;
  onOpen: () => void;
  onScheduleClose: () => void;
  onClose: () => void;
}) {
  const active = isActiveGroup(pathname, group);
  const wrapperRef = React.useRef<HTMLDivElement | null>(null);

  return (
    <div
      ref={wrapperRef}
      data-nav-group
      onMouseEnter={onOpen}
      onMouseLeave={onScheduleClose}
      // Symmetric counterpart to onFocus opening the panel: when focus
      // leaves the wrapper entirely (Tab past the last item), close.
      // relatedTarget can be null when focus jumps to a non-focusable
      // surface or to another window — treat that as leaving too.
      onBlur={(e) => {
        const next = e.relatedTarget as Node | null;
        if (!wrapperRef.current || !next || !wrapperRef.current.contains(next)) {
          onClose();
        }
      }}
      style={{ position: "relative" }}
    >
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => (open ? onClose() : onOpen())}
        onFocus={onOpen}
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
                  padding: "10px 14px", minHeight: 44, boxSizing: "border-box",
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
