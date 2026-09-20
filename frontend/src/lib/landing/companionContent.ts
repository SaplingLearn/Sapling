/**
 * Copy for the six companion pages.
 *
 * Lifted verbatim from the sibling `.dc.html` design components, where it
 * lives as plain JS object literals. Content only -- no markup, no styling.
 */

import {
  JOURNAL_ARTICLES,
  articleText,
  dateLabel,
  readTime,
} from './journalArticles';

export const ABOUT_DIFFERENTIATORS = [
        'Your knowledge graph is yours. It updates in real time based on your actual performance, not just what you\u2019ve clicked through.',
        'Three distinct teaching modes mean you\u2019re never locked into one way of learning.',
        'Study rooms let you learn alongside classmates and see how your mastery compares, anonymously and collaboratively.',
        'Everything from syllabus tracking to exam study guides is powered by Gemini, so the busywork of getting organized is handled for you.',
      ] as const;

export const ABOUT_AWARDS = [
        { delay: '440ms', title: 'Best AI Tutor in Education',
          org: 'Boston University Civic Hacks 2026 \u00b7 BU Spark! & Wheelock College of Education',
          body: 'Recognized among competing teams at BU\u2019s annual civic hackathon for building the most impactful AI-driven learning experience. Sapling was awarded for its approach to personalized, student-centered tutoring, bridging the gap between artificial intelligence and meaningful education.' },
        { delay: '520ms', title: 'Code & Tell Winner', org: 'BU Spark!',
          body: 'Selected by BU Spark! as a standout project at their Code & Tell showcase, where student builders present real-world applications to faculty, mentors, and industry judges. Sapling was chosen for its technical depth and its vision for the future of how students learn.' },
      ] as const;

export const TEAM_MEMBERS = [
        { name:'Andres Lopez', role:'Full stack', slot:'team-andres', hint:'Drop a photo of Andres',
          body:'Works end to end, from the database up through the screens, and keeps the two halves speaking the same language.', delay:'0ms' },
        { name:'Jack He', role:'AI architecture and new features', slot:'team-jack', hint:'Drop a photo of Jack',
          body:'Designs how the agents, the graph, and your own materials fit together, and builds what Sapling does next.', delay:'80ms' },
        { name:'Jose Gael Cruz-Lopez', role:'Frontend', slot:'team-jose', hint:'Drop a photo of Jose',
          body:'Builds the interface you actually study in, and the motion and layout that keep it out of your way.', delay:'160ms' },
        { name:'Luke Cooper', role:'API integration', slot:'team-luke', hint:'Drop a photo of Luke',
          body:'Wires Sapling to the services your course already lives in, so your calendar, grades, and files arrive on their own.', delay:'240ms' },
        { name:'Hang Nguyen', role:'Marketing intern', slot:'team-hang', hint:'Drop a photo of Hang',
          body:'Runs the social side and the short-form video, and carries Sapling to the student groups and classmates we would never reach on our own.', delay:'320ms' },
      ] as const;

export const TEAM_WAYS = [
        'We use Sapling for our own courses before anyone else sees a feature. If it does not help us pass, it does not ship.',
        'Every feature has to feed the graph. A tool that knows nothing about what you already understand is a tool we would not add.',
        'We read every piece of beta feedback ourselves. There is no support queue between you and the people who built it.',
      ] as const;

export const FAQ_GROUPS = [
  { label: 'Academic integrity', items: [
    { q:"Isn\u2019t using AI to study just cheating?", a:"No, because Sapling never hands you the answer. It guides you toward the understanding: Socratic questioning, explanations you have to apply yourself, and TeachBack, where you do the explaining. Using Sapling is like having a tutor, not a ghostwriter. The work, and the learning, is still yours." },
    { q:"Will it just do my homework for me?", a:"It won't, by design. Answer engines hand over the solution; Sapling walks you through the process and adapts to how you learn. If you paste a homework problem, expect guiding questions, not a finished answer to copy." },
    { q:"Are tools like Sapling allowed in my classes?", a:"Sapling is a study aid, the same category as flashcards, tutoring, or a study group. It doesn't produce submittable work. That said, every course sets its own rules, so check your syllabus." },
    { q:"Won\u2019t I become dependent on the AI?", a:"We built Sapling to make you less dependent over time. Mastery only turns green when you can demonstrate understanding, and TeachBack literally requires you to explain concepts yourself. The goal is that you walk into the exam without us." },
  ]},
  { label: 'How it differs', items: [
    { q:"How is this different from just using ChatGPT?", a:"A general chatbot forgets you the moment you close the tab. Sapling maps what you know, remembers what you struggled with, schedules reviews before you forget, and grounds itself in your actual course materials. It's a study system, not a conversation." },
    { q:"What if the AI gets something wrong?", a:"It can, which is why Sapling grounds answers in your uploaded course materials and shows its reasoning instead of just a verdict. You stay the judge. Spot an error and flag it in one click, and the tutor corrects course." },
    { q:"Do I have to upload anything to get value?", a:"You can start with a single syllabus and still get a full semester of dates plus a first pass at the concept graph. The more of your own material you add, the more the quizzes and guides look like your course rather than a generic one." },
    { q:"Does it work for every subject?", a:"It works wherever your course has readable material and named concepts, which covers most lecture-based courses. Heavily studio or performance-based courses get less out of it, and we would rather say that than oversell." },
  ]},
  { label: 'Access and data', items: [
    { q:"What does it cost?", a:"Nothing during beta. Beta testers get every feature free while we build, and a say in what we build next. Join the list and you're in line." },
    { q:"What happens to my notes and documents?", a:"They stay yours. Uploads, notes, and messages are encrypted at rest with AES-256, used only to build your graph and study materials, and never sold or used to train outside models. Delete a document and its data goes with it." },
    { q:"Can I study with people from my class?", a:"Yes. Study rooms put a live chat next to a shared graph, so the room can see which concepts nobody has locked down and turn any gap into a quiz everyone takes." },
    { q:"When does the beta open?", a:"We are onboarding in small groups so we can actually read the feedback. Sign up and we will tell you which group you are in rather than leaving you on a silent list." },
  ]},
] as const;

export const GALLERY_SHOTS = [
  { slot:'shot-tree', route:'/tree', group:'Learn', cat:'learn', title:'Knowledge graph',
    body:'The whole course as nodes and edges, each ring showing mastery. Click any concept to see what it feeds.' },
  { slot:'shot-learn', route:'/learn', group:'Learn', cat:'learn', title:'AI tutor',
    body:'Socratic, expository, and TeachBack on the same concept, grounded in the documents you uploaded.' },
  { slot:'shot-quiz', route:'/quiz', group:'Learn', cat:'learn', title:'Adaptive quiz',
    body:'Difficulty re-tunes after every answer, and each result writes back to the concept it tested.' },
  { slot:'shot-study', route:'/study', group:'Study', cat:'study', title:'Flashcard review',
    body:'Rate your recall and the interval sets itself: ten minutes, one day, or four days.' },
  { slot:'shot-guide', route:'/study', group:'Study', cat:'study', title:'Study guide',
    body:'Assembled from your own library for one exam, weighted toward the concepts you keep missing.' },
  { slot:'shot-notetaker', route:'/notetaker', group:'Study', cat:'study', title:'Notetaker',
    body:'Write normally. Sapling summarizes, extracts the concepts, and links them into your graph.' },
  { slot:'shot-library', route:'/library', group:'Study', cat:'study', title:'Library',
    body:'Everything you have dropped in, with the concepts, cards, and dates each document produced.' },
  { slot:'shot-social', route:'/social', group:'Together', cat:'together', title:'Study rooms',
    body:'Live chat beside a shared graph, so the room can see exactly who is solid where.' },
  { slot:'shot-achievements', route:'/achievements', group:'Together', cat:'together', title:'Achievements',
    body:'Streaks and milestones that track demonstrated understanding rather than time logged.' },
  { slot:'shot-calendar', route:'/calendar', group:'Semester', cat:'semester', title:'Calendar',
    body:'One syllabus upload becomes every exam, pset, and quiz, dated and synced to Google Calendar.' },
  { slot:'shot-gradebook', route:'/gradebook', group:'Semester', cat:'semester', title:'Gradebook',
    body:'Syllabus weights become categories, and every score rolls into a live grade and letter.' },
  { slot:'shot-planner', route:'/course-planner', group:'Semester', cat:'semester', title:'Course planner',
    body:'Map the degree, not just the term. Prerequisites carry across semesters.' },
] as const;

export const GALLERY_FILTERS = [
  { key:'all', label:'All screens' },
  { key:'learn', label:'Learn' },
  { key:'study', label:'Study' },
  { key:'together', label:'Together' },
  { key:'semester', label:'Semester' },
] as const;

/**
 * The /news index cards.
 *
 * Derived from the article table (#601): these used to be six hand-typed
 * literals carrying their own tag, `6/12/2026`-style date, read time and an
 * `assets/...` image path that /news had to remap. `body` rides along so the
 * search box can match the prose, not just the excerpt.
 */
export const NEWS_POSTS = JOURNAL_ARTICLES.map((article) => ({
  cat: article.cat,
  tag: article.tag,
  date: dateLabel(article.publishedAt),
  time: readTime(article.body),
  art: article.art,
  slug: article.slug,
  title: article.title,
  excerpt: article.deck,
  text: articleText(article.body),
}));

export const NEWS_FILTERS = [
  { key:'all', label:'All articles' },
  { key:'release', label:'Releases' },
  { key:'product', label:'Product' },
  { key:'perspective', label:'Perspective' },
  { key:'founding', label:'Founding' },
] as const;


/* ── Wiki ────────────────────────────────────────────────────────────────
 *
 * The page promises "every value here is the one the product actually
 * uses", so every number below is copied from the backend that serves it,
 * not from a product doc. The `src` note on each row is the file that owns
 * the value — if one of them moves, the row moves with it.
 *
 * A claim that could only be sourced from a doc is not here. The page is
 * worth less with a wrong definition on it than with a missing one.
 */

/** Wiki's own tier swatches. Warmer than the landing's XTIER — these sit on
 *  the paper palette, not the dark act ground, so they are deliberately
 *  distinct values rather than a shared token. */
const TIER = { mastered: '#3a7d4e', learning: '#c89b5e', struggling: '#b25855', unexplored: '#9a9a9a' };

/** Grouped, because a flat rail of sixteen entries is a wall. The groups
 *  mirror how the product is organised: learn, capture, the semester, the
 *  people, and you. */
export const WIKI_TOC = [
  { group:'Learn', items: [
    { title:'Knowledge graph', href:'#graph' },
    { title:'Mastery tiers', href:'#mastery' },
    { title:'How mastery moves', href:'#deltas' },
    { title:'Progress stats', href:'#progress' },
    { title:'Adaptive quizzes', href:'#quizzes' },
    { title:'Tutor modes', href:'#tutor' },
  ]},
  { group:'Capture', items: [
    { title:'Uploads', href:'#uploads' },
    { title:'Ingestion', href:'#ingestion' },
    { title:'Notetaker', href:'#notes' },
    { title:'Flashcards', href:'#flashcards' },
    { title:'Study guide', href:'#guide' },
  ]},
  { group:'Semester', items: [
    { title:'Syllabus and calendar', href:'#calendar' },
    { title:'Grade scale', href:'#grades' },
  ]},
  { group:'Together', items: [
    { title:'Study rooms', href:'#rooms' },
    { title:'Class intelligence', href:'#class' },
  ]},
  { group:'You', items: [
    { title:'Onboarding', href:'#onboarding' },
    { title:'Achievements', href:'#achievements' },
    { title:'Your data', href:'#privacy' },
  ]},
] as const;

export const WIKI_GRAPH_TERMS = [
  { term:'Node', def:'One concept in one course, carrying a mastery score from 0.00 to 1.00. Every concept you touch anywhere in Sapling resolves to a node.' },
  { term:'Course root', def:'The labelled hub at the centre of a course’s cluster. Every concept in the course wires back to it.' },
  { term:'Edge', def:'A link between two concepts, drawn at a thickness that follows its strength. Stored with a type — prerequisite, builds on, part of, or related — though the tree draws all four the same way today.' },
  { term:'Dedup', def:'“Linear Regression”, “linear regression” and a double-spaced copy all resolve to one node, so re-running an extract never splits a concept in two.' },
  { term:'Scope', def:'Your graph is yours, and it keys to the course rather than the section. Retake a course and your mastery carries over instead of resetting.' },
] as const;

/** backend/config.py::get_mastery_tier. The floors are MASTERY_MASTERED_MIN
 *  0.75 / MASTERY_LEARNING_MIN 0.45 / MASTERY_STRUGGLING_MIN 0.1 — the
 *  page had 0.40 and 0.01 before, which were nobody’s thresholds. */
export const WIKI_TIERS = [
  { name:'Mastered', range:'0.75 – 1.00', dot:'background:' + TIER.mastered + ';', meaning:'The top tier. Achievements that count mastered concepts count these.' },
  { name:'Learning', range:'0.45 – 0.74', dot:'background:' + TIER.learning + ';', meaning:'Partly there. Still eligible for the recommendations on your dashboard.' },
  { name:'Struggling', range:'0.10 – 0.44', dot:'background:' + TIER.struggling + ';', meaning:'Repeated misses. Quiz generation leans hardest on this tier.' },
  { name:'Unexplored', range:'0.00 – 0.09', dot:'background:' + TIER.unexplored + ';', meaning:'Planted but never demonstrated. Every new concept lands here at 0.00.' },
] as const;

/** The one arithmetic on the page. Quiz deltas are services/quiz_config.py
 *  MASTERY_DELTA_PER_CORRECT / _PER_WRONG; the tutor bound is the validated
 *  range on agents/tools/graph.py::MasteryUpdate.mastery_delta. */
export const WIKI_MASTERY_FORMULA = 'after = clamp(before + correct × 0.03 − wrong × 0.02, 0, 1)';

export const WIKI_MASTERY_MOVES = [
  { source:'Quiz answer', value:'+0.03 / −0.02', note:'Per question, right or wrong. Mastery is earned faster than it is lost, so a rough quiz dents progress without erasing it.' },
  { source:'Tutor turn', value:'−0.10 … +0.30', note:'The tutor proposes a change per concept and the range is enforced, so no conversation can hand you a mastered node.' },
  { source:'New concept', value:'0.00', note:'Whatever planted it — a document, a note, a tutor session — a concept arrives unexplored. Extracting seeds your tree, it does not grade it.' },
  { source:'Flashcard rating', value:'no change', note:'Rating a card records the rating. It does not write to the concept the card tests.' },
  { source:'Assignment score', value:'no change', note:'Your gradebook tracks the grade on your transcript. It runs alongside your graph rather than into it.' },
] as const;

export const WIKI_PROGRESS_TERMS = [
  { term:'Mastery event', def:'Every change is appended as a timestamped delta with a reason, never written over a running total. Your graph keeps the whole history of how a concept moved.' },
  { term:'Streak', def:'Consecutive UTC calendar days with study activity. Any activity counts once; miss a day and it restarts at 1.' },
  { term:'Learning velocity', def:'Mastery gained per day across the last 14 days, counting gains only. A node with no recent events reads 0.' },
  { term:'Times studied', def:'How many study actions have touched a concept. It ticks up whether the action moved mastery or not.' },
] as const;

/** services/quiz_config.py, which exists so the client builds its selectors
 *  from GET /api/quiz/config and can never offer a value the route rejects. */
export const WIKI_QUIZ_SPECS = [
  { label:'Length', value:'3, 5, or 10', note:'Ten is a hard ceiling, not a preference: the model rejects a longer structured request outright.' },
  { label:'Difficulty', value:'Easy · Medium · Hard · Adaptive', note:'Adaptive hands the choice to the generator, which picks each question’s level and reports back the mix it settled on.' },
  { label:'Question type', value:'Multiple choice', note:'The only type today. Grading is an exact match against the correct option, never an interpretation.' },
  { label:'Generation limit', value:'8 per 5 minutes', note:'Sized for a person comparing difficulties or retaking a concept, not for a loop.' },
  { label:'Generation timeout', value:'90 seconds', note:'Past this you are told to try again rather than left on a spinner.' },
  { label:'Abandoned after', value:'24 hours', note:'A quiz is one sitting. An attempt left open longer stops being offered as resumable.' },
] as const;

export const WIKI_MODES = [
  { name:'Socratic', def:'Leads with the question that gets you to the answer yourself. The default, and the mode every Learn this and Explain this link opens in.' },
  { name:'Expository', def:'Explains the concept directly, grounded in the material you uploaded for that course.' },
  { name:'TeachBack', def:'You do the explaining and it plays the student, naming the step you skipped.' },
] as const;

/** routes/documents.py: ALLOWED_EXTENSIONS and MAX_FILE_SIZE. */
export const WIKI_UPLOAD_SPECS = [
  { label:'File types', value:'PDF · DOCX · PPTX', note:'Anything else is refused at upload. Photos and images are not accepted here.' },
  { label:'Size limit', value:'100 MB', note:'Per file. A larger one is rejected before any processing starts.' },
  { label:'Text extraction', value:'Docling, then Tesseract', note:'A layout-aware pass first, falling back to plain OCR. A clean digital PDF reads better than a scan, and a scan better than handwriting.' },
  { label:'Retries', value:'Processed once', note:'An upload that gets retried — a flaky connection, a second tap — is recognised as the same request and not run through the pipeline again.' },
] as const;

/** The five progress events the upload actually streams over SSE
 *  (routes/documents.py). The old four-step copy described a chunking stage
 *  and a flashcard fan-out that no upload has ever performed. */
export const WIKI_PIPELINE = [
  { num:'01', title:'Extract text', body:'The file is read page by page, with OCR where the page is an image rather than text.' },
  { num:'02', title:'Classify', body:'Sapling works out what it is holding — a syllabus, a lecture deck, a reading — and writes a short summary.' },
  { num:'03', title:'Extract concepts', body:'Every concept named in the material is pulled out, along with the notes backing it.' },
  { num:'04', title:'Update graph', body:'Those concepts are merged onto your tree as new unexplored nodes, deduplicated against what is already there.' },
  { num:'05', title:'Finalise', body:'The document lands in your library with its summary and concept list attached. A syllabus also goes on to produce assignments and dates.' },
] as const;

export const WIKI_NOTE_SPECS = [
  { label:'Autosave', value:'800 ms', note:'Typing settles, then the note saves. Switching notes or closing the tab flushes it immediately.' },
  { label:'Summarise', value:'2 – 4 sentences', note:'Faithful to what you wrote, including the questions you left yourself. A near-empty note is told it is near-empty rather than embellished.' },
  { label:'Extract concepts', value:'up to 15', note:'Title-Case ideas only — not assignment titles or page numbers. Each is merged onto your graph and linked back to the note.' },
  { label:'Generate quiz', value:'weakest linked concept', note:'Picks the lowest-mastery concept linked to the note. Needs at least one link before it will run.' },
] as const;

/** routes/flashcards.py::rate_card writes times_reviewed, last_rating and
 *  last_reviewed_at — and nothing else. The section this replaced published
 *  10 min / 1 day / 4 day intervals for a scheduler that does not exist. */
export const WIKI_FLASHCARD_RATINGS = [
  { label:'Forgot', key:'1', tone:'color:' + TIER.struggling + ';' },
  { label:'Hard', key:'2', tone:'color:' + TIER.learning + ';' },
  { label:'Easy', key:'3', tone:'color:' + TIER.mastered + ';' },
] as const;

export const WIKI_FLASHCARD_NOTES = [
  'A rating is recorded against the card: your latest rating, the time, and one more on its review count.',
  'There is no review schedule yet. A card you forgot does not come back sooner than one you found easy — you choose what to study.',
  'Generating a deck reads the concepts you are weakest on. Studying one does not write back to them.',
] as const;

export const WIKI_GUIDE_SPECS = [
  { label:'Built from', value:'Your document library', note:'The summaries and concept notes from what you uploaded for that course. Not from your graph — a guide does not yet lean harder on your weak concepts.' },
  { label:'Scope', value:'Per course, per exam', note:'Saved once generated, so coming back to it is instant.' },
  { label:'Regenerate', value:'On demand', note:'Rebuilds from scratch, which is what you want after adding material.' },
] as const;

export const WIKI_CALENDAR_SPECS = [
  { label:'From a syllabus', value:'Assignments, dates, weights', note:'You review what was found before it saves. Due dates come through only where the syllabus states them plainly.' },
  { label:'Re-upload', value:'Deduplicated', note:'An updated syllabus will not double your assignment list.' },
  { label:'Grading categories', value:'Into your gradebook', note:'The weight buckets a syllabus names — Exams 40%, Homework 20% — seed the categories your grade is computed from.' },
  { label:'Google Calendar', value:'Import, sync, export', note:'Optional, and disconnectable. Sapling can also suggest study blocks around what is due.' },
] as const;

/** services/gradebook_service.py::DEFAULT_LETTER_SCALE, all twelve bands.
 *  The page previously stopped at D and skipped D+ / D− entirely. */
export const WIKI_LETTERS = [
  { letter:'A', min:'≥ 93' }, { letter:'A−', min:'≥ 90' },
  { letter:'B+', min:'≥ 87' }, { letter:'B', min:'≥ 83' }, { letter:'B−', min:'≥ 80' },
  { letter:'C+', min:'≥ 77' }, { letter:'C', min:'≥ 73' }, { letter:'C−', min:'≥ 70' },
  { letter:'D+', min:'≥ 67' }, { letter:'D', min:'≥ 63' }, { letter:'D−', min:'≥ 60' },
  { letter:'F', min:'< 60' },
] as const;

export const WIKI_GRADE_NOTES = [
  'A category scores as points earned over points possible, after any dropped lowest. Your course grade is the weighted average across categories.',
  'The bands above are the default. You can set your own per course, because your professor’s A− might start at 92, and a curve can be applied on top.',
  'Letters roll up to the standard 4.0 scale for a term GPA: A and A+ are 4.0, A− 3.7, B+ 3.3, down to F at 0.0.',
] as const;

export const WIKI_ROOM_SPECS = [
  { label:'Joining', value:'Invite or public', note:'Join a room you were pointed at, or browse the public ones.' },
  { label:'Messages', value:'Reply, edit, delete, react', note:'Yours to edit or delete. The room also keeps an activity feed of what has been happening.' },
  { label:'Overview', value:'Shared concepts only', note:'What the room sees of you is your mastery on concepts you have in common — never your notes, documents, or grades.' },
  { label:'Matching', value:'In-room or school-wide', note:'Suggests partners by where their graph is strong and yours is not.' },
] as const;

export const WIKI_CLASS_TERMS = [
  { term:'What it is', def:'A per-class rollup of the concepts people commonly get wrong, aggregated across students with no names attached.' },
  { term:'Where it lands', def:'Quiz generation reads it, and the misconceptions become the tempting wrong answers. That is the whole of its reach today.' },
  { term:'What it is not', def:'There is no screen for it. It is plumbing meant to make your quizzes sharper, not a dashboard about your class.' },
] as const;

export const WIKI_ONBOARDING_SPECS = [
  { label:'Sign-in', value:'Google, domain-gated', note:'Gated to a school email domain — bu.edu by default.' },
  { label:'Asked once', value:'Year, majors, learning style', note:'Learning style is stored, but it does not shape the tutor much yet.' },
  { label:'Courses', value:'From the catalog', note:'Searched by name or code, then enrolled into the current term.' },
] as const;

export const WIKI_ACHIEVEMENT_TERMS = [
  { term:'Trigger', def:'Each achievement watches one real number — quizzes completed, cards reviewed, concepts mastered, login streak, rooms joined. Nothing is awarded for time logged.' },
  { term:'Cosmetics', def:'Four equippable slots: avatar frame, banner, name colour, and title. You unlock them through achievements or through a role you hold.' },
  { term:'Featured', def:'You choose which achievements and which role show on your public profile.' },
] as const;

/** services/encryption.py. Stated precisely, per the brand guide’s rule
 *  that privacy claims name what is true today rather than implying
 *  blanket encryption. */
export const WIKI_DATA_FACTS = [
  { fact:'Sensitive columns are encrypted at rest with AES-256-GCM — a fresh random nonce for every value, and a tag that makes tampering detectable.',
    detail:'Encrypted: your name and bio, your email, tutor and study-room messages, note titles and bodies, document summaries and extracted text, assignment points and notes, quiz questions and answers, flashcard fronts and backs.' },
  { fact:'Some things are deliberately not encrypted, and you should know which.',
    detail:'Concept names and mastery scores, note tags, your username and cosmetics, and generated study-guide text are stored in plain form. Access to them is scoped to you rather than hidden by encryption — so keep anything sensitive out of a tag.' },
  { fact:'Your material builds your graph and your study tools. It is never sold, and never used to train outside models.',
    detail:'Text is decrypted server-side, in flight, only to build the prompt for a study action you asked for.' },
  { fact:'Deleting a document removes it from your library, but the concepts it planted stay on your tree.',
    detail:'That is on purpose — they are yours now, and you may have studied them since. Remove one from the tree itself, where a node can be deleted directly.' },
  { fact:'You can export everything Sapling holds on you, or delete your account outright.',
    detail:'Both live in your profile settings.' },
] as const;

/**
 * Product screenshots, keyed by wiki section id.
 *
 * The files are the twelve `/gallery/<slot>.png` captures at 1440x900 — the
 * same set the gallery uses, so this page borrows them rather than owning
 * any. Nothing new goes in `public/gallery/`: the orphan check in
 * gallery.test.ts pins that directory to exactly the GALLERY_SHOTS slots.
 *
 * `title` names the screen: it heads the expanded view and becomes the alt
 * on the expanded image, which has no caption beside it. The names are
 * GALLERY_SHOTS' verbatim, so a screen is called the same thing on both
 * surfaces.
 *
 * `caption` is rendered as a visible figcaption and the thumbnail carries
 * `alt=""`, the same split the gallery uses. That is what keeps a capture
 * that has not landed yet from painting alt text and a broken-image glyph
 * across the panel.
 *
 * Two slots have no row here on purpose. `shot-tree` would otherwise appear
 * twice in adjacent sections, which reads as a mistake rather than a
 * reference; it stays on the graph section, and mastery tiers goes without.
 * `shot-planner` is a screenshot of a "Coming soon" panel — a reference page
 * has nothing to define about a screen that does not exist yet.
 */
export const WIKI_SHOTS: Record<string, { slot: string; route: string; title: string; caption: string }> = {
  graph: { slot:'shot-tree', route:'/tree', title:'Knowledge graph',
    caption:'The knowledge tree: concept nodes joined by edges, each ringed to show its mastery.' },
  quizzes: { slot:'shot-quiz', route:'/quiz', title:'Adaptive quiz',
    caption:'An adaptive quiz mid-session, showing a multiple-choice question and its difficulty.' },
  tutor: { slot:'shot-learn', route:'/learn', title:'AI tutor',
    caption:'The tutor answering in Socratic mode, leading with a question rather than an answer.' },
  ingestion: { slot:'shot-library', route:'/library', title:'Library',
    caption:'The document library, listing uploads beside the summary and concepts each produced.' },
  notes: { slot:'shot-notetaker', route:'/notetaker', title:'Notetaker',
    caption:'The notetaker with a note open and its generated summary in the side rail.' },
  flashcards: { slot:'shot-study', route:'/study', title:'Flashcard review',
    caption:'A flashcard mid-review with its three rating buttons.' },
  guide: { slot:'shot-guide', route:'/study', title:'Study guide',
    caption:'A generated study guide for one course, laid out in sections.' },
  calendar: { slot:'shot-calendar', route:'/calendar', title:'Calendar',
    caption:'The calendar, showing assignments and dates extracted from a syllabus.' },
  grades: { slot:'shot-gradebook', route:'/gradebook', title:'Gradebook',
    caption:'A course gradebook showing weighted categories and the resulting letter grade.' },
  rooms: { slot:'shot-social', route:'/social', title:'Study rooms',
    caption:'A study room with its chat thread beside the room member list.' },
  achievements: { slot:'shot-achievements', route:'/achievements', title:'Achievements',
    caption:'The achievements screen showing earned milestones and a study streak.' },
};
