import { Suspense } from "react";
import { GuidesHome } from "@/components/studyGuide/home/GuidesHome";

/**
 * `GuidesHome` reads how it was opened (`?new=1`, `?course=`) off
 * `useSearchParams`, which App Router requires to sit under a Suspense
 * boundary.
 */
export default function StudyGuidesPage() {
  return (
    <Suspense fallback={null}>
      <GuidesHome />
    </Suspense>
  );
}
