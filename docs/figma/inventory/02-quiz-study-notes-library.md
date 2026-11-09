# Inventory — /quiz, /study, /flashcards, /notetaker, /library

Paths relative to `frontend/src/`. Seed `rich-user-active` (CS101 `rich-course-cs101`, BIO, HIST, node `rich-node-cs-recursion` "Recursion" 0.25, notes, documents, flashcards, cached guides, completed attempts). `rich-user-new` is NOT onboarded → empty/error states need `page.route` mocks (pattern: `e2e/quiz-errors.spec.ts:330-420`). /quiz and /study share the AI disclaimer modal (`DisclaimerModal.tsx`, until `sapling_disclaimer_ack`).

## /quiz (`components/quiz/QuizScreen.tsx`)
Phase → screen (QuizScreen.tsx:123-199): home/configuring/paused → Home · generating/active/answered/confirm-leave/submitting → Question · results → Results · error → Error card. URL params: `concept, topic, course, scope=due, attempt, from (tree|notes|dashboard|nav|link|quiz), return, note` (`lib/quiz/source.ts:71`).

### Home & setup
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| quiz/signed-out | "Sign in to take a quiz." | no session | QuizScreen.tsx:125 | – |
| quiz/disclaimer-modal | AI disclaimer over page | clear ack | QuizScreen.tsx:209 | – |
| quiz/home-loading | 2-col skeleton, 340px graph block, 6 rows, Cancel | delay graph + courses | home/QuizHome.tsx:653 | quiz-home, quiz-cancel |
| quiz/home-error | "We couldn't load your tree" + Retry | graph → 500 | QuizHome.tsx:675 | quiz-home-error, quiz-home-retry |
| quiz/home-no-courses | "Add a course to start quizzing" + dashboard link | courses [] | QuizHome.tsx:704 | quiz-empty-state |
| quiz/home-empty-tree | "Your tree is empty" + library / tutor links | nodes [] | QuizHome.tsx:715 | quiz-empty-state |
| quiz/home-all-mastered | "Nothing needs review right now" + topics | only mastered | QuizHome.tsx:524 | quiz-pick-list |
| quiz/home-ready | "Ready for you", concept, meta, definition, config line, neighbourhood graph, Start/Adjust, review-due link; "Choose a topic" list w/ course pills + search | default | QuizHome.tsx:452-621 | quiz-proposal, quiz-start, quiz-adjust, quiz-review-due, quiz-pick-{id}, quiz-course-{id}, quiz-topic-search |
| quiz/home-definition-pending | 3 skeleton lines | delay concept-description | QuizHome.tsx:478 | quiz-definition-pending |
| quiz/home-definition-fallback | Built sentence | concept-description 500 | QuizHome.tsx:245 | – |
| quiz/home-deeplink-tree / -note / -link | Rationale "From your tree" / "From your note" / "Suggested for you" | `?concept=…&from=…` | QuizHome.tsx:76-226 | quiz-proposal |
| quiz/home-course-queue | "Practice CS101", "N concepts due" | `?course=` | QuizHome.tsx:208 | – |
| quiz/home-due-queue | "Review everything due…" | `?scope=due` | QuizHome.tsx:211 | – |
| quiz/home-unresolved-toast | Info toast "isn't in your current semester" | off-term concept | QuizHome.tsx:106 | – |
| quiz/home-your-pick | "Your pick" + Back to suggestion | click row/neighbour | QuizHome.tsx:349, 463 | quiz-pick-reset |
| quiz/home-course-filtered | pill active | 2+ courses | QuizHome.tsx:563 | – |
| quiz/home-search-empty | "No concepts match…" | no match | QuizHome.tsx:615 | quiz-topic-search-empty |
| quiz/home-resume-strip | "You left a quiz on X — 1 of 3 answered" Resume/Discard | leave mid-quiz | QuizHome.tsx:390 | quiz-resume-strip, quiz-resume, quiz-resume-discard |
| quiz/home-mobile-stacked | Columns stack ≤900, rows wrap ≤560 | 390px | home/home.css:271, 434 | – |
| quiz/adjust-dialog | Length / Difficulty / Answers (/ Format), Done / Start | Adjust | home/AdjustDialog.tsx:76 | quiz-adjust-dialog, quiz-seg-*, quiz-adjust-done/-start |
| quiz/adjust-config-loading / -at-end-note / -format-mixed | skeleton / note / mixed note | delay config / at end / mixed | QuizSettings.tsx:164, 230; AdjustDialog.tsx:24 | quiz-format-mixed-note |

### Question
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| quiz/generating | Rail, header, "Writing your quiz…", skeletons | delay generate | question/QuizQuestion.tsx:322 | quiz-generating, quiz-progress |
| quiz/q-mcq-active-empty | Stem, A–D, Submit disabled, flag, Leave | generate 200 | QuizQuestion.tsx:374-516 | quiz-panel, quiz-answer-option-{X}, quiz-submit-answer, quiz-leave, quiz-flag |
| quiz/q-mcq-selected | Selected bar, Submit on | click / A–F keys | QuizQuestion.tsx:357 | – |
| quiz/q-submitting-answer | Submit disabled | delay /answer | :229 | – |
| quiz/q-mcq-correct | ✓ "Correct." + explanation, Ask, Next | as-you-go right | :463 | quiz-review-verdict, quiz-next, quiz-ask |
| quiz/q-mcq-incorrect | red ✕, correct ✓, "Not quite — the answer is C." | as-you-go wrong | :357-362, 466 | quiz-review-verdict |
| quiz/q-at-end-answered | no verdict, advance | at-end mode | :136 | – |
| quiz/q-last-see-results / q-scoring | "See results" / "Scoring…" | last item / delay submit | :208, 220 | quiz-next |
| quiz/q-material-context | micro label | items w/ material_context | :388 | quiz-material-context |
| quiz/q-flagged | "Noted — thanks." | flag | :194 | quiz-flag |
| quiz/q-short-delivery-toast | "Only N questions were ready…" | delivered < requested | :179 | – |
| quiz/q-written-short / -numeric / -symbolic | input + hint; numeric keys + read-back (ok/invalid); symbolic keys | item types | question/WrittenAnswer.tsx:105-161 | quiz-written-answer, quiz-key-*, quiz-written-readback |
| quiz/q-written-incorrect | "Not quite — the expected answer is X." | wrong written | QuizQuestion.tsx:465 | – |
| quiz/leave-dialog | "Leave this quiz?" Keep going / Leave | Leave / Esc | question/LeaveDialog.tsx:44 | quiz-leave-dialog, -cancel, -confirm |
| quiz/ask-sheet-seed / -streaming / -reply+followup / -error | Sheet with your/correct answer cards → streaming → thread + composer → error + Try again / "Interrupted" | Ask | question/AskPanel.tsx:338-395 | quiz-ask-panel, quiz-ask-input, quiz-ask-send, quiz-ask-retry |
| quiz/error-retryable | "That didn't work" + Try again + Back + Reference | generate 502/429 RATE_LIMITED/5xx/offline/0 qs | QuizScreen.tsx:127; lib/quiz/errors.ts:50 | quiz-error, quiz-error-retry, quiz-error-back |
| quiz/error-terminal | Same, no Try again | daily limit / 404 concept / 409s | errors.ts:50-80 | quiz-error |

### Results
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| quiz/results-missed | Growing node, "25% → 34%", "2 of 3 correct", +XP/streak, missed list, Practise missed / Back / Done | ≥1 wrong | results/QuizResults.tsx:135-256 | quiz-results*, quiz-missed-{qid}, quiz-practise-missed, quiz-back-to-source, quiz-done |
| quiz/results-missed-explain-open | Explanation expanded | Show explanation | results/MissedList.tsx:400 | quiz-missed-explain-{qid} |
| quiz/results-ask-sheet | AskPanel seeded from missed row | missed Ask | QuizResults.tsx:260 | quiz-missed-ask-{qid} |
| quiz/results-perfect | "Nothing to review…" + Quiz again | all right | :190, 231 | quiz-results-perfect, quiz-again |
| quiz/results-no-xp | XP hidden | gamification fail | :183 | – |
| quiz/results-queue-next | "Next: {concept} →" | queue remaining | :207 | quiz-next-concept |
| quiz/results-missed-rerun | "The ones you missed, again" | practise-missed attempt | :75, 166 | – |
| quiz/results-back-label | "Back to your note/dashboard/tree" | from= | lib/quiz/exits.ts:28 | – |

**Transitions:** ready –Start→ generating → q-* or error · Adjust ↔ dialog –Start→ generating · pick ↔ reset · review-due → generating · Cancel → return / dashboard · resume → item; discard · option → selected –Submit→ correct/incorrect –Next→ … –See results→ scoring → results · Leave/Esc → dialog → stay / source route · Ask → sheet → close · error retry → generating; back → home · practise missed → rerun · quiz again / next concept → generating · back-to-source / Done.

## /study (`components/screens/Study.tsx`) — no testids
| State id | What the user sees | Trigger | File:line |
|---|---|---|---|
| study/guide-no-course | "Study" + chip + "Study Guide \| Flashcards"; 01 Course / 02 Exam (disabled); "Pick a course to get started"; Recent guides rail | `/study` | Study.tsx:145, 467 |
| study/guide-recent-empty / -populated | "No generated guides yet." / rows, open highlighted | cached [] / seeded | :565-568 |
| study/guide-exams-loading / -exams-error-toast | Exam "Loading…" / error toast | delay / 500 exams | :293, 447 |
| study/guide-no-exams / -choose-exam | "No exams for this course yet" / "Choose an exam" | exams [] / not picked | :473-479 |
| study/guide-loading | Guide skeleton | delay guide | :513 |
| study/guide-populated | Header (title, Due chip, Cached/Fresh, overview) + Topic N cards; Regenerate | guide 200 | :456, 515-556 |
| study/guide-regenerating / -regenerate-error | "Regenerating…" + toast / error toast | regenerate | :366-385 |
| study/guide-missing / -missing-term / -failed | "That exam isn't around anymore" / "That guide isn't available" / "didn't come through" + Try again | 404 / 404 other / 500 | :486-494 |
| study/guide-mobile | rail hidden | < 768 | :559 |

**Transitions:** course → exams → choose → loading → populated/missing/failed · Regenerate · recent row → loading · toggle ↔ Flashcards (selections reset).

## /flashcards (redirects to `/study?mode=cards`; `FlashcardsMode` Study.tsx:595 + `components/flashcards/**`)
| State id | What the user sees | Trigger | File:line |
|---|---|---|---|
| cards/loading | skeleton | delay flashcards | Study.tsx:769 |
| cards/empty-all / -empty-course | "No cards here yet" variants | [] | :770-774 |
| cards/front | Topic filters, Import, Generate; "Card i of N", progress; "Question… press Space"; forgot/hard/easy dimmed; Delete; course rail | seeded | :781-879 |
| cards/back-flipped | 3D flip "Answer", ratings enabled | click / Space | :801, 893 |
| cards/rated-next | next card | rate 1/2/3 | :671 |
| cards/topic-filtered / course-filtered | pill / rail row active | click | :737, 849 |
| cards/generating / -generate-warn / -generate-error | "Generating…" + toast + chip / warn / error | Generate | :709-747 |
| cards/deleted | toast (no confirm) | Delete | :682 |
| cards/mobile | rail hidden | < 768 | :843 |
| import/paste-empty | Dialog: course, set name, tabs Paste/Upload/URL/AI/Photo; textarea, separators; "No cards parsed yet."; Import disabled | Import | FlashcardImportModal.tsx:89; tabs/PasteTab.tsx:86 |
| import/paste-parsed / -table-flagged-row | Parse table / red "!" row, "x valid · y flagged" | paste | ParsedCardsTable.tsx:233-263 |
| import/custom-separator / reverse-on / cleaning / cloze | custom input / doubled count / "Cleaning…" / cloze gen | options | PasteTab.tsx:119-143; ParsedCardsTable.tsx:190-211 |
| import/upload-tab / -upload-errors | Drop zone → "Parsing…" / toasts (5MB, type, parse) | Upload tab | tabs/UploadTab.tsx:42-66 |
| import/url-tab / -url-blocked / -url-error | Quizlet URL + Fetch / "Couldn't fetch this URL" / toast | URL tab | tabs/UrlTab.tsx:30-53 |
| import/ai-tab-paste / -library / -generating | notes vs library, count, difficulty / doc select / "Generating…" | AI tab | tabs/AiTab.tsx:41-73 |
| import/photo-tab | "Reading image…" | Photo tab | tabs/PhotoTab.tsx:46 |
| import/committing / -commit-error | "Importing…" → toast, close / error | Import N | FlashcardImportModal.tsx:67-82 |

**Transitions:** front ↔ flipped → next · Import → tabs (deck carries) → commit → reloaded · Generate → toast.

## /notetaker (`app/(shell)/notetaker/page.tsx`) — no TopBar, no testids, no viewport branch
| State id | What the user sees | Trigger | File:line |
|---|---|---|---|
| notes/loading | "Loading notes…" | delay notes | page.tsx:513 |
| notes/empty / -empty-no-courses | "No notes yet" + Create / disabled + "Add a course first…" | notes [] (+ courses []) | :530-582 |
| notes/course-picker | "New note / Which course is this for?" | Create / + | :1418, 1475 |
| notes/three-pane | List (search, course chips, rows) · editor (title, body, "Saved · 2m ago · N words") · right (Linked concepts, Tags, Actions, Details, Delete) | seeded | :595-707 |
| notes/list-filtered / -list-no-match | "n / total" / "No notes match…" | chip / search | :767-834 |
| notes/save-unsaved / saving / saved | footer status | type (800ms debounce) | :1088-1095 |
| notes/no-concepts / concepts-linked | empty copy, quiz disabled / rows w/ unlink | links | :1161-1210, 1341 |
| notes/concept-picker | "Link concept" modal, search, Loading / No matching / rows | + Link concept | :1559, 1681-1703 |
| notes/tags-empty / tag-adding | "No tags." + Add → input | + Add | :1242-1300 |
| notes/busy-* | "Summarizing…" / "Extracting…" / "Building quiz…" / "Opening tutor…" / "Deleting…" | delay action | :1319-1411 |
| notes/summary-shown | "Last summary" box | summarize ok | :1352 |
| notes/action-error-toast | per-action toasts | 500 | :409-454 |
| notes/fullscreen | Big editor + "Quick questions" chat pane | Fullscreen | :602-705, 1034 |
| notes/chat-empty / thinking / replied / error | placeholder → "Sapling is thinking…" → bubbles → sorry bubble | send | :1802, 1855-1890 |
| notes/deep-link-note | specific note | `?note={id}` | :191 |

**Transitions:** empty → picker → new note · row switch · Link → picker → linked · Generate quiz → `/quiz?concept=…&from=notes…` · Send to tutor → `/learn?topic=…` · fullscreen ↔ Esc · Delete (no confirm).

## /library (`components/screens/Library.tsx`, `DocumentUploadModal.tsx`)
| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| lib/loading | TopBar "Library", search, Upload, category pills, Grid/List, skeleton | delay documents | Library.tsx:225 | library-search, library-upload |
| lib/empty | "Your library is quiet" (also no-match & load-error) | [] | :229 | – |
| lib/upload-disabled | Upload disabled "Enroll in a course first" | courses [] | :193 | library-upload |
| lib/grid / lib/list | cards (tile, chip, filename, course·date, 3-line summary) / rows | seeded / toggle | :238, 297 | library-doc-{id} |
| lib/category-filtered | pill active | click | :206 | – |
| lib/course-rail | Courses rail w/ counts | desktop | :358 | library-course-filter-* |
| lib/course-scan | "Scan CS101" → "Scanning…" → toasts | course picked | :73, 177 | library-course-scan |
| lib/mobile | rail hidden | < 768 | :358 | – |
| lib/detail-modal | chip, ×, filename, Summary, Key concepts accordion, Concept scan, Delete | click doc | :393, 477 | library-detail-*, library-concept-toggle-{i} |
| lib/detail-concept-open / -scanning / -scanned / -delete-armed / deleted | expanded / "Scanning…" → result / "Click again to confirm" / toast | interactions | :414-675 | library-detail-scan, library-detail-delete |
| upload/empty | "Upload / Add course materials", dropzone, Browse, course search, "0 files queued", Start disabled | Upload | DocumentUploadModal.tsx:294-538 | upload-modal* |
| upload/dragging | dropzone accent "Drop to add files" | drag over | :321, 336 | – |
| upload/rejected-toast | type / 100 MB toasts | bad file | :123 | – |
| upload/course-search-results / -course-added | result list / toast | search | :265, 371 | upload-modal-course-result-{id} |
| upload/queued | file row, "queued", course select | add file | :398 | upload-modal-file-row-{i} |
| upload/processing-sse | "processing…" + live line: Starting upload → received → Extracting text → Extracted N chars → Classifying → Classified as X → Extracting summary… → N concepts → Merging → Merged → complete | Start upload | :156-188, 465 | upload-modal-submit |
| upload/done | "done", Category select, Re-analyze, summary, concept chips, Done | SSE result | :190, 444-486 | upload-modal-done |
| upload/category-changed | toast | PATCH doc | :253 | – |
| upload/error / aborted / no-course-error | "error" + reference + Retry / ">4 min" / "Pick a course first." | SSE error / hang / no course | :144, 199-512 | upload-modal-file-retry-{i} |
| upload/close-confirm | native confirm | close while processing | :110 | – |
| lib/syllabus-toast | "Syllabus processed — …calendar." | syllabus upload | Library.tsx:431 | – |

**Transitions:** Upload → empty → queued → processing → done/error → Done → grid reload · retry / re-analyze · Grid ⇄ List · rail → filtered + scan · doc → detail → close / delete ×2.

## Uncertain / needs a human
- Study rooms live on /social, not /study.
- No onboarded-but-empty seed user; empty states need mocks (or a new seed user).
- Silent load failures (study, flashcards, library, notetaker) show the empty state — no error frame exists.
- Possible double toast on upload failure.
- `quiz-next` / `quiz-submit-answer` testid stays during "Scoring…".
- Flashcard course filter matches course *name* in topic — fragile.
- Study/flashcards/notetaker have no testids — anchor by text.
- Quiz question/results/Sheet have no phone layout.
- material_context labels and Format setting need config with >1 question type.
- Notetaker chat only reachable in fullscreen.
