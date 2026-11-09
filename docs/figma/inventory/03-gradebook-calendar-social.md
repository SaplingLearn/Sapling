# Inventory — /gradebook, /gradebook/[courseId], /calendar, /course-planner, /achievements, /social, /profile/[userId], ManageCoursesModal

Paths relative to `frontend/src/`. Only viewport branch is the shell nav (< 768px); these screens have no mobile layouts (fixed 3-col grids, 260px Social sidebar) — mobile frames would be proposals. Route transitions: `shell-loading`. Crash: `ErrorBoundary.tsx:53` ("We hit a snag" / "Your session expired", `error-fallback`). Flags `hide_grades|calendar|course_planner|social|achievements` → redirect /dashboard. Seed: terms F25/S26/F26; CS101 (F25, S26), MATH210 (S26), BIO110 (F25, Labs drop 1), ENG150 (F26, curved, no mean/sd); rooms "CS101 Study Group" (active owns) + "Rich Local Lounge" (second owns). NOT seeded: friends, earned achievements, Gradescope.

## /gradebook (`components/screens/Gradebook/Landing.tsx`)
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| gradebook/blank-hydrating | null | pre-hydration | Landing.tsx:269 | – |
| gradebook/loading | "Grades" + Upload syllabus; 6 skeleton cards; Transcript | delay courses / summary | :339, 387 | gradebook-transcript-open |
| gradebook/populated | Term chips, "Term GPA x.xx", 3-col colored course cards (letter, %, n/m graded) | default S26 | :303-344; CourseCard.tsx:117 | gradebook-term-gpa |
| gradebook/populated-no-gpa | no GPA | gpa null | :310 | – |
| gradebook/card-awaiting-grade | "—" "Awaiting First Assignment" | percent null | CourseCard.tsx:121-241 | – |
| gradebook/card-grade-colors | A/B/C/D/F colors | vary | CourseCard.tsx:12 | – |
| gradebook/chip-past-term | other chip | click / `?semester=` | :120, 165 | – |
| gradebook/empty-term | "A blank semester, ready to plant." + Upload syllabus | courses [] in term | :341, 415 | gradebook-upload-syllabus |
| gradebook/empty-new-student | no chips, hero empty | courses [] / 500 | :177, 194 | – |
| gradebook/logged-out-preview | demo chips + sample cards (reachability unconfirmed) | no user | :20-147 | – |
| gradebook/syllabus-pick-course / -extracting / -review / -review-invalid / -saving / -saved / -save-error | Dialog: course + file → "Extracting syllabus…" → editable categories, "Total: x% ✓", assignments list → red total, Save disabled → "Saving…" → toast + navigate → error toast | Upload syllabus | SyllabusUploadFlow.tsx:49-206 | – |
| gradebook/transcript-loading / -populated / -empty / -error | skeleton / cumulative + per-term GPA / "Nothing on the transcript yet…" / inline alert + Try again | Transcript | TranscriptModal.tsx:51-223 | gradebook-transcript-gpa, -retry |

## /gradebook/[courseId] (`components/screens/Gradebook/Course.tsx`)
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| course/loading | breadcrumb, Letter Scale, skeleton masthead/bar/segments | delay course GET | :598, 1636 | – |
| course/error | "We couldn't load this course." + Try again + toast | 404/500 | :265, 600, 1601 | – |
| course/populated | Masthead (CODE · term, name, letter + %), Composition bar (earned/lost/remaining hatched, ticks, now-pin, legend), Predict row, Assignments by category | CS101 S26 | :604-864 | gradebook-add-assignment |
| course/masthead-empty | "—" | percent null | :750, 822 | – |
| course/composition-status-variants | "At the Top…" / "X already guaranteed" / "out of reach" / "Need n%+…" | vary | :1345-1355 | – |
| course/composition-no-categories | "No categories yet…" + Edit Weights | 0 categories | :912 | – |
| course/weights-not-100 | orange warning | sum ≠ 100 | :1226 | – |
| course/drop-lowest | "· 1 Drops", struck row "Dropped" | BIO110 F25 | :1212; AssignmentList.tsx:384, 476 | – |
| course/bar-tooltip-{earned,lost,remaining,empty} | dark tooltip | hover segment | :1434-1483 | role=tooltip |
| course/category-highlight | group tinted 1.6s | click segment / 1-9 | :364 | – |
| course/assignments-empty / -uncategorized | "Nothing entered yet." / grey Uncategorized | data | AssignmentList.tsx:234-570 | – |
| course/inline-grade-edit | input, optimistic, revert + toast | edit score | AssignmentList.tsx:519; Course.tsx:336 | – |
| course/gradescope-setup-btn / -ready-btn / -syncing-btn | "Set Up Gradescope Sync" / "Sync from Gradescope · Synced 5m ago" / "Syncing…" + toast | creds state | AssignmentList.tsx:107-149; Course.tsx:307 | – |
| course/curve-toggle | Raw/Curved pill; "Curved" chip "→ 84.2" | assignment with mean + sd | :534; AssignmentList.tsx:485, 546 | – |
| course/predictor-none / -collapsed / -open / -missing-total / -curved | grey line / "▸ Predict My Grade…" / Hypothetical Scores sliders, dashed bar, "Predicted" / "⚠ No Total Score" / Bell Curve inputs "✓ Curve Active" | ungraded rows / ENG150 | GradePredictorPanel.tsx:54-464 | – |
| course/assignment-new / -title-required / -invalid-date / -curve-expanded / -edit / -saving / -save-error | New Assignment dialog → validation → Bell Curve section → Edit + Delete → Saving → toast | + Add / row click | AssignmentModal.tsx:85-347 | gradebook-assignment-title, -save |
| course/edit-weights / -invalid / -dragover | rows ⠿ name % drop ✕, Total / red / drag outline | Edit Weights | EditWeightsModal.tsx:85-243 | – |
| course/letter-scale / -invalid | letter/min rows, Reset / "Tiers must be sorted…" | Letter Scale | LetterScaleEditor.tsx:38, 109 | – |
| course/curve-settings | unstyled overlay "Bell Curve Settings" | ⚙ Curve | Course.tsx:113-215 | role=dialog |
| gs/loading → choose-mode → credentials / cookies / bu-sso-form → bu-sso-waiting → link / link-empty → ready → syncing → done / done-partial; error-banner; verification-error; connected; confirm-remove (native) | GradescopeSyncModal steps (3 mode cards, Duo wait spinner, course picker, 4 stats) | Set Up / Sync | GradescopeSyncModal.tsx:56-1289 | role=alert |

## /calendar (`components/screens/Calendar.tsx`)
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| calendar/loading | "Calendar · March 2026 · 0 assignments", month skeleton | delay all | :307 | – |
| calendar/error | "We couldn't load your calendar." + Try again | 500 first load | :310, 358 | calendar-load-error, -retry |
| calendar/refresh-error-toast | toast | later 500 | :128 | – |
| calendar/month / -month-empty | Mon–Sun 6×7, today accent, ≤3 items + "+n more" / empty grid | default | :512-577 | – |
| calendar/week | 7 day cards or "—" | Week | :579 | – |
| calendar/day | date heading, cards w/ due chips (overdue / due soon / Nd / no date) or "Nothing scheduled." | Day | :65, 639 | – |
| calendar/table / -empty / -row-editing / -delete-confirm | "n of m selected", sort, Export CSV, table / "No assignments yet." / inline edit / native confirm | Table | :680-947 | – |
| calendar/google-disconnected / -connected / -disconnect-armed / -events-loading / -events-modal / -events-empty / oauth-return | Connect Google / Sync + View events + Disconnect + Export to Google / "Click again" / "Loading…" / events overlay / "No upcoming events…" / toast | status mocks | :149, 262-480, 825 | – |
| calendar/upload-modal | DocumentUploadModal (see 02-library) | Import syllabus | :331 | upload-modal* |
| calendar/toasts | synced / exported / nothing to export / select first / updated / deleted / failures | actions | :185-232, 738-788 | – |

## /course-planner
| State id | What the user sees | Trigger | File:line |
|---|---|---|---|
| course-planner/coming-soon | "✦ Coming soon" pill, serif title, blurb (only state) | visit | app/(shell)/course-planner/page.tsx:7-48 |
| course-planner/flag-hidden | redirect /dashboard | `hide_course_planner` | lib/navFeatures.ts |

## /achievements (`components/screens/Achievements.tsx`)
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| achievements/loading | "0 earned · 0 in progress", tabs, pills, skeleton | delay | :234 | achievements-tab-* |
| achievements/populated | Hero (stage image in XP ring, LVL, XP bar), stat row (Streak, Daily goal ring, Badges), Showcase n/5, badge sections w/ "x / y" | seed + me | :236-332; HeroCard.tsx:10 | gamification-hero, -total-xp, -level |
| achievements/hero-max-level / no-me | "Highest stage reached" / no hero | xp_for_level 0 / me 500 | HeroCard.tsx:40; :140 | – |
| achievements/showcase-empty / -filled | 5 dashed slots / cards w/ ✕ ← → | featured | :244-317 | achievements-showcase-* |
| achievements/badge-earned / -progress / -locked / -secret | earned date + XP / progress bar / "Locked · +n XP" / "???" | data | BadgeGrid.tsx:52-96 | – |
| achievements/filter-category / grid-empty | pills / "No achievements yet." | click / empty | BadgeGrid.tsx:29, 111 | – |
| achievements/badge-modal-earned / -progress / -locked / -secret | modal w/ 🍃 burst / bar / locked / ??? | click badge | BadgeModal.tsx:23-170 | role=dialog |
| achievements/toast-unlocked / -showcase-full / -save-error | toasts | events | :111-173 | – |
| achievements/leaderboard-loading / -populated / -podium-partial / -empty / -error / -viewer-outside | scope toggle; podium + rank rows + YOU / 1–2 podium / "No XP earned…" / error / extra own row | Leaderboard tab | LeaderboardTab.tsx:57-182 | leaderboard-row-you |
| achievements/activity-loading / -populated / -zero-week / -error | 4 tiles, week bars w/ goal line, 8-week bars / stub / error | Activity tab | ActivityTab.tsx:137-171 | activity-week-total |
| global/achievement-unlock-toast | icon tile, name, rarity | watcher (60s poll / visibility) | AchievementUnlockToast.tsx:22 | – |

## /social (`components/screens/Social.tsx`) — no TopBar
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| social/loading / no-rooms | sidebar Study Rooms, Friends "Loading…"; "Select or create a room to begin." / "No rooms yet…" | delay / [] | :377, 1457-1481 | social-create-room, -join-room, -directory-open |
| social/room-chat | name, invite chip, members, Overview/Chat/Study match/Activity; bubbles; composer | seed | :485, 1431-1451 | social-chat-* |
| social/chat-empty / -has-more / -typing / -message-menu / -emoji-picker / -reactions / -replying / -editing / -deleted-message / -edited / -image / -mention-popup | "No messages yet — say hi." / Load earlier / "Name typing…" / pill 😊↪✎✕ / emoji grid / pills / reply bar / inline edit / "Message deleted" / "(edited)" / image / @ popup | interactions | :765-945 | social-chat-message-*, -emoji-{e}, -reply-cancel, -edit-*, -mention-{uid} |
| social/overview-loading / overview / -non-owner / -leave-armed / -kick-armed / -comparison | AI summary + Members (Leader, Profile, Kick) / no Kick / "Click again…" / comparison bars | Overview tab; `?suggest={uid}` | :1036-1192, 1400 | social-room-leave, social-member-* |
| social/match-idle / -results | "Find your study match" / partner cards + toast | Study match tab | :1224-1272 | social-match-run |
| social/activity | feed / "No activity yet." | Activity tab | :1279-1302 | – |
| social/directory-loading / -list / -no-match | roster search | Browse directory | :1305-1388 | social-directory-search |
| social/create-form / join-form | name, topic, course, Public checkbox / invite code | Create / Join | :165-205 | social-create-* |
| social/public-rooms-list / room-item-public | Public rooms + Join / "Public" chip | public rooms | :210-279, 1501 | social-public-join-{id} |
| social/friends-empty / -incoming / -outgoing / -list / remove-armed | "No friends yet." / Accept/Decline / Pending / "Lv n · n XP" + Remove | friendships | :282-444 | social-friend-* |
| social/invite-copied / toasts | "Copied!" / room & friend toasts | actions | :1515 | social-invite-copy |

## /profile/[userId] (`app/(shell)/profile/[userId]/page.tsx`, `ProfileView.tsx`)
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| profile/loading / error | skeleton / "Couldn't load this profile." | delay / 404-500 | page.tsx:28-35 | – |
| profile/other-populated | hero (frame, colored name, flair, roles, bio, meta), stat strip, Fields of study, Featured achievements | /profile/rich-user-second | ProfileView.tsx:109-259 | – |
| profile/other-add-friend / -pending / -friends / friend-status-loading / own | "+ Add friend" / "Request sent" / "Friends" chip / none / none | relationship | :77-99 | profile-add-friend, profile-friend-status |
| profile/banner / private / minimal | gradient hero / "This profile is private." / sparse | data | :116-261 | – |

## ManageCoursesModal (`components/ManageCoursesModal.tsx`)
open-all · term-selected · no-terms · term-empty · search-loading / no-matches · result-states (+ Add / Adding… / Already taken) · color-invalid · delete-armed · toasts (:96-358). Trigger: `dashboard-courses-manage`.

## Transitions (summary)
Gradebook chips · card → course · Upload syllabus → pick → extracting → review → save → course · Transcript → loading → states · course: breadcrumb, retry, segment highlight/tooltip, Edit Weights, + Add / row → assignment modal, Letter Scale, ⚙ Curve, Raw/Curved, predictor ↔, Gradescope chain (choose → creds/cookies/SSO → Duo → link → ready → sync → done/partial). Calendar: Month/Week/Day/Table, Prev/Today/Next, table edit/delete, Import syllabus, Google connect → OAuth → `?connected=true` → events modal / disconnect. Achievements: tabs, scopes, pills, badge → modal, showcase edit. Social: tabs, room switch, directory → profile, member Profile, leave ×2, match → profile, create/join, public join, friends accept/decline, bubble menu chain. Profile: Add friend → pending. ManageCourses: term ↔ all, add, delete ×2, close.

## Uncertain / needs a human
1. Logged-out gradebook preview may be unreachable (middleware).
2. Empty states: mock `GET /api/graph/{uid}/courses → {courses:[]}` (rich-user-new not onboarded).
3. Showcase can't be filled from UI (no "feature" button) — product gap?
4. `GradeProjector.tsx` is never rendered — excluded.
5. Hard-to-seed: curve toggle, Gradescope, Google connected, friends, achievements/XP need mocks.
6. Off-pattern surfaces: unstyled Bell Curve overlay, Social has no TopBar, native confirms.
7. LetterScaleEditor "Reset to default" stays open — possible bug.
8. No mobile layouts on these screens.
9. Chat typing / image upload need Supabase realtime/storage.
10. DocumentUploadModal is owned by the library inventory.
11. ProfileView also embedded in Settings preview.
