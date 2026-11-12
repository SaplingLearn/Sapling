"use client";

/**
 * Onboarding's screens, one component each (the flow itself is
 * screens/Onboarding.tsx). The courses and legal screens live in
 * CourseStep.tsx and LegalStep.tsx.
 */
import React, { useId, useLayoutEffect, useRef, useState } from "react";
import { CustomSelect } from "@/components/CustomSelect";
import { CakeArt, FEATURES, TourArt } from "./illustrations";
import { dayOptions, keepDay, yearOptions } from "./age";
import { BETA_LIST_HREF, CONNECTIONS, MONTHS, OTHER_SCHOOLS, type ConnChoices, type ConnKey, type Connection } from "./flow";
import { ScreenHead } from "./ScreenHead";

/** Where the legal contact sends a request about an under-13 account. */
const CONTACT_EMAIL = "careers@saplinglearn.com";

export function NameScreen({ name, onName }: { name: string; onName: (v: string) => void }) {
  return (
    <section className="ob-screen ob-screen--roomy">
      <ScreenHead title="First, what should I call you?" />
      <div className="ob-body">
        <img src="/onboarding/name-character.svg" alt="" className="ob-character" />
        <input
          data-testid="onboarding-name"
          className="ob-input ob-input--name"
          value={name}
          onChange={e => onName(e.target.value)}
          aria-label="Your first name"
          placeholder="Your first name"
          autoComplete="given-name"
          maxLength={80}
        />
        <p className="ob-note">From your Google account. Change it if you go by something else.</p>
      </div>
    </section>
  );
}

export interface Dob {
  m: string;
  d: string;
  y: string;
}

/** The app's own dropdown, dressed as the design's birthday fields. */
const OB_SELECT_TRIGGER: React.CSSProperties = {
  height: 50, padding: "0 16px", borderRadius: 14, border: "1.5px solid var(--ob-line)",
  background: "var(--ob-pan2)", color: "var(--ob-fg)", font: "500 15px 'Momo Trust Sans', sans-serif",
  backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
};

function DobSelect({ label, value, options, width, onChange }: {
  label: string; value: string; options: [string, string][]; width: number; onChange: (v: string) => void;
}) {
  const id = `onboarding-dob-${label.toLowerCase()}`;
  return (
    <CustomSelect
      testId={id}
      ariaLabel={label}
      placeholder={label}
      value={value}
      onChange={onChange}
      options={options.map(([v, l]) => ({ value: v, label: l, testId: `${id}-${v}` }))}
      style={{ minWidth: width }}
      triggerStyle={OB_SELECT_TRIGGER}
    />
  );
}

const MONTH_OPTIONS: [string, string][] = MONTHS.map((m, i) => [String(i + 1), m]);

/**
 * Shown instead of the date fields once the student says they are under 13
 * (and, in this browser, for a day after: components/onboarding/age.ts). It
 * says what is true: signing in made an account, nothing from this flow was
 * kept, and how to have the account removed.
 */
function AgeBlocked({ onSignOut }: { onSignOut: () => void }) {
  const titleRef = useRef<HTMLParagraphElement>(null);
  // The date fields this replaces had focus; hand it to the explanation.
  useLayoutEffect(() => {
    titleRef.current?.focus();
  }, []);
  return (
    <div className="ob-panel ob-blocked" data-testid="onboarding-blocked">
      <p ref={titleRef} tabIndex={-1} className="ob-blocked-title" data-testid="onboarding-blocked-title">
        Sapling is for students 13 and up.
      </p>
      <p className="ob-blocked-body">
        Signing in with Google created a Sapling account with your name and email address, but it
        can&apos;t be used until you&apos;re 13. We haven&apos;t kept your birthday or anything else you
        entered here.
      </p>
      <p className="ob-blocked-body">
        To have the account deleted, email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
      <button data-testid="onboarding-blocked-sign-out" className="ob-textlink" onClick={onSignOut}>
        Sign out
      </button>
    </div>
  );
}

export function BirthdayScreen({ dob, blocked, minor, onDob, onSignOut }: {
  dob: Dob;
  blocked: boolean;
  minor: boolean;
  onDob: (dob: Dob) => void;
  onSignOut: () => void;
}) {
  const set = (part: keyof Dob, value: string) => {
    const next = { ...dob, [part]: value };
    onDob({ ...next, d: keepDay(next.d, next.m, next.y) });
  };
  return (
    <section className="ob-screen ob-screen--roomy">
      <ScreenHead title="When's your birthday?" />
      <div className="ob-body" style={{ gap: 24 }}>
        <CakeArt />
        {blocked ? (
          <AgeBlocked onSignOut={onSignOut} />
        ) : (
          <div className="ob-dob">
            <DobSelect label="Month" value={dob.m} width={170} onChange={v => set("m", v)} options={MONTH_OPTIONS} />
            <DobSelect label="Day" value={dob.d} width={100} onChange={v => set("d", v)} options={dayOptions(dob.m, dob.y)} />
            <DobSelect label="Year" value={dob.y} width={120} onChange={v => set("y", v)} options={yearOptions()} />
          </div>
        )}
        {/* On the page before it is filled, so the note is read out when it appears. */}
        <div aria-live="polite">
          {minor && !blocked && (
            <p className="ob-bubble" data-testid="onboarding-minor-note">
              Since you&apos;re under 18, your profile starts private and sharing with your class starts
              off. You can change both later.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

export function SchoolScreen({ school, onSchool, onSignOut }: {
  school: "" | "bu";
  onSchool: (v: "bu") => void;
  onSignOut: () => void;
}) {
  const [missing, setMissing] = useState(false);
  const panelId = useId();
  return (
    <section className="ob-screen">
      <ScreenHead title="Where do you study?" sub="Tap your school's logo." />
      <div className="ob-body" style={{ gap: 18 }}>
        <div className="ob-schools">
          <button
            data-testid="onboarding-school-bu"
            className="ob-school"
            aria-pressed={school === "bu"}
            onClick={() => onSchool("bu")}
          >
            <div className="ob-school-logo"><img src="/onboarding/schools/bu-t.png" alt="" style={{ height: "52%", width: "auto", maxWidth: "90%" }} /></div>
            Boston University
          </button>
          {OTHER_SCHOOLS.map(([name, logo, h]) => (
            <div key={name} className="ob-school ob-school--soon">
              <div className="ob-school-logo"><img src={`/onboarding/schools/${logo}`} alt="" style={{ height: h, width: "auto", maxWidth: "100%" }} /></div>
              {name}
              <span className="ob-soon">Coming soon</span>
            </div>
          ))}
        </div>
        <button
          data-testid="onboarding-school-missing"
          className="ob-textlink"
          aria-expanded={missing}
          aria-controls={panelId}
          onClick={() => setMissing(m => !m)}
        >
          My school isn&apos;t listed
        </button>
        <div id={panelId} aria-live="polite" className="ob-missing-slot">
          {missing && (
            <div className="ob-panel ob-missing" data-testid="onboarding-school-missing-panel">
              <p className="ob-missing-text">
                Sapling is open to Boston University students for now. Join the beta list to hear when it
                opens to more schools.
              </p>
              <div className="ob-missing-actions">
                <a data-testid="onboarding-beta-link" className="ob-textlink" href={BETA_LIST_HREF}>Join the beta list</a>
                <button data-testid="onboarding-school-sign-out" className="ob-textlink" onClick={onSignOut}>Sign out</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export function TourScreen() {
  return (
    <section className="ob-screen">
      <ScreenHead
        title="Your notes become a map."
        sub="Drop syllabi, slides or notes into the library, and Sapling extracts the concepts intelligently."
      />
      <div className="ob-body"><TourArt /></div>
    </section>
  );
}

export function FeaturesScreen() {
  return (
    <section className="ob-screen">
      <ScreenHead title="More than a map." sub="Everything you upload also powers these." />
      <div className="ob-body">
        <div className="ob-features">
          {FEATURES.map(f => (
            <div key={f.caption} className="ob-feature">{f.art}<span>{f.caption}</span></div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ConnectionRow({ connection: c, chosen, undoHintId, onConnect, onRemove }: {
  connection: Connection;
  chosen: boolean;
  undoHintId: string;
  onConnect: (key: ConnKey) => void;
  onRemove: (key: ConnKey) => void;
}) {
  return (
    <div className="ob-panel ob-conn">
      <div className="ob-conn-icon" aria-hidden="true"><img src={`/onboarding/icons/${c.icon}`} alt="" /></div>
      <div className="ob-conn-text">
        <span className="ob-conn-name">{c.name}</span>
        <span className="ob-conn-desc">{c.desc}</span>
      </div>
      {!c.consent ? (
        // Nothing is recorded for these yet, so nothing to press.
        <span className="ob-soon-tag" data-testid={`onboarding-connect-${c.key}`}>Coming soon</span>
      ) : chosen ? (
        <button
          data-testid={`onboarding-connect-${c.key}`}
          className="ob-pill ob-pill--on"
          aria-label={`Will connect after setup: ${c.name}`}
          aria-describedby={undoHintId}
          onClick={() => onRemove(c.key)}
        >
          Will connect after setup
        </button>
      ) : (
        <button
          data-testid={`onboarding-connect-${c.key}`}
          className="ob-pill ob-pill--primary"
          aria-label={`Connect ${c.name}`}
          onClick={() => onConnect(c.key)}
        >
          Connect
        </button>
      )}
    </div>
  );
}

export function ConnectScreen({ conn, hidden, onConnect, onRemove }: {
  conn: ConnChoices;
  /** Options whose feature is switched off for this student (useHiddenConnections). */
  hidden: Set<ConnKey>;
  onConnect: (key: ConnKey) => void;
  onRemove: (key: ConnKey) => void;
}) {
  const undoHintId = useId();
  return (
    <section className="ob-screen">
      <ScreenHead
        title="Connect your accounts"
        sub="Bring your deadlines and grades in. Every one is optional, and nothing connects until setup is done."
      />
      <span id={undoHintId} className="ob-sr-only">Press again to cancel.</span>
      <div className="ob-connect-wrap">
        <div className="ob-connect">
          {CONNECTIONS.filter(c => !hidden.has(c.key)).map(c => (
            <ConnectionRow
              key={c.key}
              connection={c}
              chosen={!!conn[c.key]}
              undoHintId={undoHintId}
              onConnect={onConnect}
              onRemove={onRemove}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
