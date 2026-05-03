import Link from "next/link";

const FOOTER_LINKS = [
  { label: "Home", href: "/" },
  { label: "About", href: "/about" },
  { label: "Careers", href: "/careers" },
  { label: "Terms of Service", href: "/terms" },
  { label: "Privacy Policy", href: "/privacy" },
];

const differentiators = [
  "Your knowledge graph is yours. It updates in real time based on your actual performance, not just what you've clicked through.",
  "Three distinct teaching modes mean you're never locked into one way of learning.",
  "Study rooms let you learn alongside classmates and see how your mastery compares, anonymously and collaboratively.",
  "Everything from syllabus tracking to exam study guides is powered by Gemini, so the busywork of getting organized is handled for you.",
];

const awards = [
  {
    title: "Best AI Tutor in Education",
    org: "Boston University Civic Hacks 2026 · BU Spark! & Wheelock College of Education",
    body: "Recognized among competing teams at BU's annual civic hackathon for building the most impactful AI-driven learning experience. Sapling was awarded for its approach to personalized, student-centered tutoring, bridging the gap between artificial intelligence and meaningful education.",
  },
  {
    title: "Code & Tell Winner",
    org: "BU Spark!",
    body: "Selected by BU Spark! as a standout project at their Code & Tell showcase, where student builders present real-world applications to faculty, mentors, and industry judges. Sapling was chosen for its technical depth and its vision for the future of how students learn.",
  },
];

export default function AboutPage() {
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
          style={{ fontSize: 48, marginBottom: 32, color: "var(--text)" }}
        >
          About Sapling
        </h1>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 24,
          }}
        >
          <p
            className="body-serif fade-up anim-d2"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            <strong style={{ color: "var(--text)", fontWeight: 600 }}>Sapling</strong>{" "}
            is an AI-powered study companion built by students, for students. We believe that
            learning shouldn&apos;t be passive. It should adapt to you, challenge you, and show you
            exactly where you stand.
          </p>

          <p
            className="body-serif fade-up anim-d3"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            At its core, Sapling maps your understanding as a live knowledge graph that grows with
            every session, quiz, and document you interact with. Paired with an AI tutor that can
            reason with you Socratically, explain concepts directly, or flip the table and have
            you teach back, Sapling meets you wherever you are in your learning journey.
          </p>

          <p
            className="body-serif fade-up anim-d4"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            Sapling was born out of a hackathon and built by a team of four students who were
            frustrated with static study tools that don&apos;t actually know what you know. We wanted
            something that feels less like a flashcard app and more like a study partner who&apos;s
            always prepared.
          </p>

          <div className="fade-up anim-d5">
            <p
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 15,
                fontWeight: 600,
                color: "var(--text)",
                marginBottom: 12,
              }}
            >
              What makes Sapling different:
            </p>
            <ul
              style={{
                listStyle: "none",
                padding: 0,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {differentiators.map((item, i) => (
                <li
                  key={i}
                  className="body-serif"
                  style={{
                    display: "flex",
                    gap: 12,
                    fontSize: 15,
                    color: "var(--text-dim)",
                  }}
                >
                  <span style={{ color: "var(--accent)", marginTop: 2 }}>•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <p
            className="body-serif fade-up anim-d6"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            Sapling is actively developed and we&apos;re always building. If something&apos;s broken or
            you have an idea, there&apos;s a feedback button in the navbar and we actually read those.
          </p>
        </div>

        <div style={{ marginTop: 56 }}>
          <p
            className="label-micro fade-up anim-d7"
            style={{ color: "var(--accent)", marginBottom: 24 }}
          >
            Recognition
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            {awards.map((award, i) => (
              <div
                key={award.title}
                className="fade-up"
                style={{ animationDelay: `${Math.min(560 + i * 80, 720)}ms` }}
              >
                <p
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 16,
                    fontWeight: 600,
                    color: "var(--text)",
                  }}
                >
                  {award.title}
                </p>
                <p
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 12,
                    fontWeight: 500,
                    color: "var(--accent)",
                    marginTop: 2,
                  }}
                >
                  {award.org}
                </p>
                <p
                  className="body-serif"
                  style={{
                    fontSize: 14,
                    color: "var(--text-dim)",
                    marginTop: 8,
                  }}
                >
                  {award.body}
                </p>
              </div>
            ))}
          </div>
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
          Built by Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez © 2026
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
