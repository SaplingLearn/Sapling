'use client';

import { useState, useRef } from 'react';
import Link from 'next/link';
import { type Job, DEPT_COLORS } from '../jobs';
import { submitJobApplication } from '@/lib/api';

const FOOTER_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'About', href: '/about' },
  { label: 'Careers', href: '/careers' },
  { label: 'Terms of Service', href: '/terms' },
  { label: 'Privacy Policy', href: '/privacy' },
];

const INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  background: 'var(--bg-input)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--r-sm)',
  padding: '10px 14px',
  fontSize: 14,
  color: 'var(--text)',
  fontFamily: 'var(--font-sans)',
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color var(--dur-fast) var(--ease)',
};

const LABEL_STYLE: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 500,
  color: 'var(--text)',
  marginBottom: 6,
};

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
      <div
        style={{
          minHeight: '100vh',
          background: 'var(--bg)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'var(--font-sans)',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>Role not found.</p>
          <Link
            href="/careers"
            style={{ color: 'var(--accent)', fontSize: 13, marginTop: 12, display: 'block' }}
          >
            ← Back to opportunities
          </Link>
        </div>
      </div>
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
              style={{ width: 24, height: 24, position: 'relative', top: -1 }}
            />
            <span className="h-serif" style={{ fontSize: 20, color: 'var(--text)' }}>
              Sapling
            </span>
          </Link>
          <Link
            href="/careers"
            style={{ fontSize: 13, color: 'var(--text-muted)', textDecoration: 'none' }}
          >
            ← Back to opportunities
          </Link>
        </div>
      </header>

      <section style={{ maxWidth: 760, margin: '0 auto', padding: '56px 24px 96px' }}>
        <div className="fade-in" style={{ marginBottom: 32 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 8,
              flexWrap: 'wrap',
            }}
          >
            <h1
              className="h-serif"
              style={{ fontSize: 32, color: 'var(--text)', margin: 0 }}
            >
              {job.title}
            </h1>
            {dept && (
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
            )}
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
            {job.location} · {job.type}
          </p>
        </div>

        <div className="card fade-in">
          {submitted ? (
            <div style={{ padding: '56px 32px', textAlign: 'center' }}>
              <div
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: '50%',
                  background: 'var(--accent-soft)',
                  border: '1px solid var(--accent-border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 16px',
                }}
              >
                <svg
                  width="20"
                  height="20"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="var(--accent)"
                  strokeWidth={2.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="h-serif" style={{ fontSize: 22, color: 'var(--text)', marginBottom: 8 }}>
                Application submitted
              </h2>
              <p
                className="body-serif"
                style={{
                  fontSize: 14,
                  color: 'var(--text-dim)',
                  maxWidth: 320,
                  margin: '0 auto 24px',
                }}
              >
                Thanks for applying to Sapling. We&apos;ll review your application and reach out soon.
              </p>
              <Link
                href="/careers"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 13,
                  color: 'var(--accent)',
                  textDecoration: 'none',
                  fontWeight: 500,
                }}
              >
                ← Back to opportunities
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ padding: 32 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <div>
                  <label style={LABEL_STYLE}>
                    Full Name <span style={{ color: 'var(--err)' }}>*</span>
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
                    Email <span style={{ color: 'var(--err)' }}>*</span>
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
                    LinkedIn Profile <span style={{ color: 'var(--err)' }}>*</span>
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
                    Resume <span style={{ color: 'var(--err)' }}>*</span>
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
                      border: `1.5px dashed ${
                        dragging ? 'var(--accent)' : 'var(--border-strong)'
                      }`,
                      borderRadius: 'var(--r-sm)',
                      padding: '28px 20px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      background: dragging ? 'var(--accent-soft)' : 'var(--bg-input)',
                      transition: 'all var(--dur-fast) var(--ease)',
                    }}
                  >
                    {resumeFile ? (
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: 8,
                        }}
                      >
                        <svg
                          width="16"
                          height="16"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="var(--accent)"
                          strokeWidth={2}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
                        </svg>
                        <span style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 500 }}>
                          {resumeFile.name}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setResumeFile(null);
                          }}
                          style={{
                            color: 'var(--text-muted)',
                            padding: '0 2px',
                            fontSize: 14,
                            lineHeight: 1,
                          }}
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
                          stroke="var(--text-muted)"
                          strokeWidth={1.5}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          style={{ margin: '0 auto 8px', display: 'block' }}
                        >
                          <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                        </svg>
                        <p style={{ fontSize: 13, color: 'var(--text-dim)', margin: '0 0 2px' }}>
                          <span style={{ fontWeight: 500, color: 'var(--accent)' }}>
                            Click to upload
                          </span>{' '}
                          or drag and drop
                        </p>
                        <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0 }}>PDF only</p>
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

              <div
                style={{
                  marginTop: 20,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                }}
              >
                <input
                  type="checkbox"
                  id="privacy-consent"
                  required
                  checked={agreedToPrivacy}
                  onChange={(e) => setAgreedToPrivacy(e.target.checked)}
                  style={{
                    marginTop: 2,
                    accentColor: 'var(--accent)',
                    cursor: 'pointer',
                    flexShrink: 0,
                  }}
                />
                <label
                  htmlFor="privacy-consent"
                  style={{
                    fontSize: 13,
                    color: 'var(--text-dim)',
                    lineHeight: 1.5,
                    cursor: 'pointer',
                  }}
                >
                  I have read and agree to Sapling&apos;s{' '}
                  <Link
                    href="/privacy"
                    target="_blank"
                    style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                  >
                    Privacy Policy
                  </Link>
                  , including how my application data is collected and used.
                </label>
              </div>

              <div
                style={{
                  marginTop: 28,
                  paddingTop: 24,
                  borderTop: '1px solid var(--border)',
                }}
              >
                {submitError && (
                  <p
                    style={{
                      fontSize: 13,
                      color: 'var(--err)',
                      marginBottom: 12,
                      textAlign: 'center',
                    }}
                  >
                    {submitError}
                  </p>
                )}
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn btn--primary"
                  style={{
                    width: '100%',
                    justifyContent: 'center',
                    padding: '12px 20px',
                    fontSize: 14,
                    opacity: submitting ? 0.8 : 1,
                    cursor: submitting ? 'default' : 'pointer',
                  }}
                >
                  {submitting ? 'Submitting…' : 'Submit Application'}
                </button>
                <p
                  style={{
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    textAlign: 'center',
                    marginTop: 10,
                  }}
                >
                  Fields marked <span style={{ color: 'var(--err)' }}>*</span> are required
                </p>
              </div>
            </form>
          )}
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
