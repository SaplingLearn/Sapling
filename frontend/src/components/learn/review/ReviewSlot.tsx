"use client";
// Study's review queue: with `review_v2` on, the rebuilt head and its course
// scope (ReviewHead.tsx); the queue is keyed on the scope, so a new pick
// starts that course's queue fresh. Off: the queue over every course, as before.
import React, { useState } from "react";
import { useFlag } from "@/context/FlagsContext";
import type { EnrolledCourse } from "@/lib/api";
import { DueQueue } from "../DueQueue";

export function ReviewSlot({ userId, courses }: { userId: string; courses: readonly EnrolledCourse[] }) {
  const v2 = useFlag("review_v2") === "on";
  const [scope, setScope] = useState("");
  if (!v2) return <DueQueue userId={userId} />;
  // A course that left the list (a new semester) falls back to every course.
  const value = courses.some((c) => c.course_id === scope) ? scope : "";
  return (
    <DueQueue key={value || "all"} userId={userId} courseId={value || undefined}
      scope={{ courses, value, onChange: setScope }} />
  );
}
