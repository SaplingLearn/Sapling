import { Suspense } from 'react';
import StudyClient from './StudyClient';

export default function StudyPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40, color: '#9ca3af' }}>Loading...</div>}>
      <StudyClient />
    </Suspense>
  );
}
