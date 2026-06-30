import Link from "next/link";

const FOOTER_LINKS = [
  { label: "Home", href: "/" },
  { label: "About", href: "/about" },
  { label: "Careers", href: "/careers" },
  { label: "Terms of Service", href: "/terms" },
  { label: "Privacy Policy", href: "/privacy" },
];

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
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      <header
        style={{
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-topbar)",
          position: "sticky",
          top: 0,
          zIndex: 50,
        }}
      >
        <div
          style={{
            maxWidth: 1280,
            margin: "0 auto",
            padding: "0 24px",
            height: 52,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Link
            href="/"
            style={{ display: "flex", alignItems: "center", gap: 6, textDecoration: "none" }}
          >
            <img
              src="/sapling-icon.svg"
              alt="Sapling"
              style={{ width: 26, height: 26, flexShrink: 0, position: "relative", top: -2 }}
            />
            <span
              style={{
                fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif",
                fontWeight: 700,
                fontSize: 20,
                color: "#1a5c2a",
                letterSpacing: "-0.02em",
                lineHeight: 1.1,
              }}
            >
              Sapling
            </span>
          </Link>
          <Link
            href="/"
            style={{ fontSize: 13, color: "var(--text-muted)", textDecoration: "none" }}
          >
            ← Back to home
          </Link>
        </div>
      </header>

      <div
        style={{
          flex: 1,
          width: "100%",
          maxWidth: 880,
          margin: "0 auto",
          padding: "64px 32px",
        }}
      >
        <h1
          className="h-serif fade-up anim-d1"
          style={{ fontSize: 44, marginBottom: 8, color: "var(--text)" }}
        >
          Privacy Policy
        </h1>
        <p
          className="fade-up anim-d2"
          style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 40 }}
        >
          Last updated: May 3, 2026
        </p>

        <p
          className="body-serif fade-up anim-d3"
          style={{ fontSize: 16, color: "var(--text-dim)", marginBottom: 40 }}
        >
          This Privacy Policy explains how Sapling (&ldquo;we,&rdquo; &ldquo;us,&rdquo; or &ldquo;our&rdquo;) collects,
          uses, and protects your information when you use our Service.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
          {sections.map((section, i) => (
            <div
              key={section.title}
              className="fade-up"
              style={{ animationDelay: `${Math.min(320 + i * 40, 640)}ms` }}
            >
              <h2
                style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: 15,
                  fontWeight: 600,
                  color: "var(--text)",
                  marginBottom: 8,
                  letterSpacing: "-0.005em",
                }}
              >
                {section.title}
              </h2>

              {section.body && (
                <p
                  className="body-serif"
                  style={{ fontSize: 15, color: "var(--text-dim)", marginBottom: 12 }}
                >
                  {section.body}
                  {section.link && (
                    <a
                      href={section.link.href}
                      style={{ color: "var(--accent)", textDecoration: "none" }}
                    >
                      {section.link.label}
                    </a>
                  )}
                  {section.bodySuffix}
                </p>
              )}

              {section.list && (
                <ul
                  style={{
                    paddingLeft: 16,
                    listStyle: "none",
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  {section.list.map((item, i) => (
                    <li
                      key={i}
                      className="body-serif"
                      style={{
                        display: "flex",
                        gap: 8,
                        fontSize: 15,
                        color: "var(--text-dim)",
                      }}
                    >
                      <span style={{ color: "var(--text-muted)", marginTop: 2 }}>•</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}

              {section.subsections && (
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {section.subsections.map((sub) => (
                    <div key={sub.label}>
                      <p
                        style={{
                          fontFamily: "var(--font-sans)",
                          fontSize: 13,
                          fontWeight: 500,
                          color: "var(--text)",
                          marginBottom: 6,
                        }}
                      >
                        {sub.label}
                      </p>
                      <ul
                        style={{
                          paddingLeft: 16,
                          listStyle: "none",
                          display: "flex",
                          flexDirection: "column",
                          gap: 6,
                        }}
                      >
                        {sub.list.map((item, i) => (
                          <li
                            key={i}
                            className="body-serif"
                            style={{
                              display: "flex",
                              gap: 8,
                              fontSize: 15,
                              color: "var(--text-dim)",
                            }}
                          >
                            <span style={{ color: "var(--text-muted)", marginTop: 2 }}>•</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}

              {section.highlights && (
                <ul
                  style={{
                    paddingLeft: 16,
                    listStyle: "none",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  {section.highlights.map((h) => (
                    <li
                      key={h.label}
                      className="body-serif"
                      style={{
                        display: "flex",
                        gap: 8,
                        fontSize: 15,
                        color: "var(--text-dim)",
                      }}
                    >
                      <span style={{ color: "var(--text-muted)", marginTop: 2 }}>•</span>
                      <span>
                        <strong style={{ color: "var(--text)", fontWeight: 600 }}>
                          {h.label}
                        </strong>{" "}
                        {h.text}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {section.bodyAfter && (
                <p
                  className="body-serif"
                  style={{ fontSize: 15, color: "var(--text-dim)", marginTop: 12 }}
                >
                  {section.bodyAfter}
                </p>
              )}
            </div>
          ))}
        </div>

      </div>

      <footer
        style={{
          borderTop: "1px solid var(--border)",
          background: "var(--bg-subtle)",
          padding: "48px 32px",
        }}
      >
        <div
          style={{
            maxWidth: 1280,
            margin: "0 auto",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 24,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <img src="/sapling-icon.svg" alt="Sapling" style={{ width: 20, height: 20 }} />
            <span style={{ fontSize: 14, color: "var(--text-muted)" }}>Sapling · © 2026</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
            {FOOTER_LINKS.map(({ label, href }) => (
              <Link
                key={label}
                href={href}
                style={{
                  fontSize: 14,
                  color: "var(--text-muted)",
                  textDecoration: "none",
                }}
              >
                {label}
              </Link>
            ))}
          </div>
        </div>
        <div
          style={{
            maxWidth: 1280,
            margin: "32px auto 0",
            paddingTop: 24,
            borderTop: "1px solid var(--border)",
            textAlign: "center",
          }}
        >
          <p style={{ fontSize: 12, color: "var(--text-muted)" }}>
            © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
