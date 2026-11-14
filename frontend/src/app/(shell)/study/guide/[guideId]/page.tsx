"use client";
import { use } from "react";

import { GuideReader } from "@/components/studyGuide/reader/GuideReader";

export default function StudyGuideReaderPage({ params }: { params: Promise<{ guideId: string }> }) {
  const guideId = decodeURIComponent(use(params).guideId);
  // Keyed, so moving from one guide to another starts the reader afresh.
  return <GuideReader key={guideId} guideId={guideId} />;
}
