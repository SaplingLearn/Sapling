import Link from "next/link";

/** "← Study": the way back to the Study landing page from inside a tool,
 *  rendered as the TopBar breadcrumb above the tool's title. */
export function StudyBackLink() {
  return (
    <Link href="/study" data-testid="study-back-link" className="study-back-link">
      <span aria-hidden>←</span> Study
    </Link>
  );
}
