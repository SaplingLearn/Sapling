# Learner modeling / knowledge tracing for a per-student, per-concept AI tutor

Scope: BKT and extensions, DKT/DKVMN/SAKT/AKT, IRT (1PL/2PL/3PL), Elo-for-learners, Knowledge Space Theory (ALEKS), Bayesian networks over prerequisite graphs, commercial mastery rules, forgetting hooks, evidence weighting, open-source code. Written 2026-09-26. Every numeric claim carries its source; where a PDF could only be partially read, that is flagged.

Method note: several primary PDFs were fetched and text-extracted locally (van de Sande 2013, Baker et al. 2008, Khajah et al. 2016, Gervet et al. 2020, Pelánek 2016 and 2017, Matayoshi & Cosyn 2021, Käser et al. 2017, Wilson et al. 2016, Settles & Meeder 2016, Scarlatos et al. LAK25, Sarsa et al. 2022, Hawkins et al. 2014, Zhang et al. EDM 2025). Numbers below come from those extracted texts unless marked "search summary only".

---

## Q0. What are the exact update equations and typical parameter values (BKT, IRT, Elo, forgetting)?

### Takeaway
BKT is a 4-parameter two-state HMM whose per-answer update is three closed-form lines (Bayes step on the observation, then a learning transition); classic tutors bound P(G) ≤ 0.3 and P(S) ≤ 0.1 and declare mastery at P(L) ≥ 0.95. Elo-for-learners is one logistic line plus one additive update with K ≈ 0.4 or an uncertainty schedule U(n)=a/(1+bn), a=1, b=0.05; IRT is the same logistic with a fixed ability and per-item difficulty (plus discrimination and pseudo-guessing in 2PL/3PL).

### Cited Findings

**BKT (Corbett & Anderson 1995), as formalised by van de Sande 2013:**
- Four parameters: P(L0) initial probability the student knows the skill; P(T) probability of learning at each opportunity (assumed constant over time); P(G) probability of a correct answer when not knowing; P(S) probability of an incorrect answer when knowing — [van de Sande 2013, JEDM](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Learning transition (eq. 1): `P(L_j) = P(L_{j-1}) + P(T)·(1 − P(L_{j-1}))`; observation model (eq. 2): `P(C_j) = P(G)·(1 − P(L_j)) + (1 − P(S))·P(L_j)` — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Posterior after a CORRECT answer (eq. 8): `P(L_{j-1}|O_j) = P(L_{j-1}|O_{j-1})·(1−P(S)) / [ P(L_{j-1}|O_{j-1})·(1−P(S)) + (1−P(L_{j-1}|O_{j-1}))·P(G) ]` — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Posterior after an INCORRECT answer (eq. 9): `P(L_{j-1}|O_j) = P(L_{j-1}|O_{j-1})·P(S) / [ P(L_{j-1}|O_{j-1})·P(S) + (1−P(L_{j-1}|O_{j-1}))·(1−P(G)) ]` — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Then apply learning (eq. 10): `P(L_j|O_j) = P(L_{j-1}|O_j) + (1 − P(L_{j-1}|O_j))·P(T)` — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Combined single-line forms (eqs. 11–12): correct: `P(L_j|O_j) = 1 − (1−P(T))·(1−P(L_{j-1}|O_{j-1}))·P(G) / [ P(G) + (1−P(S)−P(G))·P(L_{j-1}|O_{j-1}) ]`; incorrect: `P(L_j|O_j) = 1 − (1−P(T))·(1−P(L_{j-1}|O_{j-1}))·(1−P(G)) / [ 1−P(G) − (1−P(S)−P(G))·P(L_{j-1}|O_{j-1}) ]` — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Closed-form population learning curve: `P(C_j) = 1 − P(S) − A·e^{−βj}` with `A = (1−P(S)−P(G))·(1−P(L0))`, `β = −log(1−P(T))` — i.e. the marginal curve depends on only three quantities, which is the root of the Beck & Chang (2007) "identifiability problem" — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Worked example parameter set used in the paper's figure: P(S)=0.05, P(G)=0.3, P(T)=0.1, P(L0)=0.36 — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Validity constraints for the online algorithm: `P(G) + P(S) < 1` (eq. 15) and `0 < P(T) < 1 − P(S)/(1−P(G))` (eq. 16); if P(G)+P(S) > 1 the update inverts (correct answers lower P(L)) — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Cognitive Tutor practice (2008): "the guess parameter is bounded to be between 0 and 0.3, and the slip parameter is bounded to be between 0 and 0.1, based on the most common number of candidate actions"; a model is "theoretically degenerate" when G or S > 0.5; mastery in Cognitive Tutors = P(L) ≥ 0.95 — [Baker, Corbett & Aleven 2008](https://learninganalytics.upenn.edu/ryanbaker/BCA2008W.pdf)
- A 2024 first-principles derivation gives the same family of constraints: 0<P(G)<1, 0<P(S)<1, 0<P(T)<1, `1 − P(S) − P(G) ≥ 0`, and a steady-state condition `P(L0) > (1−P(G))·P(T) / (1−P(S)−P(G))`; on 100 simulated datasets Baum-Welch produced 20% degenerate fits while a constrained EM-Newton produced none — [EDM 2024 "Parametric Constraints for BKT from First Principles"](https://educationaldatamining.org/edm2024/proceedings/2024.EDM-long-papers.2/index.html)
- Fitting practice in 2025 (Rori tutor): grid-search fit with G and S constrained to [0.01, 0.3] "to avoid model degeneracy" — [Zhang, Vanacore, Baker et al., EDM 2025](https://files.eric.ed.gov/fulltext/ED675652.pdf)

**BKT + forgetting (Khajah, Lindsey & Mozer 2016):**
- Forgetting adds a parameter F = probability of transitioning from knowing to not knowing; with forgetting, "BKT can count the number of intervening trials and treat each as an independent opportunity for forgetting to occur", so the probability of forgetting across n intervening trials compounds — [Khajah et al. 2016, EDM](https://arxiv.org/abs/1604.02416)
- pyBKT exposes this as `forgets=True`, the parameter being "the probability of transitioning to the 'not knowing' state given 'known'" — [pyBKT README](https://github.com/CAHLR/pyBKT)

**Elo for learners (Pelánek 2016):**
- Probability of a correct answer: `P(correct_si = 1) = 1 / (1 + e^{−(θ_s − d_i)})`; updates: `θ_s := θ_s + K·(correct_si − P(correct_si = 1))`, `d_i := d_i − K·(correct_si − P(correct_si = 1))`; initial θ_s and d_i are 0 — [Pelánek 2016, Computers & Education](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Multiple-choice with k options — shifted logistic: `P(correct) = 1/k + (1 − 1/k) / (1 + e^{−(θ_s − d_i)})` — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- K: "Previous work in student modeling used K = 0.4"; small K converges too slowly, large K is unstable — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Uncertainty functions replacing constant K: `U(n) = a/(1 + b·n)` with n = number of answers so far, fitted a=1, b=0.05 (Papoušek 2014 / Nižnan 2015); Wauters 2011: `U(n) = w0/(1 + a·e^{bn})`, w0=0.2, b=50, a∈[0.01,0.15]; Klinkenberg 2011 (Math Garden): U initialised to 1 and updated `U := U − 1/40 + (1/30)·D`, D = days since previous attempt — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Recommended default: "the basic version of the Elo rating system extended with a simple uncertainty function U(n) = a/(1+bn) provides a good starting point (e.g., with values a = 1, b = 0.05; once enough data are collected these values can be easily fitted using a grid search)"; "the precise choice of parameter values is not fundamental" — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Use different uncertainty functions for items vs students, because items accumulate far more answers than any one student — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Asymmetric "PFAE" learning variant (answering is also a learning opportunity): `θ_si := θ_si + γ·(1 − P)` if correct, `θ_si := θ_si + δ·P` if incorrect, with separate constants γ, δ — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Multivariate extension across knowledge components with correlation c_ij: `θ_sj := θ_sj + c_ij·K·(correct − P(correct))` for every KC j after an answer on KC i — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- The Elo update is one-pass SGD on the logistic log-loss; K is the learning rate — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)

**IRT (1PL/2PL/3PL):**
- 1PL/Rasch: P(correct) = f(θ_s − β_i), f sigmoidal; Knewton's 2016 implementation used the probit link ("1PO") with independent N(0,1) priors on every θ_s and β_i and MAP estimation, because the unregularised MLE is underdetermined — [Wilson et al. 2016 (Knewton), EDM](https://arxiv.org/pdf/1604.02336)
- 3PL: `P(correct) = c_i + (1 − c_i) / (1 + exp(−a_i(θ − b_i)))` with a = discrimination, b = difficulty, c = pseudo-guessing lower asymptote — [Stata irt 3pl manual](https://www.stata.com/manuals/irtirt3pl.pdf)
- c is "the probability that an examinee with very low ability will get the item correct due to guessing"; worked examples use c = 0.25 (4-option MC, giving P = (1+0.25)/2 = 0.655 at θ = b) and c = 0.15; example discriminations quoted: 0.19, 0.58, 0.86, 1.5, 2.5 — [Iowa Reading Research Center 2020](https://irrc.education.uiowa.edu/blog/2020/09/technically-speaking-determining-test-effectiveness-item-response-theory); [Assessment Systems, c parameter](https://assess.com/irt-item-pseudo-guessing-parameter/)
- Basic IRT assumes a constant skill, so it is "applicable only for short tests (where we do not expect learning) or for modeling very 'coarse-grained' skills"; Elo relaxes this by letting K stay large when skill is expected to change — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)

**Half-life regression (Duolingo, Settles & Meeder 2016) — the standard knowledge×time form:**
- `p = 2^{−Δ/h}` (Δ = lag since last practice, h = half-life) and `ĥ_Θ = 2^{Θ·x}`; loss `(p − p̂)² + α·(h − ĥ)² + λ‖Θ‖²`; features are counts of correct/incorrect exposures (square-rooted counts worked better than raw) plus lexeme tags — [Settles & Meeder 2016, ACL](https://research.duolingo.com/papers/settles.acl16.pdf)

### Inferences
- The BKT per-answer update is O(1) with three multiplications and a division; it is trivially cheap on every answer in a FastAPI request and needs only four floats per (concept) plus one float per (student, concept).
- Elo/PFAE is even cheaper to reason about (one float per student-concept, one per item) and needs no batch fitting at all; its cost is the loss of a calibrated "probability knows" semantics — θ is a logit-scale skill, not P(L).
- Both models are logistic under the hood (Pelánek notes Elo = SGD on logistic loss), which is why a single Postgres row per (student, concept) can hold either.

### Gaps
- Corbett & Anderson's original 1995 paper was not fetched; the "typical P(S)=0.10, P(G)=0.30" pairing appears only in a search summary. The 0.3/0.1 bounds from Baker et al. 2008 are the verified anchor.
- No literature-wide "typical" value for P(L0) and P(T) was found; values are skill-specific (the van de Sande example uses L0=0.36, T=0.1).

---

## Q1. Comparative accuracy and known failure modes (BKT identifiability, DKT data hunger, guessing/slipping)

### Takeaway
On the standard benchmarks, well-featured logistic regression, BKT+extensions and DKT are all within ~0.02–0.05 AUC of each other (0.75–0.86 depending on dataset); DKT's originally reported 25% AUC gain over BKT was mostly an artefact of AUC computation and of BKT lacking forgetting. BKT's "identifiability" problem is really a degeneracy problem that bounds on G/S fix; DKT overfits datasets with few learners per item.

### Cited Findings

**DKT vs BKT: the corrected picture**
- Piech et al. 2015 reported a 25% gain in AUC for DKT over BKT (0.86 vs 0.67 on ASSISTments) — as summarised in [Khajah et al. 2016](https://arxiv.org/abs/1604.02416) and [Gervet et al. 2020](https://jedm.educationaldatamining.org/index.php/JEDM/article/view/451)
- Re-run on the same ASSISTments split: classic BKT AUC 0.73 (not 0.67); BKT+Forgetting 0.83 vs DKT 0.86; "31.6% of difference in performance reported in [Piech] appears to be due to the use of a biased procedure for computing the AUC for BKT. Another 50.6% of the difference … vanishes if BKT is augmented to allow for forgetting"; with exercise-indexed skill discovery BKT+S and BKT+FSA reach 0.90, "beating DKT" — [Khajah, Lindsey & Mozer 2016](https://arxiv.org/abs/1604.02416)
- The three ingredients DKT exploits and BKT lacks: recency effects, inter-skill similarity, individual variation in ability — [Khajah et al. 2016](https://arxiv.org/abs/1604.02416)
- Knewton's team could not reproduce 0.86 for DKT on ASSISTments; after de-duplicating the raw log they got DKT 0.7429 vs 1PL-IRT 0.7651, temporal IRT 0.7653, hierarchical IRT 0.7740; on KDD: IRT 0.8542, HIRT 0.8597, DKT 0.8110; on Knewton's own data (6.3K students, 1M responses): IRT 0.8045, TIRT 0.8166, HIRT 0.8189, DKT 0.7756 — [Wilson et al. 2016](https://arxiv.org/pdf/1604.02336)

**Gervet et al. 2020 — nine-dataset benchmark (AUC, 5-fold, ± s.d.)**
- Dataset sizes (learners / interactions / KCs): algebra05 574 / 607K / 112; bridge06 1,146 / 1.8M / 493; assist09 3,241 / 279K / 124; assist12 29,018 / 2.7M / 265; assist17 1,708 / 935K / 102; statics 282 / 189K / 98; squirrel 24,500 / 6.0M / 742; spanish 182 / 579K / 221; assist15 14,657 / 659K / 100 — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- algebra05: Best-LR 0.831, DAS3H 0.827, DKT 0.821, SAKT 0.801, PFA 0.769, IRT 0.768, BKT 0.621 (prior report) — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- assist09: Best-LR 0.772, BKT+ 0.759, DKT 0.757, SAKT 0.756, PFA 0.724, IRT 0.692, BKT 0.631 (prior report) — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- assist12: DKT 0.771, Best-FFW 0.767, Best-LR 0.751, DAS3H 0.740, SAKT 0.732, IRT 0.713, PFA 0.669 — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- assist17: DKT 0.770, Best-FFW 0.761, SAKT 0.722, Best-LR 0.714, BKT+ 0.710, DAS3H 0.693, IRT 0.681, PFA 0.619 — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- statics: DKT 0.829, Best-LR 0.819, SAKT 0.813, BKT+ 0.811, IRT 0.789, PFA 0.691, BKT 0.732 (prior) — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- spanish: Best-LR 0.863, BKT+ 0.851, PFA 0.847, DKT 0.832, SAKT 0.831, IRT 0.679 — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- assist15: DKT 0.731, SAKT 0.730, Best-LR 0.702, BKT+ 0.701, PFA 0.690, IRT 0.638 (Pandey & Karypis had reported SAKT 0.85 here; Gervet: "we could not reproduce and seems impossible") — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- Headline: "Logistic regression - with the right set of features - leads on datasets of moderate size or containing a very large number of interactions per student, whereas Deep Knowledge Tracing leads on datasets of large size or where precise temporal information matters most"; "DKT overfits small datasets but LR underfits large datasets"; SAKT underperformed DKT on every dataset — [Gervet et al. 2020](https://jedm.educationaldatamining.org/index.php/JEDM/article/view/451)
- BKT+ (Khajah's extended BKT) "is competitive with Best-LR, but because it is orders of magnitude slower to train than alternatives" it could not be run on the large datasets — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- DKT plateaus after ~1000 interactions per student (spanish, bridge06) — RNNs lose long-range information; count-feature LR keeps improving — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)

**Deep successors (DKVMN, SAKT, AKT)**
- Independent re-implementation with hyperparameter sweeps on ASSISTments 2009 (updated): Vanilla-DKT 0.809, LSTM-DKT 0.814, DKVMN 0.809, SAKT 0.798, GLR 0.729 AUC; ASSIST2015: DKT ~0.720–0.725; "the AUC scores between the best two models … are typically within 0.02 AUC of each other" and differences of ~0.02 between papers are "likely due to differences in hyperparameter tuning" — [Sarsa et al. 2022](https://arxiv.org/pdf/2112.15072)
- pyKT benchmark (NeurIPS 2022): "the improvement of many DLKT approaches is minimal compared to the very first DLKT model proposed by Piech et al." and "wrong evaluation setting may cause label leakage that generally leads to performance inflation" — [Liu et al. 2022, pyKT](https://arxiv.org/abs/2206.11460)

**BKT identifiability / degeneracy**
- Beck & Chang 2007: different (P(G), P(L0)) combinations give the same marginal error curve — explained by the A = (1−S−G)(1−L0) collapse; but "the 'Identifiability Problem' for the Knowledge Tracing Algorithm does not exist, so long as there are both correct and incorrect steps … all four model parameters are needed" — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf)
- Doroudi & Brunskill 2017 ("The Misidentified Identifiability Problem"): under mild conditions BKT is identifiable; the practical problem is semantic degeneracy (nonsensical fitted parameters), a symptom of model mismatch — [ERIC ED577166](https://files.eric.ed.gov/fulltext/ED577166.pdf) (search summary only)
- Empirical degeneracy tests: (1) 3 correct answers in a row should not lower P(L); (2) 10 correct in a row should reach mastery; unbounded EM fits failed these for 23% / 5% of skills; contextual guess/slip failed the mastery test for 1.7% — [Baker, Corbett & Aleven 2008](https://learninganalytics.upenn.edu/ryanbaker/BCA2008W.pdf)
- Prediction quality (A′) on Cognitive Tutor data: baseline BKT 0.66, bounded G/S 0.61, contextual G/S 0.75 — [Baker, Corbett & Aleven 2008](https://learninganalytics.upenn.edu/ryanbaker/BCA2008W.pdf)
- EM and brute-force grid search "both suffer from identifiability. Additionally, EM can get stuck on local minima, and brute force comes with a high computational cost"; the Empirical Probabilities (EP) fit gave MAE 0.374 / RMSE 0.428 / A′ 0.615 vs EM 0.383 / 0.424 / 0.591, "mathematically impossible for EP to learn theoretically degenerate guess and slip rates" — [Hawkins, Heffernan & Baker 2014](https://learninganalytics.upenn.edu/ryanbaker/paper_143.pdf)
- StanBKT (2026): most implementations "yield only point estimates, limiting uncertainty quantification"; Stan-based HMC/VI/Pathfinder fits give posterior intervals on learn/forget/guess/slip with comparable predictive performance on ASSISTments 2020 — [Pradhan et al. 2026, arXiv](https://arxiv.org/abs/2605.23048)

**Guessing and slipping in multiple choice**
- For k-option MC use the shifted logistic (floor 1/k) — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- ALEKS avoids MC entirely: items use "answer input tools that mimic what would be done with paper and pencil. As such, the lucky guess probability may be assumed to be very small", so a correct answer moves the state distribution substantially, while an incorrect answer "cannot be very aggressive given that there is a non-negligible chance for a careless error"; an "I don't know" button lets the system update aggressively downward — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- KT-IDEM (per-item guess/slip) improves AUC by ~0.02 on ASSISTments 2009 (0.019 in pyBKT's replication vs 0.021 in the original) — [Badrinath, Wang & Pardos 2021, pyBKT](https://arxiv.org/abs/2105.00385)

### Inferences
- For a tutor whose goal is a defensible per-concept P(knows) (not leaderboard AUC), the accuracy differences above are within noise once BKT has forgetting and per-evidence-type guess/slip; the decision should be driven by data volume and interpretability, not by benchmark AUC.
- Any reported AUC must be checked for (a) per-trial vs per-skill averaging and (b) duplicate rows / label leakage; both have inflated published gaps by ≥0.05.

### Gaps
- No single paper reports AKT alongside BKT and Best-LR on identical splits with hyperparameter sweeps; pyKT has such tables but the fetched abstract did not expose the numbers.
- DKVMN/AKT numbers on small datasets (hundreds of students) are absent from the sources read.

---

## Q2. Which model is best with tens of students per course and few observations per concept? What do practitioners recommend for cold start?

### Takeaway
With tens of students there is not enough data to fit any model's parameters per concept from scratch (BKT fitting wants ~50 students × ~15 opportunities per skill; DKT wants thousands of learners). Practitioners recommend a fixed-parameter or strongly-prior'd online model — Elo/PFAE with an uncertainty schedule, or BKT run with literature priors and bounded G/S — and treating fitting as a later refinement.

### Cited Findings
- Data sufficiency for BKT fitting: "50 as a reasonable number of students to achieve convergence to canonical parameter values with any average student sequence length and 15 as a reasonable sequence length to mitigate worst-case mastery estimation accuracy"; parameter error shows "exponential error decay with respect to the number of students", and adding students helps more than lengthening sequences — [Badrinath, Wang & Pardos 2021, pyBKT](https://arxiv.org/html/2105.00385v2)
- The smallest Gervet datasets where LR beat DKT still had 574–3,241 learners; DKT "overfits small datasets" — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- Per-student cold start: "DKT needs 6 times fewer interactions than Best-LR to reach close to peak performance on a new student on the squirrel dataset", reducing the "burn-in" period — but only after being trained on 24,500 learners — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- Elo needs no fitting: "The system requires us to set only the parameter K (respectively the uncertainty function) – other student models typically have more parameters and require calibration or complex parameter fitting"; new items are added by resetting difficulty to 0; "the application of the Elo rating system is cheap as it requires expert input neither for domain knowledge nor for implementation" — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- With U(n)=a/(1+bn) "we can quickly get coarse estimates, which are then fine-tuned"; a principled Bayesian treatment of uncertainty gave estimates "very similar" to this heuristic — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- Developer guidance: "it is typically better to have a simple implementation of all important components than to have a very sophisticated model of learning … it is thus preferable to use simple learner models unless there is a clear reason to prefer more complex models" — [Pelánek 2017, UMUAI overview](https://link.springer.com/article/10.1007/s11257-017-9193-2) ([preprint](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf))
- Individualised (per-student) parameters "are fitted using only few data points and thus can be significantly influenced by the noise in data"; group-level individualisation (same parameters per class) is the mitigation — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)
- Hypothesis from the same overview: "If the model is used for mastery detection, it is more important what data are used for modeling than the exact details of models … Slightly different models with the same input data lead to very similar mastery decision" — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)
- IRT with small data: Knewton regularises with N(0,1) priors on every student and item parameter because the MLE is underdetermined — [Wilson et al. 2016](https://arxiv.org/pdf/1604.02336)
- Student-level cold start in BKT+A: "When the model is presented with new students, the posterior predictive distribution on abilities is used initially, but as responses from the new student are observed, uncertainty in the student's ability diminishes" — [Khajah et al. 2016](https://arxiv.org/abs/1604.02416)
- ALEKS's cold start is an adaptive initial assessment: the prior over knowledge states "is not uniform but is instead informed by past assessment data from the course"; capped at 30 questions (29 + one random "extra problem"); each next item is chosen so the probability of states containing it is ≈0.5; an item is called in-state above 80% likelihood and out-of-state below 20%; "uncertain" items are then fast-tracked in learning mode (target score 3 instead of 5) — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Empirical-Probabilities fitting (Hawkins 2014) computes the four parameters directly from a heuristic knowledge sequence: P(L0) = mean knowledge on first opportunity; P(T), P(G), P(S) as ratios of counts of transitions/observations — no EM, "considerably faster", cannot produce G or S > 0.5 — [Hawkins, Heffernan & Baker 2014](https://learninganalytics.upenn.edu/ryanbaker/paper_143.pdf)
- 2024 constrained EM-Newton fitting produced only valid (non-degenerate) parameter sets on 100 simulated datasets where Baum-Welch gave 20% degenerate — [EDM 2024](https://educationaldatamining.org/edm2024/proceedings/2024.EDM-long-papers.2/index.html)
- Evidence that priors on the update matter more than the model: in the LAK25 dialogue-tutoring study with only 153 dialogues (CoMTA), BKT, DKT, DKVMN, AKT, SAINT and simpleKT all scored AUC 0.47–0.53 — no better than the majority-class baseline — while on 2,823 dialogues (MathDial) they reached 0.60–0.64 — [Scarlatos, Baker & Lan, LAK 2025](https://arxiv.org/abs/2409.16490)

### Inferences
- With tens of students per course, per-concept EM fitting is out; the defensible configuration is BKT with fixed, bounded parameters (e.g. L0 ≈ 0.3–0.4, T ≈ 0.1–0.2, G ≤ 0.3, S ≤ 0.1, as in van de Sande's example and the Cognitive Tutor bounds) applied online, optionally with per-concept L0 set from a short diagnostic (ALEKS-style) rather than fitted.
- Elo/PFAE with U(n)=1/(1+0.05n) is the lowest-risk alternative when a calibrated probability is not required; it is defined for the very first answer and never degenerates.
- Cross-course pooling is the practical route to later fitting: the pyBKT thresholds (50 students, 15 opportunities) are reachable if concepts are shared across offerings, which argues for keeping BKT parameters keyed on the abstract concept rather than the offering.
- DKT-family models are not viable for this data regime; even the LAK25 dialogue study, from the group that wrote pyBKT, found all neural KT models at chance on 153 dialogues.

### Gaps
- No controlled study was found comparing fixed-parameter BKT vs Elo vs fitted BKT at N = 10–50 students; the recommendations above combine the pyBKT sufficiency analysis, Pelánek's practitioner advice and the small-data failures in Gervet/LAK25.
- A search snippet attributed "as few as 25 students and 3 opportunities" to the pyBKT literature, but the fetched pyBKT text states 50 / 15; the 25 / 3 figure is unverified.

---

## Q3. How do you propagate evidence along prerequisite edges (KST fringes, Bayesian nets, Elo hierarchies)?

### Takeaway
Three working mechanisms exist: (1) KST keeps a distribution over closed knowledge states, so a correct answer on an advanced item automatically raises every state that contains it — and those states contain its prerequisites; (2) dynamic Bayesian networks put explicit CPT parameters on "child known given parents", giving +0.09 to +0.20 AUC over BKT on structured domains but with cost exponential in the number of parents; (3) heuristic Elo/IRT propagation adds damped updates to related concepts (Pelánek's c_ij, Knewton's "proficiency propagation").

### Cited Findings

**Knowledge Space Theory / ALEKS**
- A knowledge structure (Q, K) lists the feasible subsets (states) of the item set Q; states are far fewer than 2^|Q| because "some items are prerequisites of other items"; a 314-item placement course has about 10^23 (≈ 2^77) states — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Outer fringe of state K = items q ∉ K with K ∪ {q} also a state ("ready to learn"); inner fringe = items q ∈ K with K \ {q} also a state ("high points"); in a learning space "the knowledge state of a student is completely determined by the inner fringe and the outer fringe of the state (Theorem A.2)" — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Assessment = "a probabilistic search among all of the feasible states": after a correct response "the update results in an increase of probability for the states containing the item and a decrease for the other states"; incorrect goes the other way; the update rule is Definition 13.4.4 of Falmagne & Doignon 2011, whose parameters have "a Bayesian interpretation … that links them to the lucky guess and careless error rates of the items" — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Because full state lists are intractable, ALEKS partitions items into substructures small enough to enumerate, updates the substructure containing the answered item, and "a key feature of the algorithm is" propagating to substructures the item does not belong to — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Progress assessments "run a local search, essentially in the neighborhood of the knowledge states recently crossed by the student" — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Validity of the initial assessment at predicting a held-out "extra problem": AUROC 0.875 (Sixth-Grade Math, n=162,900), 0.863 (College Algebra, n=174,073), 0.889 (College Placement, n=2,775,432); accuracy 0.80–0.81 — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Falmagne's own account of the theory and its validity is at [The Assessment of Knowledge, in Theory and in Practice](https://www.aleks.com/about_aleks/Science_Behind_ALEKS.pdf) and [Assessing Mathematical Knowledge in a Learning Space](https://www.aleks.com/paper_psych/Validity_in_L_Spaces.pdf) (not fetched; listed for the report writer)

**Dynamic Bayesian networks with prerequisite CPTs (Käser et al.)**
- Prerequisite encoding: the mastery of skill S_N at time t depends on S_N at t−1 and on the current states of its prerequisites S_A, S_G; named parameters: p_L0 = probability of learning S_N "despite not knowing S_A and S_G", p_LM = learning given at least one prerequisite known, p_F1 = forgetting when all prerequisites known, p_FM = forgetting when not all known, p_P0 = "probability of knowing a skill despite having mastered only part of the prerequisite skills", p_P1 = "probability of failing a skill given that all precursor skills have been mastered", plus p_0, p_G, p_L, p_F — [Käser, Klingler, Schwing & Gross 2017, IEEE TLT](https://cgl.ethz.ch/Downloads/Publications/Papers/2017/Kae17a/Kae17a.pdf)
- A CPT over n skills needs 2^(n−1) parameters; parameters are learned by constrained optimisation in a log-linear form because unconstrained learning "might result in degenerate models with for example a probability of guessing p_G > 0.5"; constraint sets bound guess/slip/learn/forget at ≤ 0.3 (C1/C2) or ≤ 0.2 (C3/C4) — [Käser et al. 2017](https://cgl.ethz.ch/Downloads/Publications/Papers/2017/Kae17a/Kae17a.pdf)
- Results (AUC): Subtraction (Calcularis): BKT 0.5995 → DBN 0.6882 (C2) / 0.6928 (C4), PFA 0.6532; Physics (77 USNA students, Andes): DBN 0.7021 vs BKT 0.4991, PFA 0.5807, AFM 0.5425; Algebra (Bridge to Algebra, 6,043 students): DBN 0.7042 vs BKT 0.6012, AFM 0.6034, PFA 0.6407; RMSE gains of ~3–6% — [Käser et al. 2017](https://cgl.ethz.ch/Downloads/Publications/Papers/2017/Kae17a/Kae17a.pdf)
- Earlier EDM 2014 version: "up to 10% cross-entropy reduction for hierarchical domains, 5% RMSE improvements"; "DBN models generally exhibit a significantly higher AUC than BKT" — [Käser et al. 2014, EDM](https://cgl.ethz.ch/publications/papers/paperKae14b.php)
- Cost caveat: "Due to the loopy structure, the learning task for DBNs is computationally more expensive than the one for HMMs" — [Käser et al. 2017](https://cgl.ethz.ch/Downloads/Publications/Papers/2017/Kae17a/Kae17a.pdf); Bayesian networks "make high demands on computational resources, because parameter estimation becomes difficult" — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)

**Heuristic propagation (Elo / IRT)**
- Multivariate Elo: after an answer on KC i, update every KC j by `θ_sj += c_ij·K·(correct − P)` where c_ij is an empirical correlation — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf); "For practical applications it is useful to consider more heuristic approaches, e.g., a hierarchical extension of the Elo rating system (Nižnan et al., 2015b)" — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)
- Knewton alta: IRT-based proficiency plus "the structure of the Knewton Knowledge Graph, in particular the prerequisite relationships between learning objectives"; "proficiency propagation, or the flow of proficiency throughout the Knowledge Graph" infers "high proficiency on related prerequisites even without direct evidence" (mastering two-digit subtraction word problems implies the subtraction prerequisites) — [Knewton alta blog (Wiley)](https://www.wiley.com/en-us/grow/teach-learn/teacher-resources/courseware/knewton-alta/resources/alta-blog-how-does-knewton-proficiency-model-estimate/)
- Knewton's published research model (2016) is hierarchical IRT where item difficulties share a prior through their parent concept/template (σ², τ² hyperparameters) — [Wilson et al. 2016](https://arxiv.org/pdf/1604.02336)

### Inferences
- The KST "fringe" logic maps directly onto a prerequisite DAG: outer fringe = concepts whose prerequisites are all mastered (the next-to-teach set); inner fringe = mastered concepts with no mastered dependents (the ones to re-verify first, since demoting them keeps the state consistent).
- A cheap, monotone propagation rule consistent with all three sources: on a correct answer at concept c, apply a damped update to each ancestor a (Elo: `θ_a += c_ac·K·(1−P_c)`; BKT: treat it as a soft observation with high guess/low weight); on an incorrect answer at c, do not lower ancestors (an error can be local), but lower descendants of c (in KST every state containing a descendant contains c). This is the asymmetric direction the state-closure implies.
- Full DBN inference is unnecessary at request time: with a DAG where each concept has ≤ 3–4 parents, a noisy-AND CPT (Käser's p_P1 / p_P0 style) evaluated on the current per-concept beliefs is O(#parents) per concept.

### Gaps
- The exact ALEKS update-rule constants (footnote 3 mentions "update parameters … about 35 for a …" and then the extracted text truncates) could not be recovered; Falmagne & Doignon 2011 §13.4 is the primary reference.
- Knewton's propagation equations are not public; only the blog's qualitative description exists.
- Nižnan et al. 2015b (hierarchical Elo) was not fetched; only Pelánek's citation of it.

---

## Q4. How do commercial systems model mastery, and what thresholds define "mastered"?

### Takeaway
Carnegie Learning MATHia uses BKT with mastery at P(L) > 0.95 per KC; ALEKS uses KST with item likelihood ≥ 0.80 in assessment and a score-to-5 rule in learning mode; Khan Academy moved from a 10-in-a-row streak to per-exercise logistic regression (2011) and now uses discrete Familiar/Proficient/Mastered levels driven by ≥70% practice accuracy and unit-test performance; Knewton uses continuous IRT with recency weighting; Duolingo models recall half-life rather than mastery. Evidence (2025) suggests 0.98 beats 0.95 for downstream learning.

### Cited Findings
- MATHia: "Knowledge component mastery is traced according to Bayesian Knowledge Tracing (BKT)"; "Students master a workspace when BKT's probability estimate of mastery of each KC is greater than the oft-adopted value of 0.95"; roughly 700 KCs per grade level — [Ritter et al., MATHia X, EDM 2016](https://www.educationaldatamining.org/EDM2016/proceedings/paper_187.pdf) and [Fancsali et al., "Towards Practical Detection of Unproductive Struggle", AIED 2020](https://files.eric.ed.gov/fulltext/ED606472.pdf) (search summary only)
- "A common stopping criterion is '95 % chance that a learner knows the next item'"; a learner model is not strictly needed — "k correct in a row" is also used — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)
- Prior simulation work found skill-specific optimal thresholds "ranging from 0.9 to 0.97"; the Rori study (upper-elementary/junior-high math, BKT with G,S ∈ [0.01,0.3]) binned end-of-lesson P(L_n) into 8 levels and found students at ≥ 0.98 had significantly higher next-lesson accuracy than those at 0.95–0.98 (estimate 0.041, p < 0.001) and higher next-lesson learning gains; conclusion: "P(Ln) > 0.98 may serve as a more effective threshold" — [Zhang, Vanacore, Baker, Ch, Mills & Henkel, EDM 2025](https://files.eric.ed.gov/fulltext/ED675652.pdf)
- ALEKS learning mode: each outer-fringe item has a score starting at 0; a correct answer +1, the second correct answer of a streak of two +2 (total 3), incorrect −1 (floor 0), reading the explanation breaks the streak; the item is "(provisionally) learned" at a target score of 5 (3 if the item was "uncertain" after assessment or was previously learned and then lost); five consecutive incorrect = failed attempt; periodic progress assessments then confirm or remove items — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- ALEKS assessment classification: in-state if item likelihood > 80%, out-of-state if < 20%; the state reported "may underestimate the student's latent state" because uncertain items are excluded — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Khan Academy 2011: replaced the streak-based proficiency rule with "a logistic regression on six data features … a model … for every exercise", with online SGD considered "for online learning of logistic regression which would allow adaptive models per user and per exercise" — [David Hu, Khan Academy, 2011 (repost)](https://statmodeling.stat.columbia.edu/2011/11/02/how-khan-academy-is-using-machine-learning-to-assess-student-mastery/) (search summary only; page returned 403 on fetch)
- Khan Academy current levels: Familiar = ≥ 70% correct on a practice set or the skill correct on a quiz/unit test; Proficient = a Familiar skill correct on a quiz/unit test, or 100% on a quiz; Mastered = start at Proficient and get all questions on that skill right on a Unit Test or Course Challenge; points 50/80/100; levels can go down when quiz/test items are missed; only Proficient and Mastered count toward unit/course mastery percentage — [Khan Academy Help Center, "How do Khan Academy's Mastery levels work?"](https://support.khanacademy.org/hc/en-us/articles/5548760867853--How-do-Khan-Academy-s-Mastery-levels-work) (search summary only; page returned 403)
- Knewton alta: proficiency model "based on Item Response Theory"; uses "temporal models that weight a student's recent responses more heavily than their older ones"; no numeric mastery threshold is published — [Knewton alta blog (Wiley)](https://www.wiley.com/en-us/grow/teach-learn/teacher-resources/courseware/knewton-alta/resources/alta-blog-how-does-knewton-proficiency-model-estimate/)
- Duolingo (2016): half-life regression predicts recall probability per student-word, replacing a Leitner-style skill meter; HLR MAE 0.128 vs Leitner 0.235, Pimsleur 0.445, logistic regression 0.211 on 12.9M traces; but AUC was only 0.538 (Leitner 0.542); a 12% daily-engagement lift in an operational study — [Settles & Meeder 2016](https://research.duolingo.com/papers/settles.acl16.pdf)

### Inferences
- Every commercial rule is a threshold on a monotone statistic plus a re-verification loop (ALEKS progress assessment, Khan unit test, MATHia's continued tracing). A single P(L) ≥ 0.95 without re-verification is the weakest of the deployed designs.
- Given the 2025 Rori result, a tutor that can afford the extra practice should set the mastery cut at 0.98 and keep 0.95 as "proficient"; a two-tier label mirrors Khan's Proficient/Mastered.

### Gaps
- The 2011 Khan logistic-regression proficiency threshold on predicted accuracy was not recoverable (the page was blocked); a commonly repeated figure is 94% but no fetched source states it.
- No public Carnegie Learning document with per-KC BKT parameter values was found.

---

## Q5. How should a knowledge estimate be combined with a forgetting / time component?

### Takeaway
Two compatible mechanisms: inside BKT, a forget transition P(F) applied once per intervening trial (Khajah 2016) or per elapsed time; outside BKT, a half-life decay p = 2^{−Δ/h} on the belief (Settles & Meeder 2016) or a time-dependent uncertainty term in Elo (Klinkenberg 2011). Forgetting matters most for fact/fluency knowledge and only slightly for conceptual understanding (Pelánek 2017 hypothesis).

### Cited Findings
- BKT+F: "Forgetting corresponds to fitting a parameter F representing the probability of transitioning from knowing to not knowing a skill"; without forgetting "once BKT infers that the student has [learned], no subsequent evidence can alter the inferred knowledge state"; forgetting counted per intervening trial makes BKT sensitive to recency and lifted ASSISTments AUC from 0.73 to 0.83 — [Khajah et al. 2016](https://arxiv.org/abs/1604.02416)
- The original day-to-day forgetting extension to BKT was motivated by "forgetting from one day to the next, not forgetting that can occur on a much [shorter] time scale" — [Khajah et al. 2016](https://arxiv.org/abs/1604.02416)
- HLR: `p = 2^{−Δ/h}`, `ĥ = 2^{Θ·x}` with x = (√count_correct, √count_incorrect, lexeme tags); fitted with a squared loss on p and h plus L2 — [Settles & Meeder 2016](https://research.duolingo.com/papers/settles.acl16.pdf)
- Elo with time: Math Garden's uncertainty `U := U − 1/40 + (1/30)·D` (D = days since last attempt) grows the step size after a gap — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- "For some knowledge components (particularly facts), it is important to take into account forgetting"; Hypothesis 2: "The modeling of forgetting is very important for fluency and memory processes, but for understanding and sense making processes it brings only slight improvement" — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)
- ALEKS handles retention procedurally: progress assessments are triggered "once the student has practiced a certain number of items, or once she has worked in the learning mode for a certain amount of time", act as retrieval practice, and can remove items from the state — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Knewton weights recent responses more heavily than older ones ("temporal models") — [Knewton alta blog](https://www.wiley.com/en-us/grow/teach-learn/teacher-resources/courseware/knewton-alta/resources/alta-blog-how-does-knewton-proficiency-model-estimate/); Knewton's temporal IRT helped on its own data (0.8045 → 0.8166 AUC) but not on ASSISTments/KDD — [Wilson et al. 2016](https://arxiv.org/pdf/1604.02336)

### Inferences
- The cleanest composition for a per-answer web app: store P(L) and `last_evidence_at`; at read time decay the belief toward P(L0) with `P(L)_now = P(L0) + (P(L) − P(L0))·2^{−Δ/h_c}` where h_c is a per-concept half-life that grows with the number of successful retrievals (HLR's form), then run the BKT update. This is equivalent to BKT+F with a time-varying F and keeps writes O(1).
- Since the other researcher covers spaced repetition, the interface to specify is: the learner model exposes (P(L), last_evidence_at, n_successes); the scheduler owns h.

### Gaps
- No source gives a fitted P(F) value for conceptual (non-fact) knowledge; Khajah reports only the AUC effect.

---

## Q6. How do you weight noisier evidence (an LLM's judgement of a chat turn) against strong evidence (a graded free response)?

### Takeaway
The model-native way is to give each evidence channel its own emission parameters: per-channel guess/slip in BKT (the KT-IDEM / contextual-guess-slip machinery, +0.02 AUC and a 27% relative A′ gain in the original studies), a per-channel K (or shifted-logistic floor) in Elo, and a per-channel c in 3PL. The one direct measurement of LLM-judged chat correctness (GPT-4o on Khanmigo dialogues) shows ~76–83% final-turn accuracy vs 86% for teachers, i.e. it is a usable but visibly noisier channel.

### Cited Findings
- Contextual guess/slip: instead of fixed G and S, predict per-observation P(guess) and P(slip) from context features and plug them into the same Bayes step; A′ rose from 0.66 (baseline BKT) to 0.75; degeneracy dropped to 1.7% of skills — [Baker, Corbett & Aleven 2008](https://learninganalytics.upenn.edu/ryanbaker/BCA2008W.pdf)
- KT-IDEM gives each item (or item class) its own guess and slip; pyBKT's `multigs=True` fits them and reproduces +0.019 AUC on ASSISTments 2009 — [Badrinath, Wang & Pardos 2021](https://arxiv.org/abs/2105.00385); [pyBKT README](https://github.com/CAHLR/pyBKT)
- Multiple-choice evidence in Elo: floor the success probability at 1/k — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf); in IRT the same role is played by c (typically 0.15–0.25 for 4–5 option MC) — [Iowa Reading Research Center](https://irrc.education.uiowa.edu/blog/2020/09/technically-speaking-determining-test-effectiveness-item-response-theory)
- ALEKS's asymmetry is a worked example of channel weighting: open-response items → lucky guess "very small" → strong upward update on correct; careless error non-negligible → weaker downward update on incorrect; "I don't know" → strong downward update — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Partial credit / wrong-answer quality carries signal: "where in a series of opportunities a student reaches the goal impacts future performance, as does … the 'level' of previous wrongness, even two questions before the current opportunity"; Wang & Heffernan 2013 extended KT with continuous instead of binary observation nodes — [Van Inwegen, Adjei, Wang & Heffernan 2015, EDM](https://files.eric.ed.gov/fulltext/ED560588.pdf)
- LLM-judged chat turns (LAK 2025, Scarlatos, Baker & Lan): GPT-4o zero-shot CoT labels each student turn correct/incorrect/na and tags Common Core KCs; on 166 Khanmigo (CoMTA) turn pairs, three former math teachers scored the correctness labels 0.93/1 with 84% three-way overlap but Krippendorff α = 0.18 (over 90% of labels are "correct", so α is uninformative); GPT-4o's final-turn correctness accuracy 75.8% overall (83.3% on the evaluated subset) vs 85.6% for the human annotators; KC labels scored 3.28/4 — [Scarlatos, Baker & Lan 2025](https://arxiv.org/abs/2409.16490)
- On those LLM-labelled turns, KT models predict next-turn correctness far worse than on item data: LLMKT (fine-tuned Llama) AUC 65.8 (CoMTA) / 76.7 (MathDial); DKT-Sem 61.8 / 66.2; BKT 52.5 / 64.2; DKT 53.2 / 63.2; AKT 51.4 / 63.3 — versus ">80% AUC" typical on item-response KT; dialogue turns are noisy, many are "na", and 58–83% of turns involve more than one KC — [Scarlatos, Baker & Lan 2025](https://arxiv.org/abs/2409.16490)
- Pelánek's hypothesis 3: for mastery decisions "it is more important what data are used for modeling than the exact details of models" — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)

### Inferences
- Implement evidence type as the KT-IDEM key: one (G, S) pair per channel, e.g. free-response graded by rubric (G ≈ 0.05–0.10, S ≈ 0.10), 4-option MC (G = 0.25–0.30, S ≈ 0.10), teach-back / explanation graded by LLM (G higher, S higher — the LAK25 numbers imply roughly 15–25% label error, so G ≈ 0.25, S ≈ 0.20 is a defensible prior), chat-turn LLM judgement (G ≈ 0.3, S ≈ 0.3, i.e. a weak observation). A channel with G + S → 1 contributes nothing, which is the correct limit for an unreliable judge; the van de Sande constraint G + S < 1 must hold per channel.
- The same numbers convert to Elo as a per-channel K multiplier (K_chat < K_mc < K_free), or to a 3PL c per channel; but only BKT/IRT give the likelihood-ratio semantics that make "how much should one chat turn move P(L)" a derived quantity rather than a tuned constant.
- If the LLM returns a confidence or partial-credit score, the Wang & Heffernan continuous-observation form (or simply mixing the two emission rows by the score) is the straightforward extension; do not threshold at 0.5 and then treat it as a full binary observation.
- Multi-KC turns need a credit-assignment rule (LAK25 used average mastery across the turn's KCs; ALEKS avoids the problem by keying items to one state element). A minimal rule: update only KCs the judge names as exercised, with the observation weight split evenly.

### Gaps
- No study calibrates BKT guess/slip specifically for LLM-graded evidence; the channel parameters above are inferred from LAK25's accuracy numbers, not fitted.
- Wang & Heffernan 2013 ("continuous versus binary nodes") was not fetched; its AUC gain is unknown here.

---

## Q7. What open-source implementations exist and what do they look like?

### Takeaway
pyBKT (Berkeley CAHLR) is the maintained BKT library: scikit-learn-style `Model().fit/predict/evaluate/crossvalidate`, EM fitting, flags for per-item guess/slip (`multigs`), per-resource learn rates (`multilearn`), per-student priors (`multiprior`), forgetting (`forgets`), a C++ backend (150–600× faster fitting than pure Python), and a `Roster` for per-answer online updates without refitting. Deep KT lives in pyKT; Elo/HLR are a few lines and Duolingo's HLR code is public.

### Cited Findings
- pyBKT: `pip install pyBKT`, Python ≥ 3.5; API `fit()`, `predict()` (DataFrame), `evaluate()` (RMSE default, AUC, accuracy, or a custom 2-arg function), `crossvalidate()`, `params()`; flags `multigs=True`, `multilearn=<column or bool>`, `forgets=True`, `multiprior`; parameters named `prior`, `learns`, `guesses`, `slips`, `forgets`; parameters can be fixed via `model.coef_` with `fixed=True`; "The separate Roster feature enables incremental state tracking for individual students, updating mastery probabilities per answer without refitting the full model" — [pyBKT README](https://github.com/CAHLR/pyBKT)
- Supported variants: KT-IDEM, KT-PPS (prior per student), BKT+Forget, Item Order Effect, Item Learning Effect; C++/Python hybrid gives "nearly 150-600x speedup for fitting and 15-30x speedup for prediction" over pure Python; KT-IDEM reproduces +0.019 AUC on ASSISTments 2009 — [Badrinath, Wang & Pardos 2021](https://arxiv.org/abs/2105.00385)
- Worked examples (KT-IDEM, etc.) — [CAHLR/pyBKT-examples](https://github.com/CAHLR/pyBKT-examples)
- StanBKT: Stan models for standard, grouped and hierarchical BKT with HMC / VI / Pathfinder inference and posterior intervals on parameters — [Pradhan et al. 2026](https://arxiv.org/abs/2605.23048)
- BKT with forgetting used by Khajah et al.: [robert-lindsey/WCRP (forgetting branch)](https://github.com/robert-lindsey/WCRP/tree/forgetting); their DKT implementation: [mmkhajah/dkt](https://github.com/mmkhajah/dkt) — [Khajah et al. 2016](https://arxiv.org/abs/1604.02416)
- pyKT: standardised deep-KT benchmark library (DKT, DKVMN, SAKT, AKT, SAINT, simpleKT …) with the label-leakage-safe evaluation protocol — [Liu et al. 2022](https://arxiv.org/abs/2206.11460)
- Knewton's IRT/HIRT/TIRT replication code — [Knewton/edm2016](https://github.com/Knewton/edm2016)
- Duolingo half-life regression reference implementation — [duolingo/halflife-regression](https://github.com/duolingo/halflife-regression)
- Elo needs no library: two update lines per answer, one float per student and per item — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)

### Inferences
- For a FastAPI + Postgres service the useful pattern is: keep the per-(student, concept, channel) state in a table and implement the 3-line BKT update in Python (or a SQL function) rather than depending on pyBKT at request time; use pyBKT offline (nightly) to refit `prior/learns/guesses/slips/forgets` per concept once the 50-student / 15-opportunity bar is met, writing the fitted parameters back to a concept-parameters table.
- pyBKT's `Roster` is the reference for the online semantics but it is an in-memory object; it does not persist to a DB.

### Gaps
- pyBKT's exact EM initialisation and whether it supports Dirichlet priors on parameters (the Beck/Chang remedy) was not confirmed from the README.

---

## Q8. What is cheap enough to run on every answer in a FastAPI + Postgres app, and what would a defensible v1 look like?

### Takeaway
A BKT-style two-state belief per (student, concept) with per-channel emission parameters, a time-decay at read, and a one-hop damped prerequisite propagation is O(1 + #parents) per answer, needs no training data to start, and matches what MATHia/ALEKS/Knewton do in spirit; DKT/DBN-class models are neither cheap nor fittable at tens of students.

### Cited Findings
- Per-answer cost: BKT update = eqs. (8)–(10) above, closed form — [van de Sande 2013](https://files.eric.ed.gov/fulltext/EJ1115329.pdf); Elo update = one logistic + one addition per parameter — [Pelánek 2016](https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf)
- DBN cost grows as 2^(n−1) CPT parameters per node with n−1 parents and needs loopy approximate inference for learning — [Käser et al. 2017](https://cgl.ethz.ch/Downloads/Publications/Papers/2017/Kae17a/Kae17a.pdf)
- BKT+ (Khajah's extended model) is "orders of magnitude slower to train" than LR/DKT — [Gervet et al. 2020](https://theophilegervet.github.io/assets/pdf/gervet2020deep.pdf)
- ALEKS caps assessment at 30 questions and relies on partitioned substructures because enumerating 10^23 states is infeasible — [Matayoshi & Cosyn 2021](https://jmatayoshi.github.io/publications/JMP2021_KST_ALEKS_preprint.pdf)
- Mastery decisions are insensitive to model details but sensitive to input data — [Pelánek 2017](https://www.fi.muni.cz/~xpelanek/publications/umuai-overview.pdf)

### Inferences
- Schema: `concept_params(concept_id, channel, L0, T, G, S, F)` seeded with literature priors (L0 0.3–0.4; T 0.1–0.2; G/S per channel as in Q6; F small), `learner_state(user_id, concept_id, p_known, n_obs, last_evidence_at, n_success)`, and `evidence(user_id, concept_id, channel, correct, weight, ts)` as the append-only log so the model can be replayed when parameters are refit (the same reason `node_mastery_events` is append-only).
- Per answer: (1) decay `p_known` by elapsed time; (2) Bayes step with the channel's G/S; (3) learning step with T; (4) propagate: for each parent, apply the same Bayes step with a heavily-attenuated observation on correct only; for each child, apply on incorrect only; (5) label mastered if `p_known ≥ 0.95` (proficient) / `≥ 0.98` (mastered) AND `n_obs ≥ k` on strong channels — the `n_obs` guard is what ALEKS's target-score-5 and Khan's unit-test rule supply.
- Keep a parallel Elo θ per (student, concept) only if item difficulty is needed for question selection; BKT alone does not model item difficulty unless `multigs` per item is used, which the data regime cannot support.
- Refit path: nightly pyBKT `fit(multigs=True, forgets=True)` on pooled evidence across courses per abstract concept; accept fitted parameters only if they satisfy G + S < 1, G ≤ 0.3, S ≤ 0.1–0.3, and T < 1 − S/(1−G); otherwise keep priors.

### Gaps
- No published system documents exactly this combination (per-channel BKT + decay + one-hop DAG propagation); it is a synthesis of the sources above, not a cited design.
