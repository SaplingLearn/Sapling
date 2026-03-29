'use client';

import { useState, useRef, useCallback, forwardRef, useImperativeHandle, useEffect } from 'react';
import { X, Search, ChevronDown, XCircle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

export interface OnboardingModalHandle {
  open: (mode: 'signin' | 'signup') => void;
}

const OnboardingModal = forwardRef<OnboardingModalHandle>(function OnboardingModal(_, ref) {
  const [modalOpen, setModalOpen] = useState(false);
  const [modalActive, setModalActive] = useState(false);
  const [modalMode, setModalMode] = useState<'signin' | 'signup'>('signup');
  const [modalStep, setModalStep] = useState(1);
  const [classChips, setClassChips] = useState<string[]>([]);
  const [classInput, setClassInput] = useState('');
  const closeTimeout = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    return () => {
      if (closeTimeout.current) clearTimeout(closeTimeout.current);
    };
  }, []);

  const openModal = useCallback((mode: 'signin' | 'signup') => {
    if (closeTimeout.current) {
      clearTimeout(closeTimeout.current);
      closeTimeout.current = null;
    }
    setModalMode(mode);
    setModalStep(1);
    setModalOpen(true);
    requestAnimationFrame(() => setModalActive(true));
  }, []);

  const closeModal = useCallback(() => {
    setModalActive(false);
    if (closeTimeout.current) clearTimeout(closeTimeout.current);
    closeTimeout.current = setTimeout(() => {
      setModalOpen(false);
      closeTimeout.current = null;
    }, 420);
  }, []);

  useImperativeHandle(ref, () => ({ open: openModal }), [openModal]);

  function handleGoogleContinue() { window.location.href = `${API_URL}/api/auth/google`; }
  function handleEmailContinue() { if (modalMode === 'signin') closeModal(); else setModalStep(2); }
  function addClass() { const v = classInput.trim(); if (v) { setClassChips(prev => [...prev, v]); setClassInput(''); } }
  function addSuggested(name: string) { setClassChips(prev => [...prev, name]); }

  if (!modalOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className={`absolute inset-0 bg-[var(--brand-text1)]/25 transition-opacity duration-400 ${modalActive ? 'opacity-100' : 'opacity-0'}`}
        onClick={closeModal}
      />
      <div className={`relative w-full max-w-md mx-4 sm:mx-auto transition-all duration-400 ${modalActive ? 'opacity-100 translate-y-0 scale-100' : 'opacity-0 translate-y-4 scale-[0.97]'}`}>
        <div className="rounded-3xl p-10 relative overflow-hidden shadow-2xl" style={{ background: 'var(--bg-panel, #f8fbf8)' }}>
          <button onClick={closeModal} className="absolute top-5 right-5 text-[#e11d48] hover:text-[#be123c] transition-colors z-20">
            <X className="w-6 h-6" strokeWidth={2.4} />
          </button>

          {modalMode === 'signup' && (
            <div className="flex justify-center gap-2 mb-8 relative z-10">
              <div className={`w-12 h-1.5 rounded-full transition-colors duration-400 ${modalStep >= 1 ? 'bg-[#1B6C42]' : 'bg-[#d7dfd0]'}`} />
              <div className={`w-12 h-1.5 rounded-full transition-colors duration-400 ${modalStep >= 2 ? 'bg-[#1B6C42]' : 'bg-[#d7dfd0]'}`} />
              <div className={`w-12 h-1.5 rounded-full transition-colors duration-400 ${modalStep >= 3 ? 'bg-[#1B6C42]' : 'bg-[#d7dfd0]'}`} />
            </div>
          )}

          <div className="relative w-full h-[320px]">
            {/* Step 1: Auth */}
            <div className={`absolute inset-0 w-full transition-all duration-300 ease-in-out flex flex-col justify-center ${modalStep === 1 ? 'translate-x-0 opacity-100' : '-translate-x-[30px] opacity-0 pointer-events-none'}`}>
              <h3 className="font-playfair text-2xl font-semibold text-[var(--brand-text1)] text-center tracking-tight">
                {modalMode === 'signin' ? 'Welcome back' : 'Welcome to Sapling'}
              </h3>
              <p className="text-[var(--brand-text2)] text-center text-sm mt-2 font-light">
                {modalMode === 'signin' ? 'Sign in to continue' : 'Start your learning journey'}
              </p>
              <button onClick={handleGoogleContinue} className="mt-8 bg-white border border-[#d9e2d7] text-[var(--brand-text1)] w-full py-3.5 rounded-xl flex items-center justify-center gap-3 shadow-sm transition-all duration-300 text-sm font-medium hover:border-[#1B6C42] hover:shadow-md focus:outline-none focus:ring-2 focus:ring-[#1B6C42]/20">
                <svg className="w-4 h-4" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" /><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" /><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" /><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" /></svg>
                Continue with Google
              </button>
              <div className="flex items-center gap-4 my-6">
                <div className="flex-1 h-px landing-divider opacity-80" />
                <span className="text-[var(--brand-text2)] text-[11px] font-medium uppercase">or</span>
                <div className="flex-1 h-px landing-divider opacity-80" />
              </div>
              <input type="email" placeholder="your@email.com" className="rounded-xl px-4 py-3 text-[var(--brand-text1)] placeholder:text-[var(--brand-text2)] placeholder:opacity-60 w-full transition-all text-sm mb-3 bg-white border border-[#d7dfd0] shadow-inner focus:border-[#1B6C42] focus:ring-2 focus:ring-[#1B6C42]/20 focus:outline-none" />
              <button onClick={handleEmailContinue} className="w-full bg-[#1B6C42] text-white py-3.5 rounded-xl font-medium text-sm hover:bg-[#155A35] shadow-sm transition-all duration-300">
                Continue
              </button>
              <p className="text-center text-[var(--brand-text2)] text-xs mt-6">
                {modalMode === 'signin' ? "Don't have an account? " : 'Already have an account? '}
                <button onClick={() => setModalMode(modalMode === 'signin' ? 'signup' : 'signin')} className="text-[#1B6C42] font-medium hover:underline cursor-pointer">
                  {modalMode === 'signin' ? 'Get started' : 'Sign in'}
                </button>
              </p>
            </div>

            {/* Step 2: School Info */}
            <div className={`absolute inset-0 w-full transition-all duration-300 ease-in-out flex flex-col justify-center ${modalStep === 2 ? 'translate-x-0 opacity-100' : 'translate-x-[30px] opacity-0 pointer-events-none'}`}>
              <h3 className="font-playfair text-2xl font-semibold text-[var(--brand-text1)] text-center tracking-tight">About You</h3>
              <p className="text-[var(--brand-text2)] text-center text-sm mt-2 mb-8 font-light">Help us personalize your experience</p>
              <div className="relative mb-4">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--brand-text2)] opacity-70 w-4 h-4" />
                <input type="text" placeholder="Search your university..." className="glass-input rounded-xl pl-10 pr-4 py-3 text-[var(--brand-text1)] placeholder:text-[var(--brand-text2)] placeholder:opacity-60 w-full transition-all text-sm" />
              </div>
              <div className="relative mb-6">
                <select className="glass-input appearance-none rounded-xl px-4 py-3 text-[var(--brand-text1)] w-full transition-all text-sm cursor-pointer invalid:text-[var(--brand-text2)]" required defaultValue="">
                  <option value="" disabled hidden>Select class year</option>
                  <option value="freshman">Freshman</option>
                  <option value="sophomore">Sophomore</option>
                  <option value="junior">Junior</option>
                  <option value="senior">Senior</option>
                  <option value="graduate">Graduate</option>
                  <option value="other">Other</option>
                </select>
                <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 text-[var(--brand-text2)] opacity-70 w-4 h-4 pointer-events-none" />
              </div>
              <button onClick={() => setModalStep(3)} className="w-full bg-[#1B6C42] text-white py-3.5 rounded-xl font-medium text-sm hover:bg-[#155A35] shadow-sm transition-all duration-300">
                Continue
              </button>
            </div>

            {/* Step 3: Classes */}
            <div className={`absolute inset-0 w-full transition-all duration-300 ease-in-out flex flex-col justify-center ${modalStep === 3 ? 'translate-x-0 opacity-100' : 'translate-x-[30px] opacity-0 pointer-events-none'}`}>
              <h3 className="font-playfair text-2xl font-semibold text-[var(--brand-text1)] text-center tracking-tight">Your Classes</h3>
              <p className="text-[var(--brand-text2)] text-center text-sm mt-2 mb-8 font-light">What are you studying this semester?</p>
              <div className="flex gap-2 mb-4">
                <input
                  type="text"
                  value={classInput}
                  onChange={e => setClassInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addClass(); } }}
                  placeholder="Add a class..."
                  className="glass-input flex-1 rounded-xl px-4 py-3 text-[var(--brand-text1)] placeholder:text-[var(--brand-text2)] placeholder:opacity-60 transition-all text-sm"
                />
                <button onClick={addClass} className="bg-[#1B6C42]/10 hover:bg-[#1B6C42]/20 text-[#1B6C42] px-5 rounded-xl text-sm font-medium transition-all">Add</button>
              </div>
              <div className="flex flex-wrap gap-2 mb-4 min-h-[42px]">
                {classChips.map((chip, idx) => (
                  <div key={`${chip}-${idx}`} className="liquid-glass-subtle rounded-full px-4 py-2 text-[var(--brand-text1)] text-sm flex items-center gap-2">
                    {chip}
                    <button onClick={() => setClassChips(prev => prev.filter((_, i) => i !== idx))} className="text-[var(--brand-text2)] hover:text-[var(--brand-text1)] ml-1 transition-colors">
                      <XCircle className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
              <div className="mb-8 flex items-center flex-wrap gap-2">
                <span className="text-[var(--brand-text2)] text-xs mr-2 font-medium">Popular:</span>
                {['CS 101', 'Calculus I', 'Physics I'].map(s => (
                  <span key={s} onClick={() => addSuggested(s)} className="liquid-glass-subtle text-[var(--brand-text2)] hover:text-[var(--brand-text1)] rounded-full px-3 py-1.5 text-xs cursor-pointer transition-all">{s}</span>
                ))}
              </div>
              <button onClick={closeModal} className="w-full bg-[#1B6C42] text-white py-3.5 rounded-xl font-medium text-sm hover:bg-[#155A35] shadow-sm transition-all duration-300">
                Launch Sapling 🌱
              </button>
              <button onClick={closeModal} className="w-full text-center text-[var(--brand-text2)] hover:text-[var(--brand-text1)] text-xs mt-3 cursor-pointer transition-colors">Skip for now</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

export default OnboardingModal;
