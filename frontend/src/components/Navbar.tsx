'use client';

import { useState, useTransition, useRef, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { getRecommendations } from '@/lib/api';
import ReportIssueFlow from '@/components/ReportIssueFlow';

const LINKS = [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/learn', label: 'Learn' },
  { href: '/study', label: 'Study' },
  { href: '/library', label: 'Library' },
  { href: '/calendar', label: 'Calendar' },
  { href: '/social', label: 'Social' },
  { href: '/tree', label: 'Tree' },
];

function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [breakpoint]);
  return isMobile;
}

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { userId, userName, avatarUrl, userReady, isAuthenticated, signOut } = useUser();
  const [suggesting, setSuggesting] = useState(false);
  const [, startTransition] = useTransition();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showReportIssue, setShowReportIssue] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const mobileNavRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
      if (mobileNavRef.current && !mobileNavRef.current.contains(e.target as Node)) {
        setMobileNavOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  const publicPaths = ['/', '/signin/callback', '/about', '/terms', '/privacy'];

  useEffect(() => {
    if (userReady && !isAuthenticated && !publicPaths.includes(pathname)) {
      router.push('/');
    }
  }, [userReady, isAuthenticated, pathname, router]);

  if (publicPaths.includes(pathname)) return null;

  const handleSuggest = async () => {
    setSuggesting(true);
    try {
      const res = await getRecommendations(userId);
      const top = res.recommendations[0];
      if (top) {
        const encoded = encodeURIComponent(top.concept_name);
        const base = pathname === '/calendar' ? '/learn' : pathname;
        startTransition(() => {
          router.push(`${base}?suggest=${encoded}`);
        });
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSuggesting(false);
    }
  };

  const handleSignOut = () => {
    setMenuOpen(false);
    setMobileNavOpen(false);
    signOut();
    router.push('/');
  };

  return (
    <>
      <nav
      style={{
        background: 'rgba(255, 255, 255, 0.92)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderBottom: '1px solid rgba(107, 114, 128, 0.12)',
        padding: isMobile ? '0 12px' : '0 24px',
        display: 'flex',
        alignItems: 'center',
        gap: isMobile ? '8px' : '32px',
        height: '48px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      {/* Hamburger — mobile only */}
      {isMobile && (
        <div ref={mobileNavRef} style={{ position: 'relative' }}>
          <button
            onClick={() => setMobileNavOpen(o => !o)}
            aria-label="Navigation menu"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '6px',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
            }}
          >
            <span style={{ width: '18px', height: '2px', background: '#374151', borderRadius: '1px', transition: 'transform 0.2s', transform: mobileNavOpen ? 'rotate(45deg) translateY(6px)' : 'none' }} />
            <span style={{ width: '18px', height: '2px', background: '#374151', borderRadius: '1px', transition: 'opacity 0.2s', opacity: mobileNavOpen ? 0 : 1 }} />
            <span style={{ width: '18px', height: '2px', background: '#374151', borderRadius: '1px', transition: 'transform 0.2s', transform: mobileNavOpen ? 'rotate(-45deg) translateY(-6px)' : 'none' }} />
          </button>

          {mobileNavOpen && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: '8px',
              background: '#ffffff',
              border: '1px solid rgba(107,114,128,0.15)',
              borderRadius: '10px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
              minWidth: '200px',
              zIndex: 100,
              overflow: 'hidden',
              padding: '6px 0',
            }}>
              {LINKS.map(link => {
                const active = pathname === link.href || (link.href !== '/dashboard' && pathname.startsWith(link.href));
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    style={{
                      display: 'block',
                      padding: '10px 16px',
                      fontSize: '14px',
                      color: active ? '#1a5c2a' : '#374151',
                      fontWeight: active ? 600 : 400,
                      textDecoration: 'none',
                      background: active ? 'rgba(26, 92, 42, 0.06)' : 'transparent',
                      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                    }}
                  >
                    {link.label}
                  </Link>
                );
              })}
              <div style={{ borderTop: '1px solid rgba(107,114,128,0.1)', margin: '4px 0' }} />
              <button
                onClick={handleSuggest}
                disabled={suggesting}
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '10px 16px',
                  background: 'none',
                  border: 'none',
                  textAlign: 'left',
                  fontSize: '13px',
                  color: '#1a5c2a',
                  fontWeight: 500,
                  cursor: suggesting ? 'default' : 'pointer',
                  opacity: suggesting ? 0.5 : 1,
                  fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                }}
              >
                ✨ What should I study next?
              </button>
            </div>
          )}
        </div>
      )}

      <Link href="/dashboard" style={{ display: 'flex', alignItems: 'center', gap: '2px', textDecoration: 'none' }}>
        <img src="/sapling-icon.svg" alt="Sapling" style={{ width: '32px', height: '32px', marginTop: '-7px', marginBottom: '-3px', marginLeft: '-2px', marginRight: '-4px', alignSelf: 'center', flexShrink: 0 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', alignItems: 'center', textAlign: 'center' }}>
          <span style={{
            fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif",
            fontWeight: 700,
            fontSize: isMobile ? '17px' : '20px',
            color: '#1a5c2a',
            letterSpacing: '-0.02em',
            textShadow: '0 0 12px rgba(26, 92, 42, 0.2)',
            lineHeight: 1.1,
          }}>
            Sapling
          </span>
          <span style={{ fontSize: '9px', fontWeight: 600, color: '#1a5c2a', letterSpacing: '0.08em', textTransform: 'uppercase', opacity: 0.7, lineHeight: 1 }}>
            Closed Alpha
          </span>
        </div>
      </Link>

      {/* Desktop nav links */}
      {!isMobile && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
          {LINKS.map(link => {
            const active = pathname === link.href || (link.href !== '/dashboard' && pathname.startsWith(link.href));
            return (
              <Link
                key={link.href}
                href={link.href}
                className="nav-link"
                style={{
                  padding: '4px 12px',
                  fontSize: '13px',
                  color: active ? '#1a5c2a' : '#9ca3af',
                  fontWeight: active ? 600 : 400,
                  textDecoration: 'none',
                  borderRadius: '5px',
                  borderBottom: 'none',
                  background: active ? 'rgba(26, 92, 42, 0.10)' : 'transparent',
                  fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                  letterSpacing: '0.2px',
                  transition: 'color 0.15s, background 0.15s',
                }}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
      )}

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          onClick={() => setShowReportIssue(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '5px 11px',
            background: 'rgba(220,38,38,0.07)',
            color: '#dc2626',
            border: '1px solid rgba(220,38,38,0.2)',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 500,
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          Report Issue
        </button>

        {/* Desktop-only suggest (mobile: hamburger menu) */}
        {!isMobile && (
          <button
            onClick={handleSuggest}
            disabled={suggesting}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '5px 13px',
              background: 'rgba(26,92,42,0.08)',
              color: '#1a5c2a',
              border: '1px solid rgba(26,92,42,0.22)',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 500,
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
              cursor: suggesting ? 'default' : 'pointer',
              opacity: suggesting ? 0.5 : 1,
              transition: 'opacity 0.15s',
              whiteSpace: 'nowrap',
            }}
          >
            What should I study next?
          </button>
        )}

        {/* User avatar/name dropdown */}
        <div ref={menuRef} style={{ position: 'relative' }}>
          <button
            onClick={() => setMenuOpen(o => !o)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: isMobile ? '4px' : '8px',
              padding: '4px 10px',
              background: 'transparent',
              border: '1px solid rgba(107,114,128,0.18)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '13px',
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
              color: '#374151',
            }}
          >
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt=""
                style={{ width: '24px', height: '24px', borderRadius: '50%' }}
                referrerPolicy="no-referrer"
              />
            ) : (
              <div style={{
                width: '24px',
                height: '24px',
                borderRadius: '50%',
                background: 'rgba(26,92,42,0.12)',
                color: '#1a5c2a',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '12px',
                fontWeight: 600,
              }}>
                {userName?.charAt(0)?.toUpperCase() || '?'}
              </div>
            )}
            {!isMobile && <span style={{ fontWeight: 500 }}>{userName || 'User'}</span>}
          </button>

          {menuOpen && (
            <div style={{
              position: 'absolute',
              top: '100%',
              right: 0,
              marginTop: '4px',
              background: '#ffffff',
              border: '1px solid rgba(107,114,128,0.15)',
              borderRadius: '8px',
              boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
              minWidth: '160px',
              zIndex: 100,
              overflow: 'hidden',
            }}>
              <div style={{
                padding: '10px 14px',
                borderBottom: '1px solid rgba(107,114,128,0.1)',
                fontSize: '12px',
                color: '#9ca3af',
              }}>
                Signed in as <strong style={{ color: '#374151' }}>{userName}</strong>
              </div>
              <button
                onClick={handleSignOut}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  background: 'none',
                  border: 'none',
                  textAlign: 'left',
                  fontSize: '13px',
                  color: '#dc2626',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
                onMouseEnter={e => e.currentTarget.style.background = '#fef2f2'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
      <ReportIssueFlow visible={showReportIssue} onDismiss={() => setShowReportIssue(false)} />
    </>
  );
}