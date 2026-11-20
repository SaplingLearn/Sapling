# Evidence for contested design choices in an AI tutoring loop (as of Nov 2026)

Scope: six features from the "Agent Harness for Learning Things" design (Eero Alvar, 2026), compared with Sapling's current loop. Sapling today uses graded checks as the only mastery evidence. It does not treat chat text as evidence, uses confidence for diagnosis only, keeps a concept graph with prerequisite edges, and limits each turn to 5 sentences and 1 question.

Source-handling note: items marked **[verified this session]** were confirmed via search or fetch on 2026-11-07. Items marked **[canonical, DOI from prior knowledge]** are well-known papers whose bibliographic details were not re-fetched this session. Their effect-size figures are restated only where the claim is widely reproduced; the writer should spot-check those DOIs. Items marked **[preprint]** are arXiv or other preprints and have not been peer-reviewed.

---

## Q1. Prediction / pretesting / generation before explanation (feature a: predict-before-explain)

### Takeaway
Asking learners to answer or guess *before* they are taught reliably improves later learning, even when the guesses are wrong, **provided the correct answer and explanation follow promptly**. The evidence is strongest for facts and text or video content. It is thinner and more mixed for multi-step conceptual STEM reasoning. A pre-question per *topic or segment* is well supported. Forcing a prediction before *every* reasoning step has no direct evidence, and the costs are plausible for novices.

### Cited Findings
- Pan & Carpenter (2023) review the field in *Educational Psychology Review* 35:97: "Prequestioning and Pretesting Effects: a Review of Empirical Research, Theoretical Perspectives, and Implications for Educational Practice." They cover more than 60 peer-reviewed articles since the early 2000s. Prequestions and pretests "can often enhance learning," with benefits found for text, video and lecture materials, even when early answers are mostly wrong. The benefit depends on learners then studying the correct answers, and its size varies with procedure and how learning is measured. Moderators and classroom best practice are still open. — [Pan & Carpenter 2023, DOI 10.1007/s10648-023-09814-5](https://link.springer.com/10.1007/s10648-023-09814-5) **[verified this session]**; NSF public-access copy: [par.nsf.gov](https://par.nsf.gov/servlets/purl/10511812)
- Kornell, Hays & Bjork (2009) found that unsuccessful retrieval attempts (guessing before seeing the answer) improved later memory compared with pure study time on weakly related word pairs. — [JEP:LMC 35(4), DOI 10.1037/a0015729](https://doi.org/10.1037/a0015729) **[canonical, DOI from prior knowledge]**
- Richland, Kornell & Kao (2009) found that pretesting on text passages improved later learning even when pretest answers were wrong, and the benefit was not explained by extra exposure alone. — [JEP:Applied 15(3), DOI 10.1037/a0016496](https://doi.org/10.1037/a0016496) **[canonical, DOI from prior knowledge]**
- Brod (2021), "Predicting as a learning strategy," *Psychonomic Bulletin & Review* 28:1839–1847, is a theoretical review. It frames predicting as a generative strategy distinct from guessing, pretesting and practice testing, and argues that prediction errors and epistemic emotions such as surprise and curiosity drive the benefit. It calls for research linking formal prediction-error models to instructional design, which is evidence that the applied evidence base is still developing. — [Brod 2021, DOI 10.3758/s13423-021-01904-1](https://link.springer.com/10.3758/s13423-021-01904-1) **[verified this session]**; [PMC PDF](https://rcastoragev2.blob.core.windows.net/64bfcffe1003bd2a2e180bb889d2de9b/PMC8642250.pdf)
- **Boundary condition (conceptual and comprehension material):** Guerrero, Griffin & Wiley (*Metacognition and Learning*, 2022) trained students to use either Predict-Observe-Explain or an explanation strategy on psychology textbook texts. Both improved comprehension monitoring, but the **explanation condition comprehended new texts better than the POE condition**. — [EasyChair preprint](https://easychair.org/publications/preprint/tDPk) **[verified this session; final version in Metacognition & Learning]**
- **Order effect in young novices:** In a CogSci 2019 study, five-year-olds learning buoyancy improved their predictions when they received conceptual information *before* anomalous evidence, but not in the reverse order. This is weak evidence (children, one study) that, for learners without a framework, prediction or anomaly first can fail without prior scaffolding. — [eScholarship](https://escholarship.org/uc/item/9h1908f1) **[verified this session]**
- **Problem-solving-before-instruction (productive failure):** Sinha & Kapur (2021, *Review of Educational Research* 91(5):761–798) meta-analysed 53 studies and 166 comparisons of problem-solving-then-instruction (PS-I) against instruction-then-problem-solving (I-PS). PS-I was favoured on conceptual knowledge and transfer, and effects were larger when the design followed productive-failure principles with high fidelity. A secondary summary reports a publication-bias-adjusted g of about 0.87 and high-fidelity g of 0.37–0.58; those subgroup numbers were not verified against the paper's tables. PS-I is generally *not* better for procedural knowledge. — [Sinha & Kapur 2021, DOI 10.3102/00346543211019105](https://doi.org/10.3102/00346543211019105) **[verified citation; subgroup numbers secondary-sourced]** via [OUCI record](https://ouci.dntb.gov.ua/works/4KnMgZq7)
- **AI-generated prequestions:** Pan, Schweppe, Teo, Indrajaya & Wenzel (2025) report four experiments in which ChatGPT-generated prequestions before a reading on brakes improved test scores over no prequestions. AI-made prequestions matched human-made ones and beat an AI-generated outline. — [Pan et al. 2025 PDF](https://sc-pan.github.io/pdf/PSTIW_2025.pdf) **[verified existence; venue status not confirmed]**
- **Adaptive AI pretesting adds no measurable gain:** Akgun (2025) ran three randomized experiments. Pretesting was compared with no pretesting, and fixed pretest questions with AI-generated adaptive ones. The adaptive AI version was more engaging, but final test performance did not differ significantly between fixed and adaptive pretests. The author reports greater benefits for AI-assisted approaches in complex, exploratory tasks. — [arXiv 2504.10249](https://arxiv.org/abs/2504.10249v1) **[preprint]**; related: [Akgun & Toker, arXiv 2412.13487](https://arxiv.org/abs/2412.13487) **[preprint]**
- **Expertise reversal:** Kalyuga et al. (2003) showed that instructional supports that help novices can become redundant or harmful for more expert learners, and vice versa. This is the general framework for why a fixed "always predict" rule is risky. — [Educational Psychologist 38(1), DOI 10.1207/S15326985EP3801_4](https://doi.org/10.1207/S15326985EP3801_4) **[canonical, DOI from prior knowledge]**

### Inferences
- The well-supported version is **one pre-question per segment or concept, followed by immediate feedback and explanation**. That is already compatible with Sapling's "1 question per turn" rule. The pre-question is not mastery evidence and should not be graded as such.
- Prediction before *every* reasoning step multiplies interaction cost, and no study found tests it at that granularity. The Guerrero 2022 result suggests that explanation-oriented prompts can beat prediction-oriented ones for comprehension. Recommendation strength: **moderate-strong for segment-level prequestions; weak or unproven for per-step prediction.** If built, run it as an experiment behind a feature flag, allow skipping ("no idea") without penalty, and fade it for learners with demonstrated prior knowledge.
- Novices: pretesting effects appear even when most answers are wrong. However, productive-failure and order-effect evidence implies novices need the explanation to follow quickly and should face predictions that are tractable (for example, multiple choice or a short answer), not open-ended derivations.

### Gaps
- No experimental study found that tests step-by-step "predict the next reasoning step" inside an LLM tutor dialogue for college STEM.
- No source found for the Eero Alvar "Agent Harness for Learning Things" design itself, so its claims were not checked.
- Carpenter & Toftness (pretesting with video) was not re-located this session; it is covered in the Pan & Carpenter 2023 review.

---

## Q2. Self-explanation and prompted self-explanation (feature b: thinking fields, part 1, the learning effect)

### Takeaway
Prompted self-explanation is one of the best-supported learning interventions (g ≈ 0.55). The benefit comes from *generating* explanations, not from the tutor reading them. Benefits depend on prompt type and cost time. A mandatory free-text field at every step is a stronger, costlier dose than the studied interventions.

### Cited Findings
- Bisra, Liu, Nesbit, Salimi & Winne (2018) meta-analysed 69 effect sizes from 64 reports: random-effects g = 0.55 for inducing self-explanation, comparable to mastery learning and peer tutoring. By prompt type: interrogative prompts g = 0.56 (k = 36), imperative g = 0.40 (k = 12), pre-directed g = 0.70 (k = 8). Most studies used undergraduates. — [Bisra et al. 2018, Educ Psych Review, DOI 10.1007/s10648-018-9434-x; full-text mirror](https://www.Gwern.net/doc/psychology/spaced-repetition/2018-bisra.pdf); [Clearinghouse moderator table](https://www.clearinghouse.edu.tum.de/wp-content/uploads/2023/09/KR_25_ENG_Table.pdf); [BPS Research Digest](https://bps.org.uk/research-digest/self-explanation-powerful-learning-technique-according-meta-analysis-64-studies) **[verified this session]**
- A secondary blog claims the effect survives controlling for time on task. This was **not** confirmed in the primary excerpts. — [idtips Substack](https://idtips.substack.com/p/self-explanation-the-evidence-behind) **[unverified]**
- Chi et al. (1994) is the origin study. Eighth graders prompted to self-explain after each line of a biology text gained more understanding, and high explainers gained most. — [Cognitive Science 18(3), DOI 10.1207/s15516709cog1803_3](https://doi.org/10.1207/s15516709cog1803_3) **[canonical, DOI from prior knowledge]**
- ICAP framework: constructive and interactive engagement (generating, co-constructing) beats active and passive engagement. Self-explanation and tutor dialogue are constructive or interactive. — [Chi & Wylie 2014, Educational Psychologist 49(4), DOI 10.1080/00461520.2014.965823](https://doi.org/10.1080/00461520.2014.965823) **[canonical, DOI from prior knowledge]**
- Comparison with step-based tutors: VanLehn (2011) found step-based ITS (d ≈ 0.76) nearly as effective as human tutoring (d ≈ 0.79) against no tutoring. Answer-based systems were weaker (d ≈ 0.31). Finer-than-step "substep" interaction added little. This bears on how granular "every step" interaction needs to be. — [VanLehn 2011, Educational Psychologist 46(4), DOI 10.1080/00461520.2011.611369](https://doi.org/10.1080/00461520.2011.611369) **[canonical, DOI from prior knowledge]**
- Explanation versus prediction for comprehension: an explanation-strategy training beat a POE training on new-text comprehension (see Q1). — [Guerrero et al. preprint](https://easychair.org/publications/preprint/tDPk) **[verified this session]**

### Inferences
- Asking learners to explain *in their own words* at key junctures (after a worked step, or when an answer is wrong) is strongly supported. Recommendation: **strong for periodic interrogative self-explanation prompts ("Why does X follow?")**, delivered as the turn's single question.
- "Every step" free-text is not what the meta-analytic literature tests. VanLehn's substep finding suggests diminishing returns below step granularity. Expect fatigue and short, low-effort responses ("idk", "ok"). Recommendation: **weak for mandatory per-step thinking fields; moderate for optional ones plus targeted prompts.**
- Writing explanations *to an AI* should benefit learning the same way (it is generation). But the AI must not short-circuit generation by explaining first. The Bastani results (Q8) show unguarded answer-giving harms learning.

### Gaps
- The time-on-task-controlled effect of self-explanation was not verified.
- No 2024–2026 RCT found that isolates typed self-explanation to an LLM tutor against no self-explanation at college level.
- Quantitative fatigue or dropout costs of per-step free-text prompts were not found.

---

## Q3. Think-aloud / free-text as diagnostic input for LLMs (feature b, part 2: using thinking fields as evidence)

### Takeaway
LLMs score short answers against rubrics with moderate-to-substantial human agreement, and they classify misconceptions in *wrong-answer* explanations well on curated benchmarks. Detecting **hidden misconceptions behind correct answers** produces many false positives (roughly 4–8 false alarms per true detection), and accuracy drops as the misconception taxonomy grows. Free text is usable as a *hint for what to probe next*, not as mastery evidence. This supports Sapling's current rule.

### Cited Findings
- Eedi/Kaggle "MAP – Charting Student Math Misunderstandings" (closed Oct 2025) used more than 52,000 student explanations across 15 math questions, labelled by expert raters and scored with MAP@3. Eedi notes the competition used broader misconception definitions than Eedi Labs normally does. — [Eedi blog](https://www.eedi.com/news/from-wrong-answers-to-real-insights-how-we-used-a-kaggle-challenge-to-map-student-misconceptions); [EdSurge Dec 2025](https://www.edsurge.com/news/2025-12-11-teaching-machines-to-spot-human-errors-in-math-assignments) **[verified this session]**. A 2026 paper gives a smaller dataset figure (>38k), so sources conflict on size.
- Eedi reports benchmarking general LLMs against purpose-built models for misconception detection and states "it wasn't close" in favour of purpose-built models. — [Eedi news](https://www.eedi.com/news/we-benchmarked-llms-against-purpose-built-models-it-wasnt-close) **[verified existence; figures not extracted]**
- A 2026 preprint reports MAP@3 0.9585 on the MAP data with a 4B model and 84.38% on cross-topic algebra misconceptions (vs. 81.25% for a 72B fine-tuned baseline). — [arXiv 2605.23925](https://arxiv.org/pdf/2605.23925.pdf) **[preprint, not independently verified]**
- Hidden misconceptions with correct answers: one study reports 84% vs 57% detection, but the best model raises about 4 false alarms per genuine detection. — [arXiv 2606.23205, "The Correct Answer Trap"](https://arxiv.org/pdf/2606.23205) **[preprint]**. A CEUR paper reports positive predictive value of 10.9% (about 8 false alarms per true detection) and concludes a teacher in the loop is necessary. — [CEUR Vol-4282 short7](https://ceur-ws.org/Vol-4282/short7.pdf) **[workshop paper]**
- Diagnostic accuracy degrades sharply as the number of candidate misconceptions grows. — [AIME-Con 2026 paper](https://aclanthology.org/2026.aimecon-main.33.pdf) **[as summarized by search; verify]**
- Short-answer grading reliability:
  - CoTAL (GPT-4 with chain-of-thought and active learning) on K-12 science, engineering and computing reports about 94.7% agreement with human scoring, using QWK. — [arXiv 2504.02323](https://arxiv.org/html/2504.02323) **[preprint]**
  - University sustainability short answers: four LLMs against humans reached QWK 0.585–0.640 (moderate), and agreement declined at higher cognitive levels. — [Emirtekin & Ozarslan, J. Computer Assisted Learning 2026](https://gcris.yasar.edu.tr/entities/publication/1eeab52d-b73f-42b4-baa8-f2c94edfc8c1) **[verified record]**
  - MCAS study: substantial agreement in math and science, but reliability drops for short-answer and zero-shot setups. — [arXiv 2606.12422](https://arxiv.org/html/2606.12422) **[preprint]**
  - A meta-analysis pools 890 QWK results from LLM short-answer scoring studies. — [Hardy, arXiv 2603.04820](https://arxiv.org/pdf/2603.04820) **[preprint; pooled figure not extracted]**

### Inferences
- Rubric-anchored scoring of a *specific* explanation question (known item, known rubric, few-shot or calibrated) is approaching human reliability. Open-ended think-aloud at every step, scored without a rubric against an open misconception space, is the regime where false alarms dominate.
- Recommendation: **do not promote free-text to mastery evidence (keep Sapling's rule; strong).** Optionally use LLM reading of learner text as a *low-trust diagnostic signal* that only chooses the next probe question. The graded check remains the evidence. The base-rate arithmetic matters: at PPV ≈ 10–20%, acting on a flagged misconception without a confirming check misleads the learner most of the time.
- Privacy: storing per-step think-aloud text expands sensitive learner data. Sapling encrypts `messages.content`, and any new table would need the same treatment.

### Gaps
- No study found that measures LLM inference of *knowledge state* (not misconception class) from college-level free-form think-aloud against human expert raters.
- The winning Kaggle MAP@3 score was not confirmed.

---

## Q4. Confidence ratings / metacognitive judgments (feature c: confidence sliders)

### Takeaway
Confidence ratings are not neutral measurements. Making judgments of learning (JOLs) changes memory slightly on average (g ≈ 0.22), positive for some materials and negative for others, with publication bias. Confidence is useful operationally: high-confidence errors are corrected *more* readily after feedback (hypercorrection), so confidence tells the tutor which errors to dwell on. Evidence that confidence ratings improve conceptual STEM learning on their own is thin.

### Cited Findings
- Double, Birney & Walker (2018, *Memory* 26(6):741–750) meta-analysed JOL reactivity. The overall effect was null (g = 0.054, 95% CI −0.027 to 0.135), positive for related word pairs (g = 0.323) and word lists (g = 0.384). — [Durham repository](https://durham-repository.worktribe.com/output/2253677/a-meta-analysis-and-systematic-review-of-reactivity-to-judgements-of-learning) **[verified this session]**
- Ingendahl, Halamish & Undorf (2025, *Psychological Bulletin* 151(7):892–929) is the newest and largest meta-analysis: 344 effect sizes, 175 experiments, N = 15,079. Immediate JOLs improve memory on average (g = 0.22, 95% CI 0.17–0.27). Effects are positive for related pairs (g = 0.44) and slightly negative for unrelated pairs (g = −0.09). Size and direction vary with materials, test type and design. The authors find publication bias favouring positive reactivity and conclude JOLs are "not a neutral measurement tool." — [Bar-Ilan summary page](https://education.biu.ac.il/en/node/12525); DOI 10.1037/bul0000487 **[verified this session]**
- Hypercorrection: errors made with high confidence are more likely to be corrected after feedback than low-confidence errors (Butterfield & Metcalfe 2001). The leading account is attentional, with larger P3a responses to feedback on high-confidence errors. Corrections persist at one week, though some high-confidence errors return on delayed tests (Butler, Fazio & Marsh 2011). In one applied study, the effect appeared for short-answer items (85% vs 61% corrected) but **not** for true/false items. — [Fazio dissertation, Duke](https://dukespace.lib.duke.edu/items/d6ab09ca-f55c-4efb-9d32-2788bc5838b2); [PMC4679660](https://pmc.ncbi.nlm.nih.gov/articles/PMC4679660/); [ASHS 2017 paper](https://ashs.confex.com/ashs/2017/webprogramarchives/Paper26571.html) **[verified this session]**; original: [Butterfield & Metcalfe 2001, JEP:LMC, DOI 10.1037/0278-7393.27.6.1491](https://doi.org/10.1037/0278-7393.27.6.1491) **[canonical]**

### Inferences
- Sapling's current use (confidence for diagnosis, not as mastery evidence) is well aligned with the evidence. A confidence capture **on graded checks** that makes a confident-wrong answer trigger fuller corrective feedback is supported by hypercorrection. Recommendation: **moderate.** Use a coarse 3-point scale ("guessing / fairly sure / certain") rather than a continuous slider, because coarse is faster and adds no known benefit lost.
- A slider on *every* answer adds friction and reactivity of unknown direction for conceptual material. No evidence found that it improves calibration or learning on its own. Recommendation: **weak** for ubiquitous sliders.
- Confidence must not feed mastery directly. A confident-correct answer is still one data point.

### Gaps
- No source found this session on certainty-based marking (Gardner-Medwin) effectiveness, or on calibration-training RCTs in college STEM.
- No source found on reactivity of confidence judgments for problem-solving or conceptual material, as opposed to word pairs.

---

## Q5. Fluency illusions (feature f: teach each step until it "feels obviously true")

### Takeaway
Feelings of understanding and fluency are poor and sometimes *inverted* signals of learning. Using "feels obvious" as the stopping criterion conflicts with robust evidence. Effortful (desirable-difficulty) methods produce more learning while *feeling* like less.

### Cited Findings
- Deslauriers, McCarty, Miller, Callaghan & Kestin (2019, *PNAS* 116(39):19251–19257) ran randomized comparisons in intro college physics. Students in active-learning classes learned more but *felt* they learned less than students in polished lectures. The authors attribute the gap to the cognitive effort of active learning, which students misread as poor learning, and warn that relying on student perceptions pushes instruction toward weaker methods. — [DOI 10.1073/pnas.1821936116; PDF](https://openlab.citytech.cuny.edu/gamelab/files/2023/01/Deslauriersa-et-al-2019.pdf); [UNL summary](https://newsroom.unl.edu/announce/nebraska-science/10051/58996); [Science Breaker](https://thesciencebreaker.org/en/breaks/psychology/are-students-learning-as-much-as-they-think-they-are-the-dangers-of-fluent-lectures) **[verified this session]**
- Koriat's cue-utilization framework: metacognitive judgments are inferences from available cues, such as processing fluency, rather than direct readouts of memory strength, so they are systematically biased by fluency. — [Koriat 1997, JEP:General 126(4), DOI 10.1037/0096-3445.126.4.349](https://doi.org/10.1037/0096-3445.126.4.349) **[canonical]**
- Rhodes & Castel (2008): larger font raised judgments of learning without changing recall, a clean fluency illusion. — [JEP:General 137(4), DOI 10.1037/a0013684](https://doi.org/10.1037/a0013684) **[canonical]**
- Generative AI case: in Bastani et al. (2025, PNAS), unguarded GPT access raised practice performance by 48% (GPT Tutor: +127%), but GPT Base students scored 17% *worse* than control on the unassisted exam. GPT Tutor's safeguards largely removed the harm, but it did not beat control on the exam. Assisted fluency during practice is not learning. — [PNAS 122(26), DOI 10.1073/pnas.2422633122 via RePEc](https://econpapers.repec.org/RePEc:nas:journl:v:122:y:2025:p:e2422633122); [Wharton summary](https://knowledge.wharton.upenn.edu/article/without-guardrails-generative-ai-can-harm-education) **[verified this session]**

### Inferences
- Recommendation: **strong against** using a felt-obviousness or learner self-report as the criterion for moving on. Sapling's rule (graded checks are the only mastery evidence) is the evidence-aligned choice.
- A weaker reading of the feature is acceptable: explain until the learner *can generate* the step (pass a check), not until it feels obvious. The tutor can also tell learners that effort and difficulty are normal. Deslauriers et al. recommend telling students this early.

### Gaps
- No study found that tests "felt understanding" as an adaptive stopping rule inside an ITS.

---

## Q6. Concept maps / knowledge graphs (feature d: persistent graphs of propositions and reasoning chains)

### Takeaway
*Learners* constructing concept maps helps learning (g ≈ 0.72 for constructing, 0.43 for studying maps). That is a learner-activity effect, not evidence for a system that silently extracts propositions from chat. Prerequisite graphs for sequencing are standard in ITS (knowledge space theory, knowledge tracing), but evidence that *auto-extracted proposition or reasoning-chain graphs* improve learning was not found.

### Cited Findings
- Schroeder, Nesbit, Anguiano & Adesope (2018, *Educ Psych Review* 30:431–455) meta-analysed 142 effect sizes (N = 11,814). Overall g = 0.58. **Creating** maps g = 0.72; **studying** maps g = 0.43. — [SFU Summit](https://summit.sfu.ca/item/17789); DOI 10.1007/s10648-017-9403-9 **[verified this session]**
- Nesbit & Adesope (2006, *RER* 76(3):413–448) is the earlier meta-analysis (67 effect sizes) that the 2018 paper extends. — [DOI 10.3102/00346543076003413](https://doi.org/10.3102/00346543076003413) **[canonical]**; extension relationship confirmed in [Schroeder et al. summary](https://summit.sfu.ca/item/17789)
- ITS in general: Ma, Adesope, Nesbit & Liu (2014) meta-analysis: ITS versus teacher-led large-group instruction g ≈ 0.42. — [J. Educ Psych 106(4), DOI 10.1037/a0037123](https://doi.org/10.1037/a0037123) **[canonical; figure from prior knowledge]**

### Inferences
- Sapling's existing concept graph with prerequisite edges is the well-trodden ITS pattern. Recommendation: **keep.**
- A persistent proposition and reasoning-chain graph extracted by an LLM from sessions inherits the Q3 reliability problem (extraction errors become stored "knowledge"). It also adds a sensitive data store and has no direct learning evidence. Recommendation: **weak.** If built, keep it as a tutor-side memory with low trust that never writes mastery. Mutations must still go through `apply_graph_update`.
- The evidence-backed version of "graphs" is **learner-constructed** maps or summaries (an occasional "connect these 3 ideas" activity), which is a generative activity. Recommendation: moderate, as an optional activity.

### Gaps
- No RCT found on LLM-extracted learner knowledge graphs or "proposition graphs" improving outcomes.
- No source fetched this session on knowledge-space-theory (ALEKS) sequencing outcomes.

---

## Q7. Variability of practice, cue variation, combining ideas (feature e)

### Takeaway
Varying surface features and interleaving similar categories improve transfer and discrimination (interleaving g ≈ 0.42, math g ≈ 0.34). Benefits depend on similarity between items and are not universal: blocking wins for some materials. Spontaneous analogical transfer from a single example is poor, and comparing multiple varied examples helps. Increasing "number of combined ideas" maps onto complexity and should be gated by mastery of the components.

### Cited Findings
- Brunmair & Richter (2019, *Psych Bull* 145(11):1029–1052) analysed 59 studies, 238 effect sizes and 158 samples. Interleaving g = 0.42 overall. Paintings g = 0.67; **math g = 0.34**; expository texts non-significant; **words favoured blocking (g = −0.39)**. Effects are larger when categories are similar to each other, varied within, and more complex. Heterogeneity is high (I² ≈ 77%). — [PubMed 31556629](https://pubmed.ncbi.nlm.nih.gov/31556629/); [author manuscript](https://www.psychologie.uni-wuerzburg.de/fileadmin/06020400/2019/Brunmair_Richter_in_press__2019_META-ANALYSIS_OF_INTERLEAVED_LEARNING.pdf) **[verified this session]**
- Contextual interference and transfer in motor learning: Czyż et al. (2024) meta-analysed 34 studies, SMD = 0.55 favouring random practice on transfer. The effect was significant in the lab (0.75) but small and non-significant in applied settings (0.34). — [PMC11349744](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11349744/) **[verified this session; motor domain, so analogical evidence only]**
- Variability's benefits for generalization depend on the type of variability and the learner's stage. It can slow initial learning while improving generalization. — [Raviv, Lupyan & Green 2022, Trends Cogn Sci 26(6), DOI 10.1016/j.tics.2022.03.007](https://doi.org/10.1016/j.tics.2022.03.007) **[canonical]**
- Gick & Holyoak (1983): learners rarely transfer a solution from one analogous story spontaneously, but comparing two analogs led to schema induction and much better transfer. — [Cognitive Psychology 15(1), DOI 10.1016/0010-0285(83)90002-6](https://doi.org/10.1016/0010-0285(83)90002-6) **[canonical]**

### Inferences
- Varying cue familiarity (same concept in unfamiliar surface form) and interleaving confusable concepts on graded checks are supported. Recommendation: **moderate-strong**, especially for review and spaced practice, less so during first exposure.
- Increasing the number of combined ideas fits integrative transfer items. Gate it on component mastery (use the prerequisite graph) to avoid overload for novices. Recommendation: **moderate.**
- Sapling can build this into check generation (surface-varied variants, interleaved review queues) without changing the evidence rule.

### Gaps
- The Brunmair & Richter math effect is from few studies. No meta-analysis found specific to college conceptual STEM cue variation.

---

## Q8. Turn length / segmentation / dialogue structure in AI tutoring (bears on Sapling's ≤5 sentences, 1 question)

### Takeaway
Segmenting instruction into learner-paced chunks helps (classic multimedia evidence), and the strongest 2025 AI-tutor result (Kestin et al.) used a tightly structured, step-by-step tutor. Guardrails that withhold answers prevent harm but do not guarantee gains. No direct evidence was found on the optimal sentence count per LLM turn. Sapling's cap is reasonable but empirically unvalidated.

### Cited Findings
- Kestin et al. (2025, *Scientific Reports*) ran a randomized crossover with 194 Harvard intro physics students. A carefully prompted AI tutor (structured, scaffolded, step-by-step) produced learning gains more than double those of an in-class active-learning session, in less time, with higher engagement. Reviewers caution that the comparison involves a specific human-taught session and a specific prompt design. — [DOI 10.1038/s41598-025-97652-6](https://doi.org/10.1038/s41598-025-97652-6) **[DOI canonical; findings via]** [ETC Journal review](https://etcjournal.com/2025/11/10/review-of-kestin-et-al-s-june-2025-harvard-study-on-ai-tutoring/), [Michelle Miller summary](https://michellemillerphd.substack.com/p/r3-37-july-15-2025-how-do-tutoring)
- Bastani et al. (2025, PNAS): an answer-giving chat interface harms learning (−17% on exam), and a safeguarded tutor prevents the harm but shows no exam gain over control. — [Wharton](https://knowledge.wharton.upenn.edu/article/without-guardrails-generative-ai-can-harm-education) **[verified this session]**
- Step-based tutoring nearly matches human tutoring, while finer substep interaction adds little (VanLehn 2011; see Q2). — [DOI 10.1080/00461520.2011.611369](https://doi.org/10.1080/00461520.2011.611369) **[canonical]**

### Inferences
- Short turns with one question align with segmentation and step-based tutoring evidence. Recommendation: **keep the cap.** Adding a prediction prompt *plus* a thinking field *plus* a confidence slider to every turn would violate the one-question discipline and push interaction toward substep granularity, which VanLehn found adds little.
- Prefer one interaction demand per turn, rotating by purpose: segment-start prequestion, then explanation chunk, then self-explanation or a graded check with optional confidence.

### Gaps
- Segmenting-effect meta-analysis (Rey et al. 2019, Educ Psych Review) was not re-verified this session.
- No RCT found that varies LLM tutor turn length or questions per turn.

---

## Summary of recommendation strengths (for the report writer)

| Feature | Evidence base | Recommendation |
|---|---|---|
| (a) Predict before explain | Pretesting robust (Pan & Carpenter 2023); AI-generated prequestions work (Pan et al. 2025); per-step prediction untested; explanation beat POE for comprehension | Segment-level pre-question: moderate-strong. Per-step: weak; flag and experiment |
| (b) Thinking fields: learning effect | Self-explanation g = 0.55 | Targeted interrogative prompts: strong. Mandatory every step: weak |
| (b) Thinking fields: diagnostic evidence | LLM grading QWK moderate-substantial with rubrics; hidden-misconception PPV ~10–20% | Do not use as mastery evidence (strong); use only to choose the next probe |
| (c) Confidence sliders | JOL reactivity g = 0.22, variable direction; hypercorrection | Coarse confidence on graded checks for feedback routing: moderate. Ubiquitous slider: weak |
| (d) Persistent proposition graphs | Learner-made maps g = 0.72; no evidence for auto-extracted graphs | Keep prerequisite graph; extracted graph: weak, low trust only |
| (e) Cue variation and combining ideas | Interleaving g = 0.42 (math 0.34); variability aids transfer; analogical comparison | Moderate-strong in checks and review; gate combos on prerequisites |
| (f) "Feels obviously true" | Deslauriers 2019, Koriat, Bastani 2025 | Strong against as a stopping criterion |
