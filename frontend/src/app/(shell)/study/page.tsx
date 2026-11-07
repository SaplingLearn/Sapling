import { Suspense } from "react";
import { Study } from "@/components/screens/Study";
import { StudyHub } from "@/components/screens/StudyHub";

/**
 * `/study` is the Study landing page (one card per tool); `?mode=guide` and
 * `?mode=cards` open the tools themselves (Quiz lives at `/quiz`). Deciding
 * here, off the route's own searchParams, keeps `Study` itself unchanged: it
 * still defaults to the guide for any mode other than "cards".
 */
export default async function StudyPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string | string[] }>;
}) {
  const { mode } = await searchParams;
  if (!mode) return <StudyHub />;
  return (
    <Suspense fallback={null}>
      <Study />
    </Suspense>
  );
}
