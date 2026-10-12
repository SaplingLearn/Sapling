import { LEGAL_LAST_UPDATED, legalDateLabel } from "@/lib/legal";
import { pageMetadata } from "@/lib/seo/pageMetadata";
import { CONTACT_EMAIL } from "@/lib/contact";
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

export const metadata = pageMetadata({
  title: "Terms of Service",
  description:
    "The terms for using Sapling: eligibility (18+), academic integrity, your rights in uploaded course materials, shared course material, takedowns, and AI output.",
  path: "/terms",
});

const RULE = "1px solid rgba(42,39,31,0.08)";
/** Sized off the longest clause title ("3. Acceptable Use and Academic Integrity"). */
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

type Section = {
  title: string;
  body: string;
  link?: { label: string; href: string };
  bodySuffix?: string;
  list?: string[];
  bodyAfter?: string;
};

const MAIL = { label: CONTACT_EMAIL, href: `mailto:${CONTACT_EMAIL}` };

const sections: Section[] = [
  {
    title: "1. Eligibility",
    body: "You must be at least 18 years old to use Sapling. Sapling's AI features run on Google's Gemini API, whose terms do not permit use by anyone under 18. Sapling is in a free closed beta. Access is currently limited to Boston University students and people we invite, and we may change who can join. Sapling is an independent student project. It is not affiliated with, sponsored by, or endorsed by Boston University or any other school.",
  },
  {
    title: "2. Your Account",
    body: "You sign in with your Google account. Keep it secure and don't share your Sapling account or use someone else's. You are responsible for activity under your account.",
  },
  {
    title: "3. Acceptable Use and Academic Integrity",
    body: "Use Sapling lawfully and for your own learning. You may not:",
    list: [
      "Upload material you don't have the right to use in this way (see Section 4)",
      "Submit AI-generated content as your own work where your course or institution doesn't allow it. You are responsible for following your instructors' and your institution's academic integrity policies",
      "Reverse-engineer, scrape, overload, or abuse Sapling's systems or APIs, or try to get around its security or sign-in",
      "Use Sapling to harass, impersonate, or harm anyone, or to post unlawful content in study rooms",
    ],
  },
  {
    title: "4. Your Content and Course Materials",
    body: "You keep ownership of everything you upload, including documents, syllabi, notes, and messages. You are responsible for having the right to upload it. Course materials such as slides, readings, and handouts usually belong to your instructor, your institution, or a publisher. Only upload materials you are permitted to use for your own study, and don't upload anything you were asked not to share.",
    list: [
      "To run Sapling, you give us a limited, non-exclusive license to store, process, and analyze your content, including sending it to our AI and infrastructure providers as described in the Privacy Policy.",
      "If you leave Class Intel on and upload a document our system identifies as course material, you also allow us to use passages from it to answer questions and build quizzes for other students in the same course. You can withdraw this at any time by turning Class Intel off or deleting the document.",
      "We do not use your content to train AI models.",
    ],
  },
  {
    title: "5. Copyright Complaints and Takedowns",
    body: "If you believe content on Sapling infringes your copyright or other rights, email ",
    link: MAIL,
    bodySuffix: " with: your contact details; the work you believe is infringed; enough information for us to find the material; a statement that you believe in good faith that the use is not authorized; and a statement that your notice is accurate and that you are the rights holder or authorized to act for them. We will remove material that infringes, and we may suspend accounts that repeatedly upload infringing content.",
  },
  {
    title: "6. AI-Generated Content",
    body: "Sapling uses Google Gemini to generate tutoring responses, quizzes, flashcards, summaries, and study guides. AI output can be inaccurate or incomplete. Check it against your course materials, and don't rely on it in place of your instructors or academic advisors. We make no guarantees about the accuracy of AI output.",
  },
  {
    title: "7. Third-Party Services",
    body: "Sapling connects to services run by other companies, including Google (sign-in and Calendar) and, if you choose to connect it, Gradescope. Your use of those services is governed by their own terms. When you connect Gradescope, you authorize Sapling to sign in to it as you to read your courses and scores. Gradescope is not affiliated with Sapling.",
  },
  {
    title: "8. Study Rooms and Social Features",
    body: "Study rooms are shared spaces. You are responsible for what you post. We may remove content or members that violate these Terms.",
  },
  {
    title: "9. The Beta",
    body: "Sapling is free during the beta. Features may change, break, or be removed, and the service may be unavailable at times. If we introduce paid features, we will tell you before charging anything.",
  },
  {
    title: "10. Intellectual Property",
    body: "Sapling's software, branding, and design belong to the Sapling team. You may not copy, reproduce, or distribute any part of the service without our permission, except as the law allows.",
  },
  {
    title: "11. Ending Your Use",
    body: "You can stop using Sapling and delete your account at any time in Settings. Deleting your account removes your data as described in the Privacy Policy. We may suspend or end your access if you violate these Terms or misuse the service, or if we shut the beta down.",
  },
  {
    title: "12. Disclaimer of Warranties",
    body: 'Sapling is provided "as is" and "as available", without warranties of any kind. We do not guarantee uninterrupted access, error-free operation, or that Sapling will meet your academic needs.',
  },
  {
    title: "13. Limitation of Liability",
    body: "To the fullest extent permitted by law, the Sapling team is not liable for any indirect, incidental, special, or consequential damages, or for lost data or grades, arising from your use of Sapling.",
  },
  {
    title: "14. Governing Law",
    body: "These Terms are governed by the laws of the Commonwealth of Massachusetts, without regard to its conflict-of-laws rules.",
  },
  {
    title: "15. Changes to These Terms",
    body: "We may update these Terms. If a change is material, we will tell you in the app before it takes effect. Continuing to use Sapling after a change takes effect means you accept it.",
  },
  {
    title: "16. Contact",
    body: "Sapling is built and operated by the Sapling team. For questions about these Terms, takedown requests, or anything else, email ",
    link: MAIL,
    bodySuffix: ".",
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
              <time dateTime={LEGAL_LAST_UPDATED} style={META}>Last updated: {legalDateLabel()}</time>
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
                  {section.bodySuffix}
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
