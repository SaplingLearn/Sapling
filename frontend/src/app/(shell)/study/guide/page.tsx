import { Suspense } from "react";

import { GuidesHome } from "@/components/studyGuide/home/GuidesHome";

/**
 * `GuidesHome` reads `?saved=1` off `useSearchParams`, which App Router
 * requires to sit under a Suspense boundary (the convention `/quiz` and
 * `/dashboard` follow).
 */
export default function StudyGuidesPage() {
  return (
    <Suspense fallback={null}>
      <GuidesHome />
    </Suspense>
  );
}
