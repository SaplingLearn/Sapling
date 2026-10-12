import { LEGAL_LAST_UPDATED, legalDateLabel } from "@/lib/legal";
import { pageMetadata } from "@/lib/seo/pageMetadata";
import { CONTACT_EMAIL } from "@/lib/contact";
import { CompanionShell } from "@/components/companion/CompanionShell";
import { ACCENT_TEXT, BODY, DISPLAY, INK, MONO, MUTED, SERIF } from "@/lib/landing/companionType";

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

export const metadata = pageMetadata({
  title: "Privacy Policy",
  description:
    "What Sapling collects, how Google Gemini processes it, when course material is shared with classmates, how Google user data is used, and how to delete it.",
  path: "/privacy",
});

const RULE = "1px solid rgba(42,39,31,0.08)";
/** Sized off the longest clause title ("4. Shared Course Material (Class Intel)"). */
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
const LINK: React.CSSProperties = { color: ACCENT_TEXT, textDecoration: 'underline' };

/** Rows fade in down the page; the cap keeps the last clause from waiting. */
function enter(i: number): React.CSSProperties {
  return { animation: "fadeUp 700ms ease both", animationDelay: `${Math.min(120 + i * 40, 640)}ms` };
}

const sections = [
  {
    title: "1. Information We Collect",
    subsections: [
      {
        label: "Information you provide:",
        list: [
          "Your Google account details when you sign in: name, email address, profile photo, and Google account ID",
          "Your profile and onboarding answers: username, school, year, majors and minors, learning style, the courses you take, and optionally a bio and location",
          "Documents you upload. We extract their text and do not keep the original file",
          "Notes, tutoring conversations, study room messages and images, and gradebook entries",
          "Your Gradescope login or session details, if you choose to connect Gradescope. If you connect through your school's single sign-on, your school password is used once to sign in and is not stored",
          "Feedback and issue reports, including any screenshots you attach",
          "Your email address, if you join the waitlist or subscribe to the Journal",
        ],
      },
      {
        label: "Information created as you use Sapling:",
        list: [
          "Your knowledge graph: concepts, mastery scores, and how they changed",
          "Quiz questions, your answers and results; flashcards and your ratings; study guides; document summaries",
          "XP, streaks, and achievements",
        ],
      },
      {
        label: "Information collected automatically:",
        list: [
          "A session cookie that keeps you signed in, and short-lived cookies that protect the sign-in flow",
          "Request logs kept by our hosting providers, which include the pages and API routes you request (these contain your user ID) and your IP address",
          "Usage events and AI usage records, such as which feature ran and how many AI tokens it used. These do not contain the text of your messages or documents",
        ],
      },
    ],
    bodyAfter: "We do not use advertising trackers or third-party analytics, and we do not sell your personal information.",
  },
  {
    title: "2. How We Use Your Information",
    body: "We use your information to:",
    list: [
      "Run Sapling for you: build your knowledge graph, and generate tutoring, quizzes, flashcards, summaries, and study guides from your own material",
      "Improve answers for students in the same course through shared course material, as described in Section 4",
      "Put assignment dates on your Google Calendar and sync grades from Gradescope, when you ask us to",
      "Run study rooms and the social features you choose to use",
      "Respond to your feedback, keep the service secure, and understand overall usage so we can fix and improve it",
    ],
  },
  {
    title: "3. AI Processing",
    body: "Sapling's AI features run on Google's Gemini API. When you use one, the content it needs (for example a document's text, your note, your recent conversation with the tutor, relevant course passages, and in some features your name or the names of study room members) is sent to Google to produce the response. We also send passages of your documents to Google to compute search embeddings, which are numerical representations used to find relevant material.",
    highlights: [
      { label: "No training on your content:", text: "we do not use your content to train AI models. We use Gemini as a paid API service, under which Google's terms say it does not use prompts or responses to improve its products. Google may keep them for a limited time to detect abuse." },
      { label: "Accuracy:", text: "AI output can be wrong. See the Terms of Service." },
    ],
  },
  {
    title: "4. Shared Course Material (Class Intel)",
    body: "When you upload a document that Sapling's classifier confidently identifies as course material (a syllabus, slides, a reading, a handout), and your Class Intel setting is on, passages from that document are added to a pool for that course. The pool covers every section and term of the same course code. Sapling's tutor and quizzes for other students in that course can draw on those passages and may quote or paraphrase them. Your name is not attached to them.",
    list: [
      "Class Intel is on by default. You can turn it off with the Class Intel control on the Learn screen. Turning it off makes your existing and future uploads private to you.",
      "Documents the classifier identifies as your own completed work or personal notes are always kept private. Classification is automated and can be wrong, so turn Class Intel off if you don't want any of your uploads shared.",
      "Deleting a document withdraws its passages from the pool. A passage stays only if another student uploaded the identical text, because it is then their upload too.",
    ],
  },
  {
    title: "5. Google User Data",
    body: "When you sign in with Google, we receive your name, email address, profile photo, and Google account ID. We also ask for permission to read your Google Calendar events and to create events, so we can show your calendar alongside your assignments and add assignment dates to it. Calendar events we read are shown to you but not stored on our servers, and they are never sent to our AI provider. We store the Google sign-in tokens, encrypted, so the calendar features keep working.",
    highlights: [
      { label: "Limited Use:", text: "Sapling's use and transfer of information received from Google APIs to any other app will adhere to the Google API Services User Data Policy, including the Limited Use requirements. We use Google user data only to provide the features described here. We do not use it for advertising, we do not sell it, and we do not use it to train AI models. People on our team do not read it unless you ask us to, it is needed for security, or the law requires it." },
      { label: "Revoking access:", text: "you can remove Sapling's access at any time at myaccount.google.com/permissions. Deleting your Sapling account also revokes our access." },
    ],
  },
  {
    title: "6. How We Share Information",
    body: "We share information only in these cases:",
    highlights: [
      { label: "Service providers that run Sapling for us:", text: "Supabase (database and file storage), Google (Gemini AI, sign-in, and Calendar), Railway (backend hosting), Cloudflare (website hosting and delivery), and, when enabled, monitoring tools such as Pydantic Logfire that receive technical telemetry about errors and performance. They process data on our behalf and under their own terms." },
      { label: "Gradescope:", text: "if you connect it, we sign in to Gradescope as you, using the details you provide, to read your courses and scores." },
      { label: "Other students:", text: "study room members can see your display name, avatar, messages, and knowledge graph. Room summaries are written by AI and can mention members by name. Your profile (display name, username, avatar, and the achievements you choose to feature) is public by default, meaning anyone with the link can view it. In Settings you can limit it to your school or make it private. Course material may be shared as described in Section 4." },
      { label: "Legal requirements:", text: "we may disclose information if the law requires it, or to protect the rights and safety of our users." },
    ],
  },
  {
    title: "7. Retention and Deletion",
    body: "We keep your data while your account is active.",
    highlights: [
      { label: "Deleting a document:", text: "deletes its extracted text, summary, and notes, and withdraws its passages from search and from shared course material. Concepts it added to your knowledge graph stay until you remove them." },
      { label: "Deleting your account:", text: "use Settings → Data → Delete my account. We delete your account and the data tied to it, withdraw your shared course material, revoke our Google access, and remove your avatar, chat images, and screenshots. A study room you created passes to another member, or is deleted if it is empty. We keep usage and AI-usage counts with your identity removed." },
      { label: "Backups and logs:", text: "copies in our providers' backups and logs expire on their normal schedules." },
      { label: "Export:", text: "Settings → Data → Export currently includes your profile, settings, roles, achievements, and cosmetics. For a complete copy of your data, email us and we will provide it." },
      { label: "Journal and waitlist:", text: "your newsletter email is kept separately from your account. Unsubscribe with the link in any Journal email, or email us to remove it." },
    ],
  },
  {
    title: "8. Cookies and Local Storage",
    body: "We use one essential session cookie (which lasts up to 30 days), short-lived cookies that secure the sign-in flow, and your browser's local storage for preferences and to remember who is signed in on that device. We do not use advertising or analytics cookies.",
  },
  {
    title: "9. Security",
    body: "We take reasonable technical and organizational measures to protect your data:",
    highlights: [
      { label: "In transit:", text: "traffic between your browser and our servers is encrypted with HTTPS/TLS." },
      { label: "At rest (application layer):", text: "our backend encrypts sensitive fields with AES-256-GCM before they are stored. These are your email address, name, bio, and location; Google and Gradescope credentials; document text, summaries, and notes; shared course passages; your notes; tutoring messages and session summaries; study room messages and summaries; quiz questions and answers; flashcards; study guides; gradebook scores and notes; and feedback and issue reports." },
      { label: "Not encrypted at the application layer:", text: "concept names and mastery scores, note tags, file names, usernames, search embeddings, and job applications. Access to them is limited by our server's access controls." },
      { label: "At rest (storage layer):", text: "our database provider (Supabase) applies its own access controls and encryption at rest." },
    ],
    bodyAfter: "Sapling manages the application-layer encryption keys, so we, and the AI and infrastructure providers described above, can decrypt your data when that is needed to run the service. This is not end-to-end encryption. No system is completely secure, and we cannot guarantee absolute security.",
  },
  {
    title: "10. Age Requirement",
    body: "Sapling is for people 18 and older. Our AI provider's terms do not permit use by anyone under 18. If you believe someone under 18 is using Sapling, email us at ",
    link: { label: CONTACT_EMAIL, href: `mailto:${CONTACT_EMAIL}` },
    bodySuffix: " and we will delete the account.",
  },
  {
    title: "11. Your Choices and Rights",
    body: "You can see and edit your profile in Settings, export what Settings offers, ask us for a full copy of your data, turn off Class Intel, revoke Google access, unsubscribe from the Journal, and delete documents or your whole account. Depending on where you live (for example California, the EU, or the UK), you may have additional rights to access, correct, delete, or restrict use of your information. Email us to exercise any of them. Your data is processed and stored in the United States.",
  },
  {
    title: "12. Job Applicants",
    body: "If you apply for a role, we collect what you submit through the application form: your name, email address, phone number, LinkedIn and portfolio links, and resume. We use it only to evaluate your application and contact you about it, and we store resumes in private storage. If your application is unsuccessful, we may keep it for up to 12 months in case another role fits. To delete it sooner, email ",
    link: { label: CONTACT_EMAIL, href: `mailto:${CONTACT_EMAIL}` },
    bodySuffix: ".",
  },
  {
    title: "13. Changes to This Policy",
    body: "We may update this policy. If a change materially affects how we use your data, we will tell you in the app before it takes effect, as well as updating the date at the top of this page.",
  },
  {
    title: "14. Contact",
    body: "Sapling is built and operated by the Sapling team, a group of students, and is not affiliated with or endorsed by Boston University. For privacy questions or requests, email ",
    link: { label: CONTACT_EMAIL, href: `mailto:${CONTACT_EMAIL}` },
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
              <time dateTime={LEGAL_LAST_UPDATED} style={META}>Last updated: {legalDateLabel()}</time>
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
