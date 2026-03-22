'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import SessionFeedbackFlow from '@/components/SessionFeedbackFlow';

const FLAG_KEY = 'sapling_learn_had_session';
const LAST_KEY = 'sapling_session_feedback_nav_last_shown';
const COOLDOWN_MS = 3 * 86_400_000;

export default function SessionFeedbackGlobal() {
  const pathname = usePathname();
  const prevPathname = useRef(pathname);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const prev = prevPathname.current;
    prevPathname.current = pathname;

    if (prev === '/learn' && pathname !== '/learn') {
      const hadSession = localStorage.getItem(FLAG_KEY) === 'true';
      const lastShown = parseInt(localStorage.getItem(LAST_KEY) ?? '0', 10);
      const cooldownPassed = Date.now() - lastShown > COOLDOWN_MS;

      if (hadSession && cooldownPassed) {
        localStorage.removeItem(FLAG_KEY);
        localStorage.setItem(LAST_KEY, String(Date.now()));
        setVisible(true);
      }
    }
  }, [pathname]);

  return (
    <SessionFeedbackFlow
      visible={visible}
      onDismiss={() => setVisible(false)}
    />
  );
}
