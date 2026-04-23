import Link from "next/link";

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
            className="body-serif fade-in"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            <strong style={{ color: "var(--text)", fontWeight: 600 }}>Sapling</strong>{" "}
            is an AI-powered study companion built by students, for students. We believe that
            learning shouldn&apos;t be passive. It should adapt to you, challenge you, and show you
            exactly where you stand.
          </p>

          <p
            className="body-serif"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            At its core, Sapling maps your understanding as a live knowledge graph that grows with
            every session, quiz, and document you interact with. Paired with an AI tutor that can
            reason with you Socratically, explain concepts directly, or flip the table and have
            you teach back, Sapling meets you wherever you are in your learning journey.
          </p>

          <p
            className="body-serif"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            Sapling was born out of a hackathon and built by a team of four students who were
            frustrated with static study tools that don&apos;t actually know what you know. We wanted
            something that feels less like a flashcard app and more like a study partner who&apos;s
            always prepared.
          </p>

          <div>
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
            className="body-serif"
            style={{ fontSize: 16, color: "var(--text-dim)" }}
          >
            Sapling is actively developed and we&apos;re always building. If something&apos;s broken or
            you have an idea, there&apos;s a feedback button in the navbar and we actually read those.
          </p>
        </div>

        <div style={{ marginTop: 56 }}>
          <p
            className="label-micro"
            style={{ color: "var(--accent)", marginBottom: 24 }}
          >
            Recognition
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            {awards.map((award) => (
              <div key={award.title}>
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
