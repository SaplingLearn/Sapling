# Assessment Validity of LLM Items/Grading and Causal Evaluation Design for Sapling (as of Nov 2026)

Scope: (1) validity of LLM-generated assessment items and LLM grading; (2) a practical, credible evaluation design for a small college AI-tutor startup. Research done 2026-11-07. Preprints are marked [preprint]. Notes based on search snippets rather than full text are marked [snippet-level].

## Q1. Quality of LLM-generated questions (MCQ and open) vs human-written

### Takeaway
On classical item statistics, LLM-written MCQs are usually comparable to human items on difficulty (sometimes easier) and roughly comparable on discrimination. The evidence is heterogeneous, and a 2026 meta-analysis leans toward humans on discrimination. The consistent weaknesses are distractors and item-writing flaws, especially "correct option is longest" and correct options that reuse words from the stem. Nearly all of this evidence comes from health-professions MCQs written from curated source material. None of it covers items generated from student-uploaded material with peer-sourced keys, which is Sapling's case.

### Cited Findings
- Preregistered GPT-4o study in imaging specialties, 24 AI vs 24 human topic-matched items. Difficulty: human 0.65 (SD 0.22) vs LLM 0.67 (0.20). Discrimination: 0.27 vs 0.29. Neither difference was significant, and participants identified an item's origin no better than chance. — [PMC12881591](https://pmc.ncbi.nlm.nih.gov/articles/PMC12881591/)
- Medical-education cohort in a high-stakes exam: AI MCQs were easier (difficulty index 0.78 ± 0.22 vs 0.69 ± 0.23, p < 0.01), with similar discrimination. — [PMC11806894](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11806894/) [snippet-level]
- Dental education, IRT 3PL: no difficulty difference, but human items discriminated better. — [Scientific Reports 2025, s41598-025-28492-7](https://www.nature.com/articles/s41598-025-28492-7) [snippet-level]
- Systematic review and meta-analysis in medical education (Medical Teacher, 2026): pooled difficulty was comparable. Human items had higher discrimination (SMD = −0.701, 95% CI −1.33 to −0.08, p = 0.028, I² = 86.2%). The result is sensitive to a single study, and excluding it flipped the pooled direction toward AI. — [Medical Teacher 10.1080/0142159X.2026.2691072](https://www.tandfonline.com/doi/full/10.1080/0142159X.2026.2691072) [snippet-level]
- A network meta-analysis of LLM MCQ generation in health professions education also exists. — [ResearchGate 399390768](https://www.researchgate.net/publication/399390768_The_use_of_large_language_models_in_generating_multiple_choice_questions_for_health_professions_education_A_systematic_review_and_network_meta-analysis) (details not extracted)
- The procedure matters. A Frontiers in Education (2026) study reports psychometric equivalence only when a validated zero-shot generation procedure is used, not an iterative one. — [Frontiers feduc.2026.1837523](https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2026.1837523/full) [snippet-level]
- Telling GPT about students' typical misconceptions improves MCQ validity. — [arXiv 2505.05815](https://arxiv.org/pdf/2505.05815) [preprint]
- Item-writing flaws:
  - Univ. of Michigan work-in-progress study: "longest option correct" was flagged in 87% of GPT-3.5 and 82% of GPT-4 MCQs, using the Moore et al. rubric. — [Michigan 2024 WIP](https://websites.umich.edu/~kevynct/pubs/L_S_2024_WorkInProgress_Question_Generation_CRFinal2.pdf)
  - GPT-based L2 listening item generation: the correct option was disproportionately the longest (binomial p < 0.05). The bias persisted across prompting and fine-tuning and worsened in one configuration. — [Computers & Education: AI 2026, S2666920X26000858](https://www.sciencedirect.com/science/article/pii/S2666920X26000858) [snippet-level]
  - Frontiers in Computer Science (2026; 152 items from 19 teachers, 19-criterion flaw rubric): the table reports "longest option correct" in 34.9% of teacher items vs 57.6% of AI items, but the prose appears to contradict this direction, so the paper is internally inconsistent. AI items systematically reused stem vocabulary in the correct answer, a lexical cue. — [Frontiers fcomp.2026.1831250](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2026.1831250/full)
  - The 19-criterion flaw rubric can be applied automatically with GPT-4 plus rule-based checks, with inter-rater agreement of 97% (κ = 0.83) on the criterion. — [arXiv 2307.08161](https://arxiv.org/pdf/2307.08161) [preprint]. Toolkit: [SAQUET, arXiv 2405.20529](https://arxiv.org/pdf/2405.20529) [preprint]
- A physiology study found AI items easier, with comparable discrimination but more non-functional distractors. — summarized in the [search synthesis of Frontiers/PMC sources](https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2026.1837523/full) [snippet-level; primary not opened]

### Inferences
- Sapling's main item risk is not average difficulty. The risks are key correctness, since peer-sourced keys can be wrong; cueing flaws, which inflate scores and look like learning; and construct misalignment with the course.
- Mitigations:
  - Run an automated item-writing-flaw linter on every item (length balance, stem-word overlap, "all of the above").
  - Randomize the position of the correct option, and balance or normalize option lengths.
  - Have an expert (TA or instructor) review a stratified sample of items to estimate key-error and flaw rates per course.
  - Once data exists, compute p-values and point-biserials. Retire items with a point-biserial below about 0.15, or with a negative one.
- For free-response and teach-back items, the literature above says little directly. Their validity rests mostly on rubric quality and grader validity (Q2).
- Difficulty labels 1–3 assigned by the generator are unvalidated claims until they are checked against empirical p-values.

### Gaps
- I found no psychometric studies of LLM items generated from student-uploaded (unvetted) course material, or of "multiple-choice-with-reason" and teach-back formats.
- I found no source giving an overall expert-rejection rate across studies. Individual studies report flaw rates, not a pooled "usable without edit" rate.
- Most evidence is from medicine and dentistry. Generalization to STEM, humanities and other undergraduate courses is unverified.

## Q2. LLM automated grading of short answers/explanations: reliability, bias, attacks, best practice

### Takeaway
LLM grading agrees with humans well enough on short, well-specified tasks with a clear rubric, and much less well on open, explanatory or long responses. Percent agreement can hide systematic score bias. All tested LLM graders were vulnerable to prompt injection in realistic grading scenarios. Sapling's 0.98 agreement on a 45-case fixture set is not evidence of validity on real student answers: n is small, the cases were probably written by the developers, and there is no human-human baseline or bias analysis.

### Cited Findings
- Hardy (2026) meta-analyzed 890 results on LLM short-answer scoring using mixed-effects meta-regression on QWK. [preprint; AIME-Con 2026 proceedings]
  - Decoder-only LLMs underperformed encoder models by about 0.37 in agreement.
  - How hard a task was for human scorers did not predict LLM performance, and some tasks that were easiest for humans were hardest for LLMs.
  - Scores were sensitive to wording and tokenization.
  - In high-stakes contexts, the LLMs showed racial bias in scoring.
  - Source: [arXiv 2603.04820](https://arxiv.org/abs/2603.04820)
- A review page tallies LLM vs human grading as comparable in 12 reviewed cases and worse in 11, with the best alignment on short, straightforward tasks. — [Learning Design Wiki](https://wiki.learningdesignalliance.org/claims/llm-grading-mixed-against-human-raters/) (secondary aggregator)
- GPT-4o on quizzes correlated with TAs up to 0.98, but exact score agreement was only 55%, and it showed a consistent conservative bias. — [Information 17(5):505, 10.3390/info17050505](https://doi.org/10.3390/info17050505) [snippet-level]
- High percent agreement can coexist with mean scores 10–20 points off from humans. The authors recommend reporting bias alongside agreement and found judges lean lenient. — [GEM 2025, ACL Anthology](https://aclanthology.org/2025.gem-1.33.pdf) [snippet-level]
- Prompt injection: all evaluated LLMs were vulnerable in realistic educational grading. Minimal, easily hidden student instructions caused substantial grade inflation. — [Education Sciences 15(11):1419, MDPI](https://www.mdpi.com/2227-7102/15/11/1419)
- Peer-review analogue: injected prompts pushed one model to a perfect score in about 30% of cases. — [arXiv 2509.09912](https://arxiv.org/abs/2509.09912) [preprint]
- Rubric-conditioned grading resisted injection in one study but was sensitive to synonym substitution. That study also covers uncertainty estimation. — [arXiv 2601.08843](https://arxiv.org/html/2601.08843) [preprint]
- Rubric design and item features shape LLM scoring accuracy. — [Frohn, Burleigh & Chen, AIED 2025](https://tylerburleigh.com/research/articles/frohn-et-al-2025)
- Rubric refinement: an LLM proposes rubric edits, and each edit is kept only if QWK against humans improves, on ASAP-SAS. — [AIME-Con 2026 session 2](https://aclanthology.org/2026.aimecon-sessions.2.pdf)
- The standard reporting set in recent studies is QWK, Cohen's κ, ICC and MAE, each computed human–human, LLM–human and LLM run-to-run. — [JMIR Med Educ 2026 preprint](https://preprints.jmir.org/preprint/89445); [Emirtekin & Ozarslan, 232 responses, 4 LLMs](https://gcris.yasar.edu.tr/entities/publication/1eeab52d-b73f-42b4-baa8-f2c94edfc8c1/full) [snippet-level]

### Inferences
These are recommended practices synthesized from the findings above, not individually sourced.
- **Calibration set.** Build a held-out set of at least 200–300 real, de-identified student responses per item family, double-scored by two independent course experts.
- **What to report.** Report human–human agreement as the ceiling, then LLM–human QWK, κ, MAE and signed mean bias.
  - Break results down by item type (free response, teach-back, MC-with-reason) and by subgroup (ESL writers, response length).
  - Report test-retest stability of the LLM itself.
- **Fixtures.** The 45-case fixture is a regression test, not a validity study.
- **Grader setup.**
  - Use an analytic rubric with reference answers and anchor exemplars per score point.
  - Have the grader output per-criterion evidence (quote the span) before giving a score.
  - Put student text inside delimiters, and instruct the grader that the text is data.
  - Run an injection detector, plus a red-team set of adversarial answers (hidden instructions, keyword stuffing, verbose wrong answers, confident tone) as a standing test.
- **Second grader.** Use a second grader (different model or prompt). Route disagreements or low-confidence cases to human review or treat them as "ungraded" for research outcomes.
- **Research outcomes.** For outcomes used as research evidence (post-test, transfer), use human or double-blind expert scoring of at least a random subsample. Ideally use selected-response or human-scored outcomes, so the outcome measure does not depend on the same LLM the treatment uses.
- **Grader circularity.** Sycophancy and self-preference are a specific risk: the tutor and the grader share a model family, and treated students learn the tutor's phrasing. The grader may then reward tutor-style wording rather than understanding. This is an outcome-alignment confound to measure, for example by checking whether LLM–human disagreement differs by condition.

### Gaps
- I found no specific 2025–2026 study measuring self-preference or sycophancy of an LLM grader toward answers phrased like the same model's tutoring. The risk is inferred, not measured.
- I could not extract a pooled QWK value from the Hardy meta-analysis abstract.
- I found no study validating LLM grading of "teach-back" explanations specifically.

## Q3. Evaluation designs feasible at small scale, and power

### Takeaway
At tens to low hundreds of students per course, a between-student RCT powered for realistic effects of about 0.1–0.2 SD is infeasible in a single course. The credible path is within-student randomization of concepts or items to conditions, in the style of Lindsey et al. (2014), with a delayed, independent outcome. This gives each student their own control and multiplies effective observations. A preregistered between-student or crossover RCT across several courses can follow. Recent AI-tutor RCTs show both large positive effects (Kestin 2025) and harm from unguarded AI (Bastani 2025). The comparison condition and the outcome measure decide what a result means.

### Cited Findings
- Kraft (2020) benchmarks for causal studies with standardized achievement outcomes, from about 750 RCTs [Educational Researcher 49(4):241–253, DOI 10.3102/0013189X20912798](https://doi.org/10.3102/0013189X20912798); [EdWorkingPaper ai19-10](https://edworkingpapers.com/ai19-10):
  - Below 0.05 SD is small, 0.05 to under 0.20 is medium, and 0.20 or more is large. The median is 0.10 SD.
  - Studies with more than 2,000 students vs 100 or fewer have medians of 0.03 vs 0.24 SD.
  - Broad vs narrow measures have medians of 0.10 vs 0.17 SD.
  - Preregistered, IES-funded RCTs have a median of 0.03 SD (139 effect sizes from 49 RCTs).
  - Effects on researcher-designed tests aligned with the treatment are often 2–4× larger than on broad standardized tests.
  - Per-pupil cost benchmarks (2016 USD): low is under $500, moderate is $500 to under $4,000, high is $4,000 or more.
- Lindsey, Shroyer, Pashler & Mozer (2014), Psychological Science 25(3):639–647 — [DOI 10.1177/0956797613504302](https://journals.sagepub.com/doi/abs/10.1177/0956797613504302); [EurekAlert](https://www.eurekalert.org/news-releases/579380):
  - Middle-school Spanish, with review-scheduling conditions varied within students.
  - Personalized review gave a 16.5% gain over massed study and 10% over generic spaced review on a cumulative exam after the semester. The benefit persisted at 1 month.
  - A secondary source reports each student's items were split into thirds with counterbalancing, which I could not verify in the primary text. — [Mnemosyne list quoting paper](https://groups.google.com/g/mnemosyne-proj-users/c/vU4QiMqkMNE/m/9COWw4i59X4J)
- Kestin et al. (2025), Scientific Reports — [ResearchGate](https://www.researchgate.net/publication/392839220_AI_tutoring_outperforms_in-class_active_learning_an_RCT_introducing_a_novel_research-based_design_in_an_authentic_educational_setting); critique: [ETC Journal review](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/):
  - Harvard physics, N = 194, crossover design, an AI tutor vs an active-learning class.
  - Median post-test 4.5 vs 3.5. Regression effect size 0.63, with quantile-regression estimates of 0.73–1.3 SD.
  - Limits: a single course, short researcher-built tests, and the comparison condition.
- Bastani et al. (2025), PNAS 122(26):e2422633122 — [CHIBE/UPenn](https://chibe.upenn.edu/publications/generative-ai-without-guardrails-can-harm-learning-evidence-from-high-school-mathematics); [RePEc](https://ideas.repec.org/a/nas/journl/v122y2025pe2422633122.html):
  - About 1,000 Turkish high-school math students, Fall 2023.
  - Unguarded GPT-4 ("GPT Base") improved practice performance but cut later unassisted exam grades by 17% vs no access. The guardrailed "GPT Tutor" largely mitigated this.
  - The lesson: practice-time performance is not learning, so a tool-free delayed test is essential.
- Eedi × Google DeepMind (Nov 2025) [preprint] — [arXiv 2512.23633](https://arxiv.org/abs/2512.23633v1); [Eedi Substack](https://eedi.substack.com/p/ai-in-education-7-five-things-i-learned):
  - Exploratory RCT, n = 165 across 5 UK schools, comparing a human tutor, human-supervised LearnLM, and static hints.
  - LearnLM was at least as good as human tutors. Success on novel later-topic problems was 66.2% vs 60.7%.
  - Eedi itself calls it "a small first study". A 1,200-student four-arm trial is running to July 2026.
- ASSISTments E-TRIALS is a free platform for student-level RCTs inside a live learning product, run by WPI and the ASSISTments Foundation with IES NCER funding. Example: a 475-student RCT in fall 2019. The paper compares three treatment-effect estimators, including design-based methods that use remnant data for covariate adjustment. — [arXiv 2502.10545](https://arxiv.org/html/2502.10545v2) [preprint]; [assistments.org/e-trials](https://www.assistments.org/e-trials); [IES award](https://ies.ed.gov/use-work/awards/revisions-assistments-digital-learning-platform-expand-its-support-rigorous-education-research)

### Inferences (power arithmetic is my own, standard formulas, α = .05 two-sided, power .80; not from a source)
- **Between-student, 2-arm, individual randomization:** n ≈ 2(1.96 + 0.84)²/d² per arm.
  | d | n per arm | Total |
  |---|---|---|
  | 0.5 | ~64 | ~128 |
  | 0.3 | ~175 | ~350 |
  | 0.2 | ~393 | ~786 |
  | 0.1 | ~1,570 | ~3,140 |
  - A pretest covariate explaining R² = 0.5 of outcome variance roughly halves these numbers, so d = 0.2 needs about 200 per arm (about 400 total).
  - With 50–150 students per course, one course can only detect about d ≥ 0.4–0.5. Kraft's distribution says that is implausible for a broad outcome.
- **Within-student concept randomization:** each student has some concepts tutored with checks and some untouched or "read-only", balanced and counterbalanced. The test is a paired comparison of per-student mean scores across conditions.
  - n ≈ (2.8/d_z)², where d_z = d/√(2(1−ρ)) and ρ is the within-student correlation of the condition means.
  - With ρ = 0.5, d = 0.2 gives d_z = 0.2, so about 196 students. With ρ = 0.7, d_z ≈ 0.26, so about 120 students.
  - Having more items per concept raises ρ and reliability. The right analysis is a crossed random-effects model (student × item), which usually gains power over the paired t-test.
  - Practically, 100–200 consenting students pooled over 2–4 courses in one term can detect about 0.2–0.3 SD within-student effects.
- **Contamination:** within-student designs measure a concept-level effect, such as the effect of practicing with the tutor on that concept. They cannot measure whole-product effects like motivation, time reallocation or study habits. They are also biased toward zero if tutoring on one concept spills over to related concepts. Choose weakly related concepts, or randomize at the unit/chapter level.
- **Crossover by unit:** half the students get Sapling for unit A and not B, and the other half the reverse. This is feasible within one course and gives a whole-tool effect per unit, with unit exams as outcomes. Kestin 2025 used a crossover design. Carryover and differential unit difficulty must be handled with counterbalancing and unit fixed effects.
- **Waitlist (delayed access):** this is ethically easy to justify while a beta is capacity-limited. But a waitlist control in a graded course raises fairness issues, so restrict it to low-stakes study units or provide access before graded exams.
- **Encouragement design:** if access cannot be withheld, randomize nudges or invitations and estimate an instrumental-variable effect. This needs large n because compliance differences shrink power.
- **Feature A/B tests:** randomizing tutor features (e.g., guardrailed vs direct-answer mode, retrieval practice on/off) is feasible and cheap. It answers "which design works better", which is credible for product iteration but not for "Sapling causes learning".
- **Regression discontinuity:** rarely feasible at this scale. It needs a sharp assignment cutoff and large n near the threshold.
- **Comparison condition:** "business as usual" (own study, textbook, the course's own resources) answers the purchase question. "Generic ChatGPT" answers the differentiation question, and Bastani suggests generic AI can be negative. A strong active control such as Kestin's active learning is the hardest bar.

### Gaps
- I found no published within-student concept-randomized evaluation of an LLM tutor in college courses. Kestin used a crossover, and Lindsey's within-student design was scheduling, not tutoring.
- A University of Maryland study reportedly titled "When AI access didn't help" appeared in a summary, but I could not retrieve it.
- I did not find empirical ICC or ρ values for undergraduate concept-level outcomes. The power numbers above use assumed ρ and should be re-estimated from pilot data.

## Q4. Measures

### Takeaway
To convince skeptical researchers, the outcome must be independent of the intervention and not over-aligned with it. That means items not generated by the same pipeline, not graded by the same LLM, and ideally including the course's own exams, a validated concept inventory where one exists, and transfer items. Effects should be measured at a delay. Kraft shows narrow, researcher-designed outcomes inflate effects 2–4×. Bastani shows practice performance can move in the opposite direction from learning.

### Cited Findings
- Researcher-designed outcomes aligned with the treatment yield effects 2–4× larger than broad standardized tests. Kraft also cites tutoring-specific tests showing effects 8–20× larger than standardized math tests. Effects measured immediately after an intervention are larger than delayed ones. — [Kraft 2020](https://doi.org/10.3102/0013189X20912798)
- Unguarded AI raised practice scores but lowered later unassisted exam scores. — [Bastani et al. 2025, PNAS](https://ideas.repec.org/a/nas/journl/v122y2025pe2422633122.html)
- Lindsey 2014 used a cumulative exam after the semester plus a 1-month follow-up as the outcome, not in-system performance. — [EurekAlert](https://www.eurekalert.org/news-releases/579380)
- The Eedi trial used success on novel problems on later topics, a transfer-like measure, alongside retries of the same item. Retry success was over 90% for both tutors vs 65% for static hints, which showed ceiling effects on near measures. — [arXiv 2512.23633](https://arxiv.org/abs/2512.23633v1)
- Kestin's effect sizes relied on short pre/post tests with ceiling effects, which motivated the use of quantile regression. — [ETC Journal review](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/)

### Inferences
- **Recommended outcome battery for Sapling:**
  - **(a) Pretest:** short parallel form A at the start of a unit, used as a covariate and to check the randomization.
  - **(b) Delayed posttest:** form B, 1 week after a concept is practiced. Add a 4-week or end-of-term follow-up on the same concepts.
  - **(c) Near-transfer items:** new surface features, same principle.
  - **(d) Far-transfer items:** application in a new context.
  - **(e) Official course outcomes:** unit exam items mapped to concepts, obtained with instructor cooperation and student consent through a FERPA-compliant release.
  - **(f) Concept inventory:** a validated one where it exists (e.g., FCI-type instruments in physics or chemistry).
- **Outcome items:**
  - Write or vet them with instructors or TAs, independently of the generator.
  - Make them selected-response or human-scored.
  - Freeze and preregister them before treatment.
  - Never expose them in tutoring.
  - Report in-system check accuracy only as a secondary, mechanism measure.
- **Parallel forms:** build them by random split from a vetted item pool, and check equivalence via item p-values from the pilot.
- **Tool-free condition:** the current tool-free post-test (2 days or more) is a good start. Lengthen the delay to at least 1 week, add the pretest, and add the comparison condition.

### Gaps
- I found no source quantifying how much LLM-generated outcome items inflate effects vs independent items. Inferred from Kraft's alignment finding.

## Q5. Preregistration, standards (WWC/ESSA), IRB, consent, ethics

### Takeaway
Preregister on OSF (or AsPredicted, or the Registry of Efficacy and Effectiveness Studies) before data collection, with hypotheses, primary outcome, analysis model and exclusion rules. Target WWC "Meets Standards Without Reservations" features: random assignment, low attrition, and no confounds. For ESSA, one well-run RCT can technically reach Tier 1 ("Strong") in K-12 framing, but higher-ed buyers and researchers care more about independent replication. Partnering with a university faculty member gives access to the university IRB and the course outcomes, and buys credibility.

### Cited Findings
- WWC Procedures and Standards Handbook v5.0 (Aug 2022, rev. Dec 2022) is the current standard. — [handbook PDF mirror, Univ. of Memphis](https://memphis.edu/crep/pdfs/resources/wwc-handbook-ver5_0-0-508_1.pdf)
  - Randomized assignment with low attrition can meet standards without reservations. Non-random designs can at best meet standards with reservations. — [Dachet et al. 2026 citing WWC 2022 p. 41](https://orbi.umons.ac.be/bitstream/20.500.12907/54690/1/Dachet%20et%20al.%20%282026%29%20-%20ADMEE%20MTSS-K.pdf) [secondary]
  - High attrition (overall plus differential) bars the top rating. — [WWC attrition brief](https://ies.ed.gov/ncee/WWC/Docs/ReferenceResources/wwc_brief_attrition_080715.pdf); [attrition v3.0](https://ies.ed.gov/ncee/WWC/Docs/ReferenceResources/wwc_attrition_v3.0.pdf)
- ESSA evidence tiers: Tier 1 Strong is experimental, Tier 2 Moderate is quasi-experimental, Tier 3 Promising is correlational with statistical controls. — [Empirical Education explainer](https://medium.com/@empiricaleducation/evidence-according-to-essa-ebe981132e36); [AIR ESSA services](https://air.org/sites/default/files/ESSA-Tiers-of-Evidence-Services-April-2020.pdf)
- Florida requires an ESSA tier plus an effect size of at least 0.20 for some programs. — [Lexia white paper](https://www.lexialearning.com/user_area/content_media/raw/HowEffectSizeisRaisingtheBarforEdTechEvaluation.pdf) (vendor source)
- Critique: a single old RCT on a since-changed product version can earn "Strong". — [MIND Research blog](https://blog.mindresearch.org/blog/why-essa-tier-system-is-only-step-one) (vendor commentary)
- Kraft: IES-funded RCTs, which require preregistration and reporting, have a median effect of 0.03 SD. Preregistration predicts smaller and more credible effects. — [Kraft 2020](https://doi.org/10.3102/0013189X20912798)

### Inferences
- **Practical ethics plan:**
  - **IRB route:** partner faculty use their university IRB. Comparing standard practice with a supplement is usually expedited or exempt under the Common Rule, category 1 (normal educational practices), but that is the IRB's decision. Without a partner, use an independent commercial IRB.
  - **Consent:** obtain opt-in research consent separate from terms-of-service. Allow data withdrawal.
  - **Course grades:** for linking course grades, get FERPA consent or have the institution supply them.
  - **No grade harm:** design so no student is disadvantaged on graded work. Use within-student randomization of non-graded practice, give the control group access before high-stakes exams, or randomize only feature variants.
  - **Data handling:** de-identify the analysis data. Note that Sapling already encrypts sensitive columns, which helps.
- **Credibility multipliers:**
  - Have an independent evaluator or academic co-author run the analysis.
  - Preregister the analysis code on synthetic data.
  - Report all preregistered outcomes, including nulls.
  - Publish an open dataset or code where consent allows.

### Gaps
- I did not verify current commercial IRB fees, for example from WCG or Advarra. No reliable source was retrieved, so leave the figure unstated or have someone look it up.
- I did not extract the exact WWC v5.0 attrition thresholds or its "over-alignment" language.
- I did not verify OSF or REES specifics in this session. Both are well-known free registries, but neither was fetched.

## Q6. Edtech companies that did evaluation well, and cost

### Takeaway
The models are a large independent RCT (Carnegie Learning/RAND: about 0.2 SD in the second implementation year only, a roughly $6M research budget), a research-platform approach (ASSISTments E-TRIALS: continuous student-level A/B tests inside the product, grant-funded), and a fast exploratory RCT with a lab partner (Eedi × DeepMind: 165 students, then scaling). For a startup, the platform approach (feature RCTs) plus one partnered, preregistered efficacy study is the feasible combination.

### Cited Findings
- Carnegie Learning Cognitive Tutor Algebra I, RAND effectiveness trial (Pane et al., 2014):
  - No significant effect in year 1. In year 2, high-school scores rose about 0.2 SD, or about 8 percentile points. — [EdWeek 2013](https://www.edweek.org/education/study-hybrid-algebra-program-nearly-doubled-math-learning/2013/06); [arXiv 1802.08616](https://arxiv.org/pdf/1802.08616)
  - Evidence for ESSA gives a weighted mean across its three qualifying studies of +0.03. Cohort 2 was +0.22 and cohort 1 was +0.07. — [Evidence for ESSA](https://evidenceforessa.org/?p=637)
  - About $6M was dedicated to the RCT. — [EdSurge 2013](https://www.edsurge.com/n/2013-08-27-the-nature-of-big-edtech-research)
  - Critics questioned the marketing claim of "doubles math learning". RAND could not separate the effect of the software from the program as a whole. — [EdSurge](https://www.edsurge.com/n/2013-08-27-the-nature-of-big-edtech-research)
- ASSISTments E-TRIALS: free or low-cost, with thousands of students available. It was historically hampered by scattered documentation and reliance on staff help. — [arXiv 2502.10545](https://arxiv.org/html/2502.10545v2); [WPI report](https://digitalcommons.wpi.edu/iqp-all/5766)
- Eedi × Google DeepMind: an exploratory RCT (n = 165), published as a preprint within months. A 1,200-student four-arm trial and a planned US RCT with Imagine Learning in 2026 follow. — [arXiv 2512.23633](https://arxiv.org/abs/2512.23633v1); [Eedi Substack](https://eedi.substack.com/p/ai-in-education-7-five-things-i-learned)

### Inferences
- A staged plan that fits Sapling's scale and budget:
  - **Stage 0 (now to 2 months):** measurement validity work.
    - Expert audit of a stratified item sample.
    - IWF linter.
    - Grader calibration on 200–300 real double-scored responses.
    - Injection red-team.
  - **Stage 1 (one term, 2–4 partnered courses, about 100–200 consenting students):** preregistered within-student concept randomization.
    - Primary outcome: an independent, human-vetted delayed test at about 1 week.
    - Secondary outcomes: a 4-week retention test, transfer items and mapped exam items.
    - Feasible to detect about 0.2–0.3 SD.
    - Cost is mostly staff time plus participant incentives (e.g., small payments per completed test session), plus TA time for item vetting and scoring.
  - **Stage 2 (following year):** a multi-course crossover or between-student RCT with an academic partner and an independent analyst.
    - Prespecify a business-as-usual comparison and, if possible, a generic-chatbot arm.
    - Target about 400 or more students for d of about 0.2 with a pretest covariate.
    - Seek external funding, e.g., IES SBIR or NSF SBIR, or foundation grants.

### Gaps
- I found no published costs for Duolingo or Khan Academy efficacy research, and I did not research those programs in this session.
- Carnegie's per-student price was not found. Only the $6M RCT budget was found.
