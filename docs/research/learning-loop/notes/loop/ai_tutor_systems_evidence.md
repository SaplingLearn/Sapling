# Building Effective AI / Intelligent Tutoring Systems: Evidence Brief (classic ITS → LLM tutors, 2023–2026)

Scope note: classic-ITS results are older (2005–2016); LLM-tutor results are 2024–2026. Every effect size is tagged with study design and sample size where the source gave it. "Vendor" flags a company-run or company-funded claim. Research date: 2026-09-26.

---

## KQ1. Which design features are backed by RCTs / strong quasi-experiments, with what effect sizes? Which are only vibes?

### Takeaway
Step-level tutoring (feedback + hints on each step of a multi-step problem, with mastery-based problem selection) is the one architecture with decades of replicated evidence (d ≈ 0.76 vs no tutoring; ≈ 0.2 in at-scale school RCTs). For LLM tutors, three well-powered 2024–2025 field experiments agree on one thing: the *guardrailed, content-grounded* tutor (teacher-authored solutions + hint-not-answer prompting + sequential scaffolding) produces real learning, while the unguarded chatbot produces performance without learning. Feature-level claims for LLM tutors (Socratic questioning, growth-mindset phrasing, metacognitive prompts) are still mostly measured by rater preference, not learning outcomes.

### Cited Findings

**Classic ITS (pre-LLM) — what the effect sizes actually are**
- VanLehn's 2011 review: human tutoring d = 0.79, intelligent tutoring systems d = 0.76 vs no tutoring — ITS "nearly as effective as human tutoring." Prior field belief (0.3 answer-based / 1.0 ITS / 2.0 human) was not confirmed. Systems classified by interaction granularity: answer-based, step-based, substep-based; most ITS are step- or substep-based. — [VanLehn 2011, Educational Psychologist (ERIC)](https://eric.ed.gov/?id=EJ946764); [tandfonline](https://www.tandfonline.com/doi/abs/10.1080/00461520.2011.611369)
- Cognitive Tutor Algebra I at scale (Pane et al. 2014, RAND, school-level RCT): no effect in year 1; in year 2 high schools using it scored significantly higher, standardized effect ≈ 0.2 (50th → 58th percentile). — [RAND](https://www.rand.org/pubs/external_publications/EP50410.html); [EEPA](https://journals.sagepub.com/doi/abs/10.3102/0162373713507480)
- ASSISTments Maine homework RCT (Roschelle et al. 2016): g = 0.18 SD (t(20)=2.992, p=0.007), ≈ 60% improvement over the expected annual 7th-grade math gain. Replication RCT in North Carolina funded by Arnold Ventures. — [SRI](https://www.sri.com/publication/education-learning-pubs/digital-learning-pubs/how-big-is-that-reporting-the-effect-size-and-cost-of-assistments-in-the-maine-homework-efficacy-study/); [Social Programs That Work](https://evidencebasedprograms.org/programs/assistments/)
- ALEKS: one RCT (~2,500 students) found no significant effect on end-of-course algebra exam; a separate Ecuador RCT found a large, marginally significant reduction in course repetition and large positive math test effects — evidence mixed. — [IES ALEKS efficacy award](https://ies.ed.gov/use-work/awards/efficacy-aleks-improving-student-algebra-achievement?ID=1518); [Ecuador working paper](https://ideas.repec.org/p/wbk/wbrwps/10483.html)
- AutoTutor (natural-language dialogue tutor): average gains between 0.3σ (Nye et al. 2014 review) and 0.8σ (Graesser et al. 2008) vs reading text for equal time; larger vs pre-test/no-study controls. — [Nye, Graesser & Hu 2014 (ERIC)](https://files.eric.ed.gov/fulltext/ED586834.pdf); [Graesser, "Conversations with AutoTutor Help Students Learn"](https://link.springer.com/article/10.1007/s40593-015-0086-4)
- Andes physics tutor (VanLehn et al. 2005): reported effect sizes "in the neighborhood of σ = 1.0" region for ITS in the authors' framing; Andes replaced paper homework, with step-level immediate feedback and hints. — [Andes: Lessons Learned](https://journals.sagepub.com/doi/abs/10.3233/IRG-2005-15(3)02)
- Koedinger & Aleven 2007 "assistance dilemma": withholding more than needed → frustration/wasted time; giving more than needed → shallow learning and low motivation. Cognitive Tutor's answer: withhold solution info initially, then add interactively and only as needed via yes/no feedback, explanatory hints, dynamic problem selection. Optimal assistance depends on learner characteristics; not predictable a priori yet. — [Koedinger & Aleven 2007, Ed Psych Review](https://link.springer.com/article/10.1007/s10648-007-9049-0)

**LLM tutors — field experiments with learning outcomes**
- Bastani et al. (PNAS 2025; SSRN 2024) "Generative AI without guardrails can harm learning": ~1,000 students, ~50 classes, grades 9–11, one high school in Turkey, fall 2023–24, four 90-min math sessions (~15% of semester). Arms: control (notes/textbook), GPT Base (vanilla ChatGPT interface), GPT Tutor (GPT-4 with teacher-designed safeguards). Practice: GPT Base +48% (coef 0.137), GPT Tutor +127% (coef 0.361) vs control mean 0.284. Unassisted exam: GPT Base −17% (coef −0.054, p<0.05); GPT Tutor ≈ 0 (coef −0.004, n.s.) — harm removed, no positive effect. No significant heterogeneity by ability/resources/effort. — [PNAS](https://www.pnas.org/doi/10.1073/pnas.2422633122); [PMC full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC12232635/)
- Kestin et al. (Scientific Reports 2025) "AI tutoring outperforms in-class active learning": N = 194 Harvard intro-physics undergrads, crossover RCT over two consecutive weeks (surface tension; fluid flow). AI tutor median post-test 4.5 vs active-learning class 3.5; quantile-regression effect size 0.73–1.3 SD; Mann-Whitney p "below one in one hundred million"; AI condition took less time. — [Nature Sci Rep](https://www.nature.com/articles/s41598-025-97652-6); [ETCJ review with numbers](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/)
- Kestin design: GPT-4-0613 via API; system prompt promoted cognitive load management ("Keep responses BRIEF"), active engagement ("DO NOT give away the full solution"), growth mindset ("friendly, supportive… encourage them to try"); a prompt alone could not scaffold multi-part problems, so the platform walked students sequentially through each part with question-specific prompts and embedded expert-authored solutions; conversation quality pre-vetted. — [Research Square preprint](https://www.researchsquare.com/article/rs-4243877/v1); [Harvard Gazette](https://news.harvard.edu/gazette/story/2024/09/professor-tailored-ai-tutor-to-physics-course-engagement-doubled/)
- Tutor CoPilot (Wang, Demszky et al. 2024; Stanford/EdWorkingPaper 24-1054): first RCT of a human-AI tutoring system; 900 tutors, 1,800 K-12 students from underserved communities. Students of tutors with CoPilot +4 pp topic mastery (p<0.01); students of lower-rated tutors +9 pp. Tutors with CoPilot used more guiding questions and were less likely to give away answers. Cost ≈ $20/tutor/year. — [EdWorkingPapers](https://edworkingpapers.com/ai24-1054); [arXiv 2410.03017](https://arxiv.org/pdf/2410.03017v1)
- World Bank Nigeria (De Simone et al., Policy Research WP 11125, May 2025): RCT, ~800 first-year senior-secondary students, Edo State, June–July 2024, six weeks of after-school English sessions using Microsoft Copilot (GPT-4), teacher as "orchestra conductor" with structured prompts and end-of-session reflection. Overall assessment +0.31 SD; English +0.23 SD; framed as 1.5–2 years of business-as-usual schooling; outperformed ~80% of RCT-evaluated education interventions; dose-response (each extra day attended improved outcomes); largest gains for girls and higher-baseline students. — [World Bank doc](https://documents.worldbank.org/en/publication/documents-reports/documentdetail/099548105192529324); [ERIC](https://eric.ed.gov/?q=source:%22World+Bank%22&id=ED676624); [World Bank blog](https://blogs.worldbank.org/en/education/From-chalkboards-to-chatbots-Transforming-learning-in-Nigeria); [ICTworks summary](https://www.ictworks.org/genai-advance-learning-outcomes/)
- Nigeria caveats: no explicit control for extra time-on-task vs control; first weeks spent on digital literacy; power/connectivity problems; six-week horizon; no long-term follow-up. — [ICTworks](https://www.ictworks.org/genai-advance-learning-outcomes/)
- Khanmigo independent study (Journal of Teaching and Learning 2025): 69 undergrads, physics (Lunar Phases Concept Inventory pre/post), Khanmigo vs Google search vs paper-only: significant gains in all conditions, **no significant between-group difference**; students liked step-by-step guidance and saw it as supplementary. — [JTL 2025 (ERIC)](https://eric.ed.gov/?id=EJ1487444)
- Khan Academy (vendor, A/B tests, Oct 2025–Apr 2026, >15M tutoring threads): net +6.1% next-item correctness. Contributions: recent problem-history summaries +3.4%, surfacing prerequisite gaps +2.7%, 24-h in-session conversation logs +5.09% "cognitive engagement." No effect from example problem types or extra follow-up links. Monitors: no premature answer-giving before student submission, real-time math accuracy checks, active/constructive engagement levels. — [Khan Academy blog](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/) (vendor)
- Duolingo (vendor): "Explain My Answer" adopted by 65% of users, +15% course completion — completion, not learning; free to all since Jan 2026. — [Duolingo investor release](https://investors.duolingo.com/news-releases/news-release-details/duolingo-max-shows-future-ai-education) (vendor)
- A randomized experiment compared three theory-grounded LLM hint styles (Scaffolding, Socratic, Teacher-style) vs no-hint and teacher-authored baselines (AIED 2025). — [Springer](https://link.springer.com/chapter/10.1007/978-3-032-29794-5_60) (effect sizes not retrieved; see Gaps)

### Inferences
- The convergent pattern across Bastani (harm removed, not reversed), Kestin (large gain), Tutor CoPilot (+4–9 pp), and Nigeria (+0.23–0.31 SD): gains appear when the LLM is **grounded in instructor-authored solutions/curriculum**, **forced to scaffold step-by-step**, and **wrapped by a human or structured lesson**. The unguarded chatbot is the only configuration with measured harm.
- Kestin's ~1 SD is large relative to the 0.2 SD of school-scale ITS RCTs; plausible reasons are a short, tightly-controlled 1-week unit with expert-authored content and immediate post-test, so treat it as an upper bound, not a scale expectation.
- ITS history warns: the at-scale effect (0.2) is far smaller than lab effects (0.76–1.0). Expect the same shrinkage for LLM tutors.
- "Vibes" list (rater-preference or vendor-only evidence, no learning-outcome RCT): Socratic-only style per se, growth-mindset phrasing, metacognitive prompts, "encouraging tone," tool-use/RAG citations, Duolingo Explain My Answer, Study Mode / Learning Mode.

### Gaps
- Could not retrieve the AIED 2025 hint-style RCT's effect sizes (paywalled).
- Kestin engagement/motivation Likert numbers not retrieved from a fetchable source (Nature page redirected).
- No independent learning-outcome RCT located for Khanmigo beyond the 69-student null, nor for OpenAI Study Mode, Claude Learning Mode, Duolingo Max, or any "Bridge" tutor (no evaluation found under that name).

---

## KQ2. What failed or backfired (Bastani; over-reliance; sycophancy; answer-giving)?

### Takeaway
The dominant failure is "performance without learning": unguarded LLM access lifts practice scores and cuts study time, then lowers unassisted/delayed test scores. Mechanisms documented: students copy answers, models err (GPT-4 correct 51% of the time on the Turkish math problems), and models cave to student pressure (~14% pedagogical sycophancy for frontier models).

### Cited Findings
- Bastani et al.: GPT Base users mainly "ask for and copy solutions"; only a small fraction of GPT Base conversations were substantive help-seeking; GPT Tutor conversations were dominated by "Ask for Help" and "Attempted Answers." Students were "not aware of how generative AI can impede their learning." GPT-4 gave correct answers only 51% of the time on the practice problems (42% logical errors, 8% arithmetic errors), with large problem-specific variation. — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12232635/)
- Rismanchian et al. 2026 (working paper, not peer reviewed) "Faster Completion, Less Learning": 10-year panel of 3.2M ALEKS interactions + ALEKS PPL placement data; diff-in-diff using AI-susceptible text word problems vs graph-manipulation problems. Post-ChatGPT learning time on susceptible problems fell 2.8%/quarter for college students (−26.9% over 11 quarters; high school −31.3%; middle school −9.0%; grade 5 none). Odds of correct response on randomly assigned **proctored** retention items fell 25% cumulatively, while non-proctored scores rose (opposite sign). Term: "cognitive surrender." — [arXiv 2605.21629](https://arxiv.org/abs/2605.21629); [Hechinger summary](https://hechingerreport.org/proof-points-ai-eroding-math-skills/)
- Pedagogical sycophancy benchmark EduFrameTrap (2026): 360 trap families, 3,240 dialogues, six STEM domains; measures whether a tutor retreats from a correct correction under student pressure. GPT-5.2 sycophancy 14.2%, Claude 4.5 14.0%. Pressure profile differs: GPT-5.2 worst under authority appeals (16.8%) and social-affective pressure (18.1%); Claude 4.5 worst under context-switch jargon (17.9%). "Reasoning–sycophancy paradox": stronger reasoning does not buy pressure resilience. — [arXiv 2605.14604](https://arxiv.org/html/2605.14604v1)
- LearnLM authors list sycophancy as a specific prompting failure mode; prompting produced "unreliable and inconsistent" pedagogy, motivating fine-tuning. — [arXiv 2407.12687](https://arxiv.org/html/2407.12687v3)
- Systematic review (Computers & Education: AI, 2025): high-frequency LLM use linked to cognitive offloading and over-reliance risks. — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2666920X25001699)
- Khan Academy (vendor) revamped Khanmigo after low student usage. — [The Learning Standard](https://thelearningstandard.org/news/khan-academy-revamps-ai-tutor-after-low-student-usage)
- Adversarial answer-leakage: a 2026 paper evaluates LLM tutors' robustness to student jailbreak-style requests for answers. — [arXiv 2604.18660](https://arxiv.org/pdf/2604.18660)
- Learning ≠ performance (Soderstrom & Bjork 2015): current performance is an unreliable guide to learning; learning is inferred only from delayed retention or transfer; desirable difficulties (spacing, interleaving, retrieval practice, delayed feedback) depress immediate performance and raise later retention. — [Perspectives on Psychological Science](https://journals.sagepub.com/doi/abs/10.1177/1745691615569000)

### Inferences
- Bastani's 51% GPT-4 accuracy on curriculum-specific math problems (2023 model) explains why the guardrailed arm bundled teacher-provided full solutions: the "hint not answer" rule is only safe if the tutor has a verified answer to hint toward.
- The ALEKS panel shows the harm also appears in a mature mastery-learning ITS when students bring an outside chatbot, so guardrails inside the product do not protect against uncontrolled outside use; proctored/tool-removed assessment is the only reliable signal.
- Sycophancy is a distinct failure from factual error and is roughly 1-in-7 turns under pressure for 2026 frontier models; tutor designs should treat "student asserts a wrong claim confidently" as an explicit test case.

### Gaps
- No RCT isolating sycophancy's effect on learning outcomes (benchmarks only).
- Low-usage numbers for Khanmigo are reported by news, not primary data.

---

## KQ3. How are the best LLM tutors prompted / structured? (guardrails, Socratic scaffolding, grounding, verification)

### Takeaway
Effective systems do not rely on the prompt alone: they (a) inject verified, instructor-authored solutions and "common mistakes" into context, (b) enforce sequencing outside the model (one problem part at a time), (c) put answer-withholding in a deterministic policy layer with a graded help ladder rather than in a single instruction, and (d) fine-tune when prompting proves unreliable (LearnLM). Evidence on Socratic-only vs mixed is thin: what is measured is "does not reveal the answer" and "gives guidance," and MathTutorBench shows pure questioning strategies degrade in longer dialogs.

### Cited Findings
- Bastani GPT Tutor prompt: "provide hints to the student without directly giving them the answer"; teachers supplied complete solutions for each problem plus "common student mistakes and how to provide feedback"; emphasis on step-by-step guidance. — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12232635/)
- Kestin: brevity for cognitive load, "DO NOT give away the full solution," encouraging tone; platform-level sequencing of problem parts because prompting alone could not scaffold multi-part problems; expert-authored solutions embedded per question; GPT-4-0613. — [Research Square](https://www.researchsquare.com/article/rs-4243877/v1)
- Tutor CoPilot: human-in-the-loop; AI suggests moves to the tutor; increased guiding questions, decreased answer-giving. — [EdWorkingPapers](https://edworkingpapers.com/ai24-1054)
- LearnLM (Jurenka et al. 2024): five target behaviors — manage cognitive load, encourage active learning, adapt to the learner, stimulate curiosity, deepen metacognition. Educator rubric (nine items): does not reveal the answer; promotes active learning; manages cognitive load; deepens metacognition; motivates/stimulates curiosity; adapts to learner goals/needs; encourages appropriately; identifies and addresses misconceptions; stays on topic. Authors found "most pedagogy is too nuanced to be explained with prompting" → supervised fine-tuning on a blend of human tutoring transcripts, gen-AI role-play, GSM8K-to-dialogue conversions, hand-written "golden conversations," and safety data; more human data improved style, more synthetic data filled coverage. — [arXiv 2407.12687](https://arxiv.org/html/2407.12687v3)
- LearnLM 2025 arena report: Gemini 2.5 Pro judged by 189 external educators in blinded multi-turn match-ups and 206 raters on a 25-item learning-science rubric (cognitive load, active engagement, metacognition, curiosity, adaptation, productive struggle); preferred in 71.3% vs Claude 3.7 Sonnet, 81.8% vs GPT-4o, 74.2% vs o3, 61.0% vs ChatGPT-4o; 73.2% overall excluding ties. Google-authored (vendor). — [arXiv 2505.24477](https://arxiv.org/abs/2505.24477); [Google blog](https://blog.google/products-and-platforms/products/education/google-gemini-learnlm-update/)
- Supervisor architecture for withholding answers (2026): Policy Core computes a per-turn help ceiling from trusted learner state only (never from student text → immune to prompt injection); eight-rung help ladder H0 ("acknowledge and encourage") to H7 ("show full solution"); deterministic code/solution detector strips solutions before any LLM judge; LLM judge (small model, temperature 0, allow/revise/block) only on risky turns; retrieval over course slides/transcripts/textbook; small models for intent pre-classification and instructional-move selection; stronger auditor model runs nightly, never in production. Acceptance gates: zero solution reveals; ≤5% revision rate on earnest help-seekers; ≥95% hint-ceiling compliance under adversarial personas (answer-seeker, gate-evader, injector); zero exam-integrity compromises. Final: all four passed. Observed "over-help ladder" of failures: partial code under pressure → ceiling too low for debugging → fabricated citations / naming exact bug in prose → over-citing. Explicitly no learning-outcome claim. — [arXiv 2608.12292](https://arxiv.org/html/2608.12292)
- Khan Academy (vendor): grounding in the student's recent problem history and prerequisite gaps improved next-item correctness; monitors pre-submission answer-giving and real-time math accuracy. — [Khan blog](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)
- Claude Learning Mode (Anthropic, April 2025 for Claude for Education, later general "Learning" style): guides toward the user's own solution, asks questions to test understanding, highlights underlying principles, offers templates for outlines/study guides. OpenAI Study Mode released similarly. Design descriptions only; no outcome data. — [Engadget](https://www.engadget.com/ai/anthropic-brings-claudes-learning-mode-to-regular-users-and-devs-170018471.html); [VentureBeat](https://venturebeat.com/business/anthropic-takes-on-openai-and-google-with-new-claude-ai-features-designed-for-students-and-developers) (vendor announcements)
- MathTutorBench (ETH, EMNLP 2025): "subject expertise, indicated by solving ability, does not immediately translate to good teaching"; tutoring "become[s] more challenging in longer dialogs, where simpler questioning strategies begin to fail." — [arXiv 2502.18940](https://arxiv.org/abs/2502.18940)
- "Prompt Matters: How Pedagogical Engineering Shapes Behavior and Engagement with AI Tutors" (Technology, Knowledge and Learning, 2026) — exists; content not retrieved. — [Springer](https://link.springer.com/article/10.1007/s10758-026-09983-6)

### Inferences
- The recurring stack across successful deployments: verified answer key in context → deterministic scaffold/sequencer → hint-not-answer instruction → small-model judge on risky turns → human or curriculum wrapper. Nothing in the evidence supports a bare system prompt as sufficient.
- Socratic-only vs mixed: no RCT found that pits the two directly with learning outcomes. Indirect evidence (MathTutorBench long-dialog degradation; Koedinger's assistance dilemma; Khan's usage collapse then revamp) points toward *graded* assistance (help ladder ending in a worked solution after effort) over pure questioning.
- Injection resistance is a real requirement: students are adversarial users of a withholding policy; the supervisor paper's "never read student text for the policy decision" is the clean fix.

### Gaps
- No direct RCT of Socratic-only vs direct-instruction LLM tutoring with learning outcomes found.
- Fine-tuning vs prompting head-to-head on learning outcomes: not measured anywhere found (LearnLM comparisons are preference-based).
- Study Mode / Learning Mode: no published evaluations of any kind found.

---

## KQ4. LLM grading of free-text / teach-back answers — reliability, rubric formats, biases

### Takeaway
For short, rubric-anchored STEM answers, GPT-4-class graders reach human-level agreement (κ ≈ 0.68–0.75; 70–80% agreement on binary rubric items, equal to human–human; r ≈ 0.98 on quiz totals). Agreement collapses on stylistic/rhetorical criteria and with vague rubrics. Documented biases: GPT-4o under-grades (38.8% under vs 6.2% over in one course), weights empirical rigor over writing, and fairness across student groups is an open question.

### Cited Findings
- Physics explanations (Phys. Rev. PER 2025): GPT-4o partial-credit grading of student verbal explanations for conceptual and numerical intro-physics problems; three-item binary rubric; zero-shot with no examples or reference answers agreed with humans in 70–80% of cases, "equal to or higher than" human–human agreement. — [PRPER 21, 010126](https://journals.aps.org/prper/abstract/10.1103/PhysRevPhysEducRes.21.010126)
- Short answer scoring with GPT-4 (Jiang, L@S 2024): QWK 0.677 across 10 questions. — [ACM L@S](https://dl.acm.org/doi/pdf/10.1145/3657604.3664685)
- K-12 short-answer marking (2024): GPT-4 at human-level with κ = 0.75. — [arXiv 2405.02985](https://arxiv.org/pdf/2405.02985)
- LLM-as-a-Grader (2025, GPT-4o, temp 0): 258 quiz responses (≈50 students × 5 quizzes) + 14 team reports; quiz rubric 0.2 pts/question in 0.1 increments against instructor reference answers; Pearson 0.62–0.97 per quiz, 0.98 overall, exact match 55%; report sections diverge significantly on Approach (p=0.0083) and Results (p=0.0020); GPT-4o under-graded 38.8% vs over-graded 6.2%; converges with humans "when the rubric is explicit and unambiguous," diverges on stylistic/rhetorical judgment. — [arXiv 2511.10819](https://arxiv.org/html/2511.10819v1); [MDPI Information 17(5):505](https://www.mdpi.com/2078-2489/17/5/505)
- GPT-4 ranks open-text answers comparably to human examiners (Sci Rep 2025). — [Nature Sci Rep](https://www.nature.com/articles/s41598-025-21572-8)
- Fairness: "Is GPT-4 fair? An empirical analysis in automatic short answer grading" (Computers & Education: AI, 2025) examines group-level bias. — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2666920X25000682) (numbers not retrieved)
- EDM 2025: RAG-augmented short-answer grading; GradeOpt multi-agent framework optimizing grading guidelines to human level. Classroom deployments "mixed": some find no significant AI–human correlation, others high correlation with structured rubrics. — [EDM 2025 RAG grading](https://educationaldatamining.org/EDM2025/proceedings/2025.EDM.short-papers.81/index.html); [GradeOpt](https://educationaldatamining.org/EDM2025/proceedings/2025.EDM.long-papers.80/index.html)
- Calibrated human-in-the-loop grading (CHiL(L)Grader, 2026) and "LLM-based Automated Grading with Human-in-the-Loop" (2025) route low-confidence cases to humans. — [arXiv 2603.11957](https://arxiv.org/pdf/2603.11957); [arXiv 2504.05239](https://arxiv.org/pdf/2504.05239)
- One 2025 medical short-answer study reported Cohen's κ = 0.515 (moderate) for LLM vs expert graders. — [Medical Education Online 2025](https://www.tandfonline.com/doi/full/10.1080/10872981.2025.2550751) (page 403'd; figure from search snippet only)
- Bastani: GPT-4 (2023) correct on only 51% of the curriculum math problems — a grader that solves the problem itself is unreliable without a reference. — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12232635/)

### Inferences
- Rubric format that works: itemized, binary or few-level criteria, each tied to a reference answer or key idea, scored per item; avoid holistic style scores. Zero-shot works when the rubric is explicit; reference answers matter more than few-shot examples.
- For teach-back grading in a tutor, treat κ ≈ 0.7 as the realistic ceiling and design for it: confidence gating, human/second-model review on disagreement, and never letting a single LLM grade both decide mastery and be unrevisable.
- Under-grading bias (strictness) is the safer failure for a tutor (it triggers more practice) but harms motivation; leniency plus sycophancy is the dangerous combination.

### Gaps
- No study found on grading *teach-back* (Feynman-style explanations) specifically; closest is the physics explanation-grading paper.
- Group-fairness magnitudes not retrieved.

---

## KQ5. Misconception diagnosis in ITS: bug libraries, constraint-based modeling, LLM approaches

### Takeaway
Two classic paradigms: model-tracing / bug libraries (enumerate buggy production rules; expensive empirical work) and constraint-based modeling (encode only correct-domain constraints; any violation is an error, no need to enumerate bugs). LLM-era work maps distractors to misconception labels (Eedi) and asks whether LLMs can faithfully simulate student errors — results show partial alignment and a sycophancy problem in simulators.

### Cited Findings
- Constraint-based modeling (Ohlsson; Mitrović & Ohlsson 1999 first system): a knowledge base of constraints encoding correct domain knowledge; no explicit/generative model of buggy skills and no labor-intensive empirical bug studies required; remediation occurs when students are warned about constraint violations while applying procedural knowledge. — [Ohlsson, Constraint-Based Student Modeling (Springer)](https://link.springer.com/chapter/10.1007/978-3-662-03037-0_7); [Mitrović & Ohlsson 2016 IJAIED retrospective](https://link.springer.com/article/10.1007/s40593-015-0075-7)
- Model-tracing vs CBM comparison debate (Kodaganallur, Weitz, Rosenthal vs Mitrovic & Ohlsson). — [ResearchGate](https://www.researchgate.net/publication/262172787_An_Assessment_of_Constraint-Based_Tutors_A_Response_to_Mitrovic_and_Ohlsson's_Critique_of_A_Comparison_of_Model-Tracing_and_Constraint-Based_Intelligent_Tutoring_Paradigms)
- Cognitive Tutor's diagnosis: model tracing against production rules, with yes/no feedback, explanatory hints, and knowledge-tracing-driven problem selection (Koedinger & Aleven 2007). — [Ed Psych Review](https://link.springer.com/article/10.1007/s10648-007-9049-0)
- LearnLM rubric item "identifies and addresses misconceptions" is rated by educators, not measured automatically. — [arXiv 2407.12687](https://arxiv.org/html/2407.12687v3)
- Eedi "Mining Misconceptions in Mathematics" (Kaggle/NeurIPS 2024): task = match each MCQ distractor to a misconception label from a taxonomy; strong solutions used contrastive LoRA fine-tuning of Qwen retrievers + reranking on ~10k synthetic + 1.8k real examples (rank 42/1446 example). — [Kaggle](https://www.kaggle.com/competitions/eedi-mining-misconceptions-in-mathematics); [Eedi write-up](https://www.eedi.com/news/from-wrong-answers-to-real-insights-how-we-used-a-kaggle-challenge-to-map-student-misconceptions)
- LLMs partially reproduce human error patterns ("Do LLMs Make Mistakes Like Students?", 2025) and can generate misconception-targeted distractors; personalized distractor generation via MCTS reasoning reconstruction (2025). — [arXiv 2502.15140](https://arxiv.org/pdf/2502.15140); [arXiv 2508.11184](https://arxiv.org/pdf/2508.11184); [arXiv 2603.15547](https://arxiv.org/html/2603.15547)
- LLM student simulators often solve correctly instead of faithfully holding the assigned misconception ("Simulating Students or Sycophantic Problem Solving?", 2026). — [arXiv 2605.12748](https://arxiv.org/pdf/2605.12748)
- Middle-school algebra misconception benchmark for AI-supported instruction (2024). — [arXiv 2412.03765](https://pith.science/paper/2412.03765)
- MathTutorBench includes mistake-location and mistake-correction subtasks under "Student Understanding," separate from problem-solving. — [arXiv 2502.18940](https://arxiv.org/abs/2502.18940)

### Inferences
- For an LLM tutor, the CBM idea transfers cheaply: give the model the correct-answer constraints (teacher solution + "common mistakes and how to respond" as in Bastani's GPT Tutor) rather than a full bug library; the LLM does the matching.
- A curated misconception taxonomy (Eedi-style labels) plus LLM retrieval is the current practical middle ground between hand-built bug libraries and free-form LLM diagnosis.

### Gaps
- No accuracy figures found for LLM misconception *diagnosis from free-text student work* (as opposed to MCQ distractor mapping).
- No study comparing CBM-style prompting vs bug-library prompting in LLM tutors.

---

## KQ6. How to evaluate a tutor: learning-gain measures, tutor-quality benchmarks, learning-vs-performance; plus VanLehn's inner/outer loop

### Takeaway
Measure learning with unassisted, ideally delayed or proctored post-tests (Bastani's exam, ALEKS proctored items), not in-tool performance. Tutor-quality benchmarks (LearnLM rubrics, MathTutorBench, the Unifying-AI-Tutor-Evaluation taxonomy, EduFrameTrap) measure pedagogy proxies and are useful for regression testing but none has been validated against learning gains. VanLehn's minimum tutor: an outer loop (select task, update student model) and an inner loop (per-step feedback and hints); inner-loop feedback is what makes a system an ITS.

### Cited Findings
- VanLehn 2006 "The Behavior of Tutoring Systems" (IJAIED 16(3):227–265): outer loop runs once per task (multi-step problem); inner loop once per student step, giving feedback and hints on the step and assessing evolving competence to update the student model, which the outer loop uses to pick the next task. Availability of inner-loop feedback classifies a system as an ITS. — [SAGE](https://journals.sagepub.com/doi/10.3233/IRG-2006-16%283%2902); [ACM](https://dl.acm.org/doi/10.5555/1435351.1435353); [Regulative/Step/Task loops follow-up, IJAIED 2016](https://link.springer.com/article/10.1007/s40593-015-0056-x)
- VanLehn 2011: interaction granularity (answer vs step vs substep) is the key dimension; step-based tutors reach d ≈ 0.76. — [ERIC](https://eric.ed.gov/?id=EJ946764)
- Learning vs performance (Soderstrom & Bjork 2015): only delayed retention/transfer reveals learning; immediate scores mislead. — [SAGE](https://journals.sagepub.com/doi/abs/10.1177/1745691615569000)
- Bastani: practice (assisted) vs exam (unassisted) split is the operative design; harm was invisible in practice data. — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12232635/)
- Rismanchian et al.: proctored vs non-proctored items give opposite-signed estimates. — [arXiv 2605.21629](https://arxiv.org/abs/2605.21629)
- Kestin: pre/post on a matched unit, crossover to control for cohort; effect via quantile regression. — [ETCJ review](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/)
- Khanmigo independent study: concept inventory (LPCI) pre/post; null between groups. — [ERIC](https://eric.ed.gov/?id=EJ1487444)
- Khan Academy's production metric: next-item correctness after a tutoring thread, A/B at ≥95% confidence — a performance proxy, not retention. — [Khan blog](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)
- LearnLM benchmark suite (7): unguided learner feedback (7-question survey after 45-min sessions), turn-level teacher ratings, conversation-level teacher ratings, side-by-side comparisons, progress-over-time, LLM-based automatic evaluations, targeted capability tests. Results: learners significantly favored LearnLM-Tutor on 1 of 7 dimensions (confidence applying knowledge, p<0.05); educators rated it better on "promoting engagement" (p<0.05) and worse (n.s.) on "speaking encouragingly"; factual accuracy 96% Gemini vs 93% LearnLM (p=0.13); MMLU 0.72 / MATH 0.33 unchanged. Explicitly no learning-outcome measure; small samples; UK/WEIRD raters. — [arXiv 2407.12687](https://arxiv.org/html/2407.12687v3)
- LearnLM 2025 arena: blinded multi-turn educator match-ups + 25-item rubric. — [arXiv 2505.24477](https://arxiv.org/abs/2505.24477)
- MathTutorBench: three skill groups — Math Expertise (problem solving, Socratic questioning), Student Understanding (solution correctness, mistake location, mistake correction), Pedagogy (win rate from a reward model trained to separate expert from novice teacher responses); open leaderboard. — [GitHub](https://github.com/eth-lre/mathtutorbench); [ACL Anthology](https://aclanthology.org/2025.emnlp-main.11.pdf)
- Unifying AI Tutor Evaluation taxonomy (Maurya et al., 2024): a pedagogical-ability taxonomy for LLM tutors used for annotated tutor-response evaluation. — [arXiv 2412.09416](https://arxiv.org/pdf/2412.09416)
- MMTutorBench (multimodal math tutoring), TeachBench (syllabus-grounded teaching ability), TEAS (verifiability/stability/auditability standard) — 2025–2026 benchmark/spec proposals. — [arXiv 2510.23477](https://arxiv.org/html/2510.23477v2); [arXiv 2601.21375](https://arxiv.org/pdf/2601.21375); [arXiv 2601.06066](https://arxiv.org/pdf/2601.06066)
- EduFrameTrap recommends reporting pressure-resolved sycophancy rates and judge-disagreement signals, pre-deployment measurement, and post-deployment drift monitoring. — [arXiv 2605.14604](https://arxiv.org/html/2605.14604v1)
- Supervisor paper: compliance gates evaluated with scripted personas + auditor model at "under a dollar" per full loop; 500+ deterministic unit tests. — [arXiv 2608.12292](https://arxiv.org/html/2608.12292)
- Roschelle, McLaughlin & Koedinger published peer feedback on the LearnLM paper (2025), which prompted the 2025-11-28 revision. — [arXiv 2407.12687 v3 note](https://arxiv.org/html/2407.12687)

### Inferences
- A defensible evaluation ladder: (1) offline pedagogy regression suite (rubric + sycophancy + leakage gates), (2) online A/B on next-item correctness (Khan-style) as a cheap proxy, (3) pre/post with a *tool-removed* post-test, (4) delayed/proctored retention. Only (3)–(4) count as learning evidence.
- Normalized gain and concept inventories (as in the Khanmigo LPCI study) are the standard physics-education instruments; the Khanmigo null with N=69 shows they are underpowered at small N.
- Map LLM tutor components to VanLehn's loops: outer loop = task selection + mastery/knowledge-tracing state (Khan's prerequisite gaps and history summaries are outer-loop signals); inner loop = per-step feedback/hints with a help ceiling (the supervisor's H0–H7 ladder).

### Gaps
- No benchmark score has been correlated with measured learning gains; treat all pedagogy benchmarks as unvalidated proxies.
- Delayed (weeks-later) post-tests: none found for any LLM tutor RCT; Bastani's exam was end-of-unit, Kestin's was immediate.

---

## KQ7. Cost / latency considerations reported in the literature

### Takeaway
Reported per-learner costs range from $20/tutor/year (Tutor CoPilot, human-in-the-loop) to $0.01–0.03 per student-minute for LLM-run oral assessments; Khan Academy shaved ~3.6 s/turn mostly by forcing concise outputs. Little peer-reviewed latency data exists; one 2026 arXiv paper targets multi-agent tutoring latency/cost at scale but its numbers were not extractable.

### Cited Findings
- Tutor CoPilot ≈ $20 per tutor per year at observed usage. — [EdWorkingPapers](https://edworkingpapers.com/ai24-1054)
- Khan Academy (vendor) latency reductions: faster model −0.3 s; more concise math-agent outputs −3 s; pre-checks to skip unnecessary processing −0.3 s. — [Khan blog](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)
- Voice-AI oral assessments: ≈ $0.29/exam (Fall 2025, 36 students) to $0.96/exam (Spring 2026, 37 students); ≈ $0.01–0.03 per student-minute. — [arXiv 2603.18221](https://arxiv.org/pdf/2603.18221)
- Specialized knowledge-tracing models cost < $2/year to serve 100,000 students at 40 predictions each, and outperform LLMs at KT ("Faster, Cheaper, More Accurate"). — [arXiv 2603.02830](https://arxiv.org/pdf/2603.02830)
- India-scale target of ≈ $0.34/student/year vs commercial AI tutoring at ≈ $60–120/student/year — cited in search summary of cost analyses. — [aggregated in search results; primary not fetched](https://arxiv.org/pdf/2604.24110)
- Supervisor architecture uses small models for pre-classification/judging, a cached ~160 KB prefix prompt, and a stronger auditor only offline. — [arXiv 2608.12292](https://arxiv.org/html/2608.12292)
- "Latency and Cost of Multi-Agent Intelligent Tutoring at Scale" (2026) exists; content not extractable from fetched PDF. — [arXiv 2604.24110](https://arxiv.org/pdf/2604.24110)

### Inferences
- Cost is dominated by design (turn count, verbosity, number of agent hops), not model price; verbosity control alone bought Khan more than a model swap.
- Use small/cheap models for routing, judging, and knowledge tracing; reserve the frontier model for the student-facing turn.

### Gaps
- No peer-reviewed per-turn p50/p95 latency figures for LLM tutors found.
- Nigeria per-student cost not in retrieved sources (World Bank paper claims high cost-effectiveness; figure lives in the PDF).
