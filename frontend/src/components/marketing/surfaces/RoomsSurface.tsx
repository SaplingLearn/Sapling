/**
 * Bento tile — Study Rooms (#344 step 2).
 *
 * Recreates `screens/Social`: the display-font room name over the invite-code
 * chip and the member count, then the chat log — a 32px initials avatar and an
 * 11px sender name above each incoming bubble, and the outgoing bubble filled
 * and right-aligned with neither.
 *
 * Avatars stay on the warm `--ink` ramp rather than taking per-user hues. The
 * signed-in app tints them by name, but on this page colour is reserved for
 * state, and four coloured discs beside three mastery dots would read as
 * decoration competing with meaning.
 */
import { SurfaceFrame } from './Surface';

const MEMBERS = ['PN', 'MC', 'JH', 'AL'];

const MESSAGES = [
  { from: 'Priya', initials: 'PN', text: 'anyone else stuck on Q3 of the practice set?', self: false },
  { from: 'Marcus', initials: 'MC', text: 'the eigenvector one? multiply it out — λ falls right out', self: false },
  { from: 'You', initials: 'AL', text: 'oh. ok that actually helps', self: true },
];

export default function RoomsSurface() {
  return (
    <SurfaceFrame testId="landing-surface-rooms" title="Study Rooms" meta="4 members">
      <span className="landing-surface-headrow">
        <span className="landing-surface-roomname">Linear Algebra — Exam 2</span>
        <span className="landing-surface-chip is-code">MA242-7QK</span>
      </span>

      <span className="landing-surface-stack-avatars">
        {MEMBERS.map((m) => (
          <span key={m} aria-hidden className="landing-surface-avatar">
            {m}
          </span>
        ))}
      </span>

      {MESSAGES.map((m) => (
        <span key={m.from + m.text} className={`landing-surface-turn${m.self ? ' is-student' : ' is-tutor'}`}>
          {m.self ? null : (
            <span aria-hidden className="landing-surface-avatar">
              {m.initials}
            </span>
          )}
          <span className="landing-surface-msg">
            {m.self ? null : <span className="landing-surface-sender">{m.from}</span>}
            <span className={`landing-surface-bubble${m.self ? ' is-student' : ' is-tutor'}`}>{m.text}</span>
          </span>
        </span>
      ))}
    </SurfaceFrame>
  );
}
