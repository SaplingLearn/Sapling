import type { Metadata } from "next";
import { CompanionShell } from "@/components/companion/CompanionShell";
import { ACCENT, BODY, DISPLAY, INK, MONO, MUTED, SERIF  } from "@/lib/landing/companionType";

/**
 * Terms of Service.
 *
 * On the shared companion chrome, which supplies the header, the footer and
 * the page box. What is left here is the document.
 *
 * The layout is the interesting half. The box is 1116px wide and this page
 * used to set 15px prose in an 880px box of its own; dropped in as-is the
 * line ran past 145 characters. Capping the prose instead — a narrow column
 * pinned inside a frame everything else fills — is the failure /about
 * shipped: the h1 and the rules run the full width while every paragraph
 * hugs the left, and the page reads as broken rather than as narrow.
 *
 * So the document is built as columns rather than capped inside one, the way
 * /wiki was (#604). Each clause is a row: its heading in a fixed column, its
 * text in the rest. That leaves the prose 812px, and the type comes up to meet
 * it: 21px Spectral, measured in a browser at 1440px off real line boxes,
 * reads at a median 88 characters a line, range 80-91. Nothing is capped, so
 * the row rules, the masthead and every clause share one right edge.
 *
 * /privacy is the same document in the same shape. The constants below are
 * duplicated there on purpose and the two are meant to move together — they
 * are the pair a reader compares side by side.
 */

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "The terms that govern your use of Sapling's AI study tools.",
  alternates: { canonical: "/terms" },
};

const RULE = "1px solid rgba(42,39,31,0.08)";
/** Sized off the longest clause title ("6. Study Rooms and Social Features"). */
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
    title: "1. Eligibility",
    body: "Sapling is intended for use by students and individuals for personal educational purposes. As of the date above, access is limited to Boston University students and individuals invited to participate in our closed beta program; we may expand availability over time. By using the Service, you represent that you are at least 13 years of age. If you are under 18, you should have parental or guardian consent.",
  },
  {
    title: "2. Your Account",
    body: "You are responsible for maintaining the confidentiality of your account credentials. You agree not to share your account with others or use another person's account. You are responsible for all activity that occurs under your account.",
  },
  {
    title: "3. Acceptable Use",
    body: "You agree to use Sapling only for lawful, educational purposes. You may not:",
    list: [
      "Upload content you do not have the right to share (e.g., copyrighted course materials you are not permitted to distribute)",
      "Attempt to reverse-engineer, scrape, or abuse the Service's APIs",
      "Use the Service to harass, impersonate, or harm other users",
      "Attempt to circumvent any security or authentication measures",
    ],
  },
  {
    title: "4. User Content",
    body: "You retain ownership of any content you upload, including documents, syllabi, and notes. By uploading content to Sapling, you grant us a limited license to process and analyze that content solely for the purpose of providing the Service to you. We do not use your uploaded materials to train AI models.",
  },
  {
    title: "5. AI-Generated Content",
    body: "Sapling uses Google Gemini to generate tutoring responses, quizzes, flashcards, and study guides. AI-generated content may occasionally be inaccurate or incomplete. You should not rely on it as a substitute for official course materials, instructors, or academic advisors. We make no guarantees about the accuracy of AI outputs.",
  },
  {
    title: "6. Study Rooms and Social Features",
    body: "Study rooms are shared spaces. You are responsible for the messages you send and the conduct you engage in within rooms. We reserve the right to remove users who violate these terms.",
  },
  {
    title: "7. Intellectual Property",
    body: "Sapling's software, branding, and design are the intellectual property of the Sapling team. You may not copy, reproduce, or distribute any part of the Service without explicit permission.",
  },
  {
    title: "8. Termination",
    body: "We reserve the right to suspend or terminate your access to Sapling at any time, for any reason, including violation of these Terms.",
  },
  {
    title: "9. Disclaimer of Warranties",
    body: 'The Service is provided "as is" without warranties of any kind. We do not guarantee uninterrupted access, error-free operation, or that the Service will meet your specific academic needs.',
  },
  {
    title: "10. Limitation of Liability",
    body: "To the fullest extent permitted by law, the Sapling team shall not be liable for any indirect, incidental, or consequential damages arising from your use of the Service.",
  },
  {
    title: "11. Changes to These Terms",
    body: "We may update these Terms from time to time. Continued use of the Service after changes are posted constitutes acceptance of the revised Terms.",
  },
  {
    title: "12. Contact",
    body: "For questions about these Terms, please email us at ",
    link: { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" },
  },
];

export default function TermsPage() {
  return (
    <CompanionShell current="/terms">
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
            Terms of Service
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
                By accessing or using Sapling (&ldquo;the Service&rdquo;), you agree to be bound by these
                Terms of Service. If you do not agree, please do not use the Service.
              </p>
            </div>
          </div>

          {sections.map((section, i) => (
            <div key={section.title} style={{ ...ROW, ...enter(i + 1) }}>
              <div style={TITLE_CELL}>
                <h2 style={H2}>{section.title}</h2>
              </div>
              <div style={TEXT_CELL}>
                <p style={PROSE}>
                  {section.body}
                  {section.link && (
                    <a href={section.link.href} style={LINK}>
                      {section.link.label}
                    </a>
                  )}
                </p>
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
              </div>
            </div>
          ))}
        </div>
      </div>
    </CompanionShell>
  );
}
