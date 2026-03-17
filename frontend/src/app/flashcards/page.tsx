'use client';

import { useState, useEffect } from 'react';
import { useUser } from '@/context/UserContext';
import { generateFlashcards, getFlashcards, rateFlashcard, deleteFlashcard, getCourses } from '@/lib/api';
import Link from 'next/link';
import AIDisclaimerChip from '@/components/AIDisclaimerChip';

interface Flashcard {
  id: string;
  topic: string;
  front: string;
  back: string;
  times_reviewed: number;
  last_rating: number | null;
}

export default function FlashcardsPage() {
  const { userId: USER_ID, userReady } = useUser();

  const [cards, setCards] = useState<Flashcard[]>([]);
  const [courses, setCourses] = useState<string[]>([]);
  const [topic, setTopic] = useState('');
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterTopic, setFilterTopic] = useState('');

  // Study mode
  const [studyMode, setStudyMode] = useState(false);
  const [studyIndex, setStudyIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [studyCards, setStudyCards] = useState<Flashcard[]>([]);

  useEffect(() => {
    if (!userReady || !USER_ID) return;
    setLoading(true);
    Promise.all([
      getFlashcards(USER_ID),
      getCourses(USER_ID),
    ]).then(([cardData, courseData]) => {
      setCards(cardData.flashcards ?? []);
      setCourses(courseData.courses.map((c: any) => c.course_name));
    }).catch(err => {
      console.error('Failed to load flashcards:', err);
      setCards([]);
    }).finally(() => setLoading(false));
  }, [USER_ID, userReady]);

  const [lastContextUsed, setLastContextUsed] = useState<{ documents_found: number; weak_concepts_found: number } | null>(null);

  const handleGenerate = async (selectedTopic: string) => {
    if (!selectedTopic.trim()) return;
    setTopic(selectedTopic);
    setGenerating(true);
    setError(null);
    setLastContextUsed(null);
    try {
      const res = await generateFlashcards(USER_ID, selectedTopic.trim(), 10);
      setCards(prev => [...res.flashcards, ...prev]);
      if (res.context_used) setLastContextUsed(res.context_used);
    } catch (e: any) {
      setError(e?.message || 'Failed to generate flashcards.');
    } finally {
      setGenerating(false);
    }
  };

  const handleRate = async (cardId: string, rating: number) => {
    try {
      await rateFlashcard(USER_ID, cardId, rating);
      setCards(prev => prev.map(c =>
        c.id === cardId ? { ...c, last_rating: rating, times_reviewed: c.times_reviewed + 1 } : c
      ));
      if (studyMode) {
        setTimeout(() => {
          setFlipped(false);
          if (studyIndex < studyCards.length - 1) {
            setStudyIndex(i => i + 1);
          } else {
            setStudyMode(false);
          }
        }, 300);
      }
    } catch (e) { console.error(e); }
  };

  const handleDelete = async (cardId: string) => {
    try {
      await deleteFlashcard(USER_ID, cardId);
      setCards(prev => prev.filter(c => c.id !== cardId));
    } catch (e) { console.error(e); }
  };

  const startStudy = (topicFilter?: string) => {
    const filtered = topicFilter ? cards.filter(c => c.topic === topicFilter) : cards;
    if (filtered.length === 0) return;
    setStudyCards(filtered);
    setStudyIndex(0);
    setFlipped(false);
    setStudyMode(true);
  };

  const ratingMeta = (r: number | null) => {
    if (r === 1) return { label: 'Forgot', color: '#dc2626' };
    if (r === 2) return { label: 'Hard', color: '#d97706' };
    if (r === 3) return { label: 'Easy', color: '#16a34a' };
    return null;
  };

  const topics = [...new Set(cards.map(c => c.topic))].sort();
  const filteredCards = filterTopic ? cards.filter(c => c.topic === filterTopic) : cards;
  const currentCard = studyCards[studyIndex];

  // ── Study Mode ───────────────────────────────────────────────────────────────
  if (studyMode && currentCard) {
    const progress = (studyIndex / studyCards.length) * 100;
    return (
      <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', background: '#f0f5f0' }}>
        <div style={{
          background: '#f0f5f0',
          borderBottom: '1px solid rgba(107,114,128,0.12)',
          padding: '0 20px',
          height: '52px',
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          flexShrink: 0,
        }}>
          <button
            onClick={() => setStudyMode(false)}
            style={{ background: 'none', border: 'none', color: '#6b7280', fontSize: '18px', cursor: 'pointer', lineHeight: 1 }}
          >←</button>
          <span style={{ fontSize: '14px', fontWeight: 500, color: '#374151' }}>{currentCard.topic}</span>
          <span style={{ fontSize: '13px', color: '#9ca3af' }}>{studyIndex + 1} / {studyCards.length}</span>
          <div style={{ flex: 1, height: '4px', background: 'rgba(107,114,128,0.15)', borderRadius: '2px', overflow: 'hidden' }}>
            <div style={{ width: `${progress}%`, height: '100%', background: '#1a5c2a', borderRadius: '2px', transition: 'width 0.3s' }} />
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '32px 24px', gap: '24px' }}>
          <style>{`
            .flip-card { perspective: 1200px; }
            .flip-card-inner {
              position: relative;
              width: 100%;
              height: 100%;
              transition: transform 0.55s cubic-bezier(0.4, 0.2, 0.2, 1);
              transform-style: preserve-3d;
            }
            .flip-card-inner.flipped { transform: rotateY(180deg); }
            .flip-card-front, .flip-card-back {
              position: absolute;
              inset: 0;
              backface-visibility: hidden;
              -webkit-backface-visibility: hidden;
              display: flex;
              flex-direction: column;
              align-items: center;
              justify-content: center;
              padding: 40px;
              border-radius: 16px;
              border: 1px solid rgba(107,114,128,0.15);
              box-shadow: 0 8px 32px rgba(0,0,0,0.08);
              gap: 16px;
              cursor: pointer;
              user-select: none;
            }
            .flip-card-front { background: #ffffff; }
            .flip-card-back {
              background: #f0fdf4;
              transform: rotateY(180deg);
              border-color: rgba(26,92,42,0.2);
            }
          `}</style>

          <div
            className="flip-card"
            onClick={() => setFlipped(f => !f)}
            style={{ width: '100%', maxWidth: '600px', minHeight: '280px', position: 'relative' }}
          >
            <div className={`flip-card-inner${flipped ? ' flipped' : ''}`} style={{ minHeight: '280px' }}>
              {/* Front */}
              <div className="flip-card-front">
                <span style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Question
                </span>
                <p style={{ fontSize: '20px', fontWeight: 500, color: '#111827', textAlign: 'center', lineHeight: 1.6, margin: 0 }}>
                  {currentCard.front}
                </p>
                <span style={{ fontSize: '12px', color: '#9ca3af', marginTop: '8px' }}>tap to reveal</span>
              </div>
              {/* Back */}
              <div className="flip-card-back">
                <span style={{ fontSize: '11px', fontWeight: 500, color: '#1a5c2a', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Answer
                </span>
                <p style={{ fontSize: '20px', fontWeight: 500, color: '#111827', textAlign: 'center', lineHeight: 1.6, margin: 0 }}>
                  {currentCard.back}
                </p>
              </div>
            </div>
          </div>

          {flipped && (
            <div style={{ display: 'flex', gap: '12px' }}>
              {[
                { rating: 1, label: 'Forgot', bg: '#fef2f2', color: '#dc2626', border: '#fca5a5' },
                { rating: 2, label: 'Hard', bg: '#fffbeb', color: '#d97706', border: '#fcd34d' },
                { rating: 3, label: 'Easy', bg: '#f0fdf4', color: '#16a34a', border: '#86efac' },
              ].map(({ rating, label, bg, color, border }) => (
                <button key={rating} onClick={() => handleRate(currentCard.id, rating)} style={{
                  padding: '10px 28px', background: bg, color, border: `1px solid ${border}`,
                  borderRadius: '8px', fontSize: '14px', fontWeight: 600, cursor: 'pointer',
                  fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                }}>
                  {label}
                </button>
              ))}
            </div>
          )}

          <button onClick={() => setStudyMode(false)} style={{ fontSize: '13px', color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer' }}>
            Exit study mode
          </button>
        </div>
      </div>
    );
  }

  // ── Main View ────────────────────────────────────────────────────────────────
  return (
    <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column' }}>
      {/* Top bar */}
      <div className="panel-in panel-in-1" style={{
        background: '#f0f5f0', borderBottom: '1px solid rgba(107,114,128,0.12)',
        padding: '0 20px', height: '52px', display: 'flex', alignItems: 'center',
        gap: '16px', flexShrink: 0, zIndex: 20,
      }}>
        <Link href="/" style={{ color: '#6b7280', textDecoration: 'none', fontSize: '18px', lineHeight: 1 }}>←</Link>
        <span style={{ fontSize: '15px', fontWeight: 600, color: '#111827' }}>Flashcards</span>
        <div style={{ marginLeft: 'auto' }}><AIDisclaimerChip /></div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'flex' }}>

        {/* Left panel */}
        <div style={{
          width: '320px', flexShrink: 0, borderRight: '1px solid rgba(107,114,128,0.12)',
          padding: '24px 20px', display: 'flex', flexDirection: 'column', gap: '20px', background: '#f9fafb',
        }}>
          <div>
            <p style={{ fontSize: '13px', fontWeight: 600, color: '#374151', margin: '0 0 12px' }}>Generate flashcards</p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontSize: '12px', color: '#6b7280' }}>Select a course to generate cards</label>
              {courses.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {courses.map(c => (
                    <button
                      key={c}
                      onClick={() => handleGenerate(c)}
                      disabled={generating}
                      style={{
                        padding: '10px 14px',
                        background: topic === c && generating ? 'rgba(26,92,42,0.08)' : '#ffffff',
                        border: `1px solid ${topic === c ? 'rgba(26,92,42,0.4)' : 'rgba(107,114,128,0.18)'}`,
                        borderRadius: '8px',
                        fontSize: '13px',
                        color: topic === c ? '#1a5c2a' : '#374151',
                        fontWeight: topic === c ? 600 : 400,
                        cursor: generating ? 'default' : 'pointer',
                        textAlign: 'left',
                        fontFamily: 'inherit',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        opacity: generating && topic !== c ? 0.5 : 1,
                        transition: 'all 0.15s',
                      }}
                    >
                      <span>{c}</span>
                      {topic === c && generating
                        ? <span style={{ fontSize: '11px', color: '#1a5c2a' }}>Generating…</span>
                        : <span style={{ fontSize: '11px', color: '#9ca3af' }}>✦ Generate</span>
                      }
                    </button>
                  ))}
                </div>
              ) : (
                <p style={{ fontSize: '12px', color: '#9ca3af', margin: 0 }}>
                  No courses found. Add courses in the Dashboard first.
                </p>
              )}
            </div>

            {error && <p style={{ fontSize: '12px', color: '#dc2626', marginTop: '8px' }}>{error}</p>}

            {lastContextUsed && (
              <div style={{
                marginTop: '10px', padding: '8px 12px',
                background: 'rgba(26,92,42,0.06)', border: '1px solid rgba(26,92,42,0.18)',
                borderRadius: '6px', fontSize: '12px', color: '#1a5c2a', lineHeight: 1.5,
              }}>
                ✦ Generated using{' '}
                {lastContextUsed.documents_found > 0
                  ? `${lastContextUsed.documents_found} library doc${lastContextUsed.documents_found > 1 ? 's' : ''}`
                  : 'no library docs'}
                {lastContextUsed.weak_concepts_found > 0
                  ? ` · focused on ${lastContextUsed.weak_concepts_found} weak concept${lastContextUsed.weak_concepts_found > 1 ? 's' : ''}`
                  : ''}
              </div>
            )}
          </div>

          {/* Study by topic */}
          {topics.length > 0 && (
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: '#374151', margin: '0 0 10px' }}>Study by topic</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <button onClick={() => startStudy()} style={{
                  padding: '8px 12px', background: '#ffffff', border: '1px solid rgba(26,92,42,0.25)',
                  borderRadius: '6px', fontSize: '13px', color: '#1a5c2a', fontWeight: 500,
                  cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit',
                }}>
                  All cards ({cards.length})
                </button>
                {topics.map(t => (
                  <button key={t} onClick={() => startStudy(t)} style={{
                    padding: '8px 12px', background: '#ffffff', border: '1px solid rgba(107,114,128,0.18)',
                    borderRadius: '6px', fontSize: '13px', color: '#374151', cursor: 'pointer',
                    textAlign: 'left', fontFamily: 'inherit', display: 'flex',
                    justifyContent: 'space-between', alignItems: 'center',
                  }}>
                    <span>{t}</span>
                    <span style={{ fontSize: '11px', color: '#9ca3af' }}>{cards.filter(c => c.topic === t).length}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right panel — card grid */}
        <div style={{ flex: 1, padding: '24px', overflow: 'auto' }}>
          {topics.length > 1 && (
            <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
              {['', ...topics].map(t => (
                <button key={t || '__all'} onClick={() => setFilterTopic(t)} style={{
                  padding: '4px 12px',
                  background: filterTopic === t ? '#1a5c2a' : '#ffffff',
                  color: filterTopic === t ? '#ffffff' : '#374151',
                  border: `1px solid ${filterTopic === t ? '#1a5c2a' : 'rgba(107,114,128,0.22)'}`,
                  borderRadius: '20px', fontSize: '12px',
                  fontWeight: filterTopic === t ? 600 : 400,
                  cursor: 'pointer', fontFamily: 'inherit',
                }}>
                  {t || 'All'}
                </button>
              ))}
            </div>
          )}

          {loading && <p style={{ color: '#9ca3af', fontSize: '13px' }}>Loading…</p>}

          {!loading && filteredCards.length === 0 && (
            <div style={{ textAlign: 'center', marginTop: '80px', color: '#9ca3af' }}>
              <p style={{ fontSize: '32px', margin: '0 0 12px' }}>🃏</p>
              <p style={{ fontSize: '15px', fontWeight: 500, color: '#6b7280' }}>No flashcards yet</p>
              <p style={{ fontSize: '13px' }}>Generate some using the panel on the left.</p>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px' }}>
            {filteredCards.map(card => {
              const rating = ratingMeta(card.last_rating);
              return (
                <div key={card.id} style={{
                  background: '#ffffff', border: '1px solid rgba(107,114,128,0.15)',
                  borderRadius: '12px', padding: '18px', display: 'flex',
                  flexDirection: 'column', gap: '10px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{
                      fontSize: '10px', fontWeight: 600, color: '#1a5c2a',
                      background: 'rgba(26,92,42,0.08)', padding: '2px 8px',
                      borderRadius: '10px', textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>{card.topic}</span>
                    {rating && <span style={{ fontSize: '11px', color: rating.color, fontWeight: 500 }}>{rating.label}</span>}
                  </div>

                  <div>
                    <p style={{ fontSize: '10px', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 4px' }}>Q</p>
                    <p style={{ fontSize: '14px', color: '#111827', margin: 0, lineHeight: 1.5, fontWeight: 500 }}>{card.front}</p>
                  </div>

                  <div style={{ height: '1px', background: 'rgba(107,114,128,0.1)' }} />

                  <div>
                    <p style={{ fontSize: '10px', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 4px' }}>A</p>
                    <p style={{ fontSize: '13px', color: '#374151', margin: 0, lineHeight: 1.5 }}>{card.back}</p>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '4px' }}>
                    <span style={{ fontSize: '11px', color: '#9ca3af' }}>
                      {card.times_reviewed > 0 ? `Reviewed ${card.times_reviewed}×` : 'Not reviewed'}
                    </span>
                    <button
                      onClick={() => handleDelete(card.id)}
                      style={{ background: 'none', border: 'none', color: '#d1d5db', cursor: 'pointer', fontSize: '13px', padding: '2px 4px', borderRadius: '4px', lineHeight: 1 }}
                      onMouseEnter={e => e.currentTarget.style.color = '#dc2626'}
                      onMouseLeave={e => e.currentTarget.style.color = '#d1d5db'}
                    >✕</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}