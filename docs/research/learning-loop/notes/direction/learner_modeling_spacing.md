# Learner Modeling (Knowledge Tracing) and Review Scheduling for Sapling — evidence as of Nov 2026

Compiled 2026-11-07. Researcher notes for report writer. "Preprint" = arXiv/unreviewed at time of writing. Items marked [not re-fetched] are well-known citations given from prior knowledge with DOI; their content was not re-verified in this session.

## (a) Which KT approach wins at small data and for mastery decisions? (BKT vs IRT/Elo/PFA/LR vs DKT/attention KT)

### Takeaway
No benchmark shows deep/attention KT beating well-featured logistic models (IRT/PFA/"best-LR") at Sapling's scale (tens of students per course); deep KT wins mainly on large datasets. For mastery *decisions* (as opposed to next-answer prediction), the evidence says the choice of evidence sources and threshold matters more than the model family, so bounded BKT is defensible; the higher-value change is calibration checking and possibly a logistic/IRT-style model with item difficulty, not a deeper model.

### Cited Findings
- Gervet, Koedinger, Schneider, Mitchell (JEDM 2020, "When is Deep Learning the Best Approach to Knowledge Tracing?"): across 9 datasets, logistic regression with the right features tended to win on moderate-sized datasets or where students have very many interactions each; DKT won on large datasets and where precise timing matters; the paper includes reliability (calibration) analysis and calls calibration crucial for downstream use — [JEDM PDF](https://jedm.educationaldatamining.org/index.php/JEDM/article/download/451/123); [Zenodo record](https://zenodo.org/records/4143614)
- Empirical evaluation of deep-learning KT (arXiv 2112.15072, preprint): deep models generally beat traditional ones, but simple baselines with little predictive value can outperform DLKT on accuracy; conclusions depend strongly on baseline and metric choice — [arXiv](https://arxiv.org/abs/2112.15072v4)
- Adhikary et al. (IEEE Access, 2026, per search summary): benchmark of 9 lightweight KT families on ASSISTments 09-10 and DigiArvi 2025 with multiple calibration metrics under a time budget; traditional baselines such as logistic regression "remain highly competitive" — [search-result summary, utupub](https://www.utupub.fi/handle/11111/60233) (full text not fetched; venue/authors not independently verified)
- "Stable and Faithful Explanations for Knowledge Tracing" (arXiv 2609.28502, preprint, Sept 2026): on ASSISTments 2012, ECE ranged 0.0006 (restricted XGBoost) to 0.0236 (AKT, an attention model) while AUC varied much less; deep baselines did not beat the gradient-boosted model — [arXiv](https://arxiv.org/pdf/2609.28502) (not independently verified; preprint)
- Pelánek & Řihák (UMAP 2017 Best Paper, "Experimental Analysis of Mastery Learning Criteria"): for mastery decisions, the choice of data sources and threshold setting matter more than the learner-modeling technique; recommend a simple exponential moving average criterion plus methods to pick the threshold. 2018 journal follow-up (New Review of Hypermedia and Multimedia 24(3)) adds time-intensity and a deployment — [MUNI record](https://is.muni.cz/publication/1392193/en/Experimental-Analysis-of-Mastery-Learning-Criteria/Pelanek-Rihak); [UMAP awards](https://um.org/announcements/30-umap-2017-best-paper-awards)
- Hooshyar et al. (arXiv 2512.23036, Dec 2025; listed as IEEE Access 2026): fine-tuned LLM KT improved AUC ~8% over zero-shot but stayed ~6% below DKT; DKT produced stable, directionally correct mastery updates whereas LLM variants showed inconsistent and wrong-direction updates; fine-tuning cost ~198 h of high-compute training; authors recommend LLMs as pedagogical interface paired with a dedicated learner model — [arXiv](https://arxiv.org/abs/2512.23036)
- Khajah, Lindsey, Mozer (EDM 2016, "How Deep is Knowledge Tracing?"): BKT extended with forgetting, skill discovery and student abilities matched DKT performance [not re-fetched] — arXiv:1604.02416, https://arxiv.org/abs/1604.02416
- pyKT (Liu et al., NeurIPS 2022 Datasets & Benchmarks): standardized benchmark of ~10+ deep KT models on large datasets; found many claimed gains shrink under consistent evaluation [not re-fetched] — arXiv:2206.11460, https://arxiv.org/abs/2206.11460

### Inferences
- Deep KT (DKT, SAKT, AKT, etc.) is not appropriate for tens of students per course; no evidence it would beat BKT/LR there, and it loses interpretability. Sapling's "no deep KT" stance is consistent with evidence.
- BKT's known weaknesses (no item difficulty, no student ability, identifiability of guess/slip) are what PFA/IRT-style logistic models and BKT+ability/forgetting extensions fix. With LLM-generated items of varying difficulty, a difficulty term (IRT-like) is the most evidence-backed upgrade. The 2026 BEA dialogue-KT paper (below) also maps LLM output onto IRT ability/difficulty parameters.
- Sapling's per-channel guess/slip is hand-set. Pelánek's result implies the evidence channel choice (which channels count toward mastery) is a first-order decision; weak channels (chat turn 0.30/0.30) arguably should not count toward the mastery gate at all, only toward priors/scheduling.
- Calibration (ECE / reliability curves) of the mastery probability is not established for any hand-set BKT; Sapling should log predictions vs next-observation outcomes and check calibration once data accrues.

### Gaps
- Found no benchmark specifically at tens-of-students scale with calibration as primary metric. Adhikary 2026 and arXiv 2609.28502 full texts not read.
- Exact Gervet/pyKT numbers not re-fetched.

## (a2) LLM-based knowledge tracing from dialogue / free text — accuracy, reliability, usable as evidence?

### Takeaway
LLMs are usable as *annotators* of evidence (KC tagging, correctness labeling) with decent expert agreement in math dialogue, but are poor as the KT model itself: 2025–2026 evaluations show raw LLMs near trivial baselines and wrong-direction mastery updates. LLM grading of free-text answers shows only moderate human agreement (QWK ~0.4–0.65), degrading on higher-order items. This supports Sapling's design of treating LLM-judged channels as noisy evidence with high guess/slip feeding a classical model.

### Cited Findings
- Scarlatos, Baker, Lan (LAK 2025, "Exploring Knowledge Tracing in Tutor-Student Dialogues using LLMs"): GPT-4o annotates each dialogue turn with KCs and student-correctness; human experts judged annotations accurate; proposed LLMKT (fine-tuned Llama 3 on KT objective) significantly outperformed existing KT methods on two math tutoring dialogue datasets; authors note dialogue datasets are small and work is math-only — [arXiv 2409.16490](https://arxiv.org/abs/2409.16490v1)
- Huang, Scarlatos, Lee, Lan (BEA 2026 @ ACL 2026, "Interpretable Difficulty-Aware Knowledge Tracing in Tutor-Student Dialogues", arXiv May 2026, rev. Oct 2026): LLM estimates knowledge state and next-turn difficulty, mapped through IRT to ability/difficulty parameters for interpretability; outperforms existing KT baselines on two dialogue datasets (numbers not on abstract page) — [arXiv 2605.01097](https://arxiv.org/abs/2605.01097)
- FoundationalASSIST (Worden, Heffernan, Heffernan, Sonkar; arXiv 2602.00070, Jan 2026, preprint): 1.7M interactions from 5,000 students with full question text and actual responses; GPT-OSS-120B, Llama-3.3-70B, Qwen3-Next-80B "barely achieve a trivial baseline on knowledge tracing"; below chance on item discrimination; up to 68.6% on relative item difficulty — [arXiv](https://arxiv.org/abs/2602.00070)
- ConceptKT (arXiv 2603.24073, Mar 2026, preprint): benchmark of LLMs/reasoning models diagnosing concept-level deficiencies from student histories; tests selecting relevant past records vs full history — [arXiv](https://arxiv.org/html/2603.24073)
- Findings of ACL 2026: LLM pipeline generating/tagging KCs for open-ended programming problems plus LLM-based KT on top — [ACL Anthology](https://aclanthology.org/2026.findings-acl.1670.pdf)
- Hooshyar et al. 2025/2026: LLM mastery trajectories inconsistent and sometimes wrong-direction vs DKT (see above) — [arXiv 2512.23036](https://arxiv.org/abs/2512.23036); related case study "Why LLMs Alone Fall Short for Responsible Learner Modelling in K–12 Tutoring" — [JYX](https://jyx.jyu.fi/handle/123456789/112104)
- LLM grading agreement with humans: university sustainability course (JCAL 2026), 232 responses, LLM–human QWK 0.585–0.640 on totals vs good-to-excellent human–human reliability; agreement declined as cognitive complexity increased — [record](https://gcris.yasar.edu.tr/entities/publication/1eeab52d-b73f-42b4-baa8-f2c94edfc8c1/full). Harvard Medical School GPT-4o short answers: QWK 0.443±0.127 for factual accuracy in multi-grader set — [journal club summary](https://ctisus.com/learning/journalclub/349828). Postgrad medicine ChatGPT-4o: Cohen's κ = −0.0786 (poor) — per same search; source page not fetched. Human-in-the-loop rubric optimization improves LLM grading (arXiv 2504.05239, preprint) — [arXiv](https://arxiv.org/pdf/2504.05239)

### Inferences
- Sapling's teach-back guess/slip 0.25/0.20 and chat-turn 0.30/0.30 are directionally right: QWK ~0.6 corresponds to substantial label noise. Slip 0.20 on teach-back may be optimistic for higher-order items where agreement drops.
- Best practice from the literature: LLM produces structured labels (KC, correct/partial/incorrect, rubric criteria) and a classical model (BKT/IRT) does the tracing; never let the LLM output mastery probabilities directly.
- Sapling should measure its own judge reliability: a small double-graded set (human vs Claude judge) per course to estimate per-channel slip/guess empirically, rather than fixed constants.

### Gaps
- No found study of Claude-specific grading agreement on college conceptual answers (Sorbonne JMIR 2026 preprint includes Claude Sonnet 4 but QWK not seen).
- Exact AUC numbers for LLMKT (LAK 2025) and BEA 2026 not retrieved.

## (a3) Does the mastery threshold (0.95 vs 0.98) matter?

### Takeaway
Yes, modestly. Zhang et al. (EDM 2025, Rori data) found 0.95 still useful but 0.98 gave additional benefit in next-lesson performance and learning; an earlier JEDM randomized experiment found higher thresholds reduced forgetting but the advantage shrank over time. Sapling's 0.98 + 3 strong unassisted observations is at the conservative end and is supported, at the cost of more practice.

### Cited Findings
- Zhang, Vanacore, Baker, et al., Mills, Henkel (EDM 2025, pp. 427–433, "How Much Mastery is Enough Mastery?"): Rori (foundational math, users in African countries); end-of-lesson BKT estimates binned into 8 levels; 0.95 "remains relevant" but "higher thresholds, such as 0.98, yield additional benefits" in performance and learning in the subsequent lesson. Effect sizes not visible in fetched text — [EDM 2025 PDF](https://educationaldatamining.org/edm2025/proceedings/2025.EDM.short-papers.4/2025.EDM.short-papers.4.pdf); [Baker lab copy](https://learninganalytics.upenn.edu/ryanbaker/edm25_short_bkt%20threshold_CR_final.pdf)
- JEDM randomized experiment comparing mastery thresholds: higher threshold → less forgetting, but advantage shrinks over time — [JEDM article 900](https://jedm.educationaldatamining.org/index.php/JEDM/article/download/900/254)
- Pelánek & Řihák 2017: threshold choice and data sources matter more than the model — [MUNI](https://is.muni.cz/publication/1392193/en/Experimental-Analysis-of-Mastery-Learning-Criteria/Pelanek-Rihak)

### Inferences
- The 0.98 threshold is only meaningful if BKT parameters are roughly calibrated; with hand-set guess/slip, "0.98" is a nominal number. The "3 strong unassisted observations" rule is a sensible guard that makes the decision robust to miscalibration (it resembles an N-consecutive-correct / EMA criterion Pelánek favors).
- The shrinking forgetting advantage supports pairing mastery with spaced review (which Sapling does) rather than raising the threshold further.

### Gaps
- Rori is K-12 foundational math in Africa; no evidence found for college conceptual material. Exact effect sizes not extracted.

## (b) Spaced-repetition scheduling: FSRS vs HLR vs DASH; evidence beyond flashcards

### Takeaway
On the open srs-benchmark (~10k Anki users, ~350M evaluated reviews, all flashcards), FSRS-6 is the best non-neural model (log loss 0.346, RMSE-bins 0.065), clearly ahead of HLR and somewhat ahead of DASH variants; neural sequence models (LSTM/GRU/RWKV) beat it. The peer-reviewed basis is Ye et al. KDD 2022 / TKDE 2023 (MaiMemo vocabulary). There is essentially no evidence of FSRS validity for conceptual/problem-solving material; all benchmark data are flashcards. FSRS-6 is a reasonable default but its per-user optimization needs more reviews than a semester of tens of students per course provides — expect to run near default parameters.

### Cited Findings
- srs-benchmark (open-spaced-repetition, fetched Nov 2026). Evaluation on 9,999 collections, 349,923,850 reviews (excluding same-day); 10,000 collections, 519,296,315 reviews (including same-day); data = Anki flashcard reviews. Log Loss / RMSE(bins) / AUC excluding same-day: FSRS-6 0.3460/0.0653/0.7034; FSRS-5 0.3561/0.0742/0.7010; FSRS-4.5 0.3625/0.0764/0.6891; DASH 0.3682/0.0838/0.6311; DASH[MCM] 0.3688/0.0861/0.6343; DASH[ACT-R] 0.3728/0.0886/0.6239; ACT-R 0.4033/0.1074/0.5225; HLR 0.4694/0.1275/0.6369; LSTM 0.3332/0.0538/0.7329; GRU (pretrained) 0.3328/0.0549/0.7324; RWKV-Curve 0.3193; RWKV-Instant 0.2773. Including same-day reviews: FSRS-6 0.3842, DASH 0.3487, DASH[MCM] 0.3459, HLR 0.7050. Log-loss 99% CIs ~±0.004–0.008. Parameter counts: FSRS-6 21, DASH 9, HLR 3. The page now also lists FSRS-7 and notes default parameters perform worse than per-user optimization — [GitHub srs-benchmark](https://github.com/open-spaced-repetition/srs-benchmark); [Expertium benchmark explainer](https://expertium.github.io/Benchmark.html)
- Note: when same-day (short-term) reviews are included in evaluation, DASH/DASH[MCM] have lower log loss than FSRS-6 (0.346–0.349 vs 0.384) — same source. Relevant to Sapling's same-session successive relearning steps.
- Ye, Su, Cao (KDD 2022, "A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling", pp. 4381–4390): memory model + SSP scheduler minimizing review cost; 12.6% improvement over prior SOTA; deployed in MaiMemo (vocabulary). Extension: Su, Ye, Nie, Cao, Chen, IEEE TKDE 35(10):10085–10097, doi:10.1109/TKDE.2023.3251721. Data: 220M MaiMemo logs, doi:10.7910/DVN/VAGUL0 — [SSP-MMC repo](https://github.com/maimemo/ssp-mmc); [HIT scholar record](https://scholar.hit.edu.cn/en/publications/a-stochastic-shortest-path-algorithm-for-optimizing-spaced-repeti/)
- Community-reported concern: FSRS-5+ regresses for a minority of users who press "Again" a lot on new/learning cards — [Anki forum thread](https://forums.ankiweb.net/t/fsrs-5-is-a-significant-regression-for-a-minority-of-users-who-use-again-a-lot-on-new-and-learn-cards/66593?page=2) (forum, not peer-reviewed)
- DASH origin: Lindsey, Shroyer, Pashler, Mozer (Psychological Science 2014, "Improving students' long-term knowledge retention through personalized review"), classroom Spanish vocabulary, personalized review beat generic spaced review [not re-fetched] — doi:10.1177/0956797613504302

### Inferences
- FSRS-6 is best-in-class among interpretable schedulers for item recall; but Sapling schedules *concepts* reviewed with *varying, freshly generated* items. FSRS assumes the same card recurs; with new item variants each review, "difficulty" partly reflects item variance, not memory. No benchmark covers this. Treat FSRS stability as an approximate forgetting-curve prior, not a validated model.
- With tens of students and few reviews per concept, per-user FSRS optimization will not converge; use defaults or pool parameters across course/cohort (the benchmark's pretrained-GRU result shows pooling helps neural models; default FSRS is worse than optimized).
- Ordering by |R−0.33|: I could not confirm a DASH paper prescribing 0.33 as the target; DASH is a memory model, not a priority rule. Labeling this "DASH" in Sapling docs may be a misattribution — verify source (possibly Khajah, Lindsey & Mozer 2014 Topics in Cognitive Science on review thresholds). Combined with FSRS's 0.90 retention target, the two rules conflict: items are due at R≈0.90 but prioritized toward R≈0.33, i.e., the most overdue items are favored. That is defensible under a capped 12 min/day budget (overdue items gain the most stability per review per FSRS's stability-increase function), but it should be described as an overdue-triage policy.
- Since DASH beats FSRS-6 when same-day reviews are evaluated, Sapling's same-day relearning steps should not rely on FSRS predictions for intra-day scheduling (fixed relearning steps are fine).

### Gaps
- No peer-reviewed evaluation of FSRS on conceptual/problem-solving material, or in college courses, found.
- No found independent (non-FSRS-author) peer-reviewed comparison of FSRS vs HLR vs DASH; srs-benchmark is maintained by FSRS developers (open data/code, but not peer-reviewed).
- Minimum review count for useful FSRS optimization not stated on benchmark page.

## (c) Retrieval practice, spacing, successive relearning, interleaving — robustness for college conceptual material

### Takeaway
Retrieval practice and spacing are among the most robust findings in learning science, including in real classrooms (Yang et al. 2021 classroom g≈0.50). Transfer effects are smaller and depend on moderators (Pan & Rickard 2018: bias-adjusted intercept often ~0 transfer without supportive moderators). Spacing retrieval beats massing (Latimier 2021 g≈0.74), but expanding vs uniform schedules don't differ (g≈0.03), which weakens the case for precision scheduling algorithms over simple spacing. Successive relearning has college course field evidence (~letter-grade gains in intro psych), but a smaller effect for problem-solving (d=0.28). Interleaving helps mainly for discriminating similar categories; small for math (g=0.34), null for expository text, negative for words.

### Cited Findings
- Yang, Luo, Vadillo, Yu, Shanks (Psychological Bulletin 2021, 147(4):399–435, doi:10.1037/bul0000309), "Testing (quizzing) boosts classroom learning": classroom quizzing improved learning ≈ g = 0.50 (per secondary summary); proposed mechanisms: additional exposure, transfer-appropriate processing, motivation — [HKBU record](https://scholars.hkbu.edu.hk/en/publications/testing-quizzing-boosts-classroom-learning-a-systematic-and-meta-/); [PDF mirror](https://gwern.net/docs/spacedrepetition/2021-yang.pdf)
- Latimier, Peyre, Ramus (Educational Psychology Review 2021, 33:959–987): spacing retrieval practice vs massed g = 0.74 (29 studies, 39 effect sizes); expanding vs uniform intervals g = 0.034 (no difference). Numbers from a secondary summary — verify against paper [doi:10.1007/s10648-020-09572-8, not re-fetched] — [ACU summary](https://inspire.acu.edu.au/articles/spaced-practice)
- Pan & Rickard (Psychological Bulletin 2018, transfer of test-enhanced learning): moderator effects minimally affected by publication-bias checks, but intercept predictions substantially reduced, often indicating no positive transfer when no moderators present — [PDF](https://sc-pan.github.io/pdf/PR_2018.pdf)
- Agarwal et al. 2021 systematic review: retrieval practice improved learning across education levels, content areas, designs, delays and formats; only 6% of experiments in non-WEIRD countries — [Springer](https://link.springer.com/10.1007/s10648-021-09595-9)
- Classroom practice-test meta-analysis (EPR 2023): minimal publication-bias evidence; reduces test anxiety g = −0.52 — [Springer](https://link.springer.com/article/10.1007/s10648-023-09801-w)
- Adesope, Trevisan, Sundararajan (Review of Educational Research 2017): practice tests beat restudy across 272 effect sizes [details not re-fetched] — doi:10.3102/0034654316689306
- Carpenter, Pan, Butler (Nature Reviews Psychology 2022, "The science of effective learning with spacing and retrieval practice") [not re-fetched] — doi:10.1038/s44159-022-00089-1
- Successive relearning: Rawson, Dunlosky, Sciartelli (EPR 2013) intro psychology course — improved course exam scores and long-term retention; summarized as ~a letter grade over spaced restudy/baseline — [EPR PDF](https://springerlink.bibliotecabuap.elogim.com/content/pdf/10.1007/s10648-013-9240-4.pdf); [teacher guide summary](https://www.sec-ed.co.uk/content/best-practice/a-teacher-s-guide-to-retrieval-practice-successive-relearning). Follow-ups: Janes et al. 2020 biopsychology course; Higham et al. 2022 classroom, better end-of-semester recall than restudy — [Dunlosky et al. guide](https://www.unh.edu/teaching-learning-resource-hub/sites/default/files/media/2023-06/itow-successive-relearning-dunlosky-greve-badali-wissman-rawson.pdf). Review: Current Directions in Psychological Science 2022, "underexplored but potent" — [SAGE](https://journals.sagepub.com/doi/full/10.1177/09637214221100484)
- Successive relearning boundary: Rawson, Dunlosky & Janes, probability problem-solving — only small advantage over single-session learning, pooled d = 0.28 — [ERIC EJ1263194](https://searchworks.jioinstitute.edu.in/articles/eric__EJ1263194)
- NSF grant ($552k) to Dunlosky/Rawson/Kent State for web flashcard successive relearning in intro chemistry and STEM — [Kent State](https://www.kent.edu/sole/news/nsf-grant-supports-kent-state-researchers-plan-help-students-improve-study-habits)
- Spacing for math procedures: Rohrer & Taylor (2006) — 216 college students; distributed practice boosted long-term retention, overlearning did not — [USF](https://digitalcommons.usf.edu/psy_facpub/1770/). Emeny et al. 2021 engineering precalculus course: spaced quizzes produced realistic confidence vs overconfidence under massing. Ebersbach & Barzagar Nazari (2020): no distributed-practice effect for procedural math retention — [Frontiers 2020](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2020.00811/pdf); [EPR 2022 review](https://link.springer.com/10.1007/s10648-022-09677-2)
- Interleaving: Brunmair & Richter (Psychological Bulletin 2019, 145(11):1029–1052, doi:10.1037/bul0000209), 59 studies/238 effect sizes/158 samples: paintings g = 0.67; math tasks g = 0.34 (small); expository texts and tastes non-significant; words favored blocking g = −0.39; larger effects when between-category similarity is high, within-category similarity low, and materials complex — [PubMed](https://pubmed.ncbi.nlm.nih.gov/31556629/); [author PDF](https://www.psychologie.uni-wuerzburg.de/fileadmin/06020400/2019/Brunmair_Richter_in_press__2019_META-ANALYSIS_OF_INTERLEAVED_LEARNING.pdf)
- Dunlosky et al. (PSPI 2013) rated practice testing and distributed practice "high utility"; interleaving "moderate" [not re-fetched] — doi:10.1177/1529100612453266

### Inferences
- Sapling's core (retrieval-based review, spaced, successive relearning) is evidence-backed for college courses. The 3+3 successive relearning default follows Rawson & Dunlosky's typical criterion-3-then-3-relearning-sessions design, supported in intro psych/biopsych courses; expect smaller gains for problem-solving concepts (d≈0.28).
- Latimier's null expanding-vs-uniform result implies the marginal benefit of FSRS precision over simple spacing is unproven for learning outcomes (FSRS is optimized for recall prediction, not shown to raise exam scores). Sapling should A/B the scheduler only if cheap; otherwise do not over-invest.
- For transfer to novel problems, retrieval items should vary (application/elaborative questions), consistent with Pan & Rickard moderators. LLM-generated varied items are an advantage here.
- Interleaving should be applied selectively: mix confusable concepts within a course (similar categories, e.g., which statistical test applies) not across unrelated topics; avoid for definitional/vocabulary items.

### Gaps
- No 2024–2026 publication-bias-corrected meta-analysis of retrieval practice found in this session.
- Effect sizes for Yang 2021 and Latimier 2021 come from secondary summaries.

## (d) Combining KT with LLM tutors in practice (2025–2026)

### Takeaway
Industry and academic consensus in 2025–2026 is "LLM as interface/annotator + separate learner model." Eedi/Google DeepMind's RCT (165 students, exploratory) used LearnLM inside Eedi's diagnostic-question system, triggered after an incorrect diagnostic answer. No published Khan Academy/Khanmigo or Carnegie Learning KT-with-LLM evaluation found.

### Cited Findings
- Google/Eedi exploratory RCT (arXiv 2512.23633, Dec 2025, preprint): 165 UK students, 7 weeks; arms: static hints, human text tutor, LearnLM drafting with human approval; LearnLM arm at least as good as human tutors on all measures; novel problems 66.2% vs 60.7% (+5.5 pp); tutors approved 76.4% of LearnLM drafts with little/no edits; AI activates only after an incorrect diagnostic question — [arXiv](https://arxiv.org/abs/2512.23633v1); [Eedi Substack](https://eedi.substack.com/p/ai-in-education-7-five-things-i-learned)
- Eedi's separate 2-year platform trial: no clear difference at 6 months, effect size 0.17 at 12 months; four-arm follow-up running until July 2026 (results not found) — per search summary of [Eedi Substack](https://eedi.substack.com/p/ai-in-education-7-five-things-i-learned)
- Hooshyar et al. 2025/2026 recommend dedicated learner models paired with LLM interfaces — [arXiv 2512.23036](https://arxiv.org/abs/2512.23036)
- Stanford SCALE research note on emerging AI tutoring strategies — [SCALE](https://scale.stanford.edu/news/research-notes-two-emerging-strategies-using-ai-tutoring) (not fetched)

### Inferences
- Sapling's architecture (Claude tutor + classical BKT + FSRS) matches the 2025–2026 recommended pattern. Main levers for improvement: empirically estimate channel noise; add item difficulty (IRT-style) to evidence; validate calibration; restrict mastery gating to high-validity channels.

### Gaps
- No found published KT evaluation from Khan Academy, Carnegie Learning (MATHia+LLM), or college-level LLM tutors. Eedi four-arm 2026 results not found.
