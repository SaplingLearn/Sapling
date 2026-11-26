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
import { RETENTION_NAV_HREF, RetentionDueDot } from "./RetentionDueDot";
import { useUser } from "@/context/UserContext";
import { useRetentionNavDue } from "./useRetentionNav";
import { useIsMobile } from "@/lib/useIsMobile";
import type { NavSection } from "@/lib/navFeatures";
import { useVisibleNavSections } from "@/lib/useNavSections";
import { STUDY_TOOL_PATHS } from "@/lib/toolHrefs";
import styles from "./TopNav.module.css";

type NavGroup = NavSection;

/** The bar's height, px: `--sp-28`, which TopNav.module.css sets it to. */
export const TOP_NAV_HEIGHT = 56;
/** How long a hovered group's panel stays open after the cursor leaves the row, ms. */
const HOVER_CLOSE_DELAY_MS = 140;
/** The wordmark's rendered width, px, by layout. */
const WORDMARK_WIDTH = { mobile: 88, desktop: 104 } as const;

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
  // hide_study hides the check's page: the closed menu then carries no dot
  const { due: retentionDue } = useRetentionNavDue();
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
      className={isMobile ? `${styles.nav} ${styles.navMobile}` : styles.nav}
    >
      {/* Mobile hamburger */}
      {isMobile && (
        <div ref={mobileRef} className={styles.menuWrap}>
          <button
            aria-label={retentionDue ? "Navigation menu, retention check due" : "Navigation menu"}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((o) => !o)}
            className={styles.burger}
          >
            {/* A126: the closed menu hides the Study row, so the button carries the dot */}
            {retentionDue && !mobileOpen && <RetentionDueDot testid="topnav-menu-retention-due" overlay />}
            {/* Three bars that cross into an X while open (aria-expanded). */}
            {[styles.barTop, styles.barMid, styles.barBottom].map((bar, i) => (
              <span key={i} className={`${styles.burgerBar} ${bar}`} />
            ))}
          </button>
          {mobileOpen && <MobilePanel pathname={pathname} groups={groups} />}
        </div>
      )}

      {/* Logo — the approved wordmark (#728). */}
      <Link href="/dashboard" aria-label="Sapling — home" className={styles.logo}>
        <SaplingWordmark width={isMobile ? WORDMARK_WIDTH.mobile : WORDMARK_WIDTH.desktop} decorative />
      </Link>

      {/* Desktop group row — hover/focus reveals each group's items */}
      {!isMobile && <DesktopGroups pathname={pathname} groups={groups} />}

      <div className={isMobile ? `${styles.right} ${styles.rightMobile}` : styles.right}>
        {isAuthenticated && (
          <>
            <ShellActions />
            {isAdmin && (
              <Link
                href="/admin"
                aria-label="Admin"
                title="Admin"
                data-active={pathname.startsWith("/admin")}
                className={styles.admin}
              >
                <Icon name="shield" size={16} />
              </Link>
            )}
            <div
              aria-label={userName || "Account"}
              title={userName || "Account"}
              className={styles.account}
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
    closeTimer.current = window.setTimeout(() => setOpenIndex(null), HOVER_CLOSE_DELAY_MS);
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
    <div className={styles.groups}>
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
  // A126: the Study row hides in the panel, so its group's trigger carries the dot
  const { due: retentionDue } = useRetentionNavDue();
  const groupDue = retentionDue && group.items.some((item) => item.href === RETENTION_NAV_HREF);

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
      className={styles.groupWrap}
    >
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => (open ? onClose() : onOpen())}
        onFocus={onOpen}
        data-active={active}
        className={styles.trigger}
      >
        {group.label}
        {groupDue && <RetentionDueDot testid="topnav-group-retention-due" />}
        <span aria-hidden className={styles.chev}>
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
          className={styles.panel}
        >
          {group.items.map((item) => {
            const itemActive = isActiveItem(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                data-active={itemActive}
                className={styles.item}
              >
                <Icon name={item.icon} size={15} />
                <span className={styles.itemLabel}>{item.label}</span>
                {groupDue && item.href === RETENTION_NAV_HREF && (
                  <RetentionDueDot testid="topnav-retention-due" />
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MobilePanel({ pathname, groups }: { pathname: string; groups: NavGroup[] }) {
  const { due: retentionDue } = useRetentionNavDue();
  return (
    <div className={styles.mobilePanel}>
      {groups.map((g, i) => (
        <React.Fragment key={g.label}>
          {i > 0 && <div className={styles.divider} aria-hidden />}
          <div className={`label-micro ${styles.mobileHeading}`}>
            {g.label}
          </div>
          {g.items.map((item) => {
            const itemActive = isActiveItem(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                data-active={itemActive}
                className={styles.mobileItem}
              >
                <Icon name={item.icon} size={15} />
                {item.label}
                {retentionDue && item.href === RETENTION_NAV_HREF && (
                  <RetentionDueDot testid="topnav-mobile-retention-due" />
                )}
              </Link>
            );
          })}
        </React.Fragment>
      ))}
    </div>
  );
}
