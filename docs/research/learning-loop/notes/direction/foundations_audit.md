# Foundations audit: do the learning-science and AI-tutor studies behind Sapling hold up? (as of 2026-11-07)

Method note: about 20 searches and fetches, 2026-11-07. Each claim is labelled **[fetched]** (read from the primary page this session), **[search]** (search-result snippet or secondary summary, not checked against the full text) or **[training]** (from model background knowledge; the DOI or URL is given but the full text was NOT re-read this session, so verify before citing externally). Anything with no label and no source is in Gaps.

---

## 1. Bastani et al. 2025 PNAS, "Generative AI without guardrails can harm learning"

### Takeaway
Preregistered RCT, about 1,000 Turkish high-school students. The direction of the finding (unguarded ChatGPT practice → worse unassisted exam; guarded tutor → about zero) is now **corroborated in college students** by an independent Oct 2026 university RCT (−0.37 SD final grades). It is also echoed by an Aug 2026 NBER middle-school RCT (structure determines value). Verdict: **solid on direction, qualified on magnitude/generalizability.**

### Cited Findings
- Published PNAS 122(26) e2422633122, 2025. Authors H. Bastani, O. Bastani, Sungu, Ge, Kabakcı, Mariman. Preregistered RCT; primary analysis = unassisted exam outcomes across arms [search] — [PNAS](https://www.pnas.org/doi/10.1073/pnas.2422633122); [PubMed 40560616](https://pubmed.ncbi.nlm.nih.gov/40560616/); [SSRN 4895486](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4895486)
- Headline: GPT-4 access improved assisted practice performance. Unassisted exam −17% for GPT Base; GPT Tutor (teacher-designed guardrails, hints, no direct answers) "largely mitigated" the harm [search]. Practice gains were +48% (Base) and +127% (Tutor) [training; abstract figures, verify] — [PNAS](https://www.pnas.org/doi/10.1073/pnas.2422633122)
- A **correction** was published 2025-08-20 (PNAS e2518204122). Its content could not be read: the fetch returned 403. Must check whether it touches any effect estimate — [Correction](https://www.pnas.org/doi/10.1073/pnas.2518204122)
- No formal comment/reply, PubPeer thread, or direct replication of the Turkish trial was found in searches [search].
- **Independent college-level corroboration, Oct 2026 (preprint, not peer-reviewed):** Liu, Sweet, Chen, Engelberg, Masters, Clark, Persaud, Lancaster, Hollingsworth, King Rice. "The Effects of Course-Integrated AI Tutoring on Student Performance and Engagement: A Randomized University Trial," EdWorkingPaper 26-1598. N = 2,379 undergrads, 30 instructors, multiple disciplines, large US public university. Within the same course, tutor access **reduced final grades by 0.37 SD** and LMS participation by **0.90 SD**; losses were larger for first-generation students; the authors' mechanism is displacement of existing learning activities [fetched abstract] — [EdWorkingPapers 26-1598](https://edworkingpapers.com/ai26-1598); [PDF](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf)
- **Aug 2026 follow-up by an overlapping author (Sungu), NBER WP 35621 (not peer-reviewed):** Oreopoulos, Liut, Sungu, Low, "Making AI Tutoring Productive." More than 6,000 middle-schoolers (Hamilton County, TN), March 2026, 3-way individual randomization (AI vs CAL-only × mastery vs non-mastery × topic), **1-week delayed assessment**. AI students progressed more slowly but improved next-attempt correctness after mistakes. "Mastery increased three-correct-in-a-row attainment but did not by itself improve delayed learning." The best delayed-test signal came from AI embedded in the mastery workflow, and it was only "marginally significant," concentrated on practiced material. Guardrailed tutor (no direct answers) [fetched PDF p.1–3] — [NBER w35621](https://www.nber.org/system/files/working_papers/w35621/w35621.pdf); [AEA registry AEARCTR-0018678](https://www.socialscienceregistry.org/trials/18678)
- An arXiv meta-analysis of LLM effects on students exists (2509.22725) — not read — [arXiv](https://arxiv.org/pdf/2509.22725)

### Inferences
- The "unguarded AI harms unassisted performance" claim is now among the better-supported AI-ed findings: two independent RCTs (Turkey HS 2024; US university 2026) agree in direction. Sapling's answer-withholding (H0–H6) is consistent with this.
- The "guardrailed tutor ≈ 0 harm" half is weaker as a *positive* case. Guardrails avoided harm but did not produce exam gains in Bastani. The NBER trial shows only marginal delayed gains even with guardrails + mastery. The UMD trial is a warning that even a course-integrated tutor can be net-negative via displacement. Design implication: Sapling should measure *displacement* (time taken from other study) and subgroup effects (first-gen), not just in-tool gains.

### Gaps
- Content of the 2025-08-20 PNAS correction (403).
- Whether the UMD tutor had guardrails/answer withholding: the abstract doesn't say. Must read the full PDF before using it as "guardrails don't help."

---

## 2. Kestin et al. 2025 Scientific Reports (Harvard physics AI tutor vs active learning)

### Takeaway
Single-site crossover RCT, roughly 194 students, two short lessons, immediate post-test only, authors' own tutor. Large effects (0.73–1.3 SD) have **no independent replication** as of Nov 2026. A later large university RCT (UMD 2026) found harm from a different course-integrated tutor. Verdict: **qualified/shaky as an effect-size anchor; fine as proof-of-concept for a carefully designed tutor.**

### Cited Findings
- Kestin, Miller, Klales, et al., "AI tutoring outperforms in-class active learning: an RCT introducing a novel research-based design in an authentic educational setting," Sci Rep, published 2025-06-03. Harvard, Fall 2023, crossover design [fetched, partial] — [Nature/Sci Rep](https://www.nature.com/articles/s41598-025-97652-6); [ETC Journal review, 2025-11-10](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/)
- Median post-test 4.5 (AI) vs 3.5 (active learning); median gains more than double; about 194 students; median about 49 min with the tutor vs a 60-min class [search; secondary summaries] — [Sci Rep](https://www.nature.com/articles/s41598-025-97652-6); [erctpapers summary](https://erctpapers.com/papers/47-kestin-et-al-2025-ai-tutoring-active-learning.html)
- Effect sizes 0.73–1.3 SD; post-test immediately after each lesson (no delayed retention test); outcomes are researcher-made tests aligned to the lesson; the authors note a possible ceiling effect and that higher-order/complex tasks may differ [training + search; verify against the paper's tables] — [Sci Rep](https://www.nature.com/articles/s41598-025-97652-6)
- No independent replication found; the paper treats replication as future work [search; single secondary source] — [erctpapers](https://erctpapers.com/papers/47-kestin-et-al-2025-ai-tutoring-active-learning.html)
- No formal peer-reviewed critique/comment found. The Nov 2025 ETC Journal "review" is an editor's blog written with Claude assistance, not a peer critique [fetched] — [ETC Journal](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/)
- Popular coverage inflates it ("30% higher," "twice the learning") [search] — [bookbotkids](https://www.bookbotkids.com/updates/edtech/ai-tutoring-outperforms-classroom/)

### Inferences
- Structural reasons to discount: (a) Kraft 2020 shows effects on researcher-designed, proximal, short-duration outcomes run much larger than standardized/distal ones; (b) Lortie-Forgues & Inglis 2019 find an average large-RCT effect of about 0.06 SD; (c) single site, elite population, novelty, developer-built tool, no delayed test. A realistic expectation for a durable, transferable effect is likely an order of magnitude smaller.
- Kestin's tutor design (pre-scripted step-by-step scaffolds, no answer giving, active-learning-aligned prompts) is still a reasonable design template. What is shaky is the *size*, not the *direction* under tight design.

### Gaps
- Could not read the full paper this session to confirm exact SD figures, attrition, and the ceiling discussion.
- No search hits on PubPeer or a journal comment, so absence is not proven.

---

## 3. Bloom 1984 "2 sigma"

### Takeaway
Consensus: 2σ is an outlier and an upper bound. It comes from small, short dissertation studies of tutoring **plus** mastery learning at a 90% criterion, measured on unit-aligned tests. VanLehn 2011 puts human tutoring at d ≈ 0.79 vs no tutoring, and step-based ITS at ≈ 0.76. Verdict on 2σ: **refuted as a benchmark.** VanLehn's ≈0.8 is **qualified** (small, older studies; proximal tests).

### Cited Findings
- 2σ origin: two U. Chicago dissertations (Anania; Burke), about 3-week units (probability, cartography), tests written for the units. Tutored group also used mastery learning at a 90% criterion vs 80% for the mastery class. VanLehn argues the stricter criterion explains much of it; a replication of one Bloom study found d = 0.52 [fetched] — [Nintil, 2019, upd. 2020](https://nintil.com/bloom-sigma/); [Wikipedia](https://en.wikipedia.org/wiki/Bloom%27s_2_sigma_problem)
- VanLehn 2011, *Educational Psychologist* 46(4):197–221: human tutoring d ≈ 0.79, step-based ITS ≈ 0.76, answer-based ≈ 0.31 [training for exact citation/DOI 10.1080/00461520.2011.611369; numbers corroborated by search + Nintil] — [Nintil](https://nintil.com/bloom-sigma/)
- Other software-tutoring meta-analyses: Ma et al. 2014 ITS g ≈ 0.41; Kulik & Fletcher 2016 ITS 0.66 overall, ≈0.75 post-secondary; DARPA Digital Tutor 1.97–3.18 (small N, partly developer tests) [fetched via Nintil] — [Nintil](https://nintil.com/bloom-sigma/)
- Large-scale K-12 tutoring meta-analysis: Nickow, Oreopoulos & Quan (2020, NBER w27476) pooled ≈ 0.37 SD [training, verify]. A cited "2024 preK–12 meta pooled 0.288" could not be verified [search] — [iatrox blog](https://www.iatrox.com/blog/blooms-2-sigma-problem-can-ai-deliver-tutoring-at-scale)

### Inferences
- For product claims, ≈0.3–0.4 SD (high-dosage human tutoring at scale) is the defensible ceiling to aim at. ≈0.8 applies only on proximal measures. 2σ should not appear in design docs as a target.

### Gaps
- Primary VanLehn PDF not re-read this session.

---

## 4. Wilson et al. 2019 "Eighty Five Percent Rule"

### Takeaway
A **theoretical** result for gradient-descent learners on binary classification with Gaussian noise (optimal error ≈ 15.87%). It was demonstrated in simulations (perceptron, a perceptual-learning network model), not in human experiments. I found **no direct human experimental confirmation** in this session. Verdict: **shaky as a design constant for college tutoring.** It is a heuristic at most. Sapling's move to phase-specific bands is better supported than a single 85% target.

### Cited Findings
- Wilson, Shenhav, Straccia, Cohen, *Nature Communications* 10:4646 (2019), doi 10.1038/s41467-019-12552-4. Optimal training error ≈ 15.87% for SGD-based learners in two-choice tasks with Gaussian noise. Demonstrated on one/two-layer networks and a perceptual-learning model. Claims "exponential" learning-speed improvement [search] — [Nat Commun](https://www.nature.com/articles/s41467-019-12552-4); [PMC6831579](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6831579/)
- Press/commentary: the evidence is machine-learning simulations; human/animal support is via consistency with prior studies, not new experiments; the lead author expected it to apply mainly to perceptual learning; extension to complex learning is untested [search] — [Neuroscience News](https://neurosciencenews.com/learning-optimized-15171/); [Big Think](https://bigthink.com/neuropsych/learning-failure/); [AQR "rule" caveat](https://aqrinternational.co.uk/the-eighty-five-percent-rule-for-optimal-learning-2)
- Classroom-observation figures sometimes cited as convergent (Rosenshine: ≈80% success in effective classrooms; 82% vs 73% correct between most/least effective teachers) are correlational [search] — [Scott H. Young, 2022](https://www.scotthyoung.com/blog/2022/07/05/85-percent-rule/)

### Inferences
- The derivation's assumptions do not map onto college conceptual learning: binary choices, a fixed learner, Gaussian decision noise, learning-rate-only objective, no retention/transfer measure. Desirable-difficulties work (retrieval practice, spacing) suggests the optimum for *durable* learning may sit at lower success rates than the optimum for *in-session acquisition speed*. That supports phase-specific bands (e.g., higher success in teach/check, lower in review/retrieval).
- Sapling's bands should be treated as **tunable hypotheses** logged against delayed post-tests, not as constants with literature backing.

### Gaps
- **Not verified:** Al-Fawakhiri (2023, bioRxiv/published?), van der Kooij (2026), Yamada (2025). Four searches returned no hits for these names alongside the 85% rule. They may exist under different titles. Do not cite them until someone pulls the papers via Google Scholar's "cited by" on the Wilson paper.

---

## 5. Expertise reversal effect (Kalyuga) and Tetzlaff et al. 2025 meta-analysis

### Takeaway
Tetzlaff, Simonsmeier, Peters & Brod (2025, *Learning and Instruction* 98:102142) is the first comprehensive meta-analysis: 60 experiments, 176 effects, N = 5,924. They conclude the effect is robust across contexts, and asymmetric: helping novices matters more than withholding help from experts. Verdict: **solid (qualified on magnitude).**

### Cited Findings
- Screened 1,590 records → 60 experiments, 176 effect sizes, 5,924 participants; PRISMA. "Robust across a wide variety of contexts"; "providing novices with assistance has a stronger effect than withholding assistance from experts" [search, from abstract on pedocs/ResearchGate] — [pedocs open access](https://www.pedocs.de/frontdoor.php?la=en&source_opus=34113&nr=1&anker=start&zeitschriftentitel=Learning+and+instruction&zeitschriftenjahr=2025&zeitschriftenband=98); [ResearchGate](https://www.researchgate.net/publication/390916755_A_cornerstone_of_adaptivity_-_A_meta-analysis_of_the_expertise_reversal_effect); DOI 10.1016/j.learninstruc.2025.102142
- Secondary figures: d ≈ 0.505 low prior knowledge (favoring more assistance), d ≈ −0.428 high prior knowledge (favoring less), heterogeneous [search; NOT verified against paper] — [Mapping Ignorance, 2026-10-14](https://mappingignorance.org/2026/10/14/ai-problem-solving-and-the-future-of-stem-education/)
- Older reanalysis debate exists ("Reanalyzing the expertise reversal effect") — not read — [ResearchGate](https://www.researchgate.net/publication/225348616_Reanalyzing_the_expertise_reversal_effect)
- Kalyuga, Ayres, Chandler & Sweller 2003, *Educational Psychologist* 38(1):23–31 [training, verify]

### Inferences
- The asymmetry is directly actionable for the H0–H6 ladder: under-helping novices costs more than over-helping experts. When the mastery estimate (BKT) is uncertain, err toward more scaffolding early, and fade rather than withhold.
- The lab studies are mostly short worked-example/multimedia tasks with immediate tests. Transfer to LLM dialogue tutoring is an inference.

### Gaps
- Moderator detail (publication bias tests, delayed-test subset, college-only subset) not read.

---

## 6. ZPD operationalization (success-rate band or assistance gap)

### Takeaway
No empirical literature found that validates the ZPD as a **success-rate band**. The closest operationalizations are dynamic assessment and graduated prompting (amount of assistance needed), which have some predictive validity in children. Verdict: **shaky as a measurable construct.** Treat "ZPD" as a metaphor. Sapling's "assistance gap" framing (unassisted vs. assisted success / hint level needed) is closer to the dynamic-assessment tradition than the "success-rate band" is.

### Cited Findings
- Dynamic assessment: ZPD measurement adds diagnostic information beyond static tests (map-use, children with learning difficulties); critique that research conflates ZPD with individual developmental level [search] — [Rutland 1993, Stirling thesis](https://dspace.stir.ac.uk/handle/1893/3519)
- Preschool dynamic-assessment ZPD measures predicted later school performance (Luković et al., 2022) [search] — [scidar.kg.ac.rs PDF](https://scidar.kg.ac.rs/bitstream/123456789/16069/4/0048-57052100004L.pdf)
- Observation identifies "specific indices" of the ZPD rather than the zone itself [search] — [Starodubtseva 2020](https://journal.iro38.ru/index.php/en/142-stati-zhurnala/1-2020-en/401-studying-the-zone-of-proximal-development-in-preschool-children-by-the-observation-method)
- Theoretical critique that the ZPD is misread as a scaffolding/difficulty zone (Chaiklin 2003, "The zone of proximal development in Vygotsky's analysis of learning and instruction") [training, verify]. ITS operationalization attempts (e.g., Murray & Arroyo 2002, ITS conference) [training, verify].

### Inferences
- The defensible measurable proxies are (a) the difference between unassisted and assisted success on an item family, and (b) the minimum help-ladder rung needed. Sapling already logs both via H0–H6, so it can validate its own operationalization against delayed post-tests.

### Gaps
- No search hit on reliability of "graduated prompting" scores in adults/college; no evidence found for a % band.

---

## 7. Productive failure (Sinha & Kapur 2021)

### Takeaway
Meta-analysis in *Review of Educational Research* 91(5):761–798: 53 studies, 166 comparisons. Problem-solving-before-instruction (PS-I) beats instruction-first on conceptual knowledge and transfer, g ≈ 0.36 [0.20, 0.51], with no procedural cost. The bias-"corrected" estimate (g ≈ 0.87) is implausible. Verdict: **qualified.** The effect depends on fidelity to PF design, older learners, and conceptual outcomes, and is contested by cognitive-load theorists for high element-interactivity material.

### Cited Findings
- g = 0.36 [0.20, 0.51] for conceptual/transfer; no procedural compromise; publication-bias "corrected" g = 0.87 [search] — [Sinha & Kapur 2021 PDF](https://janfasen.nl/wp-content/uploads/2023/05/Sinha-and-Kapur-PS-I.pdf); [ResearchGate](https://www.researchgate.net/publication/352523653_When_Problem_Solving_Followed_by_Instruction_Works_Evidence_for_Productive_Failure)
- Moderator: benefits larger with higher fidelity to PF design principles and in older students; reversal reported for grades 2–5 [search; secondary] — [Fermi News](https://news.fermi.ai/research/productive-failure-meta-analysis)
- Critics argue from element interactivity (e.g., Ashman, Kalyuga & Sweller 2020, *Educational Psychology Review*, doi 10.1007/s10648-019-09500-5, explicit instruction first for high-interactivity material) [training for citation; the "element interactivity vs grade level" framing from search] — [Fermi News](https://news.fermi.ai/research/productive-failure-meta-analysis)
- Companion comparative meta-analysis of preparatory approaches (Sinha et al.) — not read — [ResearchGate](https://www.researchgate.net/publication/351889202_From_problem-solving_to_sensemaking_A_comparative_meta-analysis_of_preparatory_approaches_for_future_learning)

### Inferences
- The upward bias correction is a red flag about the correction method, not evidence of a larger true effect. Use 0.36 or less, and expect smaller on standardized/delayed measures.
- For Sapling, the "probe" step (attempt before teaching) is supported for conceptual topics with college learners. It is not supported as a default for high element-interactivity procedural content with novices. Gate it by prior knowledge, consistent with the expertise reversal.

### Gaps
- No dedicated published critique of the PF meta-analysis's bias method was found.

---

## 8. Mastery learning (Kulik 1990, Slavin 1987/1990)

### Takeaway
Effects are large on experimenter/teacher-made tests (~0.5) and near zero on standardized tests (~0.04–0.09). Modern large RCTs are small (Jerrim 2015, d = 0.06). Verdict: **qualified.** Mastery gating improves proximal mastery, but evidence for distal/transfer gains is weak. The 2026 NBER trial again found mastery progression alone did not raise delayed learning.

### Cited Findings
- Kulik, Kulik & Bangert-Drowns 1990 (RER 60(2):265–299; 108 studies, mostly college): overall 0.52; **0.08 on standardized tests** vs about 0.5 on local tests; Learning for Mastery about 0.59 [fetched via Nintil; RER citation from training] — [Nintil](https://nintil.com/bloom-sigma/)
- Slavin 1987 (RER 57(2):175–213; 17 stricter-quality studies of group-based ML): standardized-test effects about 0, median about 0 when time is controlled. Kulik et al.'s reply finds 0.36–0.45 on examiner tests vs 0.09 standardized on 11 jointly accepted studies [fetched via Nintil] — [Nintil](https://nintil.com/bloom-sigma/)
- Jerrim et al. 2015 (Mathematics Mastery, London, more than 5,000 students): d = 0.06 [fetched via Nintil] — [Nintil](https://nintil.com/bloom-sigma/)
- NBER w35621 (Aug 2026): mastery raised 3-in-a-row attainment but not delayed learning by itself [fetched] — [NBER](https://www.nber.org/system/files/working_papers/w35621/w35621.pdf)

### Inferences
- BKT mastery thresholds should be validated against **delayed, tool-free, non-aligned** items. Sapling's delayed post-tests are the right instrument. Expect the mastery signal to overstate durable learning.

### Gaps
- Primary Kulik/Slavin papers not re-read this session.

---

## 9. Education "replication crisis" context (Kraft 2020/2023; Lortie-Forgues & Inglis 2019)

### Takeaway
Realistic effects for education interventions on standardized outcomes are small. Under Kraft's benchmarks, <0.05 is small, 0.05–0.20 medium and ≥0.20 large. 36% of RCT effects are <0.05. The average large RCT effect is about 0.06 SD. Verdict: **solid**, and it should discount every number above.

### Cited Findings
- Kraft 2020, *Educational Researcher* 49(4):241–253: benchmarks from 1,942 effect sizes in 747 RCTs; effects "small" by Cohen are large for field interventions; researcher-designed, proximal, short-term outcomes yield larger effects [search] — [Kraft 2020 PDF](https://www.matthewakraft.com/s/Kraft-2020-Interpreting-Effect-Sizes-ER.pdf)
- Kraft 2023, *Educational Researcher* 52(3):183–187: 36% of standardized-outcome RCT effects are <0.05 SD; publication bias masks more failures [search] — [SAGE](https://journals.sagepub.com/doi/10.3102/0013189X231155154)
- Lortie-Forgues & Inglis 2019, *Educational Researcher*, doi 10.3102/0013189X19832850: 141 large EEF/NCEE RCTs, about 1.2M students, mean effect 0.06 SD, mean CI width 0.30 SD, median Bayes factor 0.56, about 40% uninformative. A UCL technical comment disputes design/assessment framing but not the core point [search] — [White Rose eprint](https://eprints.whiterose.ac.uk/141754/); [UCL technical comment](https://discovery.ucl.ac.uk/id/eprint/10101577/1/Informing%20better%20trial%20design%20%20%20A%20Technical%20Comment%20on%20Lortie%20Forgues%20and%20Inglis%202019.pdf)
- Cheung & Slavin 2016: effects shrink with sample size and are larger on researcher-made measures [fetched via Nintil] — [Nintil](https://nintil.com/bloom-sigma/)

### Inferences
- Summary table (verdicts above):
  - Bastani harm from unguarded AI → solid (now independently corroborated in college, UMD 2026, preprint).
  - Guardrailed tutor → avoids harm, gains unproven (qualified).
  - Kestin 0.73–1.3 SD → qualified/shaky as a magnitude; unreplicated, immediate test, single site.
  - Bloom 2σ → refuted as a benchmark; VanLehn ≈0.8 qualified; at-scale tutoring ≈0.3–0.4.
  - 85% rule → shaky for humans/college (theory + simulation only; human tests unverified).
  - Expertise reversal → solid (Tetzlaff 2025), asymmetric.
  - ZPD as a success-rate band → shaky; assistance-gap/dynamic assessment → qualified.
  - Productive failure → qualified (g ≈ 0.36, conditional).
  - Mastery learning → qualified (≈0.5 local, ≈0.05–0.09 standardized).
- Sapling should pre-register its own internal success criteria at realistic sizes (≈0.1–0.2 SD on delayed tool-free tests) and power its experiments accordingly.

### Gaps
- No check this session of Retraction Watch/PubPeer for any listed paper (no hits surfaced in general searches).
