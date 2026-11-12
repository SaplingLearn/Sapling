import { Suspense } from "react";
import { StudyGuide } from "@/components/screens/StudyGuide";

/**
 * `StudyGuide` reads the course and exam it was opened on off
 * `useSearchParams`, which App Router requires to sit under a Suspense
 * boundary.
 */
export default function StudyGuidePage() {
  return (
    <Suspense fallback={null}>
      <StudyGuide />
    </Suspense>
  );
}
