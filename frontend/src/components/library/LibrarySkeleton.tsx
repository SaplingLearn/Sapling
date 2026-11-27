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
import { CONTROL_H } from "./primitives";

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
    <div className="grid grid-cols-[24px_minmax(0,_1fr)_120px_120px_56px_64px_40px] gap-3 items-center py-3 px-3.5 rounded-[12px]">
      <Bar width={20} height={20} radius={5} />
      <div className="flex items-center gap-3.5">
        <Bar width={30} height={38} radius={5} style={{ flexShrink: 0 }} />
        <div className="flex-1 flex flex-col gap-[7px]">
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
    <div className="rounded-[14px] border border-[rgba(42,39,31,0.08)] overflow-hidden bg-bg-panel">
      <div className="h-44 bg-[#F2EFE8] pt-4 px-5.5 pb-0 box-border">
        <Bar width="100%" height={160} radius={0} style={{ borderRadius: "4px 4px 0 0" }} />
      </div>
      <div className="pt-3 px-3.5 pb-3.5 flex flex-col gap-2">
        <Bar width="70%" height={13} radius={6} />
        <Bar width="45%" height={10} radius={5} style={{ opacity: 0.7 }} />
      </div>
    </div>
  );
}

export function LibrarySkeleton({ view }: { view: "list" | "panel" }) {
  return (
    <div aria-hidden="true" data-testid="library-skeleton" className="absolute inset-0 z-40 bg-ink-0 pt-9 pr-16 pb-0 pl-14 box-border flex flex-col pointer-events-none [animation:sapSkelOut_260ms_ease_720ms_both]">
      <div className="flex items-center gap-4 mb-6">
        <div className="flex flex-col gap-3.5 shrink-0">
          <Bar width={124} height={40} radius={10} style={{ flexShrink: 0 }} />
        </div>
        <Bar
          width="100%"
          height={CONTROL_H}
          radius={12}
          style={{ flex: 1, minWidth: 0, maxWidth: 840, marginLeft: 24 }}
        />
        <Bar
          width={136}
          height={CONTROL_H}
          radius={12}
          style={{ flexShrink: 0, marginLeft: "auto" }}
        />
      </div>

      <div className="flex items-center gap-3 pb-3.5 border-b border-b-[rgba(42,39,31,0.10)]">
        {/* The course switcher. No second bar: the Trash chip that sat
            beside it is now the switcher's last option. */}
        <Bar width={230} height={40} radius={12} />
        <span className="flex-1" />
        <Bar width={184} height={40} radius={12} />
      </div>

      {view === "list" ? (
        <div className="flex flex-col gap-1 pt-1.5">
          <div className="grid grid-cols-[24px_minmax(0,_1fr)_120px_120px_56px_64px_40px] gap-3 pt-3 px-3.5 pb-2">
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
        <div className="grid grid-cols-[repeat(auto-fill,_minmax(250px,_1fr))] gap-6 pt-5">
          {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      )}
    </div>
  );
}
