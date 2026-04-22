"use client";

import React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { useUser } from "@/context/UserContext";

type Entry = { href: string; label: string; icon: string };

const SECTIONS: { label: string; items: Entry[] }[] = [
  {
    label: "Learn",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "home" },
      { href: "/learn",     label: "Learn",     icon: "brain" },
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
];

export const SIDE_NAV_EXPANDED = 232;
export const SIDE_NAV_COLLAPSED = 64;
const COLLAPSE_KEY = "sapling_sidenav_collapsed";

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
  const router = useRouter();
  const { userName, avatarUrl, isAdmin, isAuthenticated, signOut } = useUser();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [collapsed, setCollapsed] = useCollapsed();
  const menuRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => { setMenuOpen(false); }, [pathname]);

  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const onSignOut = async () => {
    setMenuOpen(false);
    await signOut();
    router.replace("/auth");
  };

  const width = collapsed ? SIDE_NAV_COLLAPSED : SIDE_NAV_EXPANDED;

  return (
    <aside
      role="navigation"
      aria-label="Primary"
      style={{
        width,
        minWidth: width,
        height: "100vh",
        borderRight: "1px solid var(--border)",
        background: "var(--bg-subtle)",
        padding: collapsed ? "16px 6px" : "16px 10px",
        display: "flex",
        flexDirection: "column",
        gap: 2,
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
          padding: collapsed ? "2px 0 14px" : "2px 8px 14px",
          borderBottom: "1px solid var(--border)",
          marginBottom: 8,
          textDecoration: "none",
        }}
      >
        <img
          src="/sapling-icon.svg"
          alt="Sapling"
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
                color: "#1a5c2a",
                letterSpacing: "-0.02em",
                textShadow: "0 0 12px rgba(26, 92, 42, 0.2)",
                lineHeight: 1.1,
              }}
            >
              Sapling
            </span>
            <span
              style={{
                fontSize: 9,
                fontWeight: 600,
                color: "#1a5c2a",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                opacity: 0.7,
                lineHeight: 1,
              }}
            >
              Closed Alpha
            </span>
          </div>
        )}
      </Link>

      {SECTIONS.map((section, i) => (
        <React.Fragment key={section.label}>
          {!collapsed && (
            <div
              className="label-micro"
              style={{ padding: i === 0 ? "4px 10px 4px" : "14px 10px 4px" }}
            >
              {section.label}
            </div>
          )}
          {collapsed && i > 0 && (
            <div style={{ height: 1, background: "var(--border)", margin: "8px 8px" }} aria-hidden />
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

      {isAuthenticated && (
        <div
          ref={menuRef}
          style={{
            position: "relative",
            padding: collapsed ? "10px 0 4px" : "10px 6px 4px",
            borderTop: "1px solid var(--border)",
            marginTop: 8,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: collapsed ? 0 : 4,
              width: "100%",
            }}
          >
            <button
              aria-label="Account menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(o => !o)}
              title={collapsed ? (userName || "Account") : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flex: 1,
                minWidth: 0,
                padding: "6px 6px",
                borderRadius: "var(--r-sm)",
                background: "transparent",
                transition: "background var(--dur-fast) var(--ease)",
                textAlign: "left",
                justifyContent: collapsed ? "center" : "flex-start",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
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
            </button>
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
                  width: 24,
                  height: 24,
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
                height: 28,
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
          {menuOpen && (
            <div
              style={{
                position: "absolute",
                bottom: "calc(100% + 6px)",
                left: collapsed ? "calc(100% + 6px)" : 6,
                right: collapsed ? "auto" : 6,
                minWidth: collapsed ? 180 : undefined,
                padding: "6px 0",
                background: "var(--bg-panel)",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-md)",
                boxShadow: "var(--shadow-md)",
                zIndex: 100,
              }}
            >
              <MenuItem href="/settings" label="Settings" icon="cog" />
              {isAdmin && <MenuItem href="/admin" label="Admin" icon="shield" />}
              <button
                onClick={onSignOut}
                style={{
                  width: "100%",
                  padding: "8px 14px",
                  textAlign: "left",
                  fontSize: 13,
                  color: "var(--text-dim)",
                  transition: "background var(--dur-fast) var(--ease)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                Sign out
              </button>
            </div>
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
        width: "100%",
        padding: collapsed ? "8px 0" : "8px 12px",
        borderRadius: "var(--r-sm)",
        background: active ? "var(--accent-soft)" : "transparent",
        color: active ? "var(--accent)" : "var(--text-dim)",
        fontWeight: active ? 600 : 400,
        fontSize: 13,
        borderLeft: active && !collapsed ? "2px solid var(--accent)" : "2px solid transparent",
        transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
        textDecoration: "none",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.color = "var(--text)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.color = "var(--text-dim)";
      }}
    >
      <Icon name={entry.icon} size={15} />
      {!collapsed && <span style={{ flex: 1 }}>{entry.label}</span>}
    </Link>
  );
}

function MenuItem({ href, label, icon }: { href: string; label: string; icon: string }) {
  return (
    <Link
      href={href}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 14px",
        fontSize: 13,
        color: "var(--text-dim)",
        textDecoration: "none",
        transition: "background var(--dur-fast) var(--ease)",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      <Icon name={icon} size={14} />
      {label}
    </Link>
  );
}
