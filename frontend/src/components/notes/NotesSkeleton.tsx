"use client";
/**
 * The Notes page's loading skeleton: the header bar, the toolbar, the title
 * and paragraphs, a block, and the Clov panel — in the layout the content
 * will take, so nothing shifts when it arrives.
 *
 * It fades out at 720 ms while the content underneath runs its own entrance,
 * exactly as the Library's does.
 */
import React from "react";

import { Skeleton } from "../Skeleton";
import { CLOV_WIDTH } from "./ClovPanel";

function Bar({
  width, height, radius, style,
}: {
  width: number | string;
  height: number;
  radius: number;
  style?: React.CSSProperties;
}) {
  return (
    <Skeleton
      className="sapSkeleton"
      width={width}
      height={height}
      radius={radius}
      style={style}
    />
  );
}

export function NotesSkeleton({ clovOpen }: { clovOpen: boolean }) {
  return (
    <div aria-hidden="true" data-testid="notes-skeleton" style={{
      position: "absolute", inset: 0, zIndex: 40, background: "#FAF8F3",
      display: "flex", flexDirection: "column", pointerEvents: "none",
      animation: "sapSkelOut 260ms ease 720ms both",
    }}>
      <div style={{
        height: 76, flexShrink: 0, display: "flex", alignItems: "center", gap: 16,
        padding: "0 28px 0 32px",
      }}>
        <Bar width={96} height={32} radius={10} />
        <Bar width={300} height={20} radius={8} />
        <span style={{ flex: 1 }} />
        <Bar width={160} height={36} radius={10} />
        <Bar width={120} height={36} radius={10} />
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <div style={{ flex: 1, minWidth: 0, padding: "12px 48px 0" }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 26 }}>
            <Bar width={560} height={46} radius={14} />
          </div>
          <div style={{
            maxWidth: 944, margin: "0 auto", display: "flex", flexDirection: "column", gap: 12,
          }}>
            <Bar width="52%" height={38} radius={10} />
            <Bar width="26%" height={14} radius={7} style={{ marginBottom: 18 }} />
            <Bar width="22%" height={22} radius={8} />
            <Bar width="100%" height={13} radius={6} />
            <Bar width="95%" height={13} radius={6} />
            <Bar width="82%" height={13} radius={6} style={{ marginBottom: 14 }} />
            <Bar width="100%" height={170} radius={16} style={{ marginBottom: 14 }} />
            <Bar width="26%" height={22} radius={8} />
            <Bar width="100%" height={13} radius={6} />
            <Bar width="90%" height={13} radius={6} />
            <Bar width="64%" height={13} radius={6} />
          </div>
        </div>

        {clovOpen && (
          <div style={{
            width: CLOV_WIDTH, flexShrink: 0, borderLeft: "1px solid rgba(42,39,31,0.10)",
            padding: "20px 24px", boxSizing: "border-box", display: "flex",
            flexDirection: "column", gap: 14,
          }}>
            <Bar width={120} height={22} radius={8} style={{ marginBottom: 10 }} />
            <Bar width="80%" height={72} radius={14} />
            <Bar width="60%" height={48} radius={14} style={{ alignSelf: "flex-end" }} />
            <Bar width="85%" height={96} radius={14} />
            <span style={{ flex: 1 }} />
            <Bar width="100%" height={52} radius={14} style={{ marginBottom: 20 }} />
          </div>
        )}
      </div>
    </div>
  );
}
