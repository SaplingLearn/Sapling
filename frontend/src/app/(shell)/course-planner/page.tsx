"use client";
import { TopBar } from "@/components/TopBar";
import { Icon } from "@/components/Icon";
import { FullHeightScreen } from "@/components/FullHeightScreen";

export default function CoursePlannerPage() {
  return (
    <FullHeightScreen>
      <TopBar title="Course Planner" />
      <main
        className="flex-1 flex flex-col items-center justify-center p-8 gap-3.5 text-center"
      >
        <div
          className="inline-flex items-center gap-2 py-1.5 px-3.5 rounded-[var(--r-full)] bg-accent-soft text-accent text-base font-semibold"
        >
          <Icon name="sparkle" size={12} />
          Coming soon
        </div>
        <div className="h-serif text-[28px] font-medium">
          Course Planner
        </div>
        <div className="text-text-dim text-base max-w-120 leading-[1.55]">
          Plan semesters, map prerequisites, and project your degree timeline. We&apos;re still
          building it — check back soon.
        </div>
      </main>
    </FullHeightScreen>
  );
}
