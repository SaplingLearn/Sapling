import { Suspense } from "react";
import { Social } from "@/components/screens/Social";

export default function SocialPage() {
  return (
    <Suspense fallback={null}>
      <Social />
    </Suspense>
  );
}
