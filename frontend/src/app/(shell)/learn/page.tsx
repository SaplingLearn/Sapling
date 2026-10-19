import { Learn } from "@/components/screens/Learn";
import { SaplingSurface } from "@/components/sapling";

// Learn and Tutor are two views of this ONE route and learning engine; the
// redesign tokens (prompt 01) are scoped to it, never to other routes.
export default function LearnPage() {
  return (
    <SaplingSurface>
      <Learn />
    </SaplingSurface>
  );
}
