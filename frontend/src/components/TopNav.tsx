"use client";

/**
 * Sapling top navigation.
 *
 * Replaces the vertical Sidebar with a minimal 56px sticky top bar —
 * matches the pre-revamp Navbar pattern. Text-only links (no icon
 * clutter), solid background (glassmorphism is off the table),
 * serif "Sapling" wordmark on the left, avatar dropdown on the right
 * for account actions.
 *
 * Design decisions:
 *  - Active state = `color: var(--text)` + weight 700 (no underline, no
 *    pill, no border — hierarchy through type, not decoration).
 *  - Inactive links are dimmed to `var(--text-muted)`; hover lifts to
 *    `var(--text-dim)`.
 *  - Mobile (≤768px) collapses the link list into a hamburger that
 *    drops a panel anchored to the hamburger button.
 *  - Everything on the right (account menu, report, report-issue link)
 *    stays inside a single flex group that pushes to the far right.
 */

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";

type Entry = { href: string; label: string };

const LINKS: Entry[] = [
  { href: "/dashboard",    label: "Dashboard"    },
  { href: "/learn",        label: "Learn"        },
  { href: "/tree",         label: "Tree"         },
  { href: "/study",        label: "Study"        },
  { href: "/library",      label: "Library"      },
  { href: "/calendar",     label: "Calendar"     },
  { href: "/social",       label: "Social"       },
  { href: "/achievements", label: "Achievements" },
];

export const TOP_NAV_HEIGHT = 56;

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  return pathname === href || pathname.startsWith(href + "/");
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
            onClick={() => setMobileOpen(o => !o)}
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

      {/* Desktop link row — icon + label from the pre-revamp Sidebar */}
      {!isMobile && (
        <div style={{ display: "flex", alignItems: "center", gap: 2, flex: 1, minWidth: 0 }}>
          {LINKS.map(l => {
            const active = isActive(pathname, l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "6px 10px", borderRadius: "var(--r-sm)",
                  fontSize: 13, fontWeight: active ? 700 : 500,
                  color: active ? "var(--text)" : "var(--text-muted)",
                  textDecoration: "none", whiteSpace: "nowrap",
                  transition: "color var(--dur-fast) var(--ease)",
                }}
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.color = "var(--text-dim)";
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.color = "var(--text-muted)";
                }}
              >
                {l.label}
              </Link>
            );
          })}
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

function MobilePanel({ pathname }: { pathname: string }) {
  return (
    <div
      style={{
        position: "absolute", top: "calc(100% + 6px)", left: 0,
        minWidth: 220, padding: "6px 0",
        background: "var(--bg-panel)", border: "1px solid var(--border)",
        borderRadius: "var(--r-md)", boxShadow: "var(--shadow-md)",
        zIndex: 100,
      }}
    >
      {LINKS.map(l => {
        const active = isActive(pathname, l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "10px 14px",
              fontSize: 14, fontWeight: active ? 700 : 500,
              color: active ? "var(--text)" : "var(--text-dim)",
              textDecoration: "none",
              transition: "background var(--dur-fast) var(--ease)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            {l.label}
          </Link>
        );
      })}
    </div>
  );
}
