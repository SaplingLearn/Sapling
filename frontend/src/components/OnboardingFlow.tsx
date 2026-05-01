'use client';

import { useState, useEffect, useRef } from 'react';
import { X, ChevronRight, ChevronLeft, XCircle } from 'lucide-react';


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

const STEPS = [
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

interface CourseOption {
  id: string;
  course_code: string;
  course_name: string;
}

interface FormData {
  firstName: string;
  lastName: string;
  school: string;
  year: string;
  majors: string[];
  minors: string[];
  courses: CourseOption[];
  style: string;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  onFinish: (data: { firstName: string; lastName: string; school: string; year: string; majors: string[]; minors: string[]; course_ids: string[]; style: string }) => void;
  activeStep: number;
  completed: Set<number>;
  setActiveStep: (s: number) => void;
  setCompleted: (s: Set<number>) => void;
}

export default function OnboardingFlow({ visible, onClose, onFinish, activeStep, completed, setActiveStep, setCompleted }: Props) {
  const [yearOpen, setYearOpen] = useState(false);

  const YEAR_OPTIONS = ['Freshman', 'Sophomore', 'Junior', 'Senior', 'Graduate', 'Other'];
  const [majorInput, setMajorInput] = useState('');
  const [minorInput, setMinorInput] = useState('');
  const [majorSuggestions, setMajorSuggestions] = useState<string[]>([]);
  const [minorSuggestions, setMinorSuggestions] = useState<string[]>([]);
  const [majorFocused, setMajorFocused] = useState(false);
  const [minorFocused, setMinorFocused] = useState(false);
  const [courseInput, setCourseInput] = useState('');
  const [courseSuggestions, setCourseSuggestions] = useState<CourseOption[]>([]);
  const [courseFocused, setCourseFocused] = useState(false);
  const courseDebounceRef = useRef<NodeJS.Timeout | null>(null);

  const [formData, setFormData] = useState<FormData>({
    firstName: '', lastName: '',
    school: 'Boston University', year: '', majors: [], minors: [], courses: [], style: '',
  });


  // Escape key closes
  useEffect(() => {
    if (!visible) {
      if (courseDebounceRef.current) { clearTimeout(courseDebounceRef.current); courseDebounceRef.current = null; }
      return;
    }

    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
      if (courseDebounceRef.current) { clearTimeout(courseDebounceRef.current); courseDebounceRef.current = null; }
    };
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
      case 0: return formData.firstName.trim().length > 0 && formData.lastName.trim().length > 0;
      case 1: return formData.school.trim().length > 0 && formData.year.length > 0;
      case 2: return formData.majors.length > 0;
      case 3: return formData.courses.length > 0;
      case 4: return formData.style.length > 0;
      default: return false;
    }
  }

  function handleNext() {
    if (!canAdvance()) return;
    setCompleted(new Set([...completed, activeStep]));
    if (activeStep < STEPS.length - 1) {
      setActiveStep(activeStep + 1);
    } else {
      onFinish({
        firstName: formData.firstName,
        lastName: formData.lastName,
        school: formData.school,
        year: formData.year,
        majors: formData.majors,
        minors: formData.minors,
        course_ids: formData.courses.map(c => c.id),
        style: formData.style,
      });
    }
  }

  function handleBack() {
    if (activeStep > 0) setActiveStep(activeStep - 1);
  }

  function handleCourseInput(value: string) {
    setCourseInput(value);
    if (courseDebounceRef.current) clearTimeout(courseDebounceRef.current);
    if (value.trim().length < 1) { setCourseSuggestions([]); return; }
    courseDebounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`${API_URL}/api/onboarding/courses?q=${encodeURIComponent(value)}`);
        const data: { courses: CourseOption[] } = await res.json();
        const selectedIds = new Set(formData.courses.map(c => c.id));
        setCourseSuggestions(data.courses.filter(c => !selectedIds.has(c.id)));
      } catch {
        setCourseSuggestions([]);
      } finally {
        courseDebounceRef.current = null;
      }
    }, 200);
  }

  function addCourse(course: CourseOption) {
    if (!formData.courses.some(c => c.id === course.id)) {
      setFormData(prev => ({ ...prev, courses: [...prev.courses, course] }));
    }
    setCourseInput(''); setCourseSuggestions([]);
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
        overflowY: 'auto',
      }}
    >
      {/* ── Close ── */}
      <button
        onClick={onClose}
        style={{
          position: 'fixed', top: '28px', right: '32px', zIndex: 10,
          color: 'rgba(0,0,0,0.28)', background: 'none', border: 'none',
          padding: '8px', display: 'flex', cursor: 'pointer',
          transition: 'color 0.2s ease',
        }}
      >
        <X style={{ width: '22px', height: '22px' }} strokeWidth={1.5} />
      </button>

      {/* ── Step indicator (top-left) ── */}
      <div style={{ position: 'fixed', top: '28px', left: '32px', zIndex: 10 }}>
        <div style={{
          fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
          fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase',
          color: '#1B6C42', fontWeight: 700, marginBottom: '4px',
        }}>
          Step {activeStep + 1} / {STEPS.length}
        </div>
        <div style={{
          fontFamily: "var(--font-playfair), 'Playfair Display', serif",
          fontSize: '18px', fontWeight: 600, color: '#0f172a',
          marginBottom: '10px', letterSpacing: '-0.01em',
        }}>
          {STEPS[activeStep].label}
        </div>
        {(() => {
          const totalSteps = STEPS.length;
          const GAP = 3;
          const totalWidth = 200;
          const segW = (totalWidth - (totalSteps - 1) * GAP) / totalSteps;
          const stepsDone = activeStep;
          const filledW = stepsDone > 0
            ? stepsDone * segW + (stepsDone - 1) * GAP
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

      {/* ── Scrollable content wrapper ── */}
      <div style={{
        minHeight: '100%',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        padding: '96px 0 64px',
        boxSizing: 'border-box',
      }}>

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

          {activeStep === 1 && (
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

          {activeStep === 2 && (
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

          {activeStep === 3 && (
            <div>
              <h3 style={headingStyle}>
                What are you studying?
              </h3>
              <p style={subtitleStyle}>
                Search and add your courses this semester.
              </p>
              <div style={{ position: 'relative', zIndex: courseFocused ? 20 : 1 }}>
                <input type="text" value={courseInput}
                  onChange={e => handleCourseInput(e.target.value)}
                  onFocus={() => setCourseFocused(true)}
                  onBlur={() => setTimeout(() => setCourseFocused(false), 150)}
                  placeholder="Search courses..." autoFocus style={{ ...inputStyle }} />
                {courseFocused && courseSuggestions.length > 0 && (
                  <div style={{
                    position: 'absolute', top: 'calc(100% + 6px)', left: 0, right: 0,
                    background: '#ffffff', border: '1px solid rgba(0,0,0,0.1)',
                    borderRadius: '14px', maxHeight: '192px', overflowY: 'auto',
                    zIndex: 100, boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
                  }} role="listbox" aria-label="Course suggestions">
                    {courseSuggestions.map((c, i) => (
                      <button
                        key={c.id}
                        type="button"
                        role="option"
                        aria-selected={false}
                        onMouseDown={() => addCourse(c)}
                        onKeyDown={e => handleOptionKeyDown(e, () => addCourse(c))}
                        style={{
                          width: '100%', textAlign: 'left', padding: '11px 18px',
                          fontSize: '14px', color: '#111827', cursor: 'pointer',
                          borderBottom: i < courseSuggestions.length - 1 ? '1px solid rgba(0,0,0,0.06)' : 'none',
                          fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                          transition: 'background 0.15s', background: 'transparent',
                          borderLeft: 'none', borderRight: 'none', borderTop: 'none',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(27,108,66,0.08)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                      >
                        <span style={{ fontWeight: 500 }}>{c.course_code}</span>
                        {c.course_code !== c.course_name && (
                          <span style={{ color: 'rgba(0,0,0,0.45)', marginLeft: '8px' }}>{c.course_name}</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {formData.courses.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '12px' }}>
                  {formData.courses.map((c, idx) => (
                    <div key={c.id} style={{
                      background: `${activeColor}18`, border: `1px solid ${activeColor}40`,
                      borderRadius: '9999px', padding: '6px 14px', color: '#111827',
                      fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px',
                      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                    }}>
                      {c.course_code}
                      <button onClick={() => setFormData(prev => ({ ...prev, courses: prev.courses.filter((_, i) => i !== idx) }))}
                        style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', display: 'flex', color: 'rgba(0,0,0,0.35)' }}>
                        <XCircle style={{ width: '14px', height: '14px' }} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeStep === 4 && (
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
        <div style={{ display: 'flex', gap: '10px', marginTop: '28px', justifyContent: 'center' }}>
          {activeStep > 0 && (
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
          )}
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
      </div>

      </div>
    </div>
  );
}
