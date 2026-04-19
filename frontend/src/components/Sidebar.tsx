"use client";
import React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Icon } from "./Icon";
import { Avatar } from "./Avatar";
import { useSidebar } from "@/lib/sidebar";
import { useUser } from "@/context/UserContext";

type NavEntry = {
  icon: string;
  label: string;
  route: string;
  badge?: string;
};

function NavItem({
  icon,
  label,
  route,
  current,
  badge,
  isRail,
}: NavEntry & { current: boolean; isRail: boolean }) {
  return (
    <Link
      href={`/${route}`}
      title={isRail ? label : undefined}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: isRail ? "8px" : "8px 12px",
        justifyContent: isRail ? "center" : "flex-start",
        borderRadius: "var(--r-sm)",
        background: current ? "var(--accent-soft)" : "transparent",
        color: current ? "var(--accent)" : "var(--text-dim)",
        fontWeight: current ? 600 : 400,
        fontSize: 13,
        borderLeft: current && !isRail ? "2px solid var(--accent)" : "2px solid transparent",
        transition: "all var(--dur-fast) var(--ease)",
        textAlign: "left",
        textDecoration: "none",
      }}
    >
      <Icon name={icon} size={15} />
      {!isRail && <span style={{ flex: 1 }}>{label}</span>}
      {!isRail && badge && (
        <span
          style={{
            fontSize: 10,
            padding: "2px 6px",
            borderRadius: "var(--r-full)",
            background: "var(--warn)",
            color: "#fff",
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
          }}
        >
          {badge}
        </span>
      )}
    </Link>
  );
}

export function Sidebar() {
  const { layout, toggleLayout } = useSidebar();
  const { userName, avatarUrl, isAdmin, isAuthenticated, signOut } = useUser();
  const pathname = usePathname() || "/";
  const router = useRouter();
  const current = pathname.split("/")[1] || "dashboard";
  const isRail = layout === "rail";
  const w = isRail ? 64 : 232;

  const section = (label: string) =>
    !isRail ? (
      <div className="label-micro" style={{ padding: "14px 10px 4px" }}>
        {label}
      </div>
    ) : (
      <div style={{ height: 10 }} />
    );

  const displayName = userName || "Sapling";

  const handleSignOut = async () => {
    await signOut();
    router.replace("/auth");
  };

  return (
    <aside
      style={{
        width: w,
        minWidth: w,
        borderRight: "1px solid var(--border)",
        background: "var(--bg-subtle)",
        padding: "16px 10px",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        transition: "width var(--dur) var(--ease)",
        position: "relative",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 8px 16px",
          borderBottom: "1px solid var(--border)",
          marginBottom: 8,
          justifyContent: isRail ? "center" : "flex-start",
        }}
      >
        <svg width="24" height="24" viewBox="0 0 24 24">
          <path
            d="M12 22 Q 5 15 5 9 Q 5 3 12 3 Q 19 3 19 9 Q 19 15 12 22 Z"
            fill="var(--accent)"
            opacity={0.2}
          />
          <path
            d="M12 22 V 10 M12 13 Q 8 10 7 7 M12 14 Q 16 11 17 8"
            stroke="var(--accent)"
            strokeWidth={1.5}
            fill="none"
            strokeLinecap="round"
          />
        </svg>
        {!isRail && (
          <span className="h-serif" style={{ fontSize: 18, fontWeight: 600 }}>
            Sapling
          </span>
        )}
      </div>

      {section("Learn")}
      <NavItem icon="home" label="Dashboard" route="dashboard" current={current === "dashboard"} isRail={isRail} />
      <NavItem icon="brain" label="Learn" route="learn" current={current === "learn"} isRail={isRail} />
      <NavItem icon="tree" label="Tree" route="tree" current={current === "tree"} isRail={isRail} />
      <NavItem icon="bolt" label="Study" route="study" current={current === "study"} isRail={isRail} />

      {section("Organize")}
      <NavItem icon="book" label="Library" route="library" current={current === "library"} isRail={isRail} />
      <NavItem icon="cal" label="Calendar" route="calendar" current={current === "calendar"} isRail={isRail} />

      {section("Community")}
      <NavItem icon="users" label="Social" route="social" current={current === "social"} isRail={isRail} />
      <NavItem icon="trophy" label="Achievements" route="achievements" current={current === "achievements"} isRail={isRail} />

      <div style={{ flex: 1 }} />
      <NavItem icon="cog" label="Settings" route="settings" current={current === "settings"} isRail={isRail} />
      {isAdmin && <NavItem icon="shield" label="Admin" route="admin" current={current === "admin"} isRail={isRail} />}

      {!isRail && isAuthenticated && (
        <div
          style={{
            padding: "10px 10px 0",
            borderTop: "1px solid var(--border)",
            marginTop: 8,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <Avatar name={displayName} size={32} img={avatarUrl || undefined} />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {displayName}
            </div>
            <button
              onClick={handleSignOut}
              style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "left", marginTop: 1 }}
            >
              Sign out
            </button>
          </div>
        </div>
      )}

      <button
        onClick={toggleLayout}
        title={isRail ? "Expand sidebar" : "Collapse sidebar"}
        aria-label={isRail ? "Expand sidebar" : "Collapse sidebar"}
        style={{
          position: "absolute",
          right: -12,
          bottom: 14,
          width: 24,
          height: 24,
          borderRadius: "50%",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-strong)",
          boxShadow: "var(--shadow-sm)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-dim)",
          transition: "transform var(--dur) var(--ease)",
          zIndex: 10,
        }}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.2}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ transform: isRail ? "none" : "rotate(180deg)" }}
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    </aside>
  );
}
