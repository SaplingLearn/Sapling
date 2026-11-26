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
 *  - Right-side cluster contains settings, report, admin and account.
 */

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { ShellActions } from "./ShellActions";
import { SaplingWordmark } from "./SaplingWordmark";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import type { NavSection } from "@/lib/navFeatures";
import { useVisibleNavSections } from "@/lib/useNavSections";
import { STUDY_TOOL_PATHS } from "@/lib/toolHrefs";
import { cn } from "@/lib/cn";

type NavGroup = NavSection;

export const TOP_NAV_HEIGHT = 56;

function isActiveItem(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  // The Study tools are pages of their own; Study stays lit while you're in one.
  if (href === "/study" && STUDY_TOOL_PATHS.some(p => pathname === p || pathname.startsWith(p + "/"))) return true;
  return pathname === href || pathname.startsWith(href + "/");
}

function isActiveGroup(pathname: string, group: NavGroup): boolean {
  return group.items.some((item) => isActiveItem(pathname, item.href));
}

export function TopNav() {
  const pathname = usePathname() || "/";
  const { userName, avatarUrl, isAdmin, isAuthenticated } = useUser();
  const isMobile = useIsMobile();
  const groups = useVisibleNavSections();
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
      className={cn("h-14 min-h-14 bg-bg-topbar border-b border-b-border flex items-center sticky top-0 z-20", isMobile ? "gap-2" : "gap-5", isMobile ? "py-0 px-3" : "py-0 px-5")}
    >
      {/* Mobile hamburger */}
      {isMobile && (
        <div ref={mobileRef} className="relative">
          <button
            aria-label="Navigation menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((o) => !o)}
            className="p-1.5 flex flex-col justify-center gap-1 min-w-11 min-h-11 items-center"
          >
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className={cn("w-4.5 h-0.5 rounded-[1px] bg-text-dim [transition:transform_var(--dur-fast)_var(--ease),_opacity_var(--dur-fast)_var(--ease)]", mobileOpen && i === 1 ? "opacity-0" : "opacity-100")} style={{ transform:
                    mobileOpen && i === 0 ? "rotate(45deg) translateY(4px)" :
                    mobileOpen && i === 2 ? "rotate(-45deg) translateY(-4px)" : "none" }}
              />
            ))}
          </button>
          {mobileOpen && <MobilePanel pathname={pathname} groups={groups} />}
        </div>
      )}

      {/* Logo — the approved wordmark (#728). */}
      <Link href="/dashboard" aria-label="Sapling — home" className="flex items-center no-underline">
        <SaplingWordmark width={isMobile ? 88 : 104} decorative />
      </Link>

      {/* Desktop group row — hover/focus reveals each group's items */}
      {!isMobile && <DesktopGroups pathname={pathname} groups={groups} />}

      <div className={cn("flex items-center gap-2", isMobile ? "ml-auto" : "ml-0")}>
        {isAuthenticated && (
          <>
            <ShellActions />
            {isAdmin && (
              <Link
                href="/admin"
                aria-label="Admin"
                title="Admin"
                className={cn("inline-flex items-center justify-center w-11 h-11 rounded-sm [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease)]", pathname.startsWith("/admin") ? "text-text" : "text-text-muted")}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; e.currentTarget.style.color = "var(--text)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = pathname.startsWith("/admin") ? "var(--text)" : "var(--text-muted)"; }}
              >
                <Icon name="shield" size={16} />
              </Link>
            )}
            <div
              aria-label={userName || "Account"}
              title={userName || "Account"}
              className="flex items-center gap-2 p-[3px] rounded-[var(--r-full)]"
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
function DesktopGroups({ pathname, groups }: { pathname: string; groups: NavGroup[] }) {
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
    <div className="flex items-center gap-1 flex-1 min-w-0">
      {groups.map((g, i) => (
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
      className="relative"
    >
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => (open ? onClose() : onOpen())}
        onFocus={onOpen}
        className={cn("inline-flex items-center gap-1 py-1.5 px-2.5 rounded-sm text-md whitespace-nowrap [transition:color_var(--dur-fast)_var(--ease)] cursor-pointer bg-transparent border-0", active ? "font-bold" : "font-medium", active || open ? "text-text" : "text-text-muted")}
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
          className={cn("inline-flex [transition:transform_var(--dur-fast)_var(--ease)] text-current opacity-60 mt-px", open ? "[transform:rotate(180deg)]" : "[transform:rotate(90deg)]")}
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
          className="absolute top-full left-0 min-w-50 p-1.5 bg-bg-panel border border-border rounded-md shadow-md flex flex-col gap-0.5 z-100"
        >
          {group.items.map((item) => {
            const itemActive = isActiveItem(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn("flex items-center gap-2.5 py-2 px-2.5 rounded-sm text-md no-underline [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease)]", itemActive ? "bg-bg-soft" : "bg-transparent", itemActive ? "text-text" : "text-text-dim", itemActive ? "font-semibold" : "font-normal")}
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
                <span className="flex-1">{item.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MobilePanel({ pathname, groups }: { pathname: string; groups: NavGroup[] }) {
  return (
    <div
      className="absolute top-[calc(100%_+_6px)] left-0 min-w-60 py-1.5 px-0 bg-bg-panel border border-border rounded-md shadow-md z-100"
    >
      {groups.map((g, i) => (
        <React.Fragment key={g.label}>
          {i > 0 && <div className="h-px bg-border my-1.5 mx-2" aria-hidden />}
          <div
            className="label-micro pt-2 px-3.5 pb-1"
          >
            {g.label}
          </div>
          {g.items.map((item) => {
            const itemActive = isActiveItem(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn("flex items-center gap-2.5 py-2.5 px-3.5 min-h-11 box-border text-base no-underline [transition:background_var(--dur-fast)_var(--ease)]", itemActive ? "font-bold" : "font-medium", itemActive ? "text-text" : "text-text-dim")}
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
