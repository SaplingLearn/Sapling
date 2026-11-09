import { notFound } from "next/navigation";
import GraphPreview from "./GraphPreview";

// Dev-only sandbox for the radial knowledge-graph layout: renders the real
// KnowledgeGraph2D against a large hand-written dataset, no sign-in needed.
// 404s in production builds.
export default function GraphPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <GraphPreview />;
}
