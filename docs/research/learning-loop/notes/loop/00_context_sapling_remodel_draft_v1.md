# CONTEXT (not research): first-draft remodel diagram (12 nodes, 25 arrows)

Sapling Learning Loop Proposal 

 Proposal · not built · 2026-09-26 
 A learning loop for Sapling 
 This is a proposed design, not how Sapling works today. The center of it is a learner model per student and per concept. It is fed only by graded evidence, and it drives what the tutor teaches next, what gets reviewed and when. Every node has an ID, and every arrow has a number, listed in the table below the diagram. 

 Learning loop: evidence in, knowledge estimate out 
 What the student sees and does 
 Content and context 

 [diagram omitted]

 Read it left to right: content comes in and becomes a course map. The planner and context builder use the course map and the learner model to run a tutor session. The session's graded checks flow back down through the grader and the evidence recorder into the learner model. The green arrows are that loop. The small curved arrow inside N10 is the per-step teach-then-check cycle. 

 Every arrow, in order 
 Shaded rows are the learning loop. That is the only path by which Sapling's estimate of what a student knows can change. 

 # From → To What flows 

 1 Syllabus → N1 Course goals, topic list and schedule. These set each student's default goal. 
 2 Library → N1 Uploaded course materials. 
 3 Notes → N1 The student's notes, now indexed like documents. 
 4 N1 → N3 Concepts and proposed prerequisite edges, checked before they join the map. 
 5 N1 → N2 Chunks and embeddings, each tagged with who may see it. 
 6 N3 → N8 Which concepts depend on which. 
 7 N5 → N8 Where this student's edge is on each concept, plus their goal. 
 8 N8 → N10 An ordered path for this session, which the student approves in phase 2. 
 9 N8 → Dashboard The single next step to show the student. 
 10 N2 → N9 Passages that match the current step, with citations. 
 11 N5 → N9 A short learner brief: edge, open misconceptions, last session's outcome, reviews due, the note the student sent. 
 12 N4 → N9 Mistakes common in this class, only for groups of 5 or more. 
 13 N9 → N10 Bounded context for each turn, rebuilt only when the step changes. 
 14 N10 → Student One reasoning step at a time, with a check after each step. 
 15 Student → N10 Messages, answers and the reasoning behind them, plus teach-backs. 
 16 N10 → N11 Each check's answer and reasoning, to be graded. 
 17 N11 → N6 Graded evidence. A free-text answer weighs more than a multiple-choice guess. 
 18 N10 → N6 The end-of-session summary and low-weight observations from the chat. 
 19 N6 → N5 Updated knowledge estimate, edge and misconceptions. 
 20 N5 → N4 Anonymous rollup of misconceptions across the class. 
 21 N6 → N12 A new review date for every concept that was touched. 
 22 N12 → Review quiz Concepts due for review. 
 23 N12 → Flashcards Facts and vocabulary due for review. 
 24 Review quiz → N11 Review answers go through the same grader, so reviews count as evidence too. 
 25 N6 → N7 The event log, used to measure whether students actually learn. 

 What each node replaces 

 Node Today Change Related 

 N1 Ingest Upload pipeline, concepts at mastery 0 Also proposes prerequisite edges; notes go through it too #483 
 N2 Retrieval index Two paths: vector RAG and keyword search One hybrid path, query rewriting, citations #631 #633 #634 #635 
 N3 Course map graph_nodes / graph_edges per student; prerequisite edges unused A shared, per-course map of concepts and prerequisites new 
 N4 Class patterns Class misconceptions, quiz-only, data empty Feeds the tutor, only above the n ≥ 5 floor #558 
 N5 Learner model One mastery number moved by the model's own judgment Knowledge tracing, a bracketed edge, misconceptions, review date, goal new 
 N6 Evidence recorder apply_graph_update + node_mastery_events Same single write path; evidence weighted by grading type extends today's 
 N7 Outcome eval Evals check reply shape Measures learning gain per concept new 
 N8 Planner Five lowest-mastery nodes A path over prerequisites, toward the course goal new 
 N9 Context builder _prepare_chat_run , full history, same every turn Short learner brief, cached, rebuilt when the step changes #638 #639 
 N10 Tutor session Three modes, no phases Probe → plan → teach/check loop → close new 
 N11 Grader Quiz exact-match grading only Also grades free text and teach-back against a rubric, inside chat extends today's 
 N12 Scheduler None Spaced review queue that drives the review quiz and flashcards new 

 Suggested build order 

 Send note content to the tutor, and write a real end-of-session summary (arrows 3, 11, 18). This is the cheapest fix. 
 Add a graded check tool to the tutor, with evidence weights (arrows 14–19). 
 Replace the mastery number with the learner model (N5), and connect the scheduler (N12). 
 Add the context builder's learner brief and caching (N9). 
 Build the course map with prerequisite edges and the planner (N3, N8). 
 Add the probe phase, seeded from quiz history and the syllabus. 
 Add class patterns once the n ≥ 5 floor exists, and build the outcome eval from day one of step 2. 

 The ideas come from three places: the code audit of main @ 855155f , the "How I Use AI to Learn Things" system (probe → plan → teach), and 417 viewer comments on that video. The comments mostly contributed spaced review, free-text and teach-back grading, goals set by the course, grounding in real sources, and measuring learning outcomes. Model and method choices (for example Bayesian knowledge tracing versus a forgetting-curve model) are open research questions.