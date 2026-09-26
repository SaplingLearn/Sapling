# CONTEXT (not research): Sapling today, from code audit at main@855155f

Sapling Learning Engine 

 Sapling backend · as of 2026-09-26, main @ 855155f 
 What the AI does when a student learns 
 Sapling has four places where a student meets the AI: the Library, the tutor, quizzes and notes. All four feed one knowledge graph through a single write function. Each concept in that graph has a mastery score. That graph is the "learning system". There is no separate learner model, scheduler or memory beyond it. 

 1 · The whole loop 

 [diagram omitted]

 Green arrows are writes that change what Sapling thinks the student knows. All of them go through services/graph_service.py::apply_graph_update . Grey arrows write side tables. Red text marks output that is written but never fed back into learning. 

 2 · Inside one tutor turn 
 This is the path most students hit most often. The tutor gets no memory beyond what is shown here. Everything in the middle column is rebuilt on every message. 

 [diagram omitted]

 Code: routes/learn.py (routes, _prepare_chat_run ), services/chat_stream.py (streaming), agents/chat_tutor.py (three mode agents, hard-coded prompt), agents/tools/ (tools). The size of the mastery change is the model's own judgment of the turn. 

 3 · Who reads what 
 The tutor, the quiz and note chat each see a different slice of what Sapling knows about the student. The gaps are the clearest places to start a redesign. 

 Signal Tutor Quiz agent Note chat 

 course_chunks (vector RAG) Yes injected, top 5 Yes No 
 documents (keyword search) Yes tool No Yes tool 
 Graph concepts + mastery Yes injected + tools Yes tool No writes only 
 Class misconceptions No excluded on purpose, ADR 0023 §5 Yes tool No 
 quiz_context (per-student weak areas) No Yes No 
 Past session summaries No No No only flashcards read them 
 Note content No send-to-tutor sends topic only No Yes active note 
 Recently asked questions No Yes do-not-repeat block + re-serve misses No 

 How mastery moves 

 Tutor: the model picks a change between −0.1 and +0.3 per concept per turn. No rubric checks its choice. 
 Quiz: +0.03 per correct answer, −0.02 per wrong one. The change doesn't depend on quiz length or difficulty. Grading is exact string match on the server. 
 Uploads and notes: add concepts at mastery 0. They never change existing scores. 
 Tiers: 0.1, 0.45 and 0.75 ( config.py ). 
 No decay, no forgetting curve, no review schedule. The only spaced-repetition-like behaviour is the quiz's do-not-repeat list and re-serving missed items. 

 How the Library feeds it 

 An upload is OCR'd (Docling by default) and classified. Then summary, concept and syllabus agents run in parallel. 
 Concepts go to the graph for every document type. architecture.md says syllabus and assignment only, which is out of date. 
 The text is cut into ~200-word chunks, embedded with gemini-embedding-001 , and stored in course_chunks . A background sweeper retries failed indexing. 
 A chunk is shared with the class only for course material that the uploader agreed to share. Everything else stays private to the uploader. 
 The Library screen itself is a document list with search, backed by the documents API. It has no separate backend. 

 4 · Where a redesign would press 
 Most of these are already filed under the AI-system redesign tracker #643 . 

 The tutor has two retrieval paths: vector RAG in the prompt and keyword search as a tool. The two paths don't know about each other. #631 
 RAG searches with the raw message, so a follow-up like "why?" retrieves poorly. #633 #634 
 Chat history is unbounded, and a tool re-reads it. #638 Context is rebuilt on every turn with no caching. #639 
 Model choice is a sticky UI toggle rather than a per-turn decision. #640 
 Nothing learned in one session carries into the next except the mastery numbers. Summaries are scraped rather than written by the model, and they are never read back. 
 The quiz knows the student's weak areas. The tutor doesn't. 
 Notes aren't indexed for retrieval, and nothing measures retrieval quality. #483 
 The shared corpus is nearly empty: 31 chunks in production, all on one course. #645 
 Evals exist in backend/tests/evals/ , but they check reply shape and tool use, not whether the student learned. 

 Code at 855155f was checked against the docs. docs/architecture.md is stale in three places. It claims the tutor gets cached course context (it doesn't). It says only syllabi and assignments add concepts (every document type does). It still describes a <graph_update> tag, which tool calls have replaced.