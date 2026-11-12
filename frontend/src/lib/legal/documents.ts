/**
 * The Terms of Service and the Privacy Policy: the one copy of their text.
 *
 * The public /terms and /privacy pages (components/legal/LegalDocumentPage)
 * and onboarding's Terms and Privacy screens (components/onboarding/LegalStep)
 * all render these objects, so the document a student agrees to in onboarding
 * is the one published, and its date is the version they accept
 * (./versions.ts, sent with the onboarding save).
 *
 * Editing the text of either document is a new version: change its date in
 * ./versions.ts (and backend/services/legal.py) in the same change.
 */
import { PRIVACY_VERSION, TERMS_VERSION } from "./versions";

export interface LegalLink {
  label: string;
  href: string;
}

/** One numbered clause. Every field is optional except the title; a renderer
 * shows them in this order: body (with `link` and `bodySuffix` inline), list,
 * subsections, highlights, bodyAfter. */
export interface LegalSection {
  title: string;
  /** The opening paragraph. `link` and then `bodySuffix` continue it inline. */
  body?: string;
  link?: LegalLink;
  bodySuffix?: string;
  list?: string[];
  /** Labelled sub-lists ("Information you provide directly:"). */
  subsections?: { label: string; list: string[] }[];
  /** List rows that open with a bold label ("In transit:"). */
  highlights?: { label: string; text: string }[];
  /** A closing paragraph after the lists. */
  bodyAfter?: string;
}

export interface LegalDocument {
  kind: "terms" | "privacy";
  title: string;
  /** The ISO date the document was last updated: the version a student accepts. */
  version: string;
  /** The paragraph under the date, before clause 1. */
  preamble: string;
  sections: LegalSection[];
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2026-10-22" → "October 22, 2026". Parsed by hand rather than through a
 * Date, which would read the string as UTC midnight and show the day before
 * west of Greenwich. */
export function legalDateLabel(version: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(version);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  if (!m || !month) return version;
  return `${month} ${Number(m[3])}, ${m[1]}`;
}

const CONTACT: LegalLink = { label: "careers@saplinglearn.com", href: "mailto:careers@saplinglearn.com" };

export const TERMS: LegalDocument = {
  kind: "terms",
  title: "Terms of Service",
  version: TERMS_VERSION,
  preamble:
    "By accessing or using Sapling (“the Service”), you agree to be bound by these Terms of Service. If you do not agree, please do not use the Service.",
  sections: [
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
      body: "Sapling uses Anthropic's Claude to generate tutoring responses, quizzes, flashcards, and study guides. AI-generated content may occasionally be inaccurate or incomplete. You should not rely on it as a substitute for official course materials, instructors, or academic advisors. We make no guarantees about the accuracy of AI outputs.",
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
      link: CONTACT,
    },
  ],
};

export const PRIVACY: LegalDocument = {
  kind: "privacy",
  title: "Privacy Policy",
  version: PRIVACY_VERSION,
  preamble:
    "This Privacy Policy explains how Sapling (“we,” “us,” or “our”) collects, uses, and protects your information when you use our Service.",
  sections: [
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
            "Product analytics, only while you are signed in and have not turned it off: the pages of the app you view, with basic browser and device details (but not your IP address); actions you take in the app, such as signing in, starting or finishing a quiz, messaging the tutor or uploading a document, with details like scores, counts and the IDs of the items involved; for each AI response we generate for you, the AI model used, the number of tokens processed and the cost; and reports of errors on our servers. Each record is tied to your Sapling account ID, not your name or email. We do not record what you type, or the text of your notes, documents, messages or AI responses. Analytics stores nothing in your browser (no cookies or local storage)",
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
        { label: "Service providers:", text: "We use Supabase (database), Anthropic's Claude (AI processing), Google Gemini (indexing your uploaded course materials for search), and similar infrastructure providers. These providers process data on our behalf under their own privacy policies." },
        { label: "Product analytics:", text: "We use PostHog, hosted in the United States, to understand how the Service is used so we can improve it. For signed-in users who have not turned analytics off, PostHog receives: the pages of the app you view, sent from your browser (never from our public pages or sign-in screens); records of actions you take in the app, sent from our servers; for each AI response we generate for you, the AI model, the number of tokens processed, the cost and a request reference, but never your prompt or the AI's reply; and reports of errors on our servers, showing the type of error and where in our code it happened, without the error message. Page views include basic browser and device details (browser and operating-system type, screen size, language, time zone and the referring page) but not your IP address: our servers relay them to PostHog without it, and we turn off location lookup. All of it is tied to your Sapling account ID, which is based on your Google account's ID number. Nothing is sent for anyone who is signed out. PostHog does not receive your name, email address, IP address, what you type, or the content of your notes, documents or messages; we do not record your screen, and analytics stores nothing in your browser (no cookies or local storage). You can turn product analytics off at any time under Settings → Data. The choice is saved to your account, applies wherever you sign in, and stops all of the above within about a minute. If your browser sends a Do Not Track or Global Privacy Control signal, we send no page views from it, and we don't share actions from requests that carry the signal. Records of some background processing on your documents can still be shared unless you turn product analytics off in Settings → Data." },
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
      link: CONTACT,
      bodySuffix: " and we will take steps to delete it.",
    },
    {
      title: "8. Job Applicants",
      body: "If you apply for a position at Sapling, we collect the information you submit through our application form, including your name, email address, phone number, LinkedIn profile URL, and resume. This data is used solely to evaluate your application and communicate with you about the hiring process. We do not share applicant data with third parties outside of our core infrastructure providers. If your application is unsuccessful, we may retain your information for up to 12 months in case a suitable role arises. You may request deletion of your applicant data at any time by emailing ",
      link: CONTACT,
      bodySuffix: ".",
    },
    {
      title: "9. Changes to This Policy",
      body: "We may update this Privacy Policy from time to time. We will notify users of material changes by updating the date at the top of this page.",
    },
    {
      title: "10. Contact",
      body: "If you have questions or concerns about this Privacy Policy, please email us at ",
      link: CONTACT,
      bodySuffix: ".",
    },
  ],
};

/** Every string a reader of `doc` must see, in reading order: for tests that
 * pin a renderer to the whole document (nothing dropped on one surface). */
export function legalDocumentText(doc: LegalDocument): string[] {
  const out = [doc.title, legalDateLabel(doc.version), doc.preamble];
  for (const s of doc.sections) {
    out.push(s.title);
    if (s.body) out.push(s.body.trim());
    if (s.link) out.push(s.link.label);
    if (s.bodySuffix?.trim()) out.push(s.bodySuffix.trim());
    out.push(...(s.list ?? []));
    for (const sub of s.subsections ?? []) out.push(sub.label, ...sub.list);
    for (const h of s.highlights ?? []) out.push(h.label, h.text);
    if (s.bodyAfter) out.push(s.bodyAfter);
  }
  return out;
}
