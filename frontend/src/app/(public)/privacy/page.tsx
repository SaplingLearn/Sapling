import type { Metadata } from "next";
import { CompanionShell } from "@/components/companion/CompanionShell";
import { LegalDocumentPage } from "@/components/legal/LegalDocumentPage";
import { PRIVACY } from "@/lib/legal/documents";

/**
 * Privacy Policy.
 *
 * The twin of /terms: the text, its version and its "Last updated" date live
 * in lib/legal/documents.ts (the copy onboarding shows and a student agrees
 * to), and components/legal/LegalDocumentPage lays both documents out, so the
 * two legal pages read as one document set rather than two ports.
 */

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "How Sapling collects, protects, and uses your data — including document uploads, tutoring transcripts, and study analytics.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <CompanionShell current="/privacy">
      <LegalDocumentPage doc={PRIVACY} />
    </CompanionShell>
  );
}
