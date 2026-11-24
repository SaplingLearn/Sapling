"use client";
/**
 * The full-page skeleton the Library shows on first load: the header, the
 * filter row, and nine rows (or eight cards) in the layout the content will
 * take, so nothing shifts when it arrives.
 *
 * It overlays the real page and fades out at 720 ms, which is what lets the
 * content underneath run its own entrance at 880–900 ms — the two are timed
 * against each other, not sequenced by a state change.
 *
 * Built on the repo's `Skeleton` primitive, with the design's gradient: the
 * primitive's `.skeleton` class carries the app's shimmer, and
 * `.sapSkeleton` (library-notes.css) replaces the colours and the 1.6 s
 * timing with the handoff's.
 */
import React from "react";

import { Skeleton } from "../Skeleton";

/** Cosmetic only — never announced, never interactive. */
const ROOT: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  zIndex: 40,
  background: "#FAF8F3",
  padding: "36px 64px 0 56px",
  boxSizing: "border-box",
  display: "flex",
  flexDirection: "column",
  pointerEvents: "none",
  animation: "sapSkelOut 260ms ease 720ms both",
};

const LIST_COLS = "24px minmax(0, 1fr) 120px 120px 56px 64px 40px";

function Bar(props: {
  width: number | string;
  height: number;
  radius: number;
  style?: React.CSSProperties;
}) {
  return (
    <Skeleton
      className="sapSkeleton"
      width={props.width}
      height={props.height}
      radius={props.radius}
      style={props.style}
    />
  );
}

function SkeletonRow() {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: LIST_COLS, gap: 12,
      alignItems: "center", padding: "12px 14px", borderRadius: 12,
    }}>
      <Bar width={20} height={20} radius={5} />
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Bar width={30} height={38} radius={5} style={{ flexShrink: 0 }} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 7 }}>
          <Bar width="46%" height={13} radius={6} />
          <Bar width="30%" height={10} radius={5} style={{ opacity: 0.7 }} />
        </div>
      </div>
      <Bar width={80} height={12} radius={6} />
      <Bar width={70} height={12} radius={6} />
      <Bar width={24} height={12} radius={6} style={{ justifySelf: "end" }} />
      <Bar width={44} height={12} radius={6} style={{ justifySelf: "end" }} />
      <Bar width={20} height={6} radius={3} style={{ justifySelf: "end" }} />
    </div>
  );
}

function SkeletonCard() {
  return (
    <div style={{
      borderRadius: 14, border: "1px solid rgba(42,39,31,0.08)",
      overflow: "hidden", background: "#FDFCF9",
    }}>
      <div style={{
        height: 176, background: "#F2EFE8", padding: "16px 22px 0", boxSizing: "border-box",
      }}>
        <Bar width="100%" height={160} radius={0} style={{ borderRadius: "4px 4px 0 0" }} />
      </div>
      <div style={{
        padding: "12px 14px 14px", display: "flex", flexDirection: "column", gap: 8,
      }}>
        <Bar width="70%" height={13} radius={6} />
        <Bar width="45%" height={10} radius={5} style={{ opacity: 0.7 }} />
      </div>
    </div>
  );
}

export function LibrarySkeleton({ view }: { view: "list" | "panel" }) {
  return (
    <div aria-hidden="true" data-testid="library-skeleton" style={ROOT}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, flexShrink: 0 }}>
          <Bar width={124} height={40} radius={10} style={{ flexShrink: 0 }} />
        </div>
        <Bar
          width="100%"
          height={48}
          radius={12}
          style={{ flex: 1, minWidth: 0, maxWidth: 840, marginLeft: 24 }}
        />
        <Bar
          width={136}
          height={48}
          radius={12}
          style={{ flexShrink: 0, marginLeft: "auto" }}
        />
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 12, paddingBottom: 14,
        borderBottom: "1px solid rgba(42,39,31,0.10)",
      }}>
        <Bar width={230} height={40} radius={12} />
        <Bar width={104} height={40} radius={12} />
        <span style={{ flex: 1 }} />
        <Bar width={184} height={40} radius={12} />
      </div>

      {view === "list" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 6 }}>
          <div style={{
            display: "grid", gridTemplateColumns: LIST_COLS, gap: 12, padding: "12px 14px 8px",
          }}>
            <Bar width={20} height={20} radius={5} />
            <Bar width={48} height={11} radius={5} />
            <Bar width={52} height={11} radius={5} />
            <Bar width={38} height={11} radius={5} />
            <Bar width={40} height={11} radius={5} style={{ justifySelf: "end" }} />
            <Bar width={44} height={11} radius={5} style={{ justifySelf: "end" }} />
            <span />
          </div>
          {Array.from({ length: 9 }).map((_, i) => <SkeletonRow key={i} />)}
        </div>
      ) : (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))",
          gap: 24, paddingTop: 20,
        }}>
          {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      )}
    </div>
  );
}
