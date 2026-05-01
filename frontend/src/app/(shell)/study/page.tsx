import { Suspense } from "react";
import { Study } from "@/components/screens/Study";

export default function StudyPage() {
  return (
    <Suspense fallback={null}>
      <Study />
    </Suspense>
  );
}
