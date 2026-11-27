"use client";
import React from "react";
import { cn } from "@/lib/cn";

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
      className={cn(`skeleton ${className || ""}`.trim(), "block")}
      aria-hidden
      style={{ width, height, borderRadius: r, ...style }}
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
    <div className="flex flex-col" style={{ gap }}>
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
      className="grid grid-cols-[repeat(auto-fill,_minmax(280px,_1fr))] gap-4"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="card p-(--pad-lg) flex flex-col gap-2.5"
        >
          <div
            className="flex justify-between items-start"
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
    <div className="card p-0">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={cn("flex items-center gap-4 py-3.5 px-5", i < count - 1 ? "border-b border-b-border" : "border-b-0")}
        >
          <Skeleton width={28} height={36} radius="var(--r-xs)" />
          <div className="flex-1 min-w-0 flex flex-col gap-1.5">
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
      className="flex flex-col gap-4 py-5 px-0 max-w-225 my-0 mx-auto"
    >
      <section
        className="flex gap-5 items-start p-(--pad-lg) bg-bg-panel border border-border rounded-xl"
      >
        <Skeleton width={88} height={88} circle />
        <div className="flex-1 min-w-0 flex flex-col gap-2.5">
          <Skeleton width="40%" height={26} />
          <Skeleton width="20%" height={11} />
          <div className="flex gap-1.5 mt-1">
            <Skeleton width={64} height={20} radius={999} />
            <Skeleton width={80} height={20} radius={999} />
          </div>
          <SkeletonText lines={2} lineHeight={11} lastWidth="70%" />
          <div className="flex gap-3.5 mt-1">
            <Skeleton width={120} height={11} />
            <Skeleton width={80} height={11} />
            <Skeleton width={100} height={11} />
          </div>
        </div>
      </section>

      <section
        className="py-2.5 px-0 border-t border-t-border border-b border-b-border flex gap-3.5"
      >
        <Skeleton width={120} height={14} />
        <Skeleton width={120} height={14} />
        <Skeleton width={120} height={14} />
        <Skeleton width={140} height={14} />
      </section>

      <section className="card p-(--pad-lg)">
        <Skeleton width={120} height={10} style={{ marginBottom: 12 }} />
        <div className="flex gap-2 flex-wrap">
          <Skeleton width={90} height={22} radius={999} />
          <Skeleton width={120} height={22} radius={999} />
          <Skeleton width={70} height={22} radius={999} />
        </div>
      </section>

      <section className="card p-(--pad-lg)">
        <Skeleton width={160} height={10} style={{ marginBottom: 12 }} />
        <div
          className="grid grid-cols-[repeat(auto-fill,_minmax(140px,_1fr))] gap-2.5"
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
      className="pt-4.5 px-8 pb-6 grid gap-4 grid-cols-[minmax(0,_1fr)_minmax(280px,_360px)] flex-1 min-h-0"
    >
      <div className="flex flex-col gap-3.5 min-w-0">
        <Skeleton width={140} height={11} />
        <Skeleton width="55%" height={42} />
        <Skeleton width="80%" height={14} />
        <div
          className="card p-0 overflow-hidden min-h-105 flex flex-col flex-1"
        >
          <div
            className="flex justify-between items-center py-4 px-5.5 border-b border-b-border"
          >
            <div className="flex flex-col gap-1.5">
              <Skeleton width={140} height={10} />
              <Skeleton width={260} height={20} />
            </div>
            <Skeleton width={32} height={28} radius="var(--r-sm)" />
          </div>
          <div className="flex-1 min-h-65 p-5.5 grid place-items-center">
            <Skeleton width={200} height={200} circle style={{ opacity: 0.5 }} />
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 min-w-0">
        <div className="flex justify-end gap-2 min-h-7.5">
          <Skeleton width={80} height={28} radius="var(--r-sm)" />
          <Skeleton width={120} height={28} radius="var(--r-sm)" />
        </div>
        <div className="card p-0 grid grid-cols-[1fr_1fr]">
          <div className="py-4 px-4.5 border-r border-r-border flex flex-col gap-2">
            <Skeleton width={60} height={10} />
            <Skeleton width={70} height={32} />
            <Skeleton width={100} height={10} />
          </div>
          <div className="py-4 px-4.5 flex flex-col gap-2">
            <Skeleton width={60} height={10} />
            <Skeleton width={50} height={32} />
            <Skeleton width={100} height={10} />
          </div>
        </div>
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="card p-(--pad-lg)">
            <Skeleton width={80} height={10} style={{ marginBottom: 8 }} />
            <Skeleton width="60%" height={16} style={{ marginBottom: 14 }} />
            {Array.from({ length: 3 }).map((__, j) => (
              <div
                key={j}
                className="flex gap-2.5 py-2.5 px-3 rounded-md bg-bg-subtle mb-1.5 items-center"
              >
                <Skeleton width={20} height={20} circle />
                <div className="flex-1 flex flex-col gap-1.5">
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
    <div className="py-5 px-8">
      <div className="grid grid-cols-[repeat(7,_1fr)] gap-1 mb-1">
        {weekdays.map(d => (
          <div key={d} className="label-micro p-1.5">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-[repeat(7,_1fr)] gap-1">
        {Array.from({ length: 42 }).map((_, i) => (
          <div
            key={i}
            className="card p-2 min-h-24 flex flex-col gap-1.5"
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
    <div className="py-6 px-8">
      <Skeleton width={220} height={11} style={{ marginBottom: 12 }} />
      <div className="grid grid-cols-[repeat(5,_1fr)] gap-2.5 mb-7.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="card p-3 min-h-23 flex flex-col gap-2 items-center"
          >
            <Skeleton width={32} height={32} circle />
            <Skeleton width="80%" height={10} />
          </div>
        ))}
      </div>
      <Skeleton width={120} height={10} style={{ marginBottom: 12 }} />
      <div className="grid grid-cols-[repeat(auto-fill,_minmax(320px,_1fr))] gap-3.5">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card p-(--pad-lg) flex gap-3.5">
            <Skeleton width={52} height={52} radius="var(--r-md)" />
            <div className="flex-1 flex flex-col gap-2">
              <div className="flex justify-between gap-1.5">
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
    <div className="p-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="py-2.5 px-3 rounded-md mb-1 flex flex-col gap-1.5"
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
    <div className="max-w-160 my-0 mx-auto py-6 px-8">
      <Skeleton width={120} height={22} style={{ marginBottom: 20 }} />
      <div
        className="card p-(--pad-lg) flex gap-5 items-center mb-4"
      >
        <Skeleton width={72} height={72} circle />
        <div className="flex-1 flex flex-col gap-1.5">
          <Skeleton width={140} height={18} />
          <Skeleton width={180} height={11} />
        </div>
        <Skeleton width={120} height={28} radius="var(--r-sm)" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[180px_1fr] gap-4 py-3 px-0 border-b border-b-border items-center"
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
    <div className="flex-1 grid place-items-center">
      <div className="flex flex-col items-center gap-3.5">
        <Skeleton width={220} height={220} circle style={{ opacity: 0.6 }} />
        <Skeleton width={180} height={11} />
      </div>
    </div>
  );
}

export function FlashcardsSkeleton() {
  return (
    <div className="py-6 px-8 max-w-180 my-0 mx-auto">
      <div className="flex justify-between items-center mb-4">
        <Skeleton width={160} height={11} />
        <Skeleton width={120} height={28} radius="var(--r-sm)" />
      </div>
      <div
        className="card p-(--pad-lg) min-h-70 flex flex-col gap-3.5 justify-center items-center"
      >
        <Skeleton width="60%" height={18} />
        <SkeletonText lines={3} lineHeight={12} lastWidth="55%" />
      </div>
      <div className="flex gap-2 mt-4 justify-center">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} width={100} height={36} radius="var(--r-sm)" />
        ))}
      </div>
    </div>
  );
}

/**
 * The Study hub while its courses and concepts load (#v3). Mirrors the real
 * layout — header, readiness block, focus card, roadmap columns, right rail —
 * so nothing jumps when the data lands, and so the "Add a course" empty state
 * is never flashed at a student who simply has not finished loading.
 */
export function StudyHubSkeleton({ isMobile = false }: { isMobile?: boolean }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading your study hub"
      role="status"
      className={cn("grid gap-x-10 [align-content:start] box-border bg-bg", isMobile ? "h-auto" : "h-full", isMobile ? "min-h-full" : "min-h-160", isMobile ? "grid-cols-[minmax(0,_1fr)]" : "grid-cols-[minmax(0,_1fr)_340px]", isMobile ? "pt-2 px-5 pb-4" : "pt-4.5 px-8 pb-0")}
    >
      <div className={cn("flex items-center gap-4 pt-1.5 px-0 pb-4.5", isMobile ? "[grid-column:1]" : "[grid-column:1_/_3]")}>
        <Skeleton width={120} height={48} radius={10} />
        <Skeleton width={240} height={20} />
        <Skeleton width={120} height={20} style={{ marginLeft: "auto" }} />
      </div>

      <div className="flex flex-col gap-5.5 min-w-0">
        <div className="flex gap-7">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <Skeleton width={120} height={16} />
              <Skeleton width={90} height={12} />
            </div>
          ))}
        </div>
        <div className={cn("grid gap-7 items-center", isMobile ? "grid-cols-[1fr]" : "grid-cols-[minmax(0,_300px)_minmax(0,_1fr)]")}>
          <div className="flex flex-col gap-3">
            <Skeleton width={180} height={52} radius={12} />
            <div className="flex gap-1.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} width={18} height={18} radius={4} />
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} width={104} height={28} radius={999} />
              ))}
            </div>
          </div>
          <Skeleton height={170} radius={16} style={{ opacity: 0.75 }} />
        </div>

        <div className="flex flex-col gap-3">
          <Skeleton width={90} height={11} />
          <div className="flex gap-6">
            {Array.from({ length: 3 }).map((_, col) => (
              <div key={col} className="flex-1 min-w-0 flex flex-col gap-2.5">
                <Skeleton width="70%" height={15} />
                <Skeleton width="100%" height={4} radius={2} />
                {Array.from({ length: 2 }).map((_, row) => (
                  <Skeleton key={row} height={50} radius={10} />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      {!isMobile && (
        <div className="flex flex-col gap-6.5">
          <Skeleton width={120} height={11} />
          <Skeleton width={150} height={40} />
          <Skeleton height={96} radius={12} />
          <Skeleton height={58} radius={10} />
          <Skeleton width={130} height={11} />
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} height={38} radius={10} />
          ))}
        </div>
      )}
    </div>
  );
}

export function AdminTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="card p-0 overflow-hidden">
      <div
        className="grid grid-cols-[32px_1fr_1fr_1fr_100px] gap-3 py-2.5 px-3.5 bg-bg-subtle border-b border-b-border"
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} width={i === 0 ? 14 : "60%"} height={11} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className={cn("grid grid-cols-[32px_1fr_1fr_1fr_100px] gap-3 py-3 px-3.5 items-center", i === 0 ? "border-t-0" : "border-t border-t-border")}
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
