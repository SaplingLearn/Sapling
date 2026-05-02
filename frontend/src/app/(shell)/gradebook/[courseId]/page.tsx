"use client";
import { use } from "react";
import { GradebookCourseScreen } from "@/components/screens/Gradebook/Course";

export default function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  return <GradebookCourseScreen courseId={decodeURIComponent(courseId)} />;
}
