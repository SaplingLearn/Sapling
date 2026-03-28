'use client';

import { useState, useRef } from 'react';
import Link from 'next/link';
import { type Job, DEPT_COLORS } from '../jobs';
import { submitJobApplication } from '@/lib/api';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const PANEL: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid rgba(107, 114, 128, 0.15)',
  borderRadius: '12px',
  boxShadow: '0 2px 10px rgba(26, 92, 42, 0.07), 0 1px 3px rgba(26, 92, 42, 0.04)',
};

const INPUT: React.CSSProperties = {
  width: '100%',
  background: '#f8fbf8',
  border: '1px solid rgba(107, 114, 128, 0.18)',
  borderRadius: '8px',
  padding: '10px 14px',
  fontSize: '14px',
  color: '#111827',
  fontFamily: UI_FONT,
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.15s',
};

const LABEL: React.CSSProperties = {
  display: 'block',
  fontSize: '13px',
  fontWeight: 500,
  color: '#374151',
  marginBottom: '6px',
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
      <div style={{ minHeight: '100vh', background: '#E9EFED', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: UI_FONT }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: '#6b7280', fontSize: '14px' }}>Role not found.</p>
          <Link href="/careers" style={{ color: '#1a5c2a', fontSize: '13px', marginTop: '12px', display: 'block' }}>← Back to opportunities</Link>
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
            href="/careers"
            style={{ fontSize: '13px', color: '#6b7280', textDecoration: 'none' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#111827')}
            onMouseLeave={e => (e.currentTarget.style.color = '#6b7280')}
          >
            ← Back to opportunities
          </Link>
        </div>
      </header>

      {/* ── Content ── */}
      <section style={{ maxWidth: '760px', margin: '0 auto', padding: '56px 24px 96px' }}>

        {/* Job context */}
        <div className="fade-up anim-d1" style={{ marginBottom: '32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
            <h1 style={{
              fontFamily: "var(--font-playfair), 'Playfair Display', serif",
              fontSize: '28px', fontWeight: 700, color: '#111827',
              letterSpacing: '-0.02em', margin: 0,
            }}>
              {job.title}
            </h1>
            {dept && (
              <span style={{
                fontSize: '11px', fontWeight: 500, padding: '2px 9px', borderRadius: '999px',
                background: dept.bg, color: dept.text, border: `1px solid ${dept.border}`,
              }}>
                {job.department}
              </span>
            )}
          </div>
          <p style={{ fontSize: '13px', color: '#9ca3af', margin: 0 }}>
            {job.location} · {job.type}
          </p>
        </div>

        {/* Form panel */}
        <div className="fade-up anim-d2" style={PANEL}>
          {submitted ? (
            <div style={{ padding: '56px 32px', textAlign: 'center' }}>
              <div style={{
                width: '48px', height: '48px', borderRadius: '50%',
                background: 'rgba(26,92,42,0.08)', border: '1px solid rgba(26,92,42,0.18)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                margin: '0 auto 16px',
              }}>
                <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="#1a5c2a" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 style={{ fontFamily: "var(--font-spectral), 'Spectral', serif", fontSize: '20px', fontWeight: 600, color: '#111827', marginBottom: '8px' }}>
                Application submitted
              </h2>
              <p style={{ fontSize: '13px', color: '#6b7280', lineHeight: 1.6, maxWidth: '320px', margin: '0 auto 24px' }}>
                Thanks for applying to Sapling. We&apos;ll review your application and reach out soon.
              </p>
              <Link
                href="/careers"
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '6px',
                  fontSize: '13px', color: '#1a5c2a', textDecoration: 'none', fontWeight: 500,
                }}
              >
                ← Back to opportunities
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ padding: '32px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

                {/* Full Name */}
                <div>
                  <label style={LABEL}>Full Name <span style={{ color: '#dc2626' }}>*</span></label>
                  <input
                    type="text"
                    required
                    placeholder="Jane Smith"
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    style={INPUT}
                    onFocus={e => (e.currentTarget.style.borderColor = 'rgba(26,92,42,0.4)')}
                    onBlur={e => (e.currentTarget.style.borderColor = 'rgba(107,114,128,0.18)')}
                  />
                </div>

                {/* Email */}
                <div>
                  <label style={LABEL}>Email <span style={{ color: '#dc2626' }}>*</span></label>
                  <input
                    type="email"
                    required
                    placeholder="jane@university.edu"
                    value={form.email}
                    onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                    style={INPUT}
                    onFocus={e => (e.currentTarget.style.borderColor = 'rgba(26,92,42,0.4)')}
                    onBlur={e => (e.currentTarget.style.borderColor = 'rgba(107,114,128,0.18)')}
                  />
                </div>

                {/* Phone */}
                <div>
                  <label style={LABEL}>Phone Number</label>
                  <input
                    type="tel"
                    placeholder="+1 (555) 000-0000"
                    value={form.phone}
                    onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                    style={INPUT}
                    onFocus={e => (e.currentTarget.style.borderColor = 'rgba(26,92,42,0.4)')}
                    onBlur={e => (e.currentTarget.style.borderColor = 'rgba(107,114,128,0.18)')}
                  />
                </div>

                {/* LinkedIn */}
                <div>
                  <label style={LABEL}>LinkedIn Profile <span style={{ color: '#dc2626' }}>*</span></label>
                  <input
                    type="url"
                    required
                    placeholder="https://linkedin.com/in/yourprofile"
                    value={form.linkedin}
                    onChange={e => setForm(f => ({ ...f, linkedin: e.target.value }))}
                    style={INPUT}
                    onFocus={e => (e.currentTarget.style.borderColor = 'rgba(26,92,42,0.4)')}
                    onBlur={e => (e.currentTarget.style.borderColor = 'rgba(107,114,128,0.18)')}
                  />
                </div>

                {/* Portfolio */}
                <div>
                  <label style={LABEL}>Portfolio Link</label>
                  <input
                    type="url"
                    placeholder="https://yourportfolio.com"
                    value={form.portfolio}
                    onChange={e => setForm(f => ({ ...f, portfolio: e.target.value }))}
                    style={INPUT}
                    onFocus={e => (e.currentTarget.style.borderColor = 'rgba(26,92,42,0.4)')}
                    onBlur={e => (e.currentTarget.style.borderColor = 'rgba(107,114,128,0.18)')}
                  />
                </div>

                {/* Resume */}
                <div>
                  <label style={LABEL}>Resume <span style={{ color: '#dc2626' }}>*</span></label>
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    onDragOver={e => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={handleDrop}
                    style={{
                      border: `1.5px dashed ${dragging ? 'rgba(26,92,42,0.5)' : 'rgba(107,114,128,0.25)'}`,
                      borderRadius: '8px',
                      padding: '28px 20px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      background: dragging ? 'rgba(26,92,42,0.03)' : '#f8fbf8',
                      transition: 'all 0.15s',
                    }}
                  >
                    {resumeFile ? (
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                        <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="#1a5c2a" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                          <path d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
                        </svg>
                        <span style={{ fontSize: '13px', color: '#1a5c2a', fontWeight: 500 }}>{resumeFile.name}</span>
                        <button
                          type="button"
                          onClick={e => { e.stopPropagation(); setResumeFile(null); }}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: '0 2px', fontSize: '14px', lineHeight: 1 }}
                        >
                          ×
                        </button>
                      </div>
                    ) : (
                      <>
                        <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="#9ca3af" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" style={{ margin: '0 auto 8px', display: 'block' }}>
                          <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                        </svg>
                        <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 2px' }}>
                          <span style={{ fontWeight: 500, color: '#1a5c2a' }}>Click to upload</span> or drag and drop
                        </p>
                        <p style={{ fontSize: '11px', color: '#9ca3af', margin: 0 }}>PDF only</p>
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

              {/* Privacy consent */}
              <div style={{ marginTop: '20px', display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                <input
                  type="checkbox"
                  id="privacy-consent"
                  required
                  checked={agreedToPrivacy}
                  onChange={e => setAgreedToPrivacy(e.target.checked)}
                  style={{ marginTop: '2px', accentColor: '#1a5c2a', cursor: 'pointer', flexShrink: 0 }}
                />
                <label htmlFor="privacy-consent" style={{ fontSize: '13px', color: '#6b7280', lineHeight: 1.5, cursor: 'pointer' }}>
                  I have read and agree to Sapling&apos;s{' '}
                  <Link href="/privacy" target="_blank" style={{ color: '#1a5c2a', textDecoration: 'underline' }}>
                    Privacy Policy
                  </Link>
                  , including how my application data is collected and used.
                </label>
              </div>

              {/* Submit */}
              <div style={{ marginTop: '28px', paddingTop: '24px', borderTop: '1px solid rgba(107,114,128,0.10)' }}>
                {submitError && (
                  <p style={{ fontSize: '13px', color: '#dc2626', marginBottom: '12px', textAlign: 'center' }}>
                    {submitError}
                  </p>
                )}
                <button
                  type="submit"
                  disabled={submitting}
                  style={{
                    width: '100%',
                    background: submitting ? '#4a9e6d' : '#1B6C42', color: 'white',
                    border: 'none', borderRadius: '8px',
                    padding: '12px 20px',
                    fontSize: '14px', fontWeight: 500,
                    fontFamily: UI_FONT,
                    cursor: submitting ? 'default' : 'pointer',
                    transition: 'background 0.15s',
                    opacity: submitting ? 0.8 : 1,
                  }}
                  onMouseEnter={e => { if (!submitting) e.currentTarget.style.background = '#155A35'; }}
                  onMouseLeave={e => { if (!submitting) e.currentTarget.style.background = '#1B6C42'; }}
                >
                  {submitting ? 'Submitting…' : 'Submit Application'}
                </button>
                <p style={{ fontSize: '11px', color: '#9ca3af', textAlign: 'center', marginTop: '10px' }}>
                  Fields marked <span style={{ color: '#dc2626' }}>*</span> are required
                </p>
              </div>
            </form>
          )}
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
