'use client';

/**
 * Apply to one open role.
 *
 * Moved onto CompanionShell, so the page no longer ships its own sticky
 * topbar or its own stale five-link footer; the shell supplies both plus the
 * content box. Palette converted from the app-shell `var(--*)` tokens to the
 * warm paper hexes — inside the shell those variables resolve against a
 * different layer and clash with the paper ground.
 *
 * The layout is a real two-column split rather than a narrow column pinned
 * inside a wide frame: the role description sits left at a ~65-character
 * measure in Spectral and the form sits right, so the page has one right
 * edge. `auto-fit`/`minmax` does the collapse to a single column, because
 * inline styles cannot carry a media query. The left column is sticky since
 * the form is roughly twice its height — otherwise half the page is blank
 * paper next to a scrolling form.
 *
 * The form itself is untouched below the styling: same fields, same required
 * marks, same resume-before-submit guard, same `submitJobApplication` call.
 */

import { useState, useRef } from 'react';
import Link from 'next/link';
import { type Job, DEPT_COLORS } from '../jobs';
import { submitJobApplication } from '@/lib/api';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ACCENT, BODY, DISPLAY, INK, MONO, MUTED, SERIF } from '@/lib/landing/companionType';

const SANS = "'DM Sans',system-ui,sans-serif";

/**
 * Warm brick for the required-field marks and submit errors. Hardcoded like
 * every other colour on the companion pages: `var(--err)` is an app-shell
 * token and does not belong to this palette layer.
 */
const ALERT = '#a83a3a';

const HAIRLINE = '1px solid rgba(42,39,31,0.10)';

/** Fields are white on the `#faf8f3` card so an input reads as an input. */
const INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  background: '#fff',
  border: '1px solid rgba(42,39,31,0.16)',
  borderRadius: 8,
  padding: '11px 14px',
  fontSize: 14.5,
  color: INK,
  fontFamily: SANS,
  boxSizing: 'border-box',
  transition: 'border-color 200ms',
};

const LABEL_STYLE: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: INK,
  marginBottom: 7,
};

const EYEBROW: React.CSSProperties = {
  display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em',
  textTransform: 'uppercase', color: ACCENT,
};

/**
 * The way back to the list. The old chrome's only back link pointed at `/`,
 * which is not where anyone arrives from; the openings list is. It lives in
 * the page content now — CompanionShell's header is the same on every
 * companion surface and takes no per-page links.
 */
function BackToOpenings() {
  return (
    <Link
      href="/careers"
      className="cp-navlink"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, color: MUTED, animation: 'fadeUp 600ms ease both' }}
    >
      <span aria-hidden="true">←</span> All openings
    </Link>
  );
}

export default function ApplyForm({ job }: { job: Job | null }) {
  const [form, setForm] = useState({ name: '', email: '', phone: '', linkedin: '', portfolio: '' });
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [agreedToPrivacy, setAgreedToPrivacy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!job) {
    return (
      <CompanionShell current="/careers">
        <div style={{ padding: '80px 0' }}>
          <h1 style={{ margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 40, lineHeight: 1.15, letterSpacing: '-0.015em', color: INK }}>
            Role not found
          </h1>
          <p style={{ margin: '18px 0 26px', fontFamily: SERIF, fontSize: 16, lineHeight: 1.6, color: BODY, maxWidth: '58ch' }}>
            That opening is closed or the link is wrong. The roles we are hiring for right now are
            all on the openings page.
          </p>
          <BackToOpenings />
        </div>
      </CompanionShell>
    );
  }

  const dept = DEPT_COLORS[job.department];

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) setResumeFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setResumeFile(file);
  };

  const handleSubmit = async (e: React.SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!resumeFile) {
      setSubmitError('Please attach your resume (PDF) before submitting.');
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitJobApplication({
        position: job.slug,
        full_name: form.name,
        email: form.email,
        phone: form.phone,
        linkedin_url: form.linkedin,
        portfolio_link: form.portfolio || undefined,
        resume: resumeFile,
      });
      setSubmitted(true);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <CompanionShell current="/careers">
      <div>
        <BackToOpenings />

        <h1 style={{ margin: '18px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', color: INK, animation: 'fadeUp 700ms ease 60ms both' }}>
          {job.title}
        </h1>

        <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 12, animation: 'fadeUp 700ms ease 120ms both' }}>
          {dept && (
            <span
              style={{
                fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 99,
                background: dept.bg, color: dept.text, border: `1px solid ${dept.border}`,
              }}
            >
              {job.department}
            </span>
          )}
          <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: MUTED }}>
            {job.location} · {job.type}
          </span>
        </div>

        <div
          style={{
            marginTop: 40, paddingTop: 40, borderTop: HAIRLINE,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%,380px),1fr))',
            gap: 48,
            alignItems: 'start',
          }}
        >
          {/* Sticky because the form beside it is about twice as tall; the
              offset clears the shell's 92px header scrim. */}
          <aside style={{ position: 'sticky', top: 108, animation: 'fadeUp 700ms ease 200ms both' }}>
            <span style={EYEBROW}>The role</span>
            <p style={{ margin: '14px 0 0', fontFamily: SERIF, fontSize: 17.5, lineHeight: 1.64, color: BODY }}>
              {job.description}
            </p>

            <div style={{ marginTop: 30, paddingTop: 26, borderTop: HAIRLINE }}>
              <span style={EYEBROW}>What you&apos;d touch</span>
              <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                {job.tags.map((tag) => (
                  <span
                    key={tag}
                    style={{ fontSize: 12, padding: '4px 11px', borderRadius: 7, background: '#faf8f3', border: HAIRLINE, color: BODY }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </aside>

          <div style={{ background: '#faf8f3', border: HAIRLINE, borderRadius: 18, animation: 'fadeUp 700ms ease 260ms both' }}>
            {submitted ? (
              <div style={{ padding: 'clamp(36px,5vw,52px) clamp(24px,4vw,36px)', textAlign: 'center' }}>
                <div
                  style={{
                    width: 48, height: 48, borderRadius: '50%',
                    background: 'rgba(45,143,92,0.10)', border: '1px solid rgba(45,143,92,0.28)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    margin: '0 auto 18px',
                  }}
                >
                  <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={ACCENT} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <h2 style={{ margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 26, lineHeight: 1.2, letterSpacing: '-0.015em', color: INK }}>
                  Application submitted
                </h2>
                <p style={{ margin: '12px auto 26px', maxWidth: '38ch', fontFamily: SERIF, fontSize: 15.5, lineHeight: 1.65, color: BODY }}>
                  Thanks for applying to Sapling. We&apos;ll review your application and reach out soon.
                </p>
                <Link
                  href="/careers"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13.5, fontWeight: 600, color: '#1B6C42' }}
                >
                  <span aria-hidden="true">←</span> All openings
                </Link>
              </div>
            ) : (
              <form onSubmit={handleSubmit} style={{ padding: 'clamp(24px,3.4vw,34px)' }}>
                <span style={EYEBROW}>Apply</span>

                <div style={{ marginTop: 22, display: 'flex', flexDirection: 'column', gap: 20 }}>
                  <div>
                    <label style={LABEL_STYLE}>
                      Full Name <span style={{ color: ALERT }}>*</span>
                    </label>
                    <input
                      type="text"
                      required
                      placeholder="Jane Smith"
                      value={form.name}
                      onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                      style={INPUT_STYLE}
                    />
                  </div>

                  <div>
                    <label style={LABEL_STYLE}>
                      Email <span style={{ color: ALERT }}>*</span>
                    </label>
                    <input
                      type="email"
                      required
                      placeholder="jane@university.edu"
                      value={form.email}
                      onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                      style={INPUT_STYLE}
                    />
                  </div>

                  <div>
                    <label style={LABEL_STYLE}>Phone Number</label>
                    <input
                      type="tel"
                      placeholder="+1 (555) 000-0000"
                      value={form.phone}
                      onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                      style={INPUT_STYLE}
                    />
                  </div>

                  <div>
                    <label style={LABEL_STYLE}>
                      LinkedIn Profile <span style={{ color: ALERT }}>*</span>
                    </label>
                    <input
                      type="url"
                      required
                      placeholder="https://linkedin.com/in/yourprofile"
                      value={form.linkedin}
                      onChange={(e) => setForm((f) => ({ ...f, linkedin: e.target.value }))}
                      style={INPUT_STYLE}
                    />
                  </div>

                  <div>
                    <label style={LABEL_STYLE}>Portfolio Link</label>
                    <input
                      type="url"
                      placeholder="https://yourportfolio.com"
                      value={form.portfolio}
                      onChange={(e) => setForm((f) => ({ ...f, portfolio: e.target.value }))}
                      style={INPUT_STYLE}
                    />
                  </div>

                  <div>
                    <label style={LABEL_STYLE}>
                      Resume <span style={{ color: ALERT }}>*</span>
                    </label>
                    <div
                      onClick={() => fileInputRef.current?.click()}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragging(true);
                      }}
                      onDragLeave={() => setDragging(false)}
                      onDrop={handleDrop}
                      style={{
                        border: `1.5px dashed ${dragging ? ACCENT : 'rgba(42,39,31,0.22)'}`,
                        borderRadius: 10,
                        padding: '28px 20px',
                        textAlign: 'center',
                        cursor: 'pointer',
                        background: dragging ? 'rgba(45,143,92,0.08)' : '#fff',
                        transition: 'border-color 200ms, background 200ms',
                      }}
                    >
                      {resumeFile ? (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                          <svg
                            width="16"
                            height="16"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke={ACCENT}
                            strokeWidth={2}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <path d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
                          </svg>
                          <span style={{ fontSize: 13, color: '#1B6C42', fontWeight: 600 }}>
                            {resumeFile.name}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setResumeFile(null);
                            }}
                            aria-label="Remove attached resume"
                            style={{ color: MUTED, padding: '0 2px', fontSize: 15, lineHeight: 1, cursor: 'pointer' }}
                          >
                            ×
                          </button>
                        </div>
                      ) : (
                        <>
                          <svg
                            width="20"
                            height="20"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke={MUTED}
                            strokeWidth={1.5}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            style={{ margin: '0 auto 8px', display: 'block' }}
                          >
                            <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                          </svg>
                          <p style={{ fontSize: 13, color: BODY, margin: '0 0 3px' }}>
                            <span style={{ fontWeight: 600, color: '#1B6C42' }}>Click to upload</span>{' '}
                            or drag and drop
                          </p>
                          <p style={{ fontSize: 11, color: MUTED, margin: 0 }}>PDF only</p>
                        </>
                      )}
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".pdf"
                        onChange={handleFileChange}
                        style={{ display: 'none' }}
                      />
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: 22, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  <input
                    type="checkbox"
                    id="privacy-consent"
                    required
                    checked={agreedToPrivacy}
                    onChange={(e) => setAgreedToPrivacy(e.target.checked)}
                    style={{ marginTop: 2, accentColor: '#1B6C42', cursor: 'pointer', flexShrink: 0 }}
                  />
                  <label
                    htmlFor="privacy-consent"
                    style={{ fontSize: 13, color: BODY, lineHeight: 1.55, cursor: 'pointer' }}
                  >
                    I have read and agree to Sapling&apos;s{' '}
                    <Link href="/privacy" target="_blank" style={{ color: '#1B6C42', fontWeight: 600, textDecoration: 'underline' }}>
                      Privacy Policy
                    </Link>
                    , including how my application data is collected and used.
                  </label>
                </div>

                <div style={{ marginTop: 28, paddingTop: 24, borderTop: HAIRLINE }}>
                  {submitError && (
                    <p style={{ fontSize: 13, color: ALERT, margin: '0 0 12px', textAlign: 'center' }}>
                      {submitError}
                    </p>
                  )}
                  <button
                    type="submit"
                    disabled={submitting}
                    className="cp-cta"
                    style={{
                      width: '100%',
                      display: 'flex',
                      justifyContent: 'center',
                      alignItems: 'center',
                      background: '#1B6C42',
                      color: '#fff',
                      borderRadius: 8,
                      padding: '13px 22px',
                      fontFamily: SANS,
                      fontSize: 14.5,
                      fontWeight: 600,
                      opacity: submitting ? 0.8 : 1,
                      cursor: submitting ? 'default' : 'pointer',
                    }}
                  >
                    {submitting ? 'Submitting…' : 'Submit Application'}
                  </button>
                  <p style={{ fontSize: 11, color: MUTED, textAlign: 'center', margin: '12px 0 0' }}>
                    Fields marked <span style={{ color: ALERT }}>*</span> are required
                  </p>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    </CompanionShell>
  );
}
