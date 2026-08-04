import type { Metadata } from 'next';
import { CompanionBody, CompanionShell } from '@/components/companion/CompanionShell';
import { Award, Bullets, Eyebrow, PageTitle, Prose } from '@/components/companion/primitives';
import { TEAM_AWARDS, TEAM_MEMBERS, TEAM_WAYS } from '@/lib/landing/companionContent';

export const metadata: Metadata = {
  title: 'Meet the team',
  description:
    'Four Boston University students who got tired of study tools that did not know what they were studying.',
};

export default function TeamPage() {
  return (
    <CompanionShell current="/team">
      <CompanionBody>
        <PageTitle>Meet the team</PageTitle>
        <Prose delay={80}>
          Four Boston University students who got tired of study tools that did not know what they
          were studying. We build Sapling between problem sets, and we use it for our own classes
          first.
        </Prose>

        <div style={{ marginTop: 48, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 32 }}>
          {TEAM_MEMBERS.map((m) => (
            <div key={m.name} style={{ animation: 'fadeUp 700ms ease both', animationDelay: m.delay }}>
              <p style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#1a1814' }}>{m.name}</p>
              <p style={{ margin: '2px 0 0', fontSize: 12, fontWeight: 500, color: '#2D8F5C' }}>{m.role}</p>
              <p style={{ margin: '8px 0 0', fontFamily: "'Spectral',Georgia,serif", fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>
                {m.body}
              </p>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 56 }}>
          <Eyebrow delay={320}>How we work</Eyebrow>
          <Bullets items={TEAM_WAYS} />
        </div>

        <div style={{ marginTop: 56 }}>
          <Eyebrow delay={400}>Recognition</Eyebrow>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
            {TEAM_AWARDS.map((a, i) => (
              <Award key={a.title} title={a.title} org={a.org} body={a.body} delay={`${440 + i * 80}ms`} />
            ))}
          </div>
        </div>
      </CompanionBody>
    </CompanionShell>
  );
}
