# Feature · Flashcards (standalone page)

> Covers: `/flashcards/page.tsx` (`src/app/flashcards/page.tsx`, 500+ lines). **Orphaned route** — no in-app link points to it (see Phase 2 §4). Duplicates most of the logic in `src/app/study/FlashcardsPanel.tsx` (see `features/study.md`).

---

## 1. Overview

`/flashcards` is a standalone copy of the flashcards experience. It has its own top bar (`← / Flashcards / AIDisclaimerChip`), a left generator panel, a right card grid, and a full-screen study mode identical to the one inside `/study`.

Because the Navbar does not link to `/flashcards`, this page is only reachable by direct URL. CLAUDE.md suggests the intended primary surface is `/study → Flashcards`. If so, `/flashcards` should be treated as legacy and either removed or redirected to `/study?mode=flashcards`.

---

## 2. User flows

Identical to `FlashcardsPanel`:

- Generate → `POST /api/flashcards/generate {user_id, topic, count:10}` with `topic` = a course name. Prepends into the deck.
- Topic filter pills on the right panel.
- "Study by topic" buttons on the left — enter full-screen study mode on click.
- Study mode: flip card (0.55s 3D rotation), Forgot/Hard/Easy rating (1/2/3). Rating calls `rateFlashcard` and auto-advances after 300ms. Exits to list on last card.
- Card actions: delete (X in bottom-right of each card) → `deleteFlashcard`.

Divergence from `FlashcardsPanel`:

- Top bar includes `AIDisclaimerChip` (desktop); `FlashcardsPanel` does not have its own top bar.
- Mobile: `mobileTab` state toggles between `cards` and `generate` pills (shown in a sticky top strip). `FlashcardsPanel` stacks the two panels vertically on mobile instead.
- `/flashcards` is wrapped by Navbar + root layout (so `SessionFeedbackGlobal` and `FeedbackFlow` are mounted). `FlashcardsPanel` is embedded inside `/study` and shares that route's chrome.

---

## 3. State

Same as `FlashcardsPanel` plus:
- `mobileTab`: `'generate' | 'cards'` for mobile layout.

---

## 4. API calls

Identical to `FlashcardsPanel` (§4 of `features/study.md`).

---

## 5. Components involved

- `AIDisclaimerChip` (top-right of top bar)
- `Link` from `next/link` (back arrow to `/`)
- Inline: generator, topic filter pills, card grid, flip-card study mode

---

## 6. Edge cases

1. **Orphaned route.** No in-app Link or `router.push` points here (verified by grep). Either a legacy page or an intentionally URL-only deep link. Flag.
2. **Duplicate generator state** in two places — if the user generates cards on `/flashcards`, `/study → Flashcards` won't see them until remount (and vice versa).
3. **Study mode doesn't lock body scroll** — the user can accidentally scroll the page behind the flip card.
4. **No keyboard shortcuts** for flip (Space) or rate (1/2/3).

---

## 7. Things to preserve in the rebuild

- The same card UI (Topic pill + Q/A + `times_reviewed` + last-rating chip + delete X).
- The same full-screen flip-card study mode (keep the 0.55s cubic-bezier animation).
- The Forgot/Hard/Easy (1/2/3) rating semantics.
- "Generated using N library docs / M weak concepts" chip when `context_used` is returned.

## 8. Things to rework

- Consolidate with `FlashcardsPanel`. Either:
  - Remove `/flashcards` and redirect to `/study?mode=flashcards`, **or**
  - Keep `/flashcards` as the canonical route and delete `FlashcardsPanel`'s parallel copy (embed by routing inside `/study`).
- Add keyboard shortcuts.
- Add body scroll-lock while in study mode.
