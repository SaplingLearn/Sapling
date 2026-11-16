import type { Metadata } from "next";
import { CompanionShell } from "@/components/companion/CompanionShell";
import { LegalDocumentPage } from "@/components/legal/LegalDocumentPage";
import { TERMS } from "@/lib/legal/documents";

/**
 * Terms of Service.
 *
 * The text, its version and its "Last updated" date live in
 * lib/legal/documents.ts, the copy onboarding shows and a student agrees to;
 * the layout is components/legal/LegalDocumentPage, shared with /privacy so
 * the pair a reader compares side by side keep the same shape.
 */

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "The terms that govern your use of Sapling's AI study tools.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <CompanionShell current="/terms">
      <LegalDocumentPage doc={TERMS} />
    </CompanionShell>
  );
}
