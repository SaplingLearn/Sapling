"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { SaplingWordmark } from "./SaplingWordmark";
import { useUser } from "@/context/UserContext";
import type { NavItem } from "@/lib/navFeatures";
import { useVisibleNavSections } from "@/lib/useNavSections";

type Entry = NavItem;

export const SIDE_NAV_EXPANDED = 200;
export const SIDE_NAV_COLLAPSED = 64;
const COLLAPSE_KEY = "sapling_sidenav_collapsed";

/* Palette and geometry follow the "Sapling Sidebar" handoff design
   (rounded tabs, dark text on the light sage rail). The rail's token block
   in globals.css ([data-app-sidenav]) re-declares --text/--border/--accent
   for anything nested that still reads shell tokens (focus ring, Avatar). */
export const SIDENAV = {
  bg: "#DCE8CE",
  hoverBg: "#EBF0E1",
  activeBg: "#C9DCB2",
  activeRing: "inset 0 0 0 1px rgba(68,93,34,0.28), 0 1px 2px rgba(25,37,11,0.08)",
  heading: "#4A5A38",
  divider: "rgba(74,90,56,0.22)",
  icon: "#416207",
  iconHover: "#597536",
  label: "#3f3b31",
  labelHover: "#1a1814",
  labelActive: "#1a1814",
  shadow: "0 0 0 1px rgba(74,90,56,0.06), 6px 0 24px -6px rgba(25,37,11,0.10)",
} as const;

/* Row rhythm from the design: 47px rows, 16px labels, 20px glyphs, 4px
   between rows. Never take NAV_ITEM_MIN_HEIGHT below 36. */
const NAV_ITEM_MIN_HEIGHT = 47;
const NAV_GAP = 4;
const ICON_SIZE = 20;
const ROW_RADIUS = 10;

/* Collapse/expand geometry. Wide rows sit 10px in from the rail edge with
   the glyph 12px inside the pill; narrow rows keep a 6px inset and centre the
   glyph with a computed left padding, so margin and padding tween on the same
   curve as the rail's width and every icon glides to the centre. */
const ROW = {
  wide: { inset: 10, padX: 12 },
  narrow: { inset: 6, padX: (SIDE_NAV_COLLAPSED - 2 * 6 - ICON_SIZE) / 2 },
};
const LOGO_SLOT_HEIGHT = 34;
const SAPLING_SYMBOL_SRC = "/design/sapling/originals/logo-symbol.svg";
const SYMBOL_WIDTH = Math.round(LOGO_SLOT_HEIGHT * (258.58 / 366.39));
/* Group header slot: 32px tall, label 6px off its bottom, 20px from the rail edge. */
const HEADER = { height: 32, below: 6, line: 14, left: 20 };

const GEOMETRY_TRANSITION =
  "margin var(--dur) var(--ease), padding var(--dur) var(--ease), height var(--dur) var(--ease)";

function rowGeometry(collapsed: boolean): React.CSSProperties {
  const r = collapsed ? ROW.narrow : ROW.wide;
  return {
    marginLeft: r.inset,
    marginRight: r.inset,
    padding: `6px ${r.padX}px`,
    overflow: "hidden",
  };
}

/* Text fades rather than mounting/unmounting: out at once, in a beat late. */
function fade(collapsed: boolean): React.CSSProperties {
  return {
    opacity: collapsed ? 0 : 1,
    whiteSpace: "nowrap",
    transition: `opacity var(--dur-fast) var(--ease) ${collapsed ? "0ms" : "90ms"}`,
  };
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  if (href === "/study" && (pathname === "/quiz" || pathname.startsWith("/quiz/"))) return true;
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

/* Shared row surface: hover is a lighter sage, active a deeper sage with a
   hairline ring. Hover is handled in React state (not by mutating style) so
   the label and glyph colours change together. */
function rowSurface(active: boolean, hover: boolean): React.CSSProperties {
  return {
    background: active ? SIDENAV.activeBg : hover ? SIDENAV.hoverBg : "transparent",
    boxShadow: active ? SIDENAV.activeRing : "none",
    color: active ? SIDENAV.labelActive : hover ? SIDENAV.labelHover : SIDENAV.label,
  };
}

export function SideNav() {
  const pathname = usePathname() || "/";
  const { userName, avatarUrl, isAdmin, isAuthenticated } = useUser();
  const [collapsed, setCollapsed] = useCollapsed();
  const [collapseHover, setCollapseHover] = React.useState(false);
  const sections = useVisibleNavSections();

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
        height: "100%",
        background: SIDENAV.bg,
        borderRadius: "0 36px 36px 0",
        // Progressive: squircle corners where supported, round elsewhere.
        ...({ cornerShape: "squircle" } as React.CSSProperties),
        boxShadow: SIDENAV.shadow,
        position: "relative",
        zIndex: 1,
        padding: "16px 0",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        gap: 1,
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        lineHeight: 1.5,
        color: "#1a1814",
        // The rail never scrolls: only the destinations region below does,
        // so the account footer stays pinned at the bottom.
        overflow: "hidden",
        transition: "width var(--dur) var(--ease), min-width var(--dur) var(--ease)",
      }}
    >
      {/* Wide: the wordmark. Narrow: the Sapling symbol, centred. They
          cross-fade in one fixed-height slot so nothing below shifts. */}
      <Link
        href="/dashboard"
        aria-label="Sapling — home"
        data-sidenav-logo=""
        style={{
          position: "relative",
          display: "block",
          height: LOGO_SLOT_HEIGHT,
          padding: collapsed ? "6px 0 14px 0" : "6px 0 14px 12px",
          margin: collapsed ? "0 6px 8px" : "0 10px 8px",
          boxSizing: "content-box",
          overflow: "hidden",
          borderBottom: `1px solid ${SIDENAV.divider}`,
          textDecoration: "none",
          transition: GEOMETRY_TRANSITION,
        }}
      >
        <SaplingWordmark
          width={112}
          decorative
          style={{ position: "absolute", left: 12, top: 6, ...fade(collapsed) }}
        />
        {/* eslint-disable-next-line @next/next/no-img-element -- a static vector; next/image adds nothing for SVG */}
        <img
          src={SAPLING_SYMBOL_SRC}
          alt=""
          aria-hidden
          data-sidenav-symbol=""
          width={SYMBOL_WIDTH}
          height={LOGO_SLOT_HEIGHT}
          draggable={false}
          style={{
            position: "absolute",
            top: 6,
            left: (SIDE_NAV_COLLAPSED - 12 - SYMBOL_WIDTH) / 2,
            width: SYMBOL_WIDTH,
            height: LOGO_SLOT_HEIGHT,
            opacity: collapsed ? 1 : 0,
            transition: `opacity var(--dur-fast) var(--ease) ${collapsed ? "90ms" : "0ms"}`,
          }}
        />
      </Link>

      {/* Destinations scroll on their own when the viewport is short, with
          the scrollbar hidden (globals.css + scrollbarWidth). */}
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
        {sections.map((section, i) => (
          <React.Fragment key={section.label}>
            {/* Header slot. Wide: the mono group label. Narrow: a hairline
                (none above the first group; the logo rule does that job). */}
            <div
              aria-hidden={collapsed || undefined}
              style={{
                position: "relative",
                flexShrink: 0,
                overflow: "hidden",
                height: collapsed ? (i === 0 ? 0 : 17) : HEADER.height,
                transition: GEOMETRY_TRANSITION,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: HEADER.left,
                  bottom: HEADER.below,
                  lineHeight: `${HEADER.line}px`,
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  letterSpacing: "0.14em",
                  textTransform: "uppercase",
                  color: SIDENAV.heading,
                  ...fade(collapsed),
                }}
              >
                {section.label}
              </div>
              {i > 0 && (
                <div
                  data-sidenav-group-rule=""
                  aria-hidden
                  style={{
                    position: "absolute",
                    left: 12,
                    right: 12,
                    top: 8,
                    height: 1,
                    background: SIDENAV.divider,
                    opacity: collapsed ? 1 : 0,
                    transition: "opacity var(--dur-fast) var(--ease)",
                  }}
                />
              )}
            </div>
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

      {/* Collapse/expand: built like a nav row, panel glyph + "Collapse". */}
      <button
        type="button"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : undefined}
        onClick={() => setCollapsed(!collapsed)}
        onMouseEnter={() => setCollapseHover(true)}
        onMouseLeave={() => setCollapseHover(false)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
          minHeight: NAV_ITEM_MIN_HEIGHT,
          ...rowGeometry(collapsed),
          borderRadius: ROW_RADIUS,
          border: "none",
          boxSizing: "border-box",
          background: collapseHover ? SIDENAV.hoverBg : "transparent",
          color: collapseHover ? SIDENAV.labelHover : SIDENAV.label,
          fontFamily: "inherit",
          fontSize: 16,
          textAlign: "left",
          cursor: "pointer",
          transition: `background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), ${GEOMETRY_TRANSITION}`,
        }}
      >
        <span style={{ display: "inline-flex", color: collapseHover ? SIDENAV.iconHover : SIDENAV.icon }}>
          <PanelToggleIcon collapsed={collapsed} />
        </span>
        <span aria-hidden style={{ flex: 1, ...fade(collapsed) }}>Collapse</span>
      </button>

      {/* Account footer under one full-width rule: Settings, Admin, profile. */}
      <div
        data-sidenav-footer=""
        style={{
          display: "flex",
          flexDirection: "column",
          gap: NAV_GAP,
          flexShrink: 0,
          marginTop: 4,
          paddingTop: 10,
          borderTop: `1px solid ${SIDENAV.divider}`,
        }}
      >
        <NavLink
          entry={{ href: "/settings", label: "Settings", icon: "setting" }}
          active={isActive(pathname, "/settings")}
          collapsed={collapsed}
          testId="nav-link-settings"
        />

        {isAdmin && (
          <NavLink
            entry={{ href: "/admin", label: "Admin", icon: "shield" }}
            active={isActive(pathname, "/admin")}
            collapsed={collapsed}
          />
        )}

        {isAuthenticated && (
          <div data-sidenav-account="" style={{ padding: "10px 0 4px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: `6px ${collapsed ? (SIDE_NAV_COLLAPSED - 30) / 2 : 22}px`,
                overflow: "hidden",
                transition: GEOMETRY_TRANSITION,
              }}
            >
              <Avatar name={userName || "?"} size={30} img={avatarUrl || undefined} />
              <div aria-hidden={collapsed || undefined} style={{ minWidth: 0, flex: 1, ...fade(collapsed) }}>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: SIDENAV.labelHover,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {userName || "You"}
                </div>
                <div style={{ fontSize: 11, color: SIDENAV.heading }}>Account</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function NavLink({
  entry,
  active,
  collapsed,
  testId,
}: {
  entry: Entry;
  active: boolean;
  collapsed: boolean;
  testId?: string;
}) {
  const [hover, setHover] = React.useState(false);
  const hot = hover && !active;
  return (
    <Link
      href={entry.href}
      data-testid={testId ?? `nav-link-${entry.href.slice(1)}`}
      aria-current={active ? "page" : undefined}
      title={collapsed ? entry.label : undefined}
      aria-label={collapsed ? entry.label : undefined}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexShrink: 0,
        minHeight: NAV_ITEM_MIN_HEIGHT,
        boxSizing: "border-box",
        ...rowGeometry(collapsed),
        borderRadius: ROW_RADIUS,
        ...rowSurface(active, hot),
        fontWeight: active ? 700 : 400,
        fontSize: 16,
        cursor: "pointer",
        transition: `background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), ${GEOMETRY_TRANSITION}`,
        textDecoration: "none",
      }}
    >
      <span style={{ display: "inline-flex", flexShrink: 0, color: hot ? SIDENAV.iconHover : SIDENAV.icon }}>
        <Icon name={entry.icon} size={ICON_SIZE} />
      </span>
      <span aria-hidden={collapsed || undefined} style={{ flex: 1, ...fade(collapsed) }}>
        {entry.label}
      </span>
    </Link>
  );
}

/* The sidebar-toggle glyph: a panel with its left column ruled off and a
   chevron that flips with the collapse. */
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
      style={{ flexShrink: 0 }}
    >
      <rect x="3" y="3" width="18" height="18" rx="2.5" />
      <path d="M9 3v18" />
      <path
        d="M16 9l-3 3 3 3"
        style={{
          transformBox: "fill-box",
          transformOrigin: "center",
          transform: collapsed ? "rotate(180deg)" : "none",
          transition: "transform var(--dur) var(--ease)",
        }}
      />
    </svg>
  );
}
