import { notFound } from "next/navigation";
import { PenGraphReference } from "@/components/graph/PenGraphReference";

/** Local/test-only source fixture. Student screens always render live IDs
 * through KnowledgeGraph; sample design labels never enter that data path. */
export default function KnowledgeGraphDesignReference() {
  if (process.env.NODE_ENV !== "development" && process.env.NEXT_PUBLIC_TEST_MODE !== "1") notFound();
  return <main style={{ width: 893, height: 601, padding: 0, margin: 0, lineHeight: 0 }}>
    <PenGraphReference />
  </main>;
}
