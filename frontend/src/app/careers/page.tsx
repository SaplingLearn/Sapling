'use client';

import { useState } from 'react';
import Link from 'next/link';
import { JOBS, DEPT_COLORS } from './jobs';

const GLASS: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid rgba(107, 114, 128, 0.15)',
  borderRadius: '10px',
  boxShadow: '0 2px 10px rgba(26, 92, 42, 0.07), 0 1px 3px rgba(26, 92, 42, 0.04)',
};

const GLASS_STRONG: React.CSSProperties = {
  background: 'rgba(255, 255, 255, 0.72)',
  backdropFilter: 'blur(40px) saturate(1.8)',
  WebkitBackdropFilter: 'blur(40px) saturate(1.8)',
  border: '1px solid rgba(255, 255, 255, 0.6)',
  borderRadius: '16px',
  boxShadow: '0 8px 32px rgba(26, 92, 42, 0.10), 0 2px 8px rgba(26, 92, 42, 0.06)',
};

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";


export default function CareersPage() {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  return (
    <div style={{ minHeight: '100vh', background: '#E9EFED', fontFamily: UI_FONT }}>

      {/* ── Header ── */}
      <header style={{
        borderBottom: '1px solid rgba(107,114,128,0.12)',
        background: 'rgba(255,255,255,0.72)',
        backdropFilter: 'blur(20px) saturate(1.5)',
        WebkitBackdropFilter: 'blur(20px) saturate(1.5)',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}>
        <div style={{ maxWidth: '1280px', margin: '0 auto', padding: '0 24px', height: '52px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: '4px', textDecoration: 'none' }}>
            <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '26px', height: '26px', flexShrink: 0, position: 'relative', top: '-2px' }} />
            <span style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: '20px', color: '#1a5c2a', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              Sapling
            </span>
          </Link>
          <Link
            href="/"
            style={{ fontSize: '13px', color: '#6b7280', textDecoration: 'none' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#111827')}
            onMouseLeave={e => (e.currentTarget.style.color = '#6b7280')}
          >
            ← Back to home
          </Link>
        </div>
      </header>

      {/* ── Hero ── */}
      <section style={{ paddingTop: '80px', paddingBottom: '60px', textAlign: 'center', padding: '80px 24px 60px' }}>
        <div className="fade-up anim-d0" style={{
          display: 'inline-flex', alignItems: 'center', gap: '6px',
          background: 'rgba(26,92,42,0.06)', border: '1px solid rgba(26,92,42,0.14)',
          borderRadius: '999px', padding: '4px 14px', marginBottom: '28px',
        }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#16a34a', display: 'inline-block' }} />
          <span style={{ fontSize: '12px', color: '#1a5c2a', fontWeight: 500, letterSpacing: '0.03em' }}>
            We&apos;re hiring
          </span>
        </div>

        <h1 className="fade-up anim-d1" style={{
          fontFamily: "var(--font-playfair), 'Playfair Display', serif",
          fontSize: 'clamp(2.5rem, 5vw, 3.75rem)',
          fontWeight: 700,
          color: '#111827',
          lineHeight: 1.1,
          letterSpacing: '-0.02em',
          marginBottom: '20px',
        }}>
          Opportunities
        </h1>

        <p className="fade-up anim-d2" style={{
          fontSize: '1.0625rem', color: '#4b5563', maxWidth: '500px',
          margin: '0 auto', lineHeight: 1.65, fontWeight: 300,
        }}>
          We&apos;re a small team building tools that help students learn better.
          If that sounds like work worth doing, we&apos;d love to meet you.
        </p>
      </section>

      {/* ── Job Listings ── */}
      <section style={{ maxWidth: '760px', margin: '0 auto', padding: '0 24px 96px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {JOBS.map((job) => {
            const dept = DEPT_COLORS[job.department] ?? DEPT_COLORS.Engineering;
            const isOpen = expandedId === job.id;

            return (
              <div key={job.id} className="fade-up" style={{ ...GLASS, overflow: 'hidden', transition: 'box-shadow 0.2s', animationDelay: `${240 + job.id * 80}ms` }}>
                {/* Toggle row — native button for keyboard/a11y */}
                <button
                  onClick={() => setExpandedId(isOpen ? null : job.id)}
                  aria-expanded={isOpen}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: '16px', width: '100%', padding: '20px 24px',
                    background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
                  }}
                  onMouseEnter={e => { if (e.currentTarget.parentElement) e.currentTarget.parentElement.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.85), 0 4px 18px rgba(26,92,42,0.10), 0 2px 6px rgba(26,92,42,0.06)'; }}
                  onMouseLeave={e => { if (e.currentTarget.parentElement) e.currentTarget.parentElement.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.85), 0 2px 10px rgba(26,92,42,0.07), 0 1px 3px rgba(26,92,42,0.04)'; }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '5px' }}>
                      <span style={{ fontSize: '15px', fontWeight: 600, color: '#111827' }}>{job.title}</span>
                      <span style={{
                        fontSize: '11px', fontWeight: 500, padding: '2px 9px', borderRadius: '999px',
                        background: dept.bg, color: dept.text, border: `1px solid ${dept.border}`,
                      }}>
                        {job.department}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: '10px', fontSize: '12px', color: '#9ca3af' }}>
                      <span>{job.location}</span>
                      <span>·</span>
                      <span>{job.type}</span>
                    </div>
                  </div>
                  <svg
                    style={{ flexShrink: 0, width: '15px', height: '15px', color: '#9ca3af', transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.65s cubic-bezier(0.16,1,0.3,1)' }}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {/* Expanded content */}
                <div
                  style={{
                    borderTop: '1px solid rgba(107,114,128,0.10)',
                    padding: isOpen ? '20px 24px 24px' : '0 24px 0',
                    maxHeight: isOpen ? '520px' : '0px',
                    opacity: isOpen ? 1 : 0,
                    overflow: 'hidden',
                    pointerEvents: isOpen ? 'auto' : 'none',
                    transition: 'max-height 700ms cubic-bezier(0.22,1,0.36,1), opacity 600ms ease, padding 700ms cubic-bezier(0.22,1,0.36,1)',
                  }}
                >
                  <p style={{ fontSize: '14px', color: '#374151', lineHeight: 1.7, marginBottom: '16px' }}>
                    {job.description}
                  </p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '22px' }}>
                    {job.tags.map(tag => (
                      <span key={tag} style={{
                        fontSize: '11px', padding: '3px 10px', borderRadius: '6px',
                        background: 'rgba(107,114,128,0.06)', border: '1px solid rgba(107,114,128,0.13)',
                        color: '#4b5563',
                      }}>
                        {tag}
                      </span>
                    ))}
                  </div>
                  <Link
                    href={`/careers/${job.slug}`}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: '6px',
                      background: '#1B6C42', color: 'white',
                      padding: '9px 20px', borderRadius: '8px',
                      fontSize: '13px', fontWeight: 500, textDecoration: 'none',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#155A35')}
                    onMouseLeave={e => (e.currentTarget.style.background = '#1B6C42')}
                  >
                    Apply for this role
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>

        {/* General Application */}
        <div className="fade-up anim-d5" style={{ ...GLASS_STRONG, marginTop: '40px', padding: '36px 32px', textAlign: 'center' }}>
          <svg
            style={{ width: '28px', height: '28px', color: '#1a5c2a', margin: '0 auto 12px' }}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707m12.728 0l-.707-.707M6.343 6.343l-.707-.707M12 6a6 6 0 100 12A6 6 0 0012 6z" />
          </svg>
          <h3 style={{ fontFamily: "var(--font-spectral), 'Spectral', serif", fontSize: '18px', fontWeight: 600, color: '#111827', marginBottom: '8px' }}>
            Don&apos;t see your role?
          </h3>
          <p style={{ fontSize: '13px', color: '#6b7280', lineHeight: 1.65, maxWidth: '360px', margin: '0 auto 22px' }}>
            We&apos;re always interested in meeting talented people. Send us a note and tell us what you&apos;d build.
          </p>
          <a
            href="mailto:careers@saplinglearn.com"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              background: 'rgba(26,92,42,0.07)', color: '#1a5c2a',
              border: '1px solid rgba(26,92,42,0.18)',
              padding: '9px 20px', borderRadius: '8px',
              fontSize: '13px', fontWeight: 500, textDecoration: 'none',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(26,92,42,0.12)'; e.currentTarget.style.borderColor = 'rgba(26,92,42,0.28)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(26,92,42,0.07)'; e.currentTarget.style.borderColor = 'rgba(26,92,42,0.18)'; }}
          >
            Get in touch
          </a>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer style={{ borderTop: '1px solid rgba(107,114,128,0.12)', background: '#E9EFED', padding: '48px 32px' }}>
        <div style={{ maxWidth: '1280px', margin: '0 auto', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '20px', height: '20px' }} />
            <span style={{ fontSize: '14px', fontWeight: 300, letterSpacing: '0.03em', color: '#6b7280' }}>Sapling · © 2026</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '24px' }}>
            {[
              { label: 'Home', href: '/' },
              { label: 'About', href: '/about' },
              { label: 'Careers', href: '/careers' },
              { label: 'Terms of Service', href: '/terms' },
              { label: 'Privacy Policy', href: '/privacy' },
            ].map(({ label, href }) => (
              <Link
                key={label}
                href={href}
                style={{ fontSize: '14px', color: '#6b7280', textDecoration: 'none', transition: 'color 0.15s' }}
                onMouseEnter={e => (e.currentTarget.style.color = '#111827')}
                onMouseLeave={e => (e.currentTarget.style.color = '#6b7280')}
              >
                {label}
              </Link>
            ))}
          </div>
        </div>
        <div style={{ maxWidth: '1280px', margin: '0 auto', marginTop: '32px', paddingTop: '24px', borderTop: '1px solid rgba(107,114,128,0.10)', textAlign: 'center' }}>
          <p style={{ fontSize: '12px', color: '#9ca3af', fontWeight: 300, letterSpacing: '0.03em' }}>
            © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
