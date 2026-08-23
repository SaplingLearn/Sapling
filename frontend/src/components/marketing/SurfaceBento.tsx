/**
 * The four-tile bento of built product surfaces (#344 step 2, spec section 4).
 *
 * Tutor, Notetaker, Study Rooms, Gradebook — the four screens the old
 * six-row feature catalog never mentioned, which is the spec's actual
 * diagnosis of "feels generic": the page undersold the product more than it
 * under-designed it.
 *
 * Every tile is a RECREATED SURFACE, never an icon over a heading over a
 * sentence. There is no per-tile copy at all, deliberately: a caption under a
 * picture of the Gradebook explaining that it is the Gradebook is the bubble-
 * panel pattern wearing a screenshot. The tiles carry the product's own chrome
 * label and let the surface argue.
 *
 * Sizes are asymmetric on purpose (7/5 then 5/7 of a 12-column grid, the wide
 * tile swapping sides between rows) so the grid reads as a composition rather
 * than as four equal boxes — and the two conversation-shaped surfaces (Tutor,
 * Study Rooms) sit on opposite diagonals from the two document-shaped ones
 * (Notetaker, Gradebook).
 *
 * Between two bands and immediately before the closing band, so it re-energises
 * the middle of the page without being asked to close it: a grid's last tile is
 * a weak place to ask for a signup.
 */
import GradebookSurface from './surfaces/GradebookSurface';
import NotesSurface from './surfaces/NotesSurface';
import RoomsSurface from './surfaces/RoomsSurface';
import TutorSurface from './surfaces/TutorSurface';

const TILES = [
  { key: 'tutor', node: <TutorSurface /> },
  { key: 'notes', node: <NotesSurface /> },
  { key: 'rooms', node: <RoomsSurface /> },
  { key: 'gradebook', node: <GradebookSurface /> },
] as const;

export default function SurfaceBento() {
  return (
    <section
      id="surfaces"
      data-testid="landing-bento"
      aria-labelledby="bento-headline"
      className="landing-section landing-bento relative z-10"
    >
      <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
        <div
          className="sapling-mesh-blob sapling-mesh-blob--3"
          style={{ top: '-6%', bottom: 'auto', left: '32%', width: '36vw', height: '36vw', opacity: 0.14 }}
        />
      </div>

      <div className="relative z-[1] max-w-7xl mx-auto px-6 lg:px-12">
        <div className="landing-bento-head landing-fade-up">
          <span className="landing-eyebrow" data-testid="landing-bento-eyebrow">
            Inside Sapling
          </span>
          <h2 id="bento-headline" className="landing-band-headline">
            Everywhere else your work happens.
          </h2>
        </div>

        <div className="landing-bento-grid landing-fade-up">
          {TILES.map((t) => (
            <div key={t.key} className={`landing-bento-tile landing-bento-tile--${t.key}`}>
              {t.node}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
