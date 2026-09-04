import type { Metadata } from "next";
import { CompanionShell } from "@/components/companion/CompanionShell";
import { ACCENT, BODY, DISPLAY, INK, MONO, MUTED, SERIF  } from "@/lib/landing/companionType";

/**
 * Privacy Policy.
 *
 * The twin of /terms: same chrome, same row geometry, same type scale, so the
 * two legal pages read as one document set rather than two ports. See the
 * header comment there for why the clauses are columns instead of a capped
 * prose block — short version, the companion box is 1116px wide and a capped
 * column inside a full-width frame is what makes /about read as broken. The
 * clause text lands on 812px at 21px Spectral, a measured median of 86
 * characters a line here; bulleted items sit an indent in and run shorter.
 *
 * This document carries four section shapes the Terms does not — labelled
 * sub-lists, bolded highlight rows, a trailing paragraph after a list, and a
 * sentence that resumes after an inline mail link. All four render inside the
 * one text cell, so they share the clause measure and the clause left edge.
 */

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "How Sapling collects, protects, and uses your data — including document uploads, tutoring transcripts, and study analytics.",
  alternates: { canonical: "/privacy" },
};

const RULE = "1px solid rgba(42,39,31,0.08)";
/** Sized off the longest clause title ("4. How We Share Your Information"). */
const TITLE_COL = 220;
const COL_GAP = 32;

/**
 * A clause row.
 *
 * Wrapping flex rather than a grid so the two columns collapse to one on a
 * narrow screen: inline styles cannot carry a media query and these pages
 * have no stylesheet of their own. The text cell's 460px basis is what
 * triggers it — below ~764px of content width there is no room for both.
 */
const ROW: React.CSSProperties = {
  display: "flex", flexWrap: "wrap", alignItems: "flex-start",
  gap: COL_GAP, padding: "22px 0", borderTop: RULE,
};
/**
 * Both cells grow, but the text cell grows a thousand times harder. Side by
 * side that is invisible — the heading takes 264.35px of the 1116 rather than
 * 264 — and once the row wraps it is the whole point: each cell is alone on
 * its line and stretches to fill it, so the stacked heading keeps the same
 * right edge as the text under it instead of stopping 60px short.
 */
const TITLE_CELL: React.CSSProperties = { flex: `1 1 ${TITLE_COL}px`, maxWidth: "100%", minWidth: 0 };
const TEXT_CELL: React.CSSProperties = { flex: "999 1 330px", minWidth: 0 };

const H2: React.CSSProperties = {
  margin: 0, fontSize: 14.5, fontWeight: 600, lineHeight: 1.45,
  letterSpacing: "-0.01em", color: INK,
};
const PROSE: React.CSSProperties = {
  margin: 0, fontFamily: SERIF, fontSize: 16, lineHeight: 1.62, color: BODY,
};
const LIST: React.CSSProperties = {
  margin: "14px 0 0", padding: 0, listStyle: "none",
  display: "flex", flexDirection: "column", gap: 10,
};
const ITEM: React.CSSProperties = { ...PROSE, display: "flex", gap: 12 };
const BULLET: React.CSSProperties = { color: MUTED, flex: "0 0 auto" };
/** The sans label that introduces a sub-list, held off the serif around it. */
const SUBLABEL: React.CSSProperties = {
  margin: 0, fontSize: 14, fontWeight: 600, letterSpacing: "-0.005em", color: INK,
};
const META: React.CSSProperties = {
  display: "block", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.04em", color: MUTED,
};
const LINK: React.CSSProperties = { color: ACCENT };

/** Rows fade in down the page; the cap keeps the last clause from waiting. */
function enter(i: number): React.CSSProperties {
  return { animation: "fadeUp 700ms ease both", animationDelay: `${Math.min(120 + i * 40, 640)}ms` };
}

const sections = [
  {
    title: "1. Information We Collect",
    subsections: [
      {
        label: "Information you provide directly:",
        list: [
          "Account information (name, email address) via Google OAuth sign-in",
          "Course names, syllabus text, and assignment information you paste or upload",
          "Documents and PDFs you upload to your document library",
          "Messages sent in study room chats",
          "Feedback and bug reports you submit",
        ],
      },
      {
        label: "Information generated through your use of the Service:",
        list: [
          "Knowledge graph data (concepts studied, mastery scores, session history)",
          "Quiz responses and performance data",
          "Flashcard ratings and review history",
          "Tutoring session transcripts",
        ],
      },
      {
        label: "Information collected automatically:",
        list: [
          "Basic usage data and session metadata to maintain and improve the Service",
        ],
      },
    ],
  },
  {
    title: "2. How We Use Your Information",
    body: "We use the information we collect to:",
    list: [
      "Provide and personalize the Service, including updating your knowledge graph and generating AI content tailored to your performance",
      "Enable study room and social features, including anonymized class-wide insights",
      "Process and respond to feedback and issue reports",
      "Maintain the security and integrity of the Service",
    ],
  },
  {
    title: "3. Google OAuth and Calendar",
    body: "If you sign in with Google or connect your Google Calendar, we receive access tokens to authenticate you and, if you grant calendar access, to read and write assignment data. We do not access any Google data beyond what is necessary to provide the features you enable. You can revoke this access at any time through your Google account settings.",
  },
  {
    title: "4. How We Share Your Information",
    body: "We do not sell your personal data. We share information only in the following limited circumstances:",
    highlights: [
      { label: "Service providers:", text: "We use Supabase (database), Google Gemini (AI processing), and similar infrastructure providers. These providers process data on our behalf under their own privacy policies." },
      { label: "Study rooms:", text: "Your display name, avatar, and knowledge graph data are visible to other members of study rooms you join. Class-wide data shared with other users is anonymized." },
      { label: "Legal requirements:", text: "We may disclose information if required by law or to protect the rights and safety of our users." },
    ],
  },
  {
    title: "5. Data Retention",
    body: "We retain your data for as long as your account is active. You may request deletion of your account and associated data by submitting a request through the app's feedback tool.",
  },
  {
    title: "6. Security",
    body: "We take reasonable technical and organizational measures to protect your data:",
    highlights: [
      { label: "In transit:", text: "traffic between your browser and our servers is encrypted using HTTPS/TLS." },
      { label: "At rest (application layer):", text: "certain sensitive fields are encrypted by our backend using AES-256-GCM before they are written to the database. This currently covers your profile name, bio, and location; Google OAuth tokens; document summaries and AI-generated concept notes; tutoring chat messages; study room messages; tutoring session summaries; gradebook assignment scores and notes; and calendar assignment notes." },
      { label: "At rest (storage layer):", text: "our database provider (Supabase) enforces access controls and applies its own encryption at rest at the storage layer." },
    ],
    bodyAfter: "The encryption keys used for application-layer encryption are managed by Sapling, which means we — and the AI and infrastructure providers described in Section 4 — can technically decrypt your data when required to operate the Service. This is not end-to-end encryption. No system is completely secure, and we cannot guarantee absolute security.",
  },
  {
    title: "7. Children's Privacy",
    body: "Sapling is not directed at children under 13. We do not knowingly collect personal information from children under 13. If you believe a child under 13 has provided us with personal data, please email us at ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
    bodySuffix: " and we will take steps to delete it.",
  },
  {
    title: "8. Job Applicants",
    body: "If you apply for a position at Sapling, we collect the information you submit through our application form, including your name, email address, phone number, LinkedIn profile URL, and resume. This data is used solely to evaluate your application and communicate with you about the hiring process. We do not share applicant data with third parties outside of our core infrastructure providers. If your application is unsuccessful, we may retain your information for up to 12 months in case a suitable role arises. You may request deletion of your applicant data at any time by emailing ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
    bodySuffix: ".",
  },
  {
    title: "9. Changes to This Policy",
    body: "We may update this Privacy Policy from time to time. We will notify users of material changes by updating the date at the top of this page.",
  },
  {
    title: "10. Contact",
    body: "If you have questions or concerns about this Privacy Policy, please email us at ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
    bodySuffix: ".",
  },
];

export default function PrivacyPage() {
  return (
    <CompanionShell current="/privacy">
      <div>
        {/* No rule of its own: the first clause row below carries a
            `borderTop`, so a masthead border drew a second line 48px above
            it — two hairlines stacked between the title and the date. The
            row rule is the structural one (every clause has one), so the
            masthead defers to it and only keeps the space. */}
        <header style={{ paddingBottom: 30 }}>
          <span
            style={{
              display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em",
              textTransform: "uppercase", color: MUTED, animation: "fadeUp 600ms ease both",
            }}
          >
            Legal
          </span>
          <h1
            style={{
              margin: "14px 0 0", fontFamily: DISPLAY, fontWeight: 500, fontSize: 34,
              lineHeight: 1.15, letterSpacing: "-0.015em", color: INK,
              animation: "fadeUp 700ms ease 60ms both",
            }}
          >
            Privacy Policy
          </h1>
        </header>

        <div>
          {/* The date is metadata about the document, so it takes the heading
              column and the preamble takes the text column. That puts the
              opening paragraph on the same measure and the same left edge as
              every clause under it, instead of running the full width alone. */}
          <div style={{ ...ROW, ...enter(0) }}>
            <div style={TITLE_CELL}>
              <span style={META}>Last updated: May 3, 2026</span>
            </div>
            <div style={TEXT_CELL}>
              <p style={PROSE}>
                This Privacy Policy explains how Sapling (&ldquo;we,&rdquo; &ldquo;us,&rdquo; or &ldquo;our&rdquo;) collects,
                uses, and protects your information when you use our Service.
              </p>
            </div>
          </div>

          {sections.map((section, i) => (
            <div key={section.title} style={{ ...ROW, ...enter(i + 1) }}>
              <div style={TITLE_CELL}>
                <h2 style={H2}>{section.title}</h2>
              </div>
              <div style={TEXT_CELL}>
                {section.body && (
                  <p style={PROSE}>
                    {section.body}
                    {section.link && (
                      <a href={section.link.href} style={LINK}>
                        {section.link.label}
                      </a>
                    )}
                    {section.bodySuffix}
                  </p>
                )}

                {section.list && (
                  <ul style={LIST}>
                    {section.list.map((item) => (
                      <li key={item} style={ITEM}>
                        <span style={BULLET}>&bull;</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                )}

                {section.subsections && (
                  <div
                    style={{
                      marginTop: section.body ? 16 : 0,
                      display: "flex", flexDirection: "column", gap: 22,
                    }}
                  >
                    {section.subsections.map((sub) => (
                      <div key={sub.label}>
                        <p style={SUBLABEL}>{sub.label}</p>
                        <ul style={{ ...LIST, marginTop: 10 }}>
                          {sub.list.map((item) => (
                            <li key={item} style={ITEM}>
                              <span style={BULLET}>&bull;</span>
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}

                {section.highlights && (
                  <ul style={LIST}>
                    {section.highlights.map((h) => (
                      <li key={h.label} style={ITEM}>
                        <span style={BULLET}>&bull;</span>
                        <span>
                          <strong style={{ color: INK, fontWeight: 600 }}>{h.label}</strong>{" "}
                          {h.text}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                {section.bodyAfter && (
                  <p style={{ ...PROSE, marginTop: 16 }}>{section.bodyAfter}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </CompanionShell>
  );
}
