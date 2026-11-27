"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { SaplingWordmark } from "./SaplingWordmark";
import { useUser } from "@/context/UserContext";
import { useRetentionDue } from "@/context/RetentionDueContext";
import type { NavItem } from "@/lib/navFeatures";
import { useVisibleNavSections } from "@/lib/useNavSections";
import { RETENTION_NAV_HREF, RetentionDueDot } from "./RetentionDueDot";
import { STUDY_TOOL_PATHS } from "@/lib/toolHrefs";
import styles from "./SideNav.module.css";
import { cn } from "@/lib/cn";

type Entry = NavItem;

export const SIDE_NAV_EXPANDED = 200;
export const SIDE_NAV_COLLAPSED = 64;
const COLLAPSE_KEY = "sapling_sidenav_collapsed";

/* Collapse/expand geometry.
 *
 * Each width keeps its own layout — wide rows run the full width of the rail
 * with the icon 12px inside the pill (so icons line up with the avatar);
 * narrow rows full-width with the icon centred — and the
 * rail animates BETWEEN them rather than snapping. The trick is that nothing
 * uses `justify-content: center` any more (it cannot be interpolated):
 * centring in the narrow rail is expressed as a computed left padding, so
 * margin and padding tween on the same curve and duration as the rail's
 * width and every icon glides from its wide position to the centre. */
const RAIL_PAD_X = { wide: 10, narrow: 6 };
const RAIL_INNER_NARROW = SIDE_NAV_COLLAPSED - 2 * RAIL_PAD_X.narrow;
const ICON_SIZE = 15;
/* Logo slot: the wordmark's height at 112px wide; the collapsed-rail symbol
   is drawn at that same height (its own aspect sets the width). */
const LOGO_SLOT_HEIGHT = 34;
const SAPLING_SYMBOL_SRC = "/design/sapling/originals/logo-symbol.svg";
const SYMBOL_WIDTH = Math.round(LOGO_SLOT_HEIGHT * (258.58 / 366.39));
const ROW = {
  wide: { inset: 0, padX: 12 },
  narrow: { inset: 0, padX: (RAIL_INNER_NARROW - ICON_SIZE) / 2 },
};
/* Wide-rail group header slot: space above the label, the label's line, and
   space below it before the first row. Kept tight so the groups read as one
   list with light dividers, not as separate blocks. */
const HEADER = { above: 12, line: 17, below: 6 };
/* Narrow-rail header slot: room for the group hairline (drawn at --sp-9,
   18px, in SideNav.module.css) with even space around it. */
const RULE_SLOT_HEIGHT = 29;
const ROW_PAD_Y = "var(--sp-3)";
/* The profile block's avatar, px; the narrow rail centres it like an icon. */
const AVATAR_SIZE = 30;
/* A fade in waits this beat (see `fade`); a fade out never waits. */
const FADE_IN_DELAY = "var(--dur-instant)";
const NO_DELAY = "0s";

function rowGeometry(collapsed: boolean, padX = (collapsed ? ROW.narrow : ROW.wide).padX): React.CSSProperties {
  const r = collapsed ? ROW.narrow : ROW.wide;
  return {
    marginLeft: r.inset,
    marginRight: r.inset,
    paddingTop: ROW_PAD_Y,
    paddingBottom: ROW_PAD_Y,
    paddingLeft: padX,
    paddingRight: padX,
  };
}

/* Text fades rather than mounting/unmounting. Out: immediately and quickly,
   so nothing is visibly squeezed as the rail narrows. In: a beat late, so the
   label arrives once there is room for it. */
function fade(collapsed: boolean): React.CSSProperties {
  return {
    opacity: collapsed ? 0 : 1,
    whiteSpace: "nowrap",
    transition: `opacity var(--dur-fast) var(--ease) ${collapsed ? NO_DELAY : FADE_IN_DELAY}`,
  };
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  // The Study tools are pages of their own; Study stays lit while you're in one.
  if (href === "/study" && STUDY_TOOL_PATHS.some(p => pathname === p || pathname.startsWith(p + "/"))) return true;
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

/* On the Tutor the rail gives its width to the chat: it shows as the narrow
   icon rail whatever the stored preference, and opens over the page (no
   layout shift) while the pointer is on it or focus is inside it. Arriving
   at the Tutor closes it at once, even with the pointer still on the rail. */
function useTutorPeek(onTutor: boolean) {
  const [peek, setPeek] = React.useState(false);
  React.useEffect(() => { if (!onTutor) setPeek(false); }, [onTutor]);
  const handlers = onTutor
    ? {
        onMouseEnter: () => setPeek(true),
        onMouseLeave: () => setPeek(false),
        onFocus: () => setPeek(true),
        onBlur: (e: React.FocusEvent<HTMLElement>) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setPeek(false);
        },
        onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
          if (e.key === "Escape") { setPeek(false); (document.activeElement as HTMLElement | null)?.blur(); }
        },
      }
    : {};
  return { peek: onTutor && peek, handlers, close: () => setPeek(false) };
}

export function SideNav() {
  const pathname = usePathname() || "/";
  const { userName, avatarUrl, isAdmin, isAuthenticated } = useUser();
  const [storedCollapsed, setCollapsed] = useCollapsed();
  const onTutor = isActive(pathname, "/learn");
  const { peek, handlers: peekHandlers } = useTutorPeek(onTutor);
  const collapsed = onTutor ? !peek : storedCollapsed;
  const sections = useVisibleNavSections();
  const { due: retentionDue } = useRetentionDue();
  const settingsActive = isActive(pathname, "/settings");

  const width = collapsed ? SIDE_NAV_COLLAPSED : SIDE_NAV_EXPANDED;

  const rail = (
    <aside
      role="navigation"
      aria-label="Primary"
      // Hook for the pre-hydration mobile guard in globals.css (#110).
      data-app-sidenav=""
      data-peek={peek}
      className={cn(`${styles.rail} ${onTutor ? styles.railFloating : styles.railInFlow}`, "pt-(--sp-8) pb-(--sp-8)")}
      style={{ width, minWidth: width, paddingLeft: collapsed ? RAIL_PAD_X.narrow : RAIL_PAD_X.wide, paddingRight: collapsed ? RAIL_PAD_X.narrow : RAIL_PAD_X.wide }}
    >
      {/* Wide: the wordmark. Narrow: the Sapling symbol, centred. The two
          cross-fade in one fixed-height slot so nothing below shifts, and the
          link stays a live home link in both widths. */}
      <Link
        href="/dashboard"
        aria-label="Sapling — home"
        data-sidenav-logo=""
        className={styles.logo}
        style={{ height: LOGO_SLOT_HEIGHT }}
      >
        <SaplingWordmark
          width={112}
          decorative
          tone="light"
          className={styles.wordmark}
          style={fade(collapsed)}
        />
        <img
          src={SAPLING_SYMBOL_SRC}
          alt=""
          aria-hidden
          data-sidenav-symbol=""
          width={SYMBOL_WIDTH}
          height={LOGO_SLOT_HEIGHT}
          draggable={false}
          className={cn(styles.symbol, collapsed ? "opacity-100" : "opacity-0")}
          style={{ left: (RAIL_INNER_NARROW - SYMBOL_WIDTH) / 2, width: SYMBOL_WIDTH, height: LOGO_SLOT_HEIGHT, transition: `opacity var(--dur-fast) var(--ease) ${collapsed ? FADE_IN_DELAY : NO_DELAY}` }}
        />
      </Link>

      {/* The destinations scroll on their own when the viewport is too short
          for them, scrollbar hidden (SideNav.module.css `.scroll`). */}
      <div data-sidenav-scroll="" className={styles.scroll}>
      {sections.map((section, i) => (
        <React.Fragment key={section.label}>
          {/* Header slot. Wide: the group label. Narrow: a hairline (none
              above the first group — the logo rule already does that job).
              The slot's height tweens between the two so the rows below
              slide rather than jump, and label/hairline cross-fade.
              Spacing lives in HEADER. */}
          <div
            aria-hidden={collapsed || undefined}
            className={styles.header}
            style={{
              height: collapsed ? (i === 0 ? 0 : RULE_SLOT_HEIGHT) : HEADER.above + HEADER.line + HEADER.below,
            }}
          >
            <div
              className={cn(`label-micro ${styles.groupLabel}`, "bottom-1.5 leading-[17px]")}
              style={{ ...fade(collapsed) }}
            >
              {section.label}
            </div>
            {i > 0 && (
              <div
                data-sidenav-group-rule=""
                aria-hidden
                className={cn(styles.groupRule, collapsed ? "opacity-100" : "opacity-0")}
              />
            )}
          </div>
          {section.items.map(item => (
            <NavLink
              key={item.href}
              entry={item}
              active={isActive(pathname, item.href)}
              collapsed={collapsed}
              retentionDue={retentionDue && item.href === RETENTION_NAV_HREF}
            />
          ))}
        </React.Fragment>
      ))}

      </div>

      {/* The account footer — Collapse, Admin and the profile block — sits
          under one full-width rule, the same line as the logo's, so the pair
          frames the rail top and bottom and the account cluster reads as split
          off from the main nav. Pinned: it never scrolls with the list above. */}
      <div data-sidenav-footer="" className={styles.footer}>
      {/* Collapse/expand opens the footer, just under its rule and above the
          account block, and is built like a nav row: panel icon + "Collapse" in the wide rail, the
          bare icon in the narrow one — the usual sidebar toggle.
          Same insets, padding and row height as NavLink so it lines up with
          the destinations above it. */}
      {!onTutor && <button
        type="button"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : undefined}
        onClick={() => setCollapsed(!collapsed)}
        className={cn(styles.row, "min-h-9.5")}
        style={{ ...rowGeometry(collapsed) }}
      >
        <PanelToggleIcon collapsed={collapsed} />
        <span aria-hidden className={styles.label} style={fade(collapsed)}>Collapse</span>
      </button>}

      {isAdmin && (
        <NavLink
          entry={{ href: "/admin", label: "Admin", icon: "shield" }}
          active={isActive(pathname, "/admin")}
          collapsed={collapsed}
        />
      )}

      {/* The profile block carries no rule of its own — the footer's rule
          already opened this cluster, and a second hairline here would box the
          avatar in. The whole block is the Settings button: avatar + name +
          a trailing gear, one link to /settings. */}
      {isAuthenticated && (
        <div className={styles.profile}>
          <div className={styles.profileRow}>
            <Link
              href="/settings"
              data-testid="nav-link-settings"
              aria-label="Settings"
              aria-current={settingsActive ? "page" : undefined}
              title={collapsed ? "Settings" : undefined}
              data-active={settingsActive}
              className={`${styles.row} ${styles.settings}`}
              // Wide: 12px in. Narrow: centred (computed, so it tweens).
              style={rowGeometry(collapsed, collapsed ? (RAIL_INNER_NARROW - AVATAR_SIZE) / 2 : ROW.wide.padX)}
            >
              <Avatar name={userName || "?"} size={AVATAR_SIZE} img={avatarUrl || undefined} />
                <div aria-hidden={collapsed || undefined} className={styles.who} style={fade(collapsed)}>
                  <div className={styles.userName}>
                    {userName || "You"}
                  </div>
                  <div className={styles.userSub}>Account</div>
                </div>
                <span aria-hidden className={styles.gear} style={fade(collapsed)}>
                  <Icon name="setting" size={ICON_SIZE} />
                </span>
            </Link>
          </div>
        </div>
      )}
      </div>
    </aside>
  );

  if (!onTutor) return rail;
  // A fixed 64px slot keeps the page where it is while the rail opens over it.
  return (
    <div
      data-app-sidenav-slot=""
      {...peekHandlers}
      className={styles.slot}
      style={{ width: SIDE_NAV_COLLAPSED, minWidth: SIDE_NAV_COLLAPSED }}
    >
      {rail}
    </div>
  );
}

function NavLink({ entry, active, collapsed, retentionDue = false }: {
  entry: Entry; active: boolean; collapsed: boolean; retentionDue?: boolean;
}) {
  const label = retentionDue ? `${entry.label}, retention check due` : entry.label;
  return (
    <Link
      href={entry.href}
      data-testid={`nav-link-${entry.href.slice(1)}`}
      title={collapsed ? label : undefined}
      aria-label={collapsed || retentionDue ? label : undefined}
      data-active={active}
      className={cn(styles.row, "min-h-9.5")}
      style={{ ...rowGeometry(collapsed) }}
    >
      {/* A126: the dot rides the icon, so the narrow rail shows it too. */}
      <span className={styles.iconWrap}>
        <Icon name={entry.icon} size={ICON_SIZE} />
        {retentionDue && <RetentionDueDot testid="nav-retention-due" overlay />}
      </span>
      <span aria-hidden={collapsed || undefined} className={styles.label} style={fade(collapsed)}>
        {entry.label}
      </span>
    </Link>
  );
}

/* The sidebar-toggle glyph: a panel with its left column ruled off and a
   chevron in the open area. Only the chevron moves — it points in (close)
   when the rail is wide and flips to point out (open) when narrow, turning
   about its own centre on the rail's duration so it animates with the
   collapse (SideNav.module.css). Stroke weight and caps match `Icon`. */
function PanelToggleIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      data-collapsed={collapsed}
      className={styles.toggleIcon}
    >
      <rect x="3" y="3" width="18" height="18" rx="2.5" />
      <path d="M9 3v18" />
      <path d="M16 9l-3 3 3 3" className={styles.toggleChevron} />
    </svg>
  );
}
