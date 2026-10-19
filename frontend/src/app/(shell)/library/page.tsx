import { Library } from "@/components/screens/Library";
import { SaplingSurface } from "@/components/sapling";

// Redesign tokens (prompt 01) scoped to the Library route only.
export default function LibraryPage() {
  return (
    <SaplingSurface>
      <Library />
    </SaplingSurface>
  );
}
