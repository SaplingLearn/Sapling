"use client";
import React from "react";

type SkeletonProps = {
  width?: number | string;
  height?: number | string;
  radius?: number | string;
  circle?: boolean;
  style?: React.CSSProperties;
  className?: string;
};

export function Skeleton({
  width = "100%",
  height = 14,
  radius,
  circle = false,
  style,
  className,
}: SkeletonProps) {
  const r = circle ? "999px" : radius ?? "var(--r-sm)";
  return (
    <div
      className={`skeleton ${className || ""}`.trim()}
      aria-hidden
      style={{
        width,
        height,
        borderRadius: r,
        display: "block",
        ...style,
      }}
    />
  );
}

export function SkeletonText({
  lines = 3,
  lastWidth = "60%",
  gap = 8,
  lineHeight = 12,
}: {
  lines?: number;
  lastWidth?: number | string;
  gap?: number;
  lineHeight?: number;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap }}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={lineHeight}
          width={i === lines - 1 ? lastWidth : "100%"}
        />
      ))}
    </div>
  );
}

export function LibraryGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 16,
      }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="card"
          style={{
            padding: "var(--pad-lg)",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
            }}
          >
            <Skeleton width={40} height={48} radius="var(--r-sm)" />
            <Skeleton width={70} height={20} radius={999} />
          </div>
          <Skeleton width="80%" height={16} />
          <Skeleton width="40%" height={11} />
          <SkeletonText lines={3} lineHeight={11} lastWidth="55%" />
        </div>
      ))}
    </div>
  );
}

export function LibraryListSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="card" style={{ padding: 0 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "14px 20px",
            borderBottom:
              i < count - 1 ? "1px solid var(--border)" : "none",
          }}
        >
          <Skeleton width={28} height={36} radius="var(--r-xs)" />
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            <Skeleton width="55%" height={13} />
            <Skeleton width="80%" height={11} />
          </div>
          <Skeleton width={70} height={20} radius={999} />
          <Skeleton width={70} height={11} />
        </div>
      ))}
    </div>
  );
}

export function ProfileSkeleton() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        padding: "20px 0",
        maxWidth: 900,
        margin: "0 auto",
      }}
    >
      <section
        style={{
          display: "flex",
          gap: 20,
          alignItems: "flex-start",
          padding: "var(--pad-lg)",
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-xl)",
        }}
      >
        <Skeleton width={88} height={88} circle />
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          <Skeleton width="40%" height={26} />
          <Skeleton width="20%" height={11} />
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <Skeleton width={64} height={20} radius={999} />
            <Skeleton width={80} height={20} radius={999} />
          </div>
          <SkeletonText lines={2} lineHeight={11} lastWidth="70%" />
          <div style={{ display: "flex", gap: 14, marginTop: 4 }}>
            <Skeleton width={120} height={11} />
            <Skeleton width={80} height={11} />
            <Skeleton width={100} height={11} />
          </div>
        </div>
      </section>

      <section
        style={{
          padding: "10px 0",
          borderTop: "1px solid var(--border)",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          gap: 14,
        }}
      >
        <Skeleton width={120} height={14} />
        <Skeleton width={120} height={14} />
        <Skeleton width={120} height={14} />
        <Skeleton width={140} height={14} />
      </section>

      <section className="card" style={{ padding: "var(--pad-lg)" }}>
        <Skeleton width={120} height={10} style={{ marginBottom: 12 }} />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Skeleton width={90} height={22} radius={999} />
          <Skeleton width={120} height={22} radius={999} />
          <Skeleton width={70} height={22} radius={999} />
        </div>
      </section>

      <section className="card" style={{ padding: "var(--pad-lg)" }}>
        <Skeleton width={160} height={10} style={{ marginBottom: 12 }} />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
            gap: 10,
          }}
        >
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} height={92} radius="var(--r-md)" />
          ))}
        </div>
      </section>
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div
      style={{
        padding: "18px 32px 24px",
        display: "grid",
        gap: 16,
        gridTemplateColumns: "minmax(0, 1fr) minmax(280px, 360px)",
        flex: 1,
        minHeight: 0,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        <Skeleton width={140} height={11} />
        <Skeleton width="55%" height={42} />
        <Skeleton width="80%" height={14} />
        <div
          className="card"
          style={{
            padding: 0,
            overflow: "hidden",
            minHeight: 420,
            display: "flex",
            flexDirection: "column",
            flex: 1,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "16px 22px",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Skeleton width={140} height={10} />
              <Skeleton width={260} height={20} />
            </div>
            <Skeleton width={32} height={28} radius="var(--r-sm)" />
          </div>
          <div style={{ flex: 1, minHeight: 260, padding: 22, display: "grid", placeItems: "center" }}>
            <Skeleton width={200} height={200} circle style={{ opacity: 0.5 }} />
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, minHeight: 30 }}>
          <Skeleton width={80} height={28} radius="var(--r-sm)" />
          <Skeleton width={120} height={28} radius="var(--r-sm)" />
        </div>
        <div className="card" style={{ padding: 0, display: "grid", gridTemplateColumns: "1fr 1fr" }}>
          <div style={{ padding: "16px 18px", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 8 }}>
            <Skeleton width={60} height={10} />
            <Skeleton width={70} height={32} />
            <Skeleton width={100} height={10} />
          </div>
          <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
            <Skeleton width={60} height={10} />
            <Skeleton width={50} height={32} />
            <Skeleton width={100} height={10} />
          </div>
        </div>
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="card" style={{ padding: "var(--pad-lg)" }}>
            <Skeleton width={80} height={10} style={{ marginBottom: 8 }} />
            <Skeleton width="60%" height={16} style={{ marginBottom: 14 }} />
            {Array.from({ length: 3 }).map((__, j) => (
              <div
                key={j}
                style={{
                  display: "flex",
                  gap: 10,
                  padding: "10px 12px",
                  borderRadius: "var(--r-md)",
                  background: "var(--bg-subtle)",
                  marginBottom: 6,
                  alignItems: "center",
                }}
              >
                <Skeleton width={20} height={20} circle />
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
                  <Skeleton width="60%" height={12} />
                  <Skeleton width="80%" height={10} />
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CalendarMonthSkeleton() {
  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div style={{ padding: "20px 32px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, marginBottom: 4 }}>
        {weekdays.map(d => (
          <div key={d} className="label-micro" style={{ padding: 6 }}>{d}</div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4 }}>
        {Array.from({ length: 42 }).map((_, i) => (
          <div
            key={i}
            className="card"
            style={{
              padding: 8,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}
          >
            <Skeleton width={16} height={11} />
            {i % 3 === 0 && <Skeleton width="80%" height={10} />}
            {i % 5 === 0 && <Skeleton width="60%" height={10} />}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AchievementsSkeleton() {
  return (
    <div style={{ padding: "24px 32px" }}>
      <Skeleton width={220} height={11} style={{ marginBottom: 12 }} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 30 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="card"
            style={{
              padding: 12,
              minHeight: 92,
              display: "flex",
              flexDirection: "column",
              gap: 8,
              alignItems: "center",
            }}
          >
            <Skeleton width={32} height={32} circle />
            <Skeleton width="80%" height={10} />
          </div>
        ))}
      </div>
      <Skeleton width={120} height={10} style={{ marginBottom: 12 }} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card" style={{ padding: "var(--pad-lg)", display: "flex", gap: 14 }}>
            <Skeleton width={52} height={52} radius="var(--r-md)" />
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                <Skeleton width="50%" height={14} />
                <Skeleton width={60} height={18} radius={999} />
              </div>
              <SkeletonText lines={2} lineHeight={11} lastWidth="70%" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SocialRoomsSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div style={{ padding: 8 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            padding: "10px 12px",
            borderRadius: "var(--r-md)",
            marginBottom: 4,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <Skeleton width="70%" height={13} />
          <Skeleton width="40%" height={10} />
        </div>
      ))}
    </div>
  );
}

export function SettingsFormSkeleton() {
  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "24px 32px" }}>
      <Skeleton width={120} height={22} style={{ marginBottom: 20 }} />
      <div
        className="card"
        style={{ padding: "var(--pad-lg)", display: "flex", gap: 20, alignItems: "center", marginBottom: 16 }}
      >
        <Skeleton width={72} height={72} circle />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
          <Skeleton width={140} height={18} />
          <Skeleton width={180} height={11} />
        </div>
        <Skeleton width={120} height={28} radius="var(--r-sm)" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: "180px 1fr",
            gap: 16,
            padding: "12px 0",
            borderBottom: "1px solid var(--border)",
            alignItems: "center",
          }}
        >
          <Skeleton width={100} height={11} />
          <Skeleton width="100%" height={32} radius="var(--r-sm)" />
        </div>
      ))}
    </div>
  );
}

export function GraphPanelSkeleton() {
  return (
    <div style={{ flex: 1, display: "grid", placeItems: "center" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
        <Skeleton width={220} height={220} circle style={{ opacity: 0.6 }} />
        <Skeleton width={180} height={11} />
      </div>
    </div>
  );
}

export function StudyGuideSkeleton() {
  return (
    <div style={{ padding: "24px 32px", maxWidth: 880, margin: "0 auto" }}>
      <Skeleton width="50%" height={28} style={{ marginBottom: 8 }} />
      <Skeleton width="30%" height={11} style={{ marginBottom: 24 }} />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} style={{ marginBottom: 24 }}>
          <Skeleton width="40%" height={18} style={{ marginBottom: 10 }} />
          <SkeletonText lines={4} lineHeight={12} lastWidth="65%" />
        </div>
      ))}
    </div>
  );
}

export function FlashcardsSkeleton() {
  return (
    <div style={{ padding: "24px 32px", maxWidth: 720, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Skeleton width={160} height={11} />
        <Skeleton width={120} height={28} radius="var(--r-sm)" />
      </div>
      <div
        className="card"
        style={{
          padding: "var(--pad-lg)",
          minHeight: 280,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <Skeleton width="60%" height={18} />
        <SkeletonText lines={3} lineHeight={12} lastWidth="55%" />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "center" }}>
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} width={100} height={36} radius="var(--r-sm)" />
        ))}
      </div>
    </div>
  );
}

export function AdminTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "32px 1fr 1fr 1fr 100px",
          gap: 12,
          padding: "10px 14px",
          background: "var(--bg-subtle)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} width={i === 0 ? 14 : "60%"} height={11} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: "32px 1fr 1fr 1fr 100px",
            gap: 12,
            padding: "12px 14px",
            borderTop: i === 0 ? "none" : "1px solid var(--border)",
            alignItems: "center",
          }}
        >
          <Skeleton width={14} height={14} radius="var(--r-xs)" />
          <Skeleton width="80%" height={12} />
          <Skeleton width="60%" height={12} />
          <Skeleton width="50%" height={12} />
          <Skeleton width={70} height={20} radius={999} />
        </div>
      ))}
    </div>
  );
}
