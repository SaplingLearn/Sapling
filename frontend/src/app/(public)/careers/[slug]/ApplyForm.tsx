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
import { ACCENT, LABEL, MUTED } from '@/lib/landing/companionType';
import { cn } from "@/lib/cn";

const EYEBROW: React.CSSProperties = {
  display: 'block', fontFamily: LABEL, fontSize: 12, 
  color: ACCENT };

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
      className="cp-navlink inline-flex items-center gap-2 text-md [animation:fadeUp_600ms_ease_both]"
      style={{ color: MUTED }}
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
        <div className="py-20 px-0">
          <h1 className="m-0 font-display font-medium text-[40px] leading-[1.15] tracking-[-0.015em] text-ink-800">
            Role not found
          </h1>
          <p className="mt-4.5 mx-0 mb-6.5 font-serif text-lg leading-[1.6] text-ink-600 max-w-[58ch]">
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

        <h1 className="mt-4.5 mx-0 mb-0 font-display font-medium text-[48px] leading-[1.15] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_60ms_both]">
          {job.title}
        </h1>

        <div className="mt-4 flex items-center flex-wrap gap-3 [animation:fadeUp_700ms_ease_120ms_both]">
          {dept && (
            <span
              className="text-xs font-medium py-[3px] px-2.5 rounded-[99px]" style={{ background: dept.bg, color: dept.text, border: `1px solid ${dept.border}` }}
            >
              {job.department}
            </span>
          )}
          <span className="font-sans text-[12.5px]" style={{ color: MUTED }}>
            {job.location} · {job.type}
          </span>
        </div>

        <div
          className="mt-10 pt-10 border-t border-t-[rgba(42,39,31,0.10)] grid grid-cols-[repeat(auto-fit,_minmax(min(100%,380px),1fr))] gap-12 [align-items:start]"
        >
          {/* Sticky because the form beside it is about twice as tall; the
              offset clears the shell's 92px header scrim. */}
          <aside className="sticky top-27 [animation:fadeUp_700ms_ease_200ms_both]">
            <span style={EYEBROW}>The role</span>
            <p className="mt-3.5 mx-0 mb-0 font-serif text-[17.5px] leading-[1.64] text-ink-600">
              {job.description}
            </p>

            <div className="mt-7.5 pt-6.5 border-t border-t-[rgba(42,39,31,0.10)]">
              <span style={EYEBROW}>What you&apos;d touch</span>
              <div className="mt-3.5 flex flex-wrap gap-[7px]">
                {job.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-sm py-1 px-[11px] rounded-[7px] bg-ink-0 border border-[rgba(42,39,31,0.10)] text-ink-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </aside>

          <div className="bg-ink-0 border border-[rgba(42,39,31,0.10)] rounded-[18px] [animation:fadeUp_700ms_ease_260ms_both]">
            {submitted ? (
              <div className="py-[clamp(36px,5vw,52px)] px-[clamp(24px,4vw,36px)] text-center">
                <div
                  className="w-12 h-12 rounded-[50%] bg-[rgba(89,117,54,0.10)] border border-[rgba(89,117,54,0.28)] flex items-center justify-center mt-0 mx-auto mb-4.5"
                >
                  <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={ACCENT} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <h2 className="m-0 font-display font-medium text-3xl leading-[1.2] tracking-[-0.015em] text-ink-800">
                  Application submitted
                </h2>
                <p className="mt-3 mx-auto mb-6.5 max-w-[38ch] font-serif text-[15.5px] leading-[1.65] text-ink-600">
                  Thanks for applying to Sapling. We&apos;ll review your application and reach out soon.
                </p>
                <Link
                  href="/careers"
                  className="inline-flex items-center gap-[7px] text-[13.5px] font-semibold text-brand-forest"
                >
                  <span aria-hidden="true">←</span> All openings
                </Link>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="p-[clamp(24px,3.4vw,34px)]">
                <span style={EYEBROW}>Apply</span>

                <div className="mt-5.5 flex flex-col gap-5">
                  <div>
                    <label className="block text-md font-semibold text-ink-800 mb-[7px]">
                      Full Name <span className="text-err">*</span>
                    </label>
                    <input
                      type="text"
                      required
                      placeholder="Jane Smith"
                      value={form.name}
                      onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                      className="w-full bg-accent-fg border border-[rgba(42,39,31,0.16)] rounded-[8px] py-[11px] px-3.5 text-[14.5px] text-ink-800 font-sans box-border [transition:border-color_200ms]"
                    />
                  </div>

                  <div>
                    <label className="block text-md font-semibold text-ink-800 mb-[7px]">
                      Email <span className="text-err">*</span>
                    </label>
                    <input
                      type="email"
                      required
                      placeholder="jane@university.edu"
                      value={form.email}
                      onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                      className="w-full bg-accent-fg border border-[rgba(42,39,31,0.16)] rounded-[8px] py-[11px] px-3.5 text-[14.5px] text-ink-800 font-sans box-border [transition:border-color_200ms]"
                    />
                  </div>

                  <div>
                    <label className="block text-md font-semibold text-ink-800 mb-[7px]">Phone Number</label>
                    <input
                      type="tel"
                      placeholder="+1 (555) 000-0000"
                      value={form.phone}
                      onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                      className="w-full bg-accent-fg border border-[rgba(42,39,31,0.16)] rounded-[8px] py-[11px] px-3.5 text-[14.5px] text-ink-800 font-sans box-border [transition:border-color_200ms]"
                    />
                  </div>

                  <div>
                    <label className="block text-md font-semibold text-ink-800 mb-[7px]">
                      LinkedIn Profile <span className="text-err">*</span>
                    </label>
                    <input
                      type="url"
                      required
                      placeholder="https://linkedin.com/in/yourprofile"
                      value={form.linkedin}
                      onChange={(e) => setForm((f) => ({ ...f, linkedin: e.target.value }))}
                      className="w-full bg-accent-fg border border-[rgba(42,39,31,0.16)] rounded-[8px] py-[11px] px-3.5 text-[14.5px] text-ink-800 font-sans box-border [transition:border-color_200ms]"
                    />
                  </div>

                  <div>
                    <label className="block text-md font-semibold text-ink-800 mb-[7px]">Portfolio Link</label>
                    <input
                      type="url"
                      placeholder="https://yourportfolio.com"
                      value={form.portfolio}
                      onChange={(e) => setForm((f) => ({ ...f, portfolio: e.target.value }))}
                      className="w-full bg-accent-fg border border-[rgba(42,39,31,0.16)] rounded-[8px] py-[11px] px-3.5 text-[14.5px] text-ink-800 font-sans box-border [transition:border-color_200ms]"
                    />
                  </div>

                  <div>
                    <label className="block text-md font-semibold text-ink-800 mb-[7px]">
                      Resume <span className="text-err">*</span>
                    </label>
                    <div
                      onClick={() => fileInputRef.current?.click()}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragging(true);
                      }}
                      onDragLeave={() => setDragging(false)}
                      onDrop={handleDrop}
                      className={cn("rounded-md py-7 px-5 text-center cursor-pointer [transition:border-color_200ms,_background_200ms]", dragging ? "bg-[rgba(89,117,54,0.08)]" : "bg-accent-fg")} style={{ border: `1.5px dashed ${dragging ? ACCENT : 'rgba(42,39,31,0.22)'}` }}
                    >
                      {resumeFile ? (
                        <div className="flex items-center justify-center gap-2">
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
                          <span className="text-md text-brand-forest font-semibold">
                            {resumeFile.name}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setResumeFile(null);
                            }}
                            aria-label="Remove attached resume"
                            className="py-0 px-0.5 text-[15px] leading-none cursor-pointer" style={{ color: MUTED }}
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
                            className="mt-0 mx-auto mb-2 block"
                          >
                            <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                          </svg>
                          <p className="text-md text-ink-600 mt-0 mx-0 mb-[3px]">
                            <span className="font-semibold text-brand-forest">Click to upload</span>{' '}
                            or drag and drop
                          </p>
                          <p className="text-xs m-0" style={{ color: MUTED }}>PDF only</p>
                        </>
                      )}
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".pdf"
                        onChange={handleFileChange}
                        className="hidden"
                      />
                    </div>
                  </div>
                </div>

                <div className="mt-5.5 flex items-start gap-2.5">
                  <input
                    type="checkbox"
                    id="privacy-consent"
                    required
                    checked={agreedToPrivacy}
                    onChange={(e) => setAgreedToPrivacy(e.target.checked)}
                    className="mt-0.5 accent-brand-forest cursor-pointer shrink-0"
                  />
                  <label
                    htmlFor="privacy-consent"
                    className="text-md text-ink-600 leading-[1.55] cursor-pointer"
                  >
                    I have read and agree to Sapling&apos;s{' '}
                    <Link href="/privacy" target="_blank" className="text-brand-forest font-semibold underline">
                      Privacy Policy
                    </Link>
                    , including how my application data is collected and used.
                  </label>
                </div>

                <div className="mt-7 pt-6 border-t border-t-[rgba(42,39,31,0.10)]">
                  {submitError && (
                    <p className="text-md text-err mt-0 mx-0 mb-3 text-center">
                      {submitError}
                    </p>
                  )}
                  <button
                    type="submit"
                    disabled={submitting}
                    className={cn("cp-cta", "w-full flex justify-center items-center [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-[13px] px-5.5 font-sans text-[14.5px] font-semibold", submitting ? "opacity-80" : "opacity-100", submitting ? "cursor-default" : "cursor-pointer")}
                  >
                    {submitting ? 'Submitting…' : 'Submit Application'}
                  </button>
                  <p className="text-xs text-center mt-3 mx-0 mb-0" style={{ color: MUTED }}>
                    Fields marked <span className="text-err">*</span> are required
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
