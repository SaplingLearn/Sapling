'use client';

import { useState } from 'react';
import Link from 'next/link';
import { JOBS, DEPT_COLORS } from './jobs';

const FOOTER_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'About', href: '/about' },
  { label: 'Careers', href: '/careers' },
  { label: 'Terms of Service', href: '/terms' },
  { label: 'Privacy Policy', href: '/privacy' },
];

export default function CareersPage() {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--bg)',
        color: 'var(--text)',
        fontFamily: 'var(--font-sans)',
      }}
    >
      <header
        style={{
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-topbar)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
        }}
      >
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            padding: '0 24px',
            height: 52,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Link
            href="/"
            style={{ display: 'flex', alignItems: 'center', gap: 6, textDecoration: 'none' }}
          >
            <img
              src="/sapling-icon.svg"
              alt="Sapling"
              style={{ width: 26, height: 26, flexShrink: 0, position: 'relative', top: -2 }}
            />
            <span
              style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: 20, color: '#1a5c2a', letterSpacing: '-0.02em', lineHeight: 1.1 }}
            >
              Sapling
            </span>
          </Link>
          <Link
            href="/"
            style={{ fontSize: 13, color: 'var(--text-muted)', textDecoration: 'none' }}
          >
            ← Back to home
          </Link>
        </div>
      </header>

      <section style={{ padding: '80px 24px 60px', textAlign: 'center' }}>
        <div
          className="fade-in"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: 'var(--accent-soft)',
            border: '1px solid var(--accent-border)',
            borderRadius: 'var(--r-full)',
            padding: '4px 14px',
            marginBottom: 28,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--accent)',
              display: 'inline-block',
            }}
          />
          <span
            style={{
              fontSize: 12,
              color: 'var(--accent)',
              fontWeight: 500,
              letterSpacing: '0.03em',
            }}
          >
            We&apos;re hiring
          </span>
        </div>

        <h1
          className="h-serif slide-up"
          style={{
            fontSize: 'clamp(2.5rem, 5vw, 3.75rem)',
            color: 'var(--text)',
            marginBottom: 20,
          }}
        >
          Opportunities
        </h1>

        <p
          className="fade-in"
          style={{
            fontSize: 17,
            color: 'var(--text-dim)',
            maxWidth: 500,
            margin: '0 auto',
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            fontWeight: 300,
          }}
        >
          We&apos;re a small team building tools that help students learn better.
          If that sounds like work worth doing, we&apos;d love to meet you.
        </p>
      </section>

      <section style={{ maxWidth: 760, margin: '0 auto', padding: '0 24px 96px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {JOBS.map((job) => {
            const dept = DEPT_COLORS[job.department] ?? DEPT_COLORS.Engineering;
            const isOpen = expandedId === job.id;

            return (
              <div
                key={job.id}
                className="card"
                style={{ overflow: 'hidden', transition: 'box-shadow var(--dur) var(--ease)' }}
              >
                <button
                  onClick={() => setExpandedId(isOpen ? null : job.id)}
                  aria-expanded={isOpen}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 16,
                    width: '100%',
                    padding: '20px 24px',
                    background: 'none',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: 8,
                        marginBottom: 5,
                      }}
                    >
                      <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>
                        {job.title}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 500,
                          padding: '2px 9px',
                          borderRadius: 'var(--r-full)',
                          background: dept.bg,
                          color: dept.text,
                          border: `1px solid ${dept.border}`,
                        }}
                      >
                        {job.department}
                      </span>
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        gap: 10,
                        fontSize: 12,
                        color: 'var(--text-muted)',
                      }}
                    >
                      <span>{job.location}</span>
                      <span>·</span>
                      <span>{job.type}</span>
                    </div>
                  </div>
                  <svg
                    style={{
                      flexShrink: 0,
                      width: 15,
                      height: 15,
                      color: 'var(--text-muted)',
                      transform: isOpen ? 'rotate(180deg)' : 'none',
                      transition: 'transform var(--dur-slow) var(--ease)',
                    }}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2.2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                <div
                  style={{
                    borderTop: isOpen ? '1px solid var(--border)' : 'none',
                    padding: isOpen ? '20px 24px 24px' : '0 24px 0',
                    maxHeight: isOpen ? 520 : 0,
                    opacity: isOpen ? 1 : 0,
                    overflow: 'hidden',
                    pointerEvents: isOpen ? 'auto' : 'none',
                    transition:
                      'max-height 700ms var(--ease), opacity 600ms ease, padding 700ms var(--ease)',
                  }}
                >
                  <p
                    style={{
                      fontSize: 14,
                      color: 'var(--text-dim)',
                      marginBottom: 16,
                      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                      fontWeight: 300,
                      lineHeight: 1.65,
                    }}
                  >
                    {job.description}
                  </p>
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 6,
                      marginBottom: 22,
                    }}
                  >
                    {job.tags.map((tag) => (
                      <span
                        key={tag}
                        style={{
                          fontSize: 11,
                          padding: '3px 10px',
                          borderRadius: 'var(--r-sm)',
                          background: 'var(--bg-soft)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-dim)',
                        }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                  <Link
                    href={`/careers/${job.slug}`}
                    className="btn btn--primary"
                    style={{ textDecoration: 'none' }}
                  >
                    Apply for this role
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>

        <div
          className="card fade-in"
          style={{
            marginTop: 40,
            padding: '36px 32px',
            textAlign: 'center',
            background: 'var(--bg-subtle)',
          }}
        >
          <svg
            style={{
              width: 28,
              height: 28,
              color: 'var(--accent)',
              margin: '0 auto 12px',
              display: 'block',
            }}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707m12.728 0l-.707-.707M6.343 6.343l-.707-.707M12 6a6 6 0 100 12A6 6 0 0012 6z"
            />
          </svg>
          <h3
            className="h-serif"
            style={{ fontSize: 20, color: 'var(--text)', marginBottom: 8 }}
          >
            Don&apos;t see your role?
          </h3>
          <p
            style={{
              fontSize: 14,
              color: 'var(--text-dim)',
              maxWidth: 360,
              margin: '0 auto 22px',
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
              fontWeight: 300,
            }}
          >
            We&apos;re always interested in meeting talented people. Send us a note and tell us what
            you&apos;d build.
          </p>
          <a
            href="mailto:careers@saplinglearn.com"
            className="btn"
            style={{ textDecoration: 'none' }}
          >
            Get in touch
          </a>
        </div>
      </section>

      <footer
        style={{
          borderTop: '1px solid var(--border)',
          background: 'var(--bg-subtle)',
          padding: '48px 32px',
        }}
      >
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 24,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <img src="/sapling-icon.svg" alt="Sapling" style={{ width: 20, height: 20 }} />
            <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>Sapling · © 2026</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
            {FOOTER_LINKS.map(({ label, href }) => (
              <Link
                key={label}
                href={href}
                style={{
                  fontSize: 14,
                  color: 'var(--text-muted)',
                  textDecoration: 'none',
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
            margin: '32px auto 0',
            paddingTop: 24,
            borderTop: '1px solid var(--border)',
            textAlign: 'center',
          }}
        >
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
