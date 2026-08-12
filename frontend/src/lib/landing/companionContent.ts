/**
 * Copy for the six companion pages.
 *
 * Lifted verbatim from the sibling `.dc.html` design components, where it
 * lives as plain JS object literals. Content only -- no markup, no styling.
 */

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
      ] as const;

export const TEAM_WAYS = [
        'We use Sapling for our own courses before anyone else sees a feature. If it does not help us pass, it does not ship.',
        'Every feature has to feed the graph. A tool that knows nothing about what you already understand is a tool we would not add.',
        'We read every piece of beta feedback ourselves. There is no support queue between you and the four of us.',
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

export const NEWS_POSTS = [
  { cat:'founding', tag:'Founding', date:'6/12/2026', time:'6 MIN', slot:'news-founding', src:'assets/journal-founding.png',
    title:'Why we built Sapling',
    excerpt:'Four students, one library table, and a nagging question: what if AI made you understand more, not less? The origin story, missteps included.' },
  { cat:'perspective', tag:'Perspective', date:'5/04/2026', time:'4 MIN', slot:'news-homework', src:'assets/journal-ai-homework.png',
    title:'AI shouldn\u2019t do your homework',
    excerpt:'Our line in the sand on AI and education: guidance over answers, process over shortcuts, and why "just give me the solution" is the wrong deal.' },
  { cat:'product', tag:'Product', date:'4/18/2026', time:'7 MIN', slot:'news-graph', src:'',
    title:'How the knowledge graph works',
    excerpt:'Nodes, edges, and mastery scores: how a semester of studying becomes a living map, and why the cross-unit edges matter most.' },
  { cat:'release', tag:'Release', date:'3/22/2026', time:'3 MIN', slot:'news-teachback', src:'',
    title:'TeachBack is live',
    excerpt:'The mode that flips the desk. You explain the concept, Sapling names the step you skipped, and mastery counts for more than reading.' },
  { cat:'product', tag:'Research', date:'2/09/2026', time:'5 MIN', slot:'news-spacing', src:'',
    title:'What spacing actually buys you',
    excerpt:'Why ten minutes, one day, and four days are the intervals we shipped, and what happened when we tested longer gaps on our own courses.' },
  { cat:'release', tag:'Release', date:'1/06/2026', time:'2 MIN', slot:'news-calendar', src:'',
    title:'Syllabus to semester in one upload',
    excerpt:'Calendar extraction went from a manual paste to a single drop. Every exam, pset, and quiz dated and synced before week one is over.' },
] as const;

export const NEWS_FILTERS = [
  { key:'all', label:'All articles' },
  { key:'release', label:'Releases' },
  { key:'product', label:'Product' },
  { key:'perspective', label:'Perspective' },
  { key:'founding', label:'Founding' },
] as const;

/** Wiki's own tier swatches. Warmer than the landing's XTIER — these sit on
 *  the paper palette, not the dark act ground, so they are deliberately
 *  distinct values rather than a shared token. */
const TIER = { mastered: '#3a7d4e', learning: '#c89b5e', struggling: '#b25855', unexplored: '#9a9a9a' };

export const WIKI_TOC = [
        { title:'Knowledge graph', href:'#graph' },
        { title:'Mastery tiers', href:'#mastery' },
        { title:'Spaced review', href:'#review' },
        { title:'Tutor modes', href:'#tutor' },
        { title:'Ingestion', href:'#ingestion' },
        { title:'Grade scale', href:'#grades' },
        { title:'Your data', href:'#privacy' },
      ] as const;

export const WIKI_GRAPH_TERMS = [
        { term:'Node', def:'A single concept, such as AVL rotations. Its radius grows with how central it is to the course.' },
        { term:'Edge', def:'A prerequisite link. Recursion feeds trees, dynamic programming, and graph traversal, so it carries three edges out.' },
        { term:'Cross-unit edge', def:'An edge between two different units. Drawn fainter, and the most common cause of a surprise on an exam.' },
        { term:'Class node', def:'The hub at the centre of the graph. It represents the course itself and connects to every unit root.' },
      ] as const;

export const WIKI_TIERS = [
        { name:'Mastered', range:'0.75 \u2013 1.00', dot:'background:' + TIER.mastered + ';', meaning:'You have demonstrated it more than once. Quizzes spend few questions here.' },
        { name:'Learning', range:'0.40 \u2013 0.74', dot:'background:' + TIER.learning + ';', meaning:'Partly there. Reviews are scheduled and the tutor still probes it.' },
        { name:'Struggling', range:'0.01 \u2013 0.39', dot:'background:' + TIER.struggling + ';', meaning:'Repeated misses. Study guides weight this concept the heaviest.' },
        { name:'Unexplored', range:'0.00', dot:'background:' + TIER.unexplored + ';', meaning:'Seen in your documents but never practised. No score yet.' },
      ] as const;

export const WIKI_RATINGS = [
        { label:'Forgot', key:'1', due:'10 min', tone:'color:' + TIER.struggling + ';' },
        { label:'Hard', key:'2', due:'1 day', tone:'color:' + TIER.learning + ';' },
        { label:'Easy', key:'3', due:'4 days', tone:'color:' + TIER.mastered + ';' },
      ] as const;

export const WIKI_MODES = [
        { name:'Socratic', def:'Asks the question that gets you to the answer yourself, and escalates its hints only when you stall.' },
        { name:'Expository', def:'Explains the concept directly, structured and cited back to the specific pages it came from.' },
        { name:'TeachBack', def:'You explain the concept and it names the step you skipped. Mastery gained here is worth more than reading.' },
      ] as const;

export const WIKI_PIPELINE = [
        { num:'01', title:'Read', body:'Text is extracted page by page, including OCR for scans and photos of handwritten notes.' },
        { num:'02', title:'Chunk', body:'The document is split by type. A syllabus is split by week, a lecture deck by slide, so context stays intact.' },
        { num:'03', title:'Scan concepts', body:'Every concept named in the material becomes a node, joined to the concepts it depends on.' },
        { num:'04', title:'Fan out', body:'The same pass produces flashcards, quiz questions, and dated calendar entries, all pointing back at their source.' },
      ] as const;

export const WIKI_LETTERS = [
        { letter:'A', min:'\u2265 93' }, { letter:'A\u2212', min:'\u2265 90' },
        { letter:'B+', min:'\u2265 87' }, { letter:'B', min:'\u2265 83' }, { letter:'B\u2212', min:'\u2265 80' },
        { letter:'C+', min:'\u2265 77' }, { letter:'C', min:'\u2265 73' }, { letter:'C\u2212', min:'\u2265 70' },
        { letter:'D', min:'\u2265 60' }, { letter:'F', min:'< 60' },
      ] as const;

export const WIKI_DATA_FACTS = [
        'Uploads, notes, and messages are encrypted at rest with AES-256.',
        'Your material is used to build your graph and study tools, and is never sold or used to train outside models.',
        'Delete a document and the concepts, cards, and dates derived from it go with it.',
      ] as const;
