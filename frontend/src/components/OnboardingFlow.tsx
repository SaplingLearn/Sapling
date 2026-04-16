'use client';

import { useState, useEffect } from 'react';
import { X, ChevronRight, ChevronLeft, XCircle } from 'lucide-react';


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

const STEPS = [
  { id: 'google',   label: 'Account',        color: '#9CA3AF' },
  { id: 'name',     label: 'Name',           color: '#D97706' },
  { id: 'school',   label: 'School',         color: '#8A63D2' },
  { id: 'academics',label: 'Academics',      color: '#3B82F6' },
  { id: 'courses',  label: 'Courses',        color: '#14B8A6' },
  { id: 'style',    label: 'Learning Style', color: '#EF4444' },
] as const;

const BU_MAJORS = [
  'Acting', 'Advertising', 'African American & Black Diaspora Studies', 'American Studies',
  'Ancient Greek & Latin', 'Ancient Greek Language & Culture', 'Anthropology & Religion',
  'Anthropology: Behavioral Biology', 'Anthropology: Biological Anthropology', 'Anthropology: Sociocultural Anthropology',
  'Archaeological & Environmental Sciences', 'Architectural Studies', 'Art', 'Art Education',
  'Astronomy', 'Astronomy & Physics', 'Astrophysics & Space Physics',
  'Behavior & Health', 'Biochemistry & Molecular Biology', 'Bioinformatics',
  'Biology', 'Biology: Behavioral Biology', 'Biology: Cell Biology, Molecular Biology & Genetics',
  'Biology: Ecology & Conservation Biology', 'Biology: Neurobiology', 'Biomedical Engineering',
  'Business Administration', 'Chemistry', 'Chemistry & Physics', 'Chemistry: Chemical Biology',
  'Chemistry: Materials and Nanoscience', 'Chinese Language & Literature', 'Cinema & Media Studies',
  'Classical Civilization', 'Classical Studies', 'Classics & Archaeology', 'Classics & Philosophy',
  'Classics & Religion', 'Comparative Literature', 'Computer Engineering', 'Computer Science',
  'Computer Science & Economics', 'Criminal Justice', 'Data Science',
  'Earth & Environmental Sciences', 'Economics', 'Economics & Mathematics',
  'Education & Human Development', 'Electrical Engineering', 'Elementary Education',
  'English', 'English Education', 'Environmental Analysis & Policy',
  'Film & Television', 'French & Linguistics', 'French Studies', 'German Language & Literature',
  'Graphic Design', 'Health Science', 'History', 'History of Art & Architecture',
  'Hospitality Administration', 'Hospitality & Communication', 'Human Physiology',
  'Interdisciplinary Studies', 'International Relations', 'Italian & Linguistics', 'Italian Studies',
  'Japanese & Linguistics', 'Japanese Language & Literature', 'Journalism',
  'Korean Language & Literature', 'Latin American Studies', 'Latin Language & Culture',
  'Linguistics', 'Linguistics & African Languages', 'Linguistics & Computer Science',
  'Linguistics & Philosophy', 'Linguistics and Speech, Language & Hearing Sciences',
  'Management Studies', 'Marine Science', 'Mathematics', 'Mathematics & Computer Science',
  'Mathematics & Mathematics Education', 'Mathematics & Philosophy', 'Mathematics & Physics',
  'Mathematics Education', 'Mechanical Engineering', 'Media Science',
  'Middle East & North Africa Studies', 'Middle Eastern and South Asian Languages & Literatures',
  'Modern Foreign Language Education', 'Music', 'Music Composition & Theory', 'Music Education',
  'Music Performance', 'Neuroscience', 'Nutrition', 'Painting', 'Philosophy',
  'Philosophy & Neuroscience', 'Philosophy & Physics', 'Philosophy & Political Science',
  'Philosophy & Psychology', 'Philosophy & Religion', 'Physical Therapy', 'Physics',
  'Physics & Computer Science', 'Political Science', 'Printmaking', 'Psychology',
  'Public Health', 'Public Relations', 'Russian Language & Literature',
  'Science Education', 'Sculpture', 'Social Studies Education', 'Sociology',
  'Sound Design', 'Spanish', 'Spanish & Linguistics', 'Special Education',
  'Speech, Language & Hearing Sciences', 'Stage Management', 'Teaching of Chemistry',
  'Theatre Arts', 'Urban Affairs',
];

const BU_MINORS = [
  'Advertising', 'African American & Black Diaspora Studies', 'African Languages & Literatures',
  'African Studies', 'American Studies', 'Ancient Greek', 'Anthropology', 'Arabic',
  'Archaeological & Environmental Sciences', 'Astronomy', 'Autism Spectrum Disorders',
  'Chinese', 'Cinema & Media Studies', 'Classical Civilization', 'Comparative Literature',
  'Computer Engineering', 'Computer Science', 'Core Curriculum', 'Core Independent Studies',
  'Dance', 'Deaf Education', 'Deaf Studies', 'Earth & Environmental Sciences', 'Economics',
  'Education', 'Emotional & Behavioral Challenges in Schools', 'Engineering Science',
  'English', 'Environmental Analysis & Policy', 'Environmental Remote Sensing & GIS',
  'European Studies', 'Event Management & Public Relations', 'Film & Television',
  'French Studies', 'German', 'Global Medieval Studies', 'Hebrew', 'History',
  'History of Art & Architecture', 'Holocaust, Genocide & Human Rights Studies',
  'Hospitality Administration', 'Human Physiology', 'Innovation & Entrepreneurship',
  'Interdisciplinary Studies', 'Israel Studies', 'Italian', 'Japanese', 'Jewish Studies',
  'Journalism', 'Korean', 'Latin', 'Latin American Studies', 'Linguistics', 'Marine Science',
  'Materials Science & Engineering', 'Mathematics', 'Mathematics Education',
  'Mechanical Engineering', 'Media Science', 'Medical Anthropology', 'Modern Greek', 'Music',
  'Muslim Cultures', 'Muslim Societies', 'Myth Studies', 'Persian Cultural Studies',
  'Philosophy', 'Physics', 'Political Science', 'Portuguese & Brazilian Cultural Studies',
  'Psychology', 'Public Health', 'Public Policy Analysis', 'Real Estate', 'Religion',
  'Russian', 'Sociology', 'Special Education', 'Statistics', 'Sustainable Energy',
  'Systems Engineering', 'Teaching Science Education', 'Theatre Arts', 'Turkish Cultural Studies',
  'Urban Affairs', 'Urban Studies', 'Visual Arts', "Women's, Gender & Sexuality Studies",
];


const LEARNING_STYLES = [
  { id: 'visual',   label: 'Visual',          desc: 'Diagrams, charts, and visual maps' },
  { id: 'reading',  label: 'Reading / Writing', desc: 'Notes, textbooks, and written summaries' },
  { id: 'auditory', label: 'Auditory',         desc: 'Lectures, discussions, verbal explanations' },
  { id: 'hands-on', label: 'Hands-On',         desc: 'Practice problems and active experimentation' },
  { id: 'mixed',    label: 'Mixed',            desc: 'A combination of multiple styles' },
];

interface FormData {
  firstName: string;
  lastName: string;
  school: string;
  year: string;
  majors: string[];
  minors: string[];
  courses: string[];
  style: string;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  onFinish: (data: { firstName: string; lastName: string; school: string; year: string; majors: string[]; minors: string[]; courses: string[]; style: string }) => void;
  activeStep: number;
  completed: Set<number>;
  setActiveStep: (s: number) => void;
  setCompleted: (s: Set<number>) => void;
}

export default function OnboardingFlow({ visible, onClose, onFinish, activeStep, completed, setActiveStep, setCompleted }: Props) {
  const [classInput, setClassInput] = useState('');
  const [yearOpen, setYearOpen] = useState(false);

  const YEAR_OPTIONS = ['Freshman', 'Sophomore', 'Junior', 'Senior', 'Graduate', 'Other'];
  const [majorInput, setMajorInput] = useState('');
  const [minorInput, setMinorInput] = useState('');
  const [majorSuggestions, setMajorSuggestions] = useState<string[]>([]);
  const [minorSuggestions, setMinorSuggestions] = useState<string[]>([]);
  const [majorFocused, setMajorFocused] = useState(false);
  const [minorFocused, setMinorFocused] = useState(false);

  const [formData, setFormData] = useState<FormData>({
    firstName: '', lastName: '',
    school: 'Boston University', year: '', majors: [], minors: [], courses: [], style: '',
  });


  // Escape key closes
  useEffect(() => {
    if (!visible) return;

    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [visible, onClose]);

  function handleOptionKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, onSelect: () => void) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect();
    }
  }

  function selectYear(option: string) {
    setFormData(prev => ({ ...prev, year: option.toLowerCase() }));
    setYearOpen(false);
  }

  function handleMajorInput(value: string) {
    setMajorInput(value);
    if (value.trim().length < 1) { setMajorSuggestions([]); return; }
    setMajorSuggestions(
      BU_MAJORS.filter(m => m.toLowerCase().includes(value.toLowerCase()) && !formData.majors.includes(m)).slice(0, 8)
    );
  }

  function addMajor(m: string) {
    if (!formData.majors.includes(m)) setFormData(prev => ({ ...prev, majors: [...prev.majors, m] }));
    setMajorInput(''); setMajorSuggestions([]);
  }

  function handleMinorInput(value: string) {
    setMinorInput(value);
    if (value.trim().length < 1) { setMinorSuggestions([]); return; }
    setMinorSuggestions(
      BU_MINORS.filter(m => m.toLowerCase().includes(value.toLowerCase()) && !formData.minors.includes(m)).slice(0, 8)
    );
  }

  function addMinor(m: string) {
    if (!formData.minors.includes(m)) setFormData(prev => ({ ...prev, minors: [...prev.minors, m] }));
    setMinorInput(''); setMinorSuggestions([]);
  }

  function canAdvance(): boolean {
    switch (activeStep) {
      case 0: return false;
      case 1: return formData.firstName.trim().length > 0 && formData.lastName.trim().length > 0;
      case 2: return formData.school.trim().length > 0 && formData.year.length > 0;
      case 3: return formData.majors.length > 0;
      case 4: return formData.courses.length > 0;
      case 5: return formData.style.length > 0;
      default: return false;
    }
  }

  function handleGoogleSignIn() {
    sessionStorage.setItem('sapling_onboarding_pending', 'true');
    window.location.href = `${API_URL}/api/auth/google`;
  }

  function handleNext() {
    if (!canAdvance()) return;
    setCompleted(new Set([...completed, activeStep]));
    if (activeStep < STEPS.length - 1) {
      setActiveStep(activeStep + 1);
    } else {
      onFinish(formData);
    }
  }

  function handleBack() {
    if (activeStep > 0) setActiveStep(activeStep - 1);
  }

  function addClass() {
    const v = classInput.trim();
    if (v) {
      setFormData(prev => ({ ...prev, courses: [...prev.courses, v] }));
      setClassInput('');
    }
  }

  const activeColor = STEPS[activeStep].color;

  const headingStyle: React.CSSProperties = {
    textAlign: 'center',
    fontFamily: "var(--font-playfair), 'Playfair Display', serif",
    fontSize: '30px', fontWeight: 600, color: '#0f172a',
    marginBottom: '8px', lineHeight: 1.2,
    textShadow: '0 0 24px rgba(255,255,255,1), 0 0 48px rgba(255,255,255,0.75)',
  };

  const subtitleStyle: React.CSSProperties = {
    textAlign: 'center',
    color: 'rgba(15,23,42,0.62)',
    fontSize: '13px', marginBottom: '28px',
    textShadow: '0 0 16px rgba(255,255,255,1), 0 0 32px rgba(255,255,255,0.7)',
  };

  const inputStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.52)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
    border: '1px solid rgba(0,0,0,0.13)',
    color: '#111827',
    borderRadius: '14px',
    padding: '14px 18px',
    fontSize: '15px',
    outline: 'none',
    width: '100%',
    fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 80,
        opacity: visible ? 1 : 0,
        transition: 'opacity 600ms cubic-bezier(0.22,1,0.36,1)',
        pointerEvents: visible ? 'auto' : 'none',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
      }}
    >
      {/* ── Close ── */}
      <button
        onClick={onClose}
        style={{
          position: 'absolute', top: '28px', right: '32px', zIndex: 10,
          color: 'rgba(0,0,0,0.28)', background: 'none', border: 'none',
          padding: '8px', display: 'flex', cursor: 'pointer',
          transition: 'color 0.2s ease',
        }}
      >
        <X style={{ width: '22px', height: '22px' }} strokeWidth={1.5} />
      </button>

      {/* ── Step indicator (top-left) ── */}
      {activeStep > 0 && (
        <div style={{ position: 'absolute', top: '28px', left: '32px', zIndex: 10 }}>
          <div style={{
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase',
            color: '#1B6C42', fontWeight: 700, marginBottom: '4px',
          }}>
            Step {activeStep} / {STEPS.length - 1}
          </div>
          <div style={{
            fontFamily: "var(--font-playfair), 'Playfair Display', serif",
            fontSize: '18px', fontWeight: 600, color: '#0f172a',
            marginBottom: '10px', letterSpacing: '-0.01em',
          }}>
            {STEPS[activeStep].label}
          </div>
          {(() => {
            const totalSteps = STEPS.length - 1;
            const GAP = 3;
            const totalWidth = 200;
            const segW = (totalWidth - (totalSteps - 1) * GAP) / totalSteps;
            const filledW = activeStep > 0
              ? activeStep * segW + (activeStep - 1) * GAP
              : 0;
            return (
              <div style={{ position: 'relative', width: `${totalWidth}px`, height: '4px' }}>
                <div style={{ display: 'flex', gap: `${GAP}px`, position: 'absolute', inset: 0 }}>
                  {Array.from({ length: totalSteps }, (_, i) => (
                    <div key={i} style={{
                      width: `${segW}px`, height: '100%', flexShrink: 0,
                      background: 'rgba(27,108,66,0.12)', borderRadius: '99px',
                    }} />
                  ))}
                </div>
                <div style={{
                  position: 'absolute', left: 0, top: 0, height: '100%',
                  width: `${filledW}px`,
                  background: '#1B6C42', borderRadius: '99px',
                  transition: 'width 0.55s cubic-bezier(0.22,1,0.36,1)',
                }} />
              </div>
            );
          })()}
        </div>
      )}

      {/* ── Centered step dot + label ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '18px' }}>
        <span style={{
          display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
          background: activeColor, boxShadow: `0 0 8px ${activeColor}cc`,
        }} />
        <span style={{
          fontFamily: "var(--font-jetbrains), 'JetBrains Mono', monospace",
          fontSize: '10px', letterSpacing: '0.28em', textTransform: 'uppercase',
          color: activeColor, fontWeight: 500,
        }}>
          {STEPS[activeStep].label}
        </span>
      </div>

      {/* ── Content column ── */}
      <div style={{ width: '100%', maxWidth: '440px', padding: '0 28px' }}>
        <div key={activeStep} style={{ animation: 'ob-card-in 0.38s cubic-bezier(0.22,1,0.36,1) both', position: 'relative', zIndex: 1 }}>

          {activeStep === 0 && (
            <div>
              <h3 style={headingStyle}>Let&apos;s get started</h3>
              <p style={subtitleStyle}>Sign in with Google to create your Sapling account. A valid .edu email is required to register.</p>
              <button
                onClick={handleGoogleSignIn}
                style={{
                  ...inputStyle,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px',
                  background: 'rgba(255,255,255,0.85)',
                  border: '1px solid rgba(0,0,0,0.13)',
                  cursor: 'pointer', fontWeight: 500, fontSize: '15px',
                  color: '#111827', transition: 'all 0.2s',
                }}
              >
                <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
                  <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
                  <path d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
                  <path d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332z" fill="#FBBC05"/>
                  <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
                </svg>
                Continue with Google
              </button>
            </div>
          )}

          {activeStep === 1 && (
            <div>
              <h3 style={headingStyle}>
                What&apos;s your name?
              </h3>
              <p style={subtitleStyle}>
                This is how you&apos;ll appear on Sapling.
              </p>
              <div style={{ display: 'flex', gap: '10px' }}>
                <input type="text" value={formData.firstName}
                  onChange={e => setFormData(prev => ({ ...prev, firstName: e.target.value }))}
                  placeholder="First" autoFocus style={{ ...inputStyle, flex: 1 }} />
                <input type="text" value={formData.lastName}
                  onChange={e => setFormData(prev => ({ ...prev, lastName: e.target.value }))}
                  placeholder="Last" style={{ ...inputStyle, flex: 1 }} />
              </div>
            </div>
          )}

          {activeStep === 2 && (
            <div>
              <h3 style={headingStyle}>
                Where do you study?
              </h3>
              <p style={subtitleStyle}>
                Sapling is currently available for BU affiliates. Select your year below.
              </p>
              <div style={{
                ...inputStyle,
                marginBottom: '10px',
                color: '#111827',
                fontWeight: 500,
                background: 'rgba(255,255,255,0.65)',
              }}>
                Boston University
              </div>
              <div style={{ position: 'relative', zIndex: yearOpen ? 20 : 1 }}>
                <button
                  type="button"
                  onClick={() => setYearOpen(o => !o)}
                  onBlur={() => setTimeout(() => setYearOpen(false), 150)}
                  style={{
                    ...inputStyle,
                    textAlign: 'left', cursor: 'pointer',
                    color: formData.year ? '#111827' : 'rgba(0,0,0,0.35)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    background: 'rgba(255,255,255,0.52)',
                  }}
                >
                  <span>{formData.year ? formData.year.charAt(0).toUpperCase() + formData.year.slice(1) : 'Select class year'}</span>
                  <ChevronRight style={{ width: '16px', height: '16px', transform: yearOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s', flexShrink: 0, color: 'rgba(0,0,0,0.35)' }} />
                </button>
                {yearOpen && (
                  <div style={{
                    position: 'absolute', top: 'calc(100% + 6px)', left: 0, right: 0,
                    background: '#ffffff',
                    border: '1px solid rgba(0,0,0,0.1)',
                    borderRadius: '14px',
                    maxHeight: '192px', overflowY: 'auto',
                    zIndex: 100,
                    boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
                  }} role="listbox" aria-label="Class year options">
                    {YEAR_OPTIONS.map((opt, i) => (
                      <button
                        key={opt}
                        type="button"
                        role="option"
                        aria-selected={formData.year === opt.toLowerCase()}
                        onMouseDown={() => selectYear(opt)}
                        onKeyDown={e => handleOptionKeyDown(e, () => selectYear(opt))}
                        style={{
                          width: '100%',
                          textAlign: 'left',
                          padding: '12px 18px',
                          fontSize: '14px',
                          color: formData.year === opt.toLowerCase() ? '#1B6C42' : '#111827',
                          fontWeight: formData.year === opt.toLowerCase() ? 500 : 400,
                          cursor: 'pointer',
                          borderBottom: i < YEAR_OPTIONS.length - 1 ? '1px solid rgba(0,0,0,0.06)' : 'none',
                          fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                          transition: 'background 0.15s',
                          background: formData.year === opt.toLowerCase() ? 'rgba(27,108,66,0.06)' : 'transparent',
                          borderLeft: 'none',
                          borderRight: 'none',
                          borderTop: 'none',
                        }}
                        onMouseEnter={e => { if (formData.year !== opt.toLowerCase()) e.currentTarget.style.background = 'rgba(27,108,66,0.08)'; }}
                        onMouseLeave={e => { e.currentTarget.style.background = formData.year === opt.toLowerCase() ? 'rgba(27,108,66,0.06)' : 'transparent'; }}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {activeStep === 3 && (
            <div>
              <h3 style={headingStyle}>What&apos;s your major?</h3>
              <p style={subtitleStyle}>Add your major(s) and any minor(s).</p>

              {/* Majors */}
              {(['majors', 'minors'] as const).map(field => {
                const isMinor = field === 'minors';
                const input = isMinor ? minorInput : majorInput;
                const suggestions = isMinor ? minorSuggestions : majorSuggestions;
                const focused = isMinor ? minorFocused : majorFocused;
                const setFocused = isMinor ? setMinorFocused : setMajorFocused;
                const handleInput = isMinor ? handleMinorInput : handleMajorInput;
                const addItem = isMinor ? addMinor : addMajor;
                const items = formData[field];
                const activeCol = STEPS[activeStep].color;
                return (
                  <div key={field} style={{ marginBottom: isMinor ? 0 : '16px' }}>
                    <div style={{
                      fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em',
                      color: 'rgba(0,0,0,0.45)', marginBottom: '8px',
                      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                    }}>
                      {isMinor ? 'Minors' : 'Majors'}{isMinor && <span style={{ fontWeight: 400, opacity: 0.6, textTransform: 'none', letterSpacing: 0 }}> · optional</span>}
                    </div>
                    <div style={{ position: 'relative', zIndex: focused ? 20 : 1 }}>
                      <input
                        type="text" value={input} autoFocus={!isMinor}
                        onChange={e => handleInput(e.target.value)}
                        onFocus={() => setFocused(true)}
                        onBlur={() => setTimeout(() => setFocused(false), 150)}
                        placeholder={isMinor ? 'Search minors...' : 'Search majors...'}
                        style={{ ...inputStyle }}
                      />
                      {focused && suggestions.length > 0 && (
                        <div style={{
                          position: 'absolute', top: 'calc(100% + 6px)', left: 0, right: 0,
                          background: '#ffffff', border: '1px solid rgba(0,0,0,0.1)',
                          borderRadius: '14px', maxHeight: '180px', overflowY: 'auto',
                          zIndex: 100, boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
                        }} role="listbox" aria-label={isMinor ? 'Minor suggestions' : 'Major suggestions'}>
                          {suggestions.map((s, i) => (
                            <button
                              key={i}
                              type="button"
                              role="option"
                              aria-selected={items.includes(s)}
                              onMouseDown={() => addItem(s)}
                              onKeyDown={e => handleOptionKeyDown(e, () => addItem(s))}
                              style={{
                              width: '100%',
                              textAlign: 'left',
                              padding: '11px 18px', fontSize: '14px', color: '#111827', cursor: 'pointer',
                              borderBottom: i < suggestions.length - 1 ? '1px solid rgba(0,0,0,0.06)' : 'none',
                              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif", transition: 'background 0.15s',
                              background: 'transparent',
                              borderLeft: 'none',
                              borderRight: 'none',
                              borderTop: 'none',
                            }}
                              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(27,108,66,0.08)')}
                              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                            >{s}</button>
                          ))}
                        </div>
                      )}
                    </div>
                    {items.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '7px', marginTop: '10px' }}>
                        {items.map((item, idx) => (
                          <div key={idx} style={{
                            background: `${activeCol}18`, border: `1px solid ${activeCol}40`,
                            borderRadius: '9999px', padding: '5px 12px', fontSize: '12px',
                            color: '#111827', display: 'flex', alignItems: 'center', gap: '7px',
                            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                          }}>
                            {item}
                            <button onClick={() => setFormData(prev => ({ ...prev, [field]: prev[field].filter((_, i) => i !== idx) }))}
                              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', display: 'flex', color: 'rgba(0,0,0,0.35)' }}>
                              <XCircle style={{ width: '13px', height: '13px' }} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {activeStep === 4 && (
            <div>
              <h3 style={headingStyle}>
                What are you studying?
              </h3>
              <p style={subtitleStyle}>
                Add your courses this semester.
              </p>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                <input type="text" value={classInput}
                  onChange={e => setClassInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addClass(); } }}
                  placeholder="Add a class..." autoFocus style={{ ...inputStyle, flex: 1 }} />
                <button onClick={addClass} style={{
                  padding: '12px 18px',
                  background: 'rgba(255,255,255,0.52)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
                  border: `1px solid ${activeColor}50`, borderRadius: '14px',
                  color: activeColor, fontSize: '13px', fontWeight: 500, cursor: 'pointer',
                  whiteSpace: 'nowrap', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                }}>Add</button>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', minHeight: '38px' }}>
                {formData.courses.map((chip, idx) => (
                  <div key={`${chip}-${idx}`} style={{
                    background: 'rgba(255,255,255,0.5)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
                    border: '1px solid rgba(0,0,0,0.1)',
                    borderRadius: '9999px', padding: '6px 14px', color: '#111827',
                    fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px',
                  }}>
                    {chip}
                    <button onClick={() => setFormData(prev => ({ ...prev, courses: prev.courses.filter((_, i) => i !== idx) }))}
                      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', display: 'flex', color: 'rgba(0,0,0,0.35)' }}>
                      <XCircle style={{ width: '14px', height: '14px' }} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeStep === 5 && (
            <div>
              <h3 style={headingStyle}>
                How do you learn best?
              </h3>
              <p style={{ ...subtitleStyle, marginBottom: '20px' }}>
                Sapling&apos;s AI adapts to your style.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {LEARNING_STYLES.map(ls => (
                  <button key={ls.id} onClick={() => setFormData(prev => ({ ...prev, style: ls.id }))} style={{
                    textAlign: 'left', padding: '12px 16px', borderRadius: '12px',
                    background: formData.style === ls.id ? `${activeColor}18` : 'rgba(255,255,255,0.45)',
                    backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)',
                    border: formData.style === ls.id ? `1px solid ${activeColor}60` : '1px solid rgba(0,0,0,0.09)',
                    cursor: 'pointer', transition: 'all 0.22s ease',
                  }}>
                    <div style={{ color: '#0f172a', fontSize: '13px', fontWeight: 500, marginBottom: '1px', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>{ls.label}</div>
                    <div style={{ color: 'rgba(0,0,0,0.4)', fontSize: '12px', fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif" }}>{ls.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Navigation ── */}
        {activeStep > 0 && (
          <div style={{ display: 'flex', gap: '10px', marginTop: '28px', justifyContent: 'center' }}>
            <button onClick={handleBack} style={{
              display: 'flex', alignItems: 'center', gap: '5px',
              padding: '13px 22px',
              background: 'rgba(255,255,255,0.48)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)',
              border: '1px solid rgba(27,108,66,0.25)', borderRadius: '100px',
              color: '#1B6C42', fontSize: '13px', fontWeight: 500,
              cursor: 'pointer', transition: 'all 0.2s ease',
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            }}>
              <ChevronLeft style={{ width: '15px', height: '15px' }} />
              Back
            </button>
            <button onClick={handleNext} disabled={!canAdvance()} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
              padding: '13px 40px',
              background: canAdvance() ? '#1B6C42' : 'rgba(255,255,255,0.4)',
              backdropFilter: canAdvance() ? 'none' : 'blur(10px)',
              WebkitBackdropFilter: canAdvance() ? 'none' : 'blur(10px)',
              border: canAdvance() ? 'none' : '1px solid rgba(0,0,0,0.09)',
              borderRadius: '100px',
              color: canAdvance() ? 'white' : 'rgba(0,0,0,0.25)',
              fontSize: '14px', fontWeight: 600,
              cursor: canAdvance() ? 'pointer' : 'not-allowed',
              boxShadow: canAdvance() ? '0 8px 32px rgba(27,108,66,0.35)' : 'none',
              transition: 'all 0.3s ease',
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            }}>
              {activeStep === STEPS.length - 1
                ? 'Launch Sapling'
                : <><span>Continue</span><ChevronRight style={{ width: '16px', height: '16px' }} /></>
              }
            </button>
          </div>
        )}
      </div>

    </div>
  );
}
