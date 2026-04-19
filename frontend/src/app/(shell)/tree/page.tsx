import { Suspense } from "react";
import { Tree } from "@/components/screens/Tree";

export default function TreePage() {
  return (
    <Suspense fallback={null}>
      <Tree />
    </Suspense>
  );
}
