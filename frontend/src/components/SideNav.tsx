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
import { STUDY_TOOL_PATHS } from "@/lib/toolHrefs";
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

/* Text fades rather than mounting/unmounting. Out: immediately and quickly,
   so nothing is visibly squeezed as the rail narrows. In: a beat late, so the
   label arrives once there is room for it. */
function fade(collapsed: boolean): React.CSSProperties {
  return {
    opacity: collapsed ? 0 : 1,
    whiteSpace: "nowrap",
    transition: `opacity var(--dur-fast) var(--ease) ${collapsed ? "0ms" : "90ms"}`,
  };
}

/* Active/hover surfaces.
 *
 * A plain neutral highlight. The selected row is a flat `--bg-soft` fill,
 * which inside the olive rail resolves to a translucent cream wash (see
 * [data-app-sidenav] in globals.css), with the label in bold cream.
 * No rail, no hue on the label: the fill IS the treatment.
 *
 * Hover is the same colour at half strength, so it is unmistakably the
 * weaker, transient state and never reads as a second selection. */
const NAV_ACTIVE_BG = "var(--bg-soft)";
const NAV_HOVER_BG = "color-mix(in srgb, var(--bg-soft) 50%, transparent)";

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

export function SideNav() {
  const pathname = usePathname() || "/";
  const { userName, avatarUrl, isAdmin, isAuthenticated } = useUser();
  const [collapsed, setCollapsed] = useCollapsed();
  const sections = useVisibleNavSections();
  const settingsActive = isActive(pathname, "/settings");

  const width = collapsed ? SIDE_NAV_COLLAPSED : SIDE_NAV_EXPANDED;

  return (
    <aside
      role="navigation"
      aria-label="Primary"
      // Hook for the pre-hydration mobile guard in globals.css (#110).
      data-app-sidenav=""
      className="h-full bg-sidenav-bg [border-radius:0_var(--r-lg)_var(--r-lg)_0] relative z-1 flex flex-col gap-px overflow-hidden [transition:width_var(--dur)_var(--ease),_min-width_var(--dur)_var(--ease),_padding_var(--dur)_var(--ease)]" style={{ width, minWidth: width, padding: `16px ${collapsed ? RAIL_PAD_X.narrow : RAIL_PAD_X.wide}px` }}
    >
      {/* Wide: the wordmark. Narrow: the Sapling symbol, centred. The two
          cross-fade in one fixed-height slot so nothing below shifts, and the
          link stays a live home link in both widths. */}
      <Link
        href="/dashboard"
        aria-label="Sapling — home"
        data-sidenav-logo=""
        className="relative block pb-3.5 box-content overflow-hidden border-b border-b-border mb-2 no-underline" style={{ height: LOGO_SLOT_HEIGHT }}
      >
        <SaplingWordmark
          width={112}
          decorative
          tone="light"
          style={{ position: "absolute", left: 6, top: 0, ...fade(collapsed) }}
        />
        <img
          src={SAPLING_SYMBOL_SRC}
          alt=""
          aria-hidden
          data-sidenav-symbol=""
          width={SYMBOL_WIDTH}
          height={LOGO_SLOT_HEIGHT}
          draggable={false}
          className={cn("absolute top-0 [filter:brightness(0)_invert(1)]", collapsed ? "opacity-100" : "opacity-0", collapsed ? "[transition:opacity_var(--dur-fast)_var(--ease)_90ms]" : "[transition:opacity_var(--dur-fast)_var(--ease)_0ms]")} style={{ left: (RAIL_INNER_NARROW - SYMBOL_WIDTH) / 2, width: SYMBOL_WIDTH, height: LOGO_SLOT_HEIGHT }}
        />
      </Link>

      {/* The destinations scroll on their own when the viewport is too short
          for them, with the scrollbar hidden (`scrollbarWidth` here, the
          WebKit pseudo-element in globals.css) — a 10px gutter in a 200px
          rail read as clutter, and wheel/trackpad/keyboard scrolling all
          still work. `minHeight: 0` is what lets a flex child shrink below
          its content and scroll at all. */}
      <div
        data-sidenav-scroll=""
        className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden [scrollbar-width:none] flex flex-col gap-px"
      >
      {sections.map((section, i) => (
        <React.Fragment key={section.label}>
          {/* Header slot. Wide: the group label. Narrow: a hairline (none
              above the first group — the logo rule already does that job).
              The slot's height tweens between the two so the rows below
              slide rather than jump, and label/hairline cross-fade.
              Spacing lives in HEADER. */}
          <div
            aria-hidden={collapsed || undefined}
            className="relative shrink-0 overflow-hidden [transition:margin_var(--dur)_var(--ease),_padding_var(--dur)_var(--ease),_height_var(--dur)_var(--ease)]" style={{ height: collapsed ? (i === 0 ? 0 : 29) : HEADER.above + HEADER.line + HEADER.below }}
          >
            <div
              className="label-micro absolute left-2.5 bottom-1.5 leading-[17px]"
              style={{ ...fade(collapsed) }}
            >
              {section.label}
            </div>
            {i > 0 && (
              <div
                data-sidenav-group-rule=""
                aria-hidden
                className={cn("absolute left-2 right-2 top-4.5 h-px bg-border [transition:opacity_var(--dur-fast)_var(--ease)]", collapsed ? "opacity-100" : "opacity-0")}
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

      {/* The account footer — Collapse, Admin and the profile block — sits
          under one full-width rule, the same line as the logo's, so the pair
          frames the rail top and bottom and the account cluster reads as split
          off from the main nav. Pinned: it never scrolls with the list above. */}
      <div
        data-sidenav-footer=""
        className="flex flex-col gap-px shrink-0 mt-1 pt-2.5 border-t border-t-border"
      >
      {/* Collapse/expand opens the footer, just under its rule and above the
          account block, and is built like a nav row: panel icon + "Collapse" in the wide rail, the
          bare icon in the narrow one — the usual sidebar toggle.
          Same insets, padding and row height as NavLink so it lines up with
          the destinations above it. */}
      <button
        type="button"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : undefined}
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2.5 shrink-0 min-h-9.5" style={{ ...rowGeometry(collapsed), borderRadius: "var(--r-xs)", color: "var(--text-dim)", fontSize: 13, textAlign: "left", transition: `background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), ${GEOMETRY_TRANSITION}` }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = NAV_HOVER_BG;
          e.currentTarget.style.color = "var(--text)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent";
          e.currentTarget.style.color = "var(--text-dim)";
        }}
      >
        <PanelToggleIcon collapsed={collapsed} />
        <span aria-hidden className="flex-1" style={{ ...fade(collapsed) }}>Collapse</span>
      </button>

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
        <div className="pt-2.5 px-0 pb-1">
          <div
            className="flex items-center w-full"
          >
            <Link
              href="/settings"
              data-testid="nav-link-settings"
              aria-label="Settings"
              aria-current={settingsActive ? "page" : undefined}
              title={collapsed ? "Settings" : undefined}
              className={cn("flex items-center gap-2.5 flex-1 min-w-0 rounded-sm text-left overflow-hidden no-underline [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease),_margin_var(--dur)_var(--ease),_padding_var(--dur)_var(--ease),_height_var(--dur)_var(--ease)]", settingsActive ? "text-text" : "text-text-dim", settingsActive ? "bg-bg-soft" : "bg-transparent")} style={{ padding: `6px ${collapsed ? (RAIL_INNER_NARROW - 30) / 2 : 12}px` }}
              onMouseEnter={(e) => {
                if (settingsActive) return;
                e.currentTarget.style.background = NAV_HOVER_BG;
                e.currentTarget.style.color = "var(--text)";
              }}
              onMouseLeave={(e) => {
                if (settingsActive) return;
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = "var(--text-dim)";
              }}
            >
              <Avatar name={userName || "?"} size={30} img={avatarUrl || undefined} />
                <div aria-hidden={collapsed || undefined} className="min-w-0 flex-1" style={{ ...fade(collapsed) }}>
                  <div
                    className="text-md font-semibold text-text overflow-hidden text-ellipsis whitespace-nowrap"
                  >
                    {userName || "You"}
                  </div>
                  <div className="text-xs text-text-muted">Account</div>
                </div>
                <span aria-hidden className="inline-flex shrink-0" style={{ ...fade(collapsed) }}>
                  <Icon name="setting" size={ICON_SIZE} />
                </span>
            </Link>
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
      data-testid={`nav-link-${entry.href.slice(1)}`}
      title={collapsed ? entry.label : undefined}
      aria-label={collapsed ? entry.label : undefined}
      className="flex items-center gap-2.5 min-h-9.5" style={{ ...rowGeometry(collapsed), borderRadius: "var(--r-xs)", background: active ? NAV_ACTIVE_BG : "transparent", color: active ? "var(--text)" : "var(--text-dim)", fontWeight: active ? 600 : 400, fontSize: 13, transition: `background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), ${GEOMETRY_TRANSITION}`, textDecoration: "none" }}
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
      <span className="inline-flex shrink-0">
        <Icon name={entry.icon} size={ICON_SIZE} />
      </span>
      <span aria-hidden={collapsed || undefined} className="flex-1" style={{ ...fade(collapsed) }}>
        {entry.label}
      </span>
    </Link>
  );
}

/* The sidebar-toggle glyph: a panel with its left column ruled off and a
   chevron in the open area. Only the chevron moves — it points in (close)
   when the rail is wide and flips to point out (open) when narrow, turning
   about its own centre on the rail's duration so it animates with the
   collapse. Stroke weight and caps match `Icon`. */
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
      className="shrink-0"
    >
      <rect x="3" y="3" width="18" height="18" rx="2.5" />
      <path d="M9 3v18" />
      <path
        d="M16 9l-3 3 3 3"
        className={cn("[transform-box:fill-box] origin-center [transition:transform_var(--dur)_var(--ease)]", collapsed ? "[transform:rotate(180deg)]" : "[transform:none]")}
      />
    </svg>
  );
}
