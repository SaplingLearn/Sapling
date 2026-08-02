/**
 * Bento tile — the Tutor (#344 step 2).
 *
 * Recreates `chat/ChatPanel`: the assistant turn is a 32px accent-soft avatar
 * with a sparkle next to a Spectral-set bubble on paper with a hairline; the
 * student turn is a filled bubble on the right in DM Sans, no avatar. Neither
 * carries a role label — the alignment and the avatar do that work, exactly as
 * the shipped panel does. Under the log sit the three quick actions the panel
 * offers above its composer: Hint, I'm confused, Skip.
 *
 * The fill is `--brand-forest`, not the panel's `--accent`: `--accent`
 * (#2D8F5C) under white is 4.04:1, which is under the 4.5:1 AA bar at the
 * ~13px this tile sets its bubbles at. Forest is 6.4:1.
 *
 * The exchange itself is a real one — a student stuck on why an eigenvalue can
 * be negative, and a Socratic reply that hands back a matrix to try rather than
 * the answer. That is the product's actual tutoring posture; a generic
 * "How can I help you today?" would have been the wrong picture.
 */
import { SurfaceFrame } from './Surface';

/** The panel's assistant avatar: a four-point sparkle in the accent tint. */
function TutorMark() {
  return (
    <span aria-hidden className="landing-surface-avatar is-tutor">
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden>
        <path
          d="M8 0.9c.55 3.35 1.8 4.6 5.15 5.15C9.8 6.6 8.55 7.85 8 11.2 7.45 7.85 6.2 6.6 2.85 6.05 6.2 5.5 7.45 4.25 8 .9z"
          fill="currentColor"
        />
        <path
          d="M12.6 10.1c.28 1.5.82 2.05 2.3 2.32-1.48.27-2.02.82-2.3 2.32-.28-1.5-.82-2.05-2.3-2.32 1.48-.27 2.02-.82 2.3-2.32z"
          fill="currentColor"
          opacity="0.7"
        />
      </svg>
    </span>
  );
}

const ACTIONS = ['Hint', "I'm confused", 'Skip'];

export default function TutorSurface() {
  return (
    <SurfaceFrame testId="landing-surface-tutor" title="Tutor" meta="Socratic · Eigenvalues">
      <span className="landing-surface-turn is-student">
        <span className="landing-surface-bubble is-student">
          I don&apos;t get why an eigenvalue is allowed to be negative.
        </span>
      </span>

      <span className="landing-surface-turn is-tutor">
        <TutorMark />
        <span className="landing-surface-bubble is-tutor">
          A negative λ just means A flips v end-for-end while it scales it. Try A = [[−2, 0], [0, 1]]
          on v = (1, 0) — what comes back out, and which way is it pointing?
        </span>
      </span>

      <span className="landing-surface-turn is-student">
        <span className="landing-surface-bubble is-student">
          it points backwards. so λ = −2 flips it and doubles it?
        </span>
      </span>

      <span className="landing-surface-turn is-tutor">
        <TutorMark />
        <span className="landing-surface-bubble is-tutor">
          That is exactly it. Now try the other one — what does v = (0, 1) do?
        </span>
      </span>

      <span className="landing-surface-actions">
        {ACTIONS.map((a) => (
          <span key={a} className="landing-surface-action">
            {a}
          </span>
        ))}
      </span>
    </SurfaceFrame>
  );
}
