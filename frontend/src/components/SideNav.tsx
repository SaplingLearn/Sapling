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

export const SIDE_NAV_WIDTH = 232;

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname.startsWith("/dashboard");
  return pathname === href || pathname.startsWith(href + "/");
}

export function SideNav() {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const { userName, avatarUrl, isAdmin, isAuthenticated, signOut } = useUser();
  const [menuOpen, setMenuOpen] = React.useState(false);
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

  return (
    <aside
      role="navigation"
      aria-label="Primary"
      style={{
        width: SIDE_NAV_WIDTH,
        minWidth: SIDE_NAV_WIDTH,
        height: "100vh",
        borderRight: "1px solid var(--border)",
        background: "var(--bg-subtle)",
        padding: "16px 10px",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        overflowY: "auto",
        overflowX: "hidden",
      }}
    >
      {/* Logo — same composition as TopNav so brand stays consistent */}
      <Link
        href="/dashboard"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          padding: "2px 8px 14px",
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
            marginLeft: -2,
            marginRight: -4,
            alignSelf: "center",
            flexShrink: 0,
          }}
        />
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
      </Link>

      {SECTIONS.map((section, i) => (
        <React.Fragment key={section.label}>
          <div
            className="label-micro"
            style={{ padding: i === 0 ? "4px 10px 4px" : "14px 10px 4px" }}
          >
            {section.label}
          </div>
          {section.items.map(item => (
            <NavLink key={item.href} entry={item} active={isActive(pathname, item.href)} />
          ))}
        </React.Fragment>
      ))}

      <div style={{ flex: 1 }} />

      <NavLink
        entry={{ href: "/settings", label: "Settings", icon: "cog" }}
        active={isActive(pathname, "/settings")}
      />
      {isAdmin && (
        <NavLink
          entry={{ href: "/admin", label: "Admin", icon: "shield" }}
          active={isActive(pathname, "/admin")}
        />
      )}

      {isAuthenticated && (
        <div
          ref={menuRef}
          style={{
            position: "relative",
            padding: "10px 6px 4px",
            borderTop: "1px solid var(--border)",
            marginTop: 8,
          }}
        >
          <button
            aria-label="Account menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(o => !o)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              width: "100%",
              padding: "6px 6px",
              borderRadius: "var(--r-sm)",
              background: "transparent",
              transition: "background var(--dur-fast) var(--ease)",
              textAlign: "left",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-soft)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <Avatar name={userName || "?"} size={30} img={avatarUrl || undefined} />
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
            <Icon name="chev" size={12} />
          </button>
          {menuOpen && (
            <div
              style={{
                position: "absolute",
                bottom: "calc(100% + 6px)",
                left: 6,
                right: 6,
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

function NavLink({ entry, active }: { entry: Entry; active: boolean }) {
  return (
    <Link
      href={entry.href}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "8px 12px",
        borderRadius: "var(--r-sm)",
        background: active ? "var(--accent-soft)" : "transparent",
        color: active ? "var(--accent)" : "var(--text-dim)",
        fontWeight: active ? 600 : 400,
        fontSize: 13,
        borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
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
      <span style={{ flex: 1 }}>{entry.label}</span>
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
