# LLM-tutor designs and durable learning: rigorous evidence 2024 to Nov 2026

Compiled 2026-11-07. Source verification legend:
- **[V]** fetched or confirmed this session from a primary source or its abstract.
- **[S]** confirmed only from search-result summaries or secondary coverage.
- **[K]** from the researcher's prior knowledge of the published paper (cutoff mid-2026), not re-fetched this session. The citation is real, but the report writer should spot-check the numbers before quoting them.
- **PREPRINT**, **WP** (working paper, not peer-reviewed) and **VENDOR** (author or funder owns the product) are marked inline.

## Q1. Which RCTs and quasi-experiments report delayed, unassisted or transfer outcomes, and what did they find?

### Takeaway
The best 2025–2026 field evidence splits by design.
- **Bare or general-purpose AI access** improves assisted performance but hurts later unassisted exams. Evidence: Bastani 2025, Strömberg 2026, Barcaui 2025, Rismanchian 2026.
- **A course-integrated GPT-4o tutor left in "direct-instruction" mode** lowered college grades by 0.27–0.37 SD (Liu et al. 2026, n=2,379).
- **Purpose-built tutors** do better. They ground answers in expert solutions, withhold answers, use structured steps or keep a human in the loop. They either avoid the harm (Bastani GPT Tutor) or produce large immediate gains (Kestin 2025), small sustained gains (Oreopoulos & Low 2026), or non-inferiority to human tutors on novel problems (Eedi/LearnLM 2025).
- **True delayed-retention tests are rare.** The longest come from observational or natural-experiment designs: Strömberg (months to 2 years) and Rismanchian (placement retests). The few RCTs with a delayed test (Oreopoulos et al. 2026, 1 week later) show only marginal gains, even for a well-designed AI.

### Cited findings: study catalog

**1. Bastani, Bastani, Sungu, Ge, Kabakcı & Mariman (2025), "Generative AI without guardrails can harm learning", *PNAS* 122(26) e2422633122. [K]**
- Population and design: about 1,000 Turkish high-school math students, field RCT across about four 90-min practice sessions.
- Three arms: GPT Base (a ChatGPT-like interface), GPT Tutor (prompted with teacher-provided solutions and told to give hints, not answers), and control.
- Assisted practice: GPT Base +48%, GPT Tutor +127%.
- Later unassisted exam: GPT Base −17% versus control; GPT Tutor not significantly different from control.
- Answer quality: GPT-4 answers in the Base arm were frequently wrong; logs show students asking for answers.
- Caveats: short duration; the "delayed" test was a closed-book exam the same term, not a long-retention test; secondary school, not college. — [PNAS DOI](https://doi.org/10.1073/pnas.2422633122)

**2. Kestin, Miller, Klales, Milbourne & Ponti (2025), "AI tutoring outperforms in-class active learning", *Scientific Reports* 15:17458. [K/S]**
- Population and design: Harvard intro physics, n≈194, crossover RCT on two lessons.
- AI design:
  - a GPT-4 tutor with a system prompt encoding best practices (scaffolding, short turns, growth mindset, avoid giving answers wholesale);
  - **grounded in instructor-written step-by-step solutions** to curb errors;
  - followed by the in-class session.
- Outcome: immediate posttest learning gains more than double those of active learning, effect size about 0.73–1.3 SD, in less time.
- Caveats:
  - immediate posttest only, with no delayed or transfer measure;
  - one course at a highly selective institution;
  - the comparison is AI plus self-pacing against a single active-learning lesson.
- Sources: [ResearchGate](https://www.researchgate.net/publication/392839220_AI_tutoring_outperforms_in-class_active_learning_an_RCT_introducing_a_novel_research-based_design_in_an_authentic_educational_setting); Liu et al. 2026 also describe it as an "immediate learning gains" result ([EdWP 26-1598](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf)).

**3. Liu, Sweet, Chen, … Rice (UMD), "The Effects of Course-Integrated AI Tutoring on Student Performance and Engagement: A Randomized University Trial", EdWorkingPaper 26-1598, Oct 2026. WP. [V]**
- Design: group-randomized at the instructor level; 2,379 undergraduates, 30 instructors, multiple disciplines, fall 2025, 13 randomization blocks.
- Tool: a GPT-4o "virtual study assistant" with **RAG over instructor-selected course materials**, embedded in the LMS. Instructors chose a "tutor mode" (guides toward the answer) or a "direct instruction mode" (gives the answer). Few switched from the default direct-instruction mode; only 2 ended the term in tutor mode.
- Effects:
  - final grades −0.37 SD in the exact-match same-course sample (range −0.27 to −0.37 SD);
  - LMS participation −0.90 SD, active days −0.51 SD;
  - homework effects null or negative;
  - first-generation students lost more than twice as much as continuing-generation students.
- Usage:
  - only 14.6% of treated students ever used the tool, and about 40% of those had a single session;
  - use spiked around exams;
  - 73.8% of requests sought information, explanations or solutions; 11.3% practice or test prep; 0.7% feedback on the student's own work.
- Caveats:
  - a large ITT effect despite 15% uptake, so the authors suggest instructor encouragement may have changed broader GenAI use (ChatGPT and Gemini were available to everyone);
  - few clusters;
  - the result concerns this default configuration, not scaffolded tutoring.
- Grounding: the paper notes that RAG grounding alone did not help, consistent with Thoeni & Fryer 2026.
- Source: [EdWP PDF](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf), DOI 10.26300/y3f8-vh05.

**4. Oreopoulos, Liut, Sungu & Low, "Making AI Tutoring Productive: Evidence from a Mastery-Based Math Practice Experiment", NBER WP 35621, Aug 2026. WP. [V abstract]**
- Design: more than 6,000 middle-school students (Hamilton County, TN) on the NUMI platform, factorial randomization: AI support versus computer-assisted learning (CAL) only × mastery versus non-mastery progression × topic.
- Assisted practice: AI students progressed more slowly and attempted fewer questions, but were more accurate. After a mistake, AI raised next-attempt correctness and increased time per question.
- Mastery: alone, it raised three-in-a-row attainment but **did not improve delayed learning**.
- Delayed test (1 week): AI embedded in the mastery workflow gave **marginally significant** gains, concentrated on practiced Exercise 1 material.
- This is one of the few RCTs that isolates AI's incremental contribution over the same practice platform.
- Sources: [NBER w35621](https://www.nber.org/papers/w35621); a secondary summary headlines "the AI tutor helped when it slowed them down" ([blog](https://www.higheredaiplaybook.com/p/6000-students-the-ai-tutor-helped)).

**5. Oreopoulos & Low, "One Click Away: AI Tutoring with Khanmigo in a Two-Year School Experiment", NBER WP 35620, Aug 2026. WP. [S]**
- Design: two-year RCT in 18 Tennessee middle schools. Khan Academy plus Khanmigo, set to coach rather than give answers, during remedial math periods.
- Effect: about 1.3 national percentile ranks per term, roughly 0.06–0.08 SD per year (about 0.14 SD for a full year of active participation). This is similar to Khan Academy practice without AI.
- Engagement:
  - 96% tried Khanmigo;
  - the median student messaged it on only one-third of practice days;
  - most messages were bare answers or clicks on suggested prompts.
- The design does not isolate AI's incremental effect. Khan Academy's founder disputes the counterfactual (VENDOR rebuttal).
- Sources: [NBER w35620](https://www.nber.org/papers/w35620); [Khan Academy blog (vendor)](https://blog.khanacademy.org/?p=22104).

**6. Strömberg, Lei & Wu, "The Generative AI Learning Penalty: Evidence from Chinese Secondary Education", CEPR DP 21577, 2026. WP, quasi-experimental. [S]**
- Data and design: 26,811 students in grades 7–12 in one Chinese county, 30-month panel, staggered-adoption difference-in-differences. Adoption is dated from teacher-distributed surveys.
- Homework: scores +18%, completion time −30%.
- Exams:
  - monthly closed-book exams −20% within 6 months;
  - high-stakes entrance exams: penalty builds over about 2 years, reaching about 24% (high-school entrance) and about 18% (college entrance).
- Mechanism: the loss is concentrated in the about 80% of users whose fast, high-scoring homework suggests outsourcing. Users who kept their homework time unchanged saw small losses.
- Heterogeneity: losses larger for high achievers, boys and junior students.
- Caveats: AI use is self-reported via teachers; one county; full paper not read.
- Sources: [VoxEU column](https://cepr.org/voxeu/columns/generative-ai-learning-penalty-secondary-school); [IDEAS](https://ideas.repec.org/p/cpr/ceprdp/21577.html).

**7. Rismanchian, Uzun, Matayoshi, Cosyn & Kurd-Misto, "Faster Completion, Less Learning: Generative AI Reduced Study Time on Math Problems and the Knowledge They Build", arXiv 2605.21629 v3, Jul 2026. PREPRINT. VENDOR-affiliated: 4 of 5 authors are McGraw Hill (ALEKS owner); disclosed. [V]**
- Data: 3.2M ALEKS learning interactions (2015–2025) and 12.2M placement (PPL) response times.
- Identification: AI-susceptible word problems versus AI-resistant graph problems, with a post-ChatGPT ramp. Proctored versus non-proctored is used as a falsification test.
- Study time: College Algebra −26.9% (CI −34.0 to −19.0), high school −31.3%, middle school −9.0%.
- **Retention on proctored items:** odds of answering AI-susceptible items correctly 0.75× (CI 0.56–0.98). Non-proctored odds rose about 85%, which is consistent with AI use on unproctored tests.
- Caveats: AI use is never observed; populations differ across analyses; results depend on functional form.
- Sources: [arXiv](https://arxiv.org/html/2605.21629); [Hechinger coverage](https://hechingerreport.org/proof-points-ai-eroding-math-skills/).

**8. Barcaui (2025), "ChatGPT as a cognitive crutch: Evidence from a randomized controlled trial on knowledge retention", *Social Sciences & Humanities Open* (Elsevier). [S]**
- Design: RCT with 120 undergraduates learning about AI.
- Outcome: retention test at **45 days**; ChatGPT-study group 57.5% correct versus traditional study 68.5%.
- Caveats: small sample; unrestricted ChatGPT; full text not accessed (403).
- Sources: [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2590291125010186); characterized in [Liu et al. 2026](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf).

**9. Google LearnLM and Eedi, "AI tutoring can safely and effectively support students: An exploratory RCT in UK classrooms", arXiv 2512.23633, Dec 2025. PREPRINT; VENDOR (Google and Eedi authors). [S]**
- Population: 165 students aged 13–15 in 5 UK schools.
- Arms: static pre-written hints versus chat. Within chat, sessions were randomized to a human tutor alone or LearnLM drafts supervised by an expert human tutor, who edited each message until they would send it themselves.
- Oversight: 76.4% of drafts were approved with zero or minimal edits.
- Outcome: novel problems on later topics, 66.2% (LearnLM) versus 60.7% (human), +5.5 pp. This is a Bayesian 93.6% posterior probability, not a conventional significance claim.
- Caveats: exploratory; small sample; human-supervised; not student-alone AI.
- Sources: [arXiv](https://arxiv.org/pdf/2512.23633); [The 74](https://www.the74million.org/article/ai-tutors-with-a-little-human-help-offer-reliable-instruction-study-finds/).

**10. De Simone, Tiberti, Barron Rodriguez, Manolio, Mosuro & Dikoru (2025), "From Chalkboards to Chatbots", World Bank Policy Research WP 11125, May 2025. WP. [S]**
- Design: RCT in Benin City, Nigeria, senior-secondary year 1. Six weeks of after-school English sessions using Microsoft Copilot (GPT-4), with teacher-guided prompts.
- Effects: about 0.31 SD on a combined assessment (English, AI knowledge, digital skills) and about 0.23 SD on English. Sources disagree on which number to headline.
- Dose-response: about 0.031 SD per extra day attended.
- Heterogeneity: larger for girls and higher-baseline students.
- Sample: a co-author's post gives about 1,300 students in 9 schools [unverified].
- Caveats: teacher-facilitated; the end-of-program test is largely immediate.
- Sources: [World Bank OKR](https://openknowledge.worldbank.org/entities/publication/15e1ff08-15ae-4f7a-b2a8-d146e6c113ee/full); [RePEc](https://econpapers.repec.org/RePEc:wbk:wbrwps:11125).

**11. Wang, Ribeiro, Robinson, Loeb & Demszky (2024), "Tutor CoPilot: A Human-AI Approach for Scaling Real-Time Expertise", arXiv 2410.03017 (Stanford). PREPRINT at release. [K]**
- Design: preregistered RCT with about 900 human tutors and about 1,800 K-12 students in an underserved US district.
- AI design: tutors (not students) got LLM-suggested expert-like moves.
- Outcome: student mastery on exit tickets +4 pp overall, +9 pp for students of lower-rated tutors. Tutors used more Socratic questioning and gave answers less often.
- Cost: about $20 per tutor per year.
- Caveats: proximal exit-ticket outcome; no delayed test; end-of-year test effects were not significant. — [arXiv](https://arxiv.org/abs/2410.03017)

**12. Lehmann, Cornelius & Sting, "AI Meets the Classroom: When Do Large Language Models Harm Learning?", arXiv 2409.09047 v2, Mar 2025. PREPRINT. [S]**
- Field study (university programming, exogenous variation in LLM availability; only substitutive use observed): significant long-term decline in learning.
- Two preregistered lab experiments: no net effect.
- Usage matters:
  - substitution (generating solutions) gives more topics covered but shallower understanding;
  - complementary use (asking for explanations) deepens understanding.
- **LLMs widen the gap between low- and high-prior-knowledge students.** — [arXiv](https://arxiv.org/abs/2409.09047)

**13. Thoeni & Fryer (2026). [S, second-hand only]**
- Design: semester RCT with about 500 marketing students; a RAG chatbot grounded in course materials.
- Outcome: no significant effect on achievement, interest, self-efficacy or engagement.
- Known only via the [Liu et al. 2026](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf) literature review; the primary paper was not located.

**14. Sungu et al. (2026), cited in Liu et al. 2026. [S, second-hand]**
- Design: teacher-facing GenAI access in K-12.
- Outcome: lowered student intrinsic motivation; no exam gain; harm for students of initially lower-performing instructors. — [Liu et al. 2026](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf)

**15. Pardos & Bhandari (2024), "ChatGPT-generated help produces learning gains equivalent to human tutor-authored help on mathematics skills", *PLOS ONE* 19(5): e0304013. [K]**
- Design: adult crowdworker algebra learners, pre/post.
- Outcome: GPT-generated worked hints, vetted for errors, gave gains statistically equivalent to tutor-authored hints.
- Hallucination finding: earlier work by the same group found about 32% of unvetted ChatGPT hints had errors; self-consistency checking reduced this.
- Caveat: immediate posttest only. — [PLOS ONE DOI](https://doi.org/10.1371/journal.pone.0304013)

**16. Henkel, Horne-Robinson, Kozhakhmetova & Lee (2024), "Effective and Scalable Math Support: Evidence on the Impact of an AI-Tutor on Math Achievement in Ghana", arXiv 2402.09809. PREPRINT; VENDOR-affiliated (Rising Academies, Rori). [K]**
- Design: 8-month RCT with about 1,000 students; a WhatsApp LLM tutor used about 1 hour per week.
- Outcome: about 0.36 SD on growth.
- Caveats: the outcome test was not independent of the platform content; attrition. — [arXiv](https://arxiv.org/abs/2402.09809)

**17. Registered but not yet reported:** NCT06809634, an 8-week RCT of LLM support for physical-therapy clinical reasoning; no results posted. [V-search] — [ClinicalTrials.gov](https://clinicaltrials.gov/study/NCT06809634)

### Inferences
- Across the field studies, the sign of the unassisted or delayed effect tracks whether the AI can be used to **produce the answer**:
  - unrestricted or answer-giving use is negative (Bastani GPT Base, Strömberg, Barcaui, Liu default mode, Rismanchian);
  - answer-withholding or solution-grounded use is null to positive (Bastani GPT Tutor, Kestin, Oreopoulos mastery+AI, Eedi).
- Positive designs also add **friction or time on task** (Oreopoulos: slower progression, more time per item; Strömberg: users who kept homework time had small losses). Sapling's answer withholding and short graded checks match this pattern.
- Grounding in course content is necessary but **not sufficient**. RAG-grounded tutors in Liu 2026 and Thoeni & Fryer 2026 showed no gain or harm when students could still request answers.
- No college RCT yet shows a **positive delayed (≥1 month) unassisted** effect from a student-facing LLM tutor. Sapling's delayed tool-free post-test would fill a genuine gap.

### Gaps
- Bastani, Kestin, Tutor CoPilot and Pardos numbers were not re-fetched this session ([K]); spot-check them.
- I found no published Anthropic "learning mode" or OpenAI "study mode" RCT with learning outcomes. Anything from those companies so far is vendor description or usage analysis, not efficacy evidence.
- I found no Carnegie Learning or J-PAL LLM-tutor RCT results with delayed outcomes in this window. J-PAL/SCALE summaries exist, but I could not verify specific new trials.
- Exact De Simone sample size and SEs: retrieve from World Bank WP 11125, Tables 2–3.

## Q2. Cognitive offloading and "metacognitive laziness": how good is the evidence?

### Takeaway
The causal evidence for harm from **unrestricted** AI is now reasonably strong. It rests on large field and natural experiments (Bastani, Strömberg, Liu, Rismanchian) and a small RCT (Barcaui). The famous "brain" and "critical-thinking" studies are weak:
- Kosmyna is an n=54 EEG preprint.
- Gerlich is a correlational survey.
- Fan 2025 is a small lab study.
Cite them as mechanism hints only.

### Cited findings
- **Fan et al. (2025), "Beware of metacognitive laziness", *British Journal of Educational Technology* 56(2). [K]**
  - Lab RCT with about 117 university students writing and revising essays; four arms: ChatGPT, human expert, checklist, no support.
  - ChatGPT improved essay scores, but there was no difference in intrinsic motivation, knowledge gain or knowledge transfer.
  - Process logs showed less metacognitive self-regulation ("metacognitive laziness").
  - Quality: small n; one session; short-term. — [BJET DOI](https://doi.org/10.1111/bjet.13544)
- **Kosmyna et al. (2025), "Your Brain on ChatGPT", arXiv 2506.08872 (MIT Media Lab). PREPRINT. [K]**
  - 54 participants in 3 essay arms (LLM, search, brain-only); 18 completed the 4th crossover session.
  - EEG connectivity was lowest in the LLM arm; LLM users had poorer recall of their own essays.
  - Quality: not peer-reviewed at release; tiny crossover; EEG interpretation contested. Mechanism suggestion only. — [arXiv](https://arxiv.org/abs/2506.08872)
- **Gerlich (2025), "AI Tools in Society: Impacts on Cognitive Offloading and the Future of Critical Thinking", *Societies* 15(1):6. [K]**
  - Survey of 666 participants plus interviews; negative correlation between AI use and self-reported critical thinking, mediated by offloading.
  - Quality: cross-sectional and self-report, so no causal inference. — [MDPI DOI](https://doi.org/10.3390/soc15010006)
- **Stadler, Bannert & Sailer (2024), *Computers in Human Behavior* 160:108386. [K]**
  - Randomized: LLM versus search engine for a science inquiry task (university students).
  - LLM users had lower cognitive load but produced lower-quality reasoning and justifications.
  - Also cited in [Liu et al. 2026](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf). — [DOI](https://doi.org/10.1016/j.chb.2024.108386)
- **Rismanchian 2026 (ALEKS):** large-scale behavioral signature of offloading (less study time, lower proctored retention). Preprint, vendor-affiliated. — [arXiv](https://arxiv.org/html/2605.21629)
- **Strömberg 2026:** the strongest quasi-causal evidence of a cumulative unassisted penalty (−20% monthly exams). Losses concentrate in "outsourcers". — [VoxEU](https://cepr.org/voxeu/columns/generative-ai-learning-penalty-secondary-school)
- **Liu 2026:** 73.8% of real student requests to a course tutor sought information, explanations or solutions; 0.7% sought feedback on their own work. — [EdWP](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf)

### Inferences
- Offloading is a **behavioral default**, not an edge case. Left to choose, most students ask for answers (Liu; Oreopoulos & Low: messages were mostly bare answers).
- The design has to make generation-before-help the path of least resistance: attempt-first, hint ladder, withholding the final answer.
- A tool-free, proctored-style delayed check is the right outcome measure. Rismanchian's reversal between proctored and non-proctored tests shows how unassisted measurement changes the sign of the result.

### Gaps
- No high-quality RCT measures "metacognitive laziness" over a full semester in college.
- I could not verify Kosmyna peer-review status as of Nov 2026.

## Q3. Socratic or answer-withholding versus direct explanation: comparative experiments

### Takeaway
No head-to-head RCT cleanly shows that Socratic beats explanatory on delayed learning.
- The one randomized Socratic versus non-Socratic LLM comparison found no learning difference. Students rated the Socratic version less helpful.
- The cleanest indirect contrasts favor **withholding answers plus grounded hints** over **answer-on-demand**: Bastani GPT Tutor versus Base; Liu tutor mode rarely used, default direct mode harmful.
- Lehmann suggests **explanations are fine (complementary)**. What harms learning is substituting AI for the student's own solution generation.

### Cited findings
- **Randomized Socratic versus non-Socratic AI study (ResearchGate, 2024).** No significant difference in learning outcomes; the Socratic version was perceived as less helpful, with shorter responses. Peer-review venue unverified. [S] — [ResearchGate](https://www.researchgate.net/publication/386547103_The_Impact_of_Large_Language_Models_on_Students_A_Randomised_Study_of_Socratic_vs_Non-Socratic_AI_and_the_Role_of_Step-by-Step_Reasoning_Statements_and_Declarations)
- **Socratic chatbot for 65 pre-service teachers (arXiv 2409.05511).** Higher *perceived* support for critical thinking; no knowledge-gain measure. [S] — [arXiv](https://arxiv.org/html/2409.05511v1)
- **2026 RL "Socratic guide" papers** (e.g., arXiv 2607.22996). Evaluated on simulated students only, so not learning evidence. [S] — [arXiv](https://arxiv.org/pdf/2607.22996)
- **Bastani 2025.** Hint-only, solution-grounded GPT Tutor eliminated the −17% exam penalty of GPT Base. [K] — [PNAS](https://doi.org/10.1073/pnas.2422633122)
- **Liu 2026.** Default "direct instruction" mode, kept by nearly all instructors, gave −0.27 to −0.37 SD grades. [V] — [EdWP](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf)
- **Lehmann 2025.** Asking for explanations (complement) increased understanding; generating solutions (substitute) decreased it. [S] — [arXiv](https://arxiv.org/abs/2409.09047)
- **Kestin 2025.** The tutor explained in small steps and asked the student to try each one, a hybrid rather than pure Socratic. It produced large immediate gains. [K]

### Inferences
- The operative variable is **who generates the solution**, not "questions versus explanations". Short explanations followed by student attempts (Sapling's "short Socratic teach turns plus graded checks") match the positive cases.
- Pure Socratic questioning risks frustration and disengagement: lower perceived helpfulness, and low uptake already plagues deployments.

### Gaps
- No preregistered college RCT of withholding versus explanation with a delayed unassisted test. Sapling could run this internally as an A/B test.

## Q4. Human-in-the-loop (teacher or tutor copilot) versus student-facing AI

### Takeaway
Human-in-the-loop designs have the cleanest positive evidence:
- Tutor CoPilot: +4 pp mastery, +9 pp for weaker tutors.
- Eedi/LearnLM: supervised AI at least as good as human tutors on novel problems.
- Nigeria: teacher-facilitated Copilot, +0.23–0.31 SD.

But teacher-facing GenAI access is not automatically good: Sungu 2026 found lower student motivation and no exam gain.

### Cited findings
- Tutor CoPilot: +4 pp, +9 pp for lower-rated tutors; about $20 per tutor per year. — [arXiv](https://arxiv.org/abs/2410.03017) [K]
- Eedi/LearnLM: 76.4% of drafts approved with minimal edits; 66.2% versus 60.7% on novel later-topic problems. — [arXiv](https://arxiv.org/pdf/2512.23633) [S]
- De Simone 2025: teacher-guided Copilot sessions. — [World Bank](https://openknowledge.worldbank.org/entities/publication/15e1ff08-15ae-4f7a-b2a8-d146e6c113ee/full) [S]
- Sungu et al. 2026 (teacher GenAI access): lower student intrinsic motivation, no exam gain, harm for students of weaker teachers. — via [Liu 2026](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf) [S]

### Inferences
- Humans in the loop mainly buy **error control and pedagogical-move quality**. For a student-facing system like Sapling, the closest analogs are grounding in vetted solutions plus a verifier, and instructor-visible dashboards.

### Gaps
- No college-level copilot RCT found.

## Q5. LLM errors and hallucinations; grounding in vetted content

### Takeaway
Errors are a material risk. Bastani reported frequent GPT-4 math errors in the Base arm, and unvetted ChatGPT hints contained substantial errors (Pardos). The positive studies all used **vetted expert solutions in the prompt** (Kestin, Bastani GPT Tutor) or **human vetting** (Eedi, Pardos). RAG over course materials alone did not produce gains (Liu 2026; Thoeni & Fryer 2026).

### Cited findings
- Pardos & Bhandari 2024: vetted GPT hints matched human-authored hints. [K] — [PLOS ONE](https://doi.org/10.1371/journal.pone.0304013)
- Kestin 2025: instructor-written step-by-step solutions included in the prompt specifically to prevent errors. [K]
- Liu 2026: the RAG tutor is "subject to the same limitations of other LLMs (e.g., hallucinations)". — [EdWP](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf) [V]

### Inferences
- Ground graded checks and hints in a **reference solution**, generated and verified offline or by a stronger model, and compare student answers against it. Don't let the model grade from scratch.

### Gaps
- I found no RCT that directly manipulates tutor error rate and measures learning harm from wrong AI explanations in 2024–2026.

## Q6. Engagement, dose-response, attrition, and who benefits

### Takeaway
Low uptake is the dominant real-world failure mode:
- 15% ever used the tool (Liu);
- the median student messaged on one-third of practice days (Khanmigo).

Dose-response is positive where attendance is structured (Nigeria: 0.031 SD per day). Who benefits is contested:
- LLMs widened prior-knowledge gaps (Lehmann);
- first-generation students were harmed more (Liu);
- Nigeria gains were larger for higher-baseline students;
- Tutor CoPilot helped most where human tutors were weakest;
- Strömberg found larger losses for high achievers.

### Cited findings
- Liu 2026: 14.6% uptake; first-generation losses more than twice those of continuing-generation students; bottom-GPA-quartile students used the tool more. — [EdWP](https://edworkingpapers.com/sites/default/files/ai26-1598.pdf) [V]
- Oreopoulos & Low 2026: 96% tried; low sustained use; mostly bare-answer messages. — [NBER](https://www.nber.org/papers/w35620) [S]
- De Simone 2025: 0.031 SD per day; larger effects for girls and higher performers. — [RePEc](https://econpapers.repec.org/RePEc:wbk:wbrwps:11125) [S]
- Lehmann 2025: widened low/high prior-knowledge gap. — [arXiv](https://arxiv.org/abs/2409.09047) [S]
- Strömberg 2026: larger losses for high achievers, boys and junior students. — [VoxEU](https://cepr.org/voxeu/columns/generative-ai-learning-penalty-secondary-school) [S]

### Inferences
- Embed the tutor in **required workflow** (assigned practice, mastery gates, scheduled reviews) rather than optional chat. Opt-in chat yields low dose and selection effects.
- Monitor subgroups (first-generation, low prior knowledge) explicitly.

## Q7. Meta-analyses, systematic reviews, and critiques (2024–2026)

### Takeaway
Early meta-analyses report moderate-to-large pooled effects (g ≈ 0.7–0.87). They are dominated by short, small, often non-randomized studies with researcher-made, immediate, often AI-assisted outcomes. A 2026 STEM meta-analysis using Robust Bayesian correction found the effect **largely attributable to publication bias** (μ ≈ 0.08).

### Cited findings
- **Wang & Fan (2025), *Humanities and Social Sciences Communications*.** 51 studies on ChatGPT and learning performance; g ≈ 0.87. Cited as "a recent review" by Liu 2026. [K] — [DOI](https://doi.org/10.1057/s41599-025-04787-y)
- **2025 *Educational Technology & Society* meta-analysis.** 31 articles, n=2,646, g = 0.689; authors report no publication bias. [S] — [record](https://acikerisim.bartin.edu.tr/entities/publication/f9d6d08d-b657-4918-8b39-c3b580baade7/full)
- ***Education Sciences* meta-analysis of GenAI feedback.** 36 studies; positive cognitive effects; Egger test not significant but visible asymmetry; authors advise caution. [S] — (found via search, primary URL not captured)
- **2026 systematic review and meta-analysis of GenAI in STEM education (*Artificial Intelligence Review*, Springer, DOI 10.1007/s10462-026-11665-9).** Funnel asymmetry; RoBMA-corrected effect μ = 0.076 ± 0.254; large heterogeneity; moderator findings robust. Paywalled; abstract-level only. [S] — [Springer](https://link.springer.com/10.1007/s10462-026-11665-9)
- **May 2026 arXiv meta-analysis on programming.** 23 studies; productivity versus learning; RoB2 and ROBINS-I risk-of-bias assessments. PREPRINT. [S] — [arXiv](https://arxiv.org/html/2605.04779v1)

### Inferences
- Treat pooled meta-analytic effects as an upper bound. Weight the large field RCTs and natural experiments (Liu, Oreopoulos ×2, Strömberg, Bastani), which mostly show small, null or negative effects for unstructured tools.

### Gaps
- No meta-analysis yet separates delayed or unassisted outcomes from immediate or assisted ones. This is the key moderator and remains unanswered.

## Synthesis: design features associated with gains versus harm

**Consistently with gains or no harm:**
1. Answer withholding with hints. Evidence: Bastani GPT Tutor; Kestin; Khanmigo coach mode, which was neutral.
2. Grounding in expert or instructor solutions, not just course RAG. Evidence: Kestin, Bastani, Pardos.
3. Structured practice with retrieval, where the AI is triggered after the student's own attempt or mistake. Evidence: Oreopoulos mastery+AI.
4. Human supervision or a copilot. Evidence: Tutor CoPilot, Eedi.
5. Scheduled, required dosage. Evidence: Nigeria dose-response.

**Consistently with harm:**
1. Unrestricted or general-purpose chat.
2. Default "direct instruction" answer mode.
3. Optional access that displaces existing practice. Evidence: Liu, −0.90 SD LMS participation.
4. Reduced time on task. Evidence: Strömberg, Rismanchian.

**Evidence gaps relevant to Sapling:**
- delayed (≥1 month) unassisted outcomes in college;
- Socratic versus explanation head-to-head;
- spaced-review integration with LLM tutors (no RCT found);
- subgroup equity effects.
