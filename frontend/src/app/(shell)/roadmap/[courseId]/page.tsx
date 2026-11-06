"use client";
import { use } from "react";
import { RoadmapScreen } from "@/components/screens/Roadmap/Roadmap";

export default function RoadmapPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  return <RoadmapScreen courseId={decodeURIComponent(courseId)} />;
}
