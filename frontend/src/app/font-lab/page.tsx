import { FontLab } from "@/components/fontlab/FontLab";

// Deliberately outside both the `(shell)` and `(public)` route groups: this
// is an internal design tool, not a page a real user should land on. Living
// outside `(shell)` also keeps it off `middleware.ts`'s PROTECTED list (which
// matches on the `/dashboard` prefix) and out from under the real SideNav —
// the whole point is a preview rail that isn't the live one.
export const metadata = {
  title: "Font Lab",
  robots: { index: false, follow: false },
};

export default function FontLabPage() {
  return <FontLab />;
}
