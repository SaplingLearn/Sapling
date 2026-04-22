import Link from "next/link";

const sections = [
  {
    title: "1. Eligibility",
    body: "Sapling is intended for use by students and individuals for personal educational purposes. By using the Service, you represent that you are at least 13 years of age. If you are under 18, you should have parental or guardian consent.",
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
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      <div
        style={{
          flex: 1,
          width: "100%",
          maxWidth: 720,
          margin: "0 auto",
          padding: "64px 32px",
        }}
      >
        <div className="fade-in" style={{ marginBottom: 48 }}>
          <Link
            href="/"
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              textDecoration: "none",
              transition: "color var(--dur-fast) var(--ease)",
            }}
          >
            ← Back to Sapling
          </Link>
        </div>

        <h1
          className="h-serif slide-up"
          style={{ fontSize: 44, marginBottom: 8, color: "var(--text)" }}
        >
          Terms of Service
        </h1>
        <p
          className="fade-in"
          style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 40 }}
        >
          Last updated: March 27, 2026
        </p>

        <p
          className="body-serif fade-in"
          style={{ fontSize: 16, color: "var(--text-dim)", marginBottom: 40 }}
        >
          By accessing or using Sapling (&ldquo;the Service&rdquo;), you agree to be bound by these
          Terms of Service. If you do not agree, please do not use the Service.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
          {sections.map((section) => (
            <div key={section.title}>
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
              <p
                className="body-serif"
                style={{ fontSize: 15, color: "var(--text-dim)" }}
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
              </p>
              {section.list && (
                <ul
                  style={{
                    marginTop: 12,
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
            </div>
          ))}
        </div>

        <div
          style={{
            marginTop: 48,
            paddingTop: 32,
            borderTop: "1px solid var(--border)",
            fontSize: 13,
            color: "var(--text-muted)",
          }}
        >
          © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
        </div>
      </div>

      <footer
        style={{
          borderTop: "1px solid var(--border)",
          background: "var(--bg-subtle)",
          padding: "32px",
        }}
      >
        <div
          style={{
            maxWidth: 720,
            margin: "0 auto",
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: 24,
            fontSize: 13,
            color: "var(--text-muted)",
          }}
        >
          <Link href="/about" style={{ color: "inherit", textDecoration: "none" }}>
            About
          </Link>
          <Link href="/terms" style={{ color: "inherit", textDecoration: "none" }}>
            Terms of Service
          </Link>
          <Link href="/privacy" style={{ color: "inherit", textDecoration: "none" }}>
            Privacy Policy
          </Link>
        </div>
      </footer>
    </div>
  );
}
