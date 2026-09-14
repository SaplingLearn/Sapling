import { Suspense } from "react";
import { QuizScreen } from "@/components/quiz";

/**
 * `QuizScreen` reads the entry off `useSearchParams`, which App Router requires
 * to sit under a Suspense boundary — the same wrapper the old `screens/Quiz.tsx`
 * chain carried, moved up to the route now that the screen is one component.
 */
export default function QuizPage() {
  return (
    <Suspense fallback={null}>
      <QuizScreen />
    </Suspense>
  );
}
