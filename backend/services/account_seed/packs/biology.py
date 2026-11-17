"""Biology major seed pack: a sophomore pre-med-track biology student.

Strengths vary by course on purpose: comfortable with evolution/ecology
(BI 107), solid on the central dogma but shaky on linkage mapping (BI 108),
genuinely struggling with the physical-chemistry side of CH 101, and early in
the signalling half of Cell Biology (BI 203).
"""
from __future__ import annotations

from services.account_seed.schema import (
    Assignment,
    Category,
    ChatMessage,
    Concept,
    ConceptNote,
    Course,
    Document,
    Edge,
    Flashcard,
    MajorPack,
    MasteryEvent,
    Note,
    QuizAttempt,
    QuizQuestion,
    StudyGuide,
    StudyGuideTopic,
    TutorSession,
)

# ---------------------------------------------------------------------------
# CAS BI 107 — Biology 1 (evolution, ecology, organismal)
# ---------------------------------------------------------------------------

BI107 = Course(
    code="CAS BI 107",
    name="Biology 1",
    department="Biology",
    nickname="Bio 1 (Evo/Eco)",
    color="#2E8B57",
    concepts=[
        Concept(name="Natural Selection", mastery=0.87,
                description="Differential survival and reproduction of heritable variants; the Grants' "
                            "Geospiza fortis beak-depth shift after the 1977 Daphne Major drought."),
        Concept(name="Phylogenetics", mastery=0.79,
                description="Reading and building evolutionary trees: clades, synapomorphies, "
                            "monophyletic vs paraphyletic groups, and maximum parsimony."),
        Concept(name="Population Ecology", mastery=0.82,
                description="Exponential vs logistic growth (dN/dt = rN(1 - N/K)), carrying capacity, "
                            "and r- vs K-selected life histories."),
        Concept(name="Genetic Drift", mastery=0.66,
                description="Random change in allele frequencies, strongest in small populations; "
                            "bottlenecks (northern elephant seals) and founder effects."),
        Concept(name="Speciation", mastery=0.57,
                description="Allopatric vs sympatric speciation and the prezygotic/postzygotic barriers "
                            "that keep species reproductively isolated."),
        Concept(name="Community Interactions", mastery=0.48,
                description="Competition, predation, mutualism; Gause's competitive exclusion, Connell's "
                            "barnacles, and Paine's Pisaster keystone experiment."),
        Concept(name="Hardy-Weinberg Equilibrium", mastery=0.34,
                description="The null model p^2 + 2pq + q^2 = 1 for a non-evolving population and the "
                            "five assumptions it requires."),
        Concept(name="Ecosystem Energy Flow", mastery=0.21,
                description="Gross vs net primary production, trophic levels, and the roughly 10% "
                            "transfer efficiency between them."),
        Concept(name="Plant Form and Function", mastery=0.05,
                description="Xylem and phloem transport, transpiration and the cohesion-tension "
                            "mechanism, stomatal regulation."),
    ],
    edges=[
        Edge(source="Hardy-Weinberg Equilibrium", target="Genetic Drift", relationship="prerequisite", strength=0.8),
        Edge(source="Hardy-Weinberg Equilibrium", target="Natural Selection", relationship="related", strength=0.6),
        Edge(source="Natural Selection", target="Speciation", relationship="prerequisite", strength=0.85),
        Edge(source="Genetic Drift", target="Speciation", relationship="builds_on", strength=0.6),
        Edge(source="Speciation", target="Phylogenetics", relationship="related", strength=0.7),
        Edge(source="Population Ecology", target="Community Interactions", relationship="prerequisite", strength=0.8),
        Edge(source="Community Interactions", target="Ecosystem Energy Flow", relationship="builds_on", strength=0.65),
        Edge(source="Plant Form and Function", target="Ecosystem Energy Flow", relationship="related", strength=0.4),
    ],
    mastery_events=[
        MasteryEvent(concept="Natural Selection", delta=0.15, reason="Scored 4/4 on the natural selection quiz"),
        MasteryEvent(concept="Hardy-Weinberg Equilibrium", delta=-0.08, reason="Missed carrier-frequency questions on quiz"),
        MasteryEvent(concept="Hardy-Weinberg Equilibrium", delta=0.06, reason="Tutor session on 2pq carrier frequency"),
        MasteryEvent(concept="Population Ecology", delta=0.12, reason="Duckweed logistic growth lab write-up"),
        MasteryEvent(concept="Phylogenetics", delta=0.1, reason="Problem Set 2 on tree reading"),
    ],
    categories=[
        Category(name="Exams", weight=0.55),
        Category(name="Lab Reports", weight=0.25),
        Category(name="Problem Sets", weight=0.20, drop_lowest=1),
    ],
    assignments=[
        Assignment(title="Problem Set 1: Hardy-Weinberg Calculations", category="Problem Sets",
                   type="homework", due_offset_days=14, points_possible=20, points_earned=15.5),
        Assignment(title="Lab Report 1: Bean Beetle Host Preference", category="Lab Reports",
                   type="project", due_offset_days=24, points_possible=50, points_earned=44),
        Assignment(title="Problem Set 2: Reading Phylogenetic Trees", category="Problem Sets",
                   type="homework", due_offset_days=33, points_possible=20, points_earned=19),
        Assignment(title="Midterm Exam 1", category="Exams", type="exam",
                   due_offset_days=47, points_possible=100, points_earned=84, is_midterm=True),
        Assignment(title="Lab Report 2: Logistic Growth in Duckweed", category="Lab Reports",
                   type="project", due_offset_days=61, points_possible=50, points_earned=43),
        Assignment(title="Problem Set 3: Trophic Efficiency", category="Problem Sets",
                   type="homework", due_offset_days=75, points_possible=20),
        Assignment(title="Lab Report 3: Transpiration Rates", category="Lab Reports",
                   type="project", due_offset_days=89, points_possible=50),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=112, points_possible=150),
    ],
    notes=[
        Note(
            title="Hardy-Weinberg: the null model",
            tags=["evolution", "population genetics", "exam 1"],
            concepts=["Hardy-Weinberg Equilibrium", "Genetic Drift", "Natural Selection"],
            body=(
                "## Hardy-Weinberg = what happens when *nothing* happens\n\n"
                "- Allele freqs: **p + q = 1**\n"
                "- Genotype freqs: **p^2 + 2pq + q^2 = 1** (AA, Aa, aa)\n\n"
                "### The 5 assumptions (if any break, the population is evolving)\n"
                "1. No mutation\n"
                "2. Random mating\n"
                "3. No natural selection\n"
                "4. Very large population (no drift)\n"
                "5. No gene flow\n\n"
                "### How to actually solve problems\n"
                "Always start from the **homozygous recessive** class, because it's the only phenotype "
                "where you know the genotype. If 1 in 2,500 newborns has cystic fibrosis, q^2 = 0.0004, "
                "so q = 0.02 and p = 0.98. Carriers = 2pq = 2(0.98)(0.02) = 0.039, about 1 in 25.\n\n"
                "**My mistake on PS1:** I took the square root of the *dominant* phenotype frequency. "
                "That frequency is p^2 + 2pq, not p^2, so the root is meaningless.\n\n"
                "Prof said: HW is a **null hypothesis**. A chi-square test against HW expectations tells "
                "you *that* something is evolving, not *which* mechanism."
            ),
        ),
        Note(
            title="Community ecology: Connell & Paine",
            tags=["ecology", "experiments"],
            concepts=["Community Interactions", "Population Ecology"],
            body=(
                "## Two field experiments to know cold\n\n"
                "**Connell (1961), Scottish rocky intertidal**\n"
                "- *Chthamalus* lives high on the rocks, *Semibalanus* lower down.\n"
                "- Removing *Semibalanus* let *Chthamalus* settle and survive lower.\n"
                "- So Chthamalus's **fundamental niche > realized niche**; competition sets the lower "
                "limit, desiccation sets the upper limit of Semibalanus.\n\n"
                "**Paine (1966), Makah Bay, Washington**\n"
                "- Removed the sea star *Pisaster ochraceus* from plots.\n"
                "- Mussels (*Mytilus*) took over; species richness dropped from 15 to 8.\n"
                "- Pisaster = **keystone species**: its effect is far larger than its biomass.\n\n"
                "### Link to logistic growth\n"
                "Competition effectively lowers K for each species. Lotka-Volterra competition just "
                "adds an alpha term to the logistic equation.\n\n"
                "TODO: re-read the textbook section on character displacement before the final."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="bi107-syllabus.pdf",
            category="syllabus",
            summary=(
                "Course syllabus for BI 107 Biology 1: evolution, ecology and organismal biology, "
                "with grading weights, the lab schedule and exam dates."
            ),
            concept_notes=[
                ConceptNote(name="Natural Selection", description="Weeks 1-3 open the course with Darwin and the evidence for selection."),
                ConceptNote(name="Hardy-Weinberg Equilibrium", description="Population genetics unit, tested on Midterm 1."),
                ConceptNote(name="Population Ecology", description="Ecology half begins week 8 with population growth models."),
                ConceptNote(name="Plant Form and Function", description="Organismal unit in the final three weeks."),
            ],
            extracted_text=(
                "BI 107 BIOLOGY 1 - Fall Semester\n"
                "Lectures: Tues/Thurs 9:30-10:45, Metcalf Science Center\n\n"
                "COURSE DESCRIPTION\n"
                "An introduction to the principles of evolution, ecology and organismal biology. "
                "We begin with the mechanisms of evolution (natural selection, genetic drift, gene "
                "flow, mutation) and the population genetics used to detect them, then turn to "
                "speciation and phylogenetic reconstruction. The second half of the course covers "
                "population, community and ecosystem ecology, and closes with plant form and function.\n\n"
                "GRADING\n"
                "Exams (Midterm 1 and cumulative Final) ........ 55%\n"
                "Laboratory reports (3) ......................... 25%\n"
                "Problem sets (lowest score dropped) ............ 20%\n\n"
                "LABORATORY\n"
                "Lab attendance is mandatory. Lab 1: host preference in the bean beetle Callosobruchus "
                "maculatus. Lab 2: logistic growth of duckweed (Lemna minor) populations. Lab 3: "
                "measuring transpiration with a potometer. Reports are due one week after the final "
                "session of each lab and must follow the scientific-paper format posted on Blackboard.\n\n"
                "POLICIES\n"
                "Late work loses 10% per day. Make-up exams require documentation from the Dean of "
                "Students. Office hours: Wednesdays 2-4 pm, BRB room 213."
            ),
        ),
        Document(
            file_name="bi107-lecture09-speciation.pdf",
            category="lecture_notes",
            summary=(
                "Lecture 9 slides on speciation: the biological species concept, reproductive barriers, "
                "and allopatric vs sympatric speciation with case studies."
            ),
            concept_notes=[
                ConceptNote(name="Speciation", description="Biological species concept and its limits for asexual and fossil taxa."),
                ConceptNote(name="Genetic Drift", description="Drift in small isolated populations accelerates divergence."),
                ConceptNote(name="Natural Selection", description="Divergent selection drives both allopatric and sympatric splits."),
                ConceptNote(name="Phylogenetics", description="Sister species identified on trees as the two tips of one node."),
            ],
            extracted_text=(
                "LECTURE 9 - HOW NEW SPECIES FORM\n\n"
                "Biological species concept (Mayr): a species is a group of populations whose members "
                "can interbreed in nature and produce viable, fertile offspring. Limitations: does not "
                "apply to asexual organisms or fossils; hybridization blurs boundaries (e.g. grizzly x "
                "polar bear hybrids).\n\n"
                "Reproductive barriers\n"
                "PREZYGOTIC: habitat isolation, temporal isolation (Rana aurora vs R. boylii breeding "
                "seasons), behavioral isolation (blue-footed booby courtship), mechanical isolation, "
                "gametic isolation (sea urchin bindin proteins).\n"
                "POSTZYGOTIC: reduced hybrid viability, reduced hybrid fertility (mule: 63 chromosomes, "
                "meiosis fails), hybrid breakdown.\n\n"
                "Allopatric speciation: a geographic barrier splits a population; drift and divergent "
                "selection act independently. Example: snapping shrimp (Alpheus) on either side of the "
                "Isthmus of Panama, ~3 million years.\n\n"
                "Sympatric speciation: divergence without geographic separation. Example: the apple "
                "maggot fly Rhagoletis pomonella, host shift from hawthorn to apple in the 1800s; "
                "mating occurs on the host fruit, so host choice is also mate choice. Polyploidy in "
                "plants can produce a new species in a single generation.\n\n"
                "Clicker Q: Which barrier is postzygotic? (answer: hybrid sterility)"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Five assumptions of Hardy-Weinberg equilibrium",
                  back="No mutation, random mating, no selection, very large population (no drift), no gene flow."),
        Flashcard(front="Bottleneck effect vs founder effect",
                  back="Bottleneck: a population shrinks drastically (elephant seals). Founder: a few individuals "
                       "colonize a new area (Amish polydactyly). Both are forms of genetic drift."),
        Flashcard(front="Logistic growth equation",
                  back="dN/dt = rN(1 - N/K); growth is fastest at N = K/2 and stops at carrying capacity K."),
        Flashcard(front="What is a synapomorphy?",
                  back="A shared derived character that defines a clade, e.g. feathers for birds."),
        Flashcard(front="Keystone species (Paine 1966)",
                  back="Pisaster ochraceus: removing it let mussels monopolize the rocks and species richness fell."),
        Flashcard(front="Fundamental vs realized niche",
                  back="Fundamental = where a species could live; realized = where it actually lives given "
                       "competitors (Connell's Chthamalus)."),
        Flashcard(front="Approximate energy transfer efficiency between trophic levels",
                  back="About 10%; the rest is lost mostly as heat from respiration and as undigested material."),
        Flashcard(front="Example of sympatric speciation",
                  back="Rhagoletis pomonella host races on hawthorn vs apple; also plant polyploidy."),
    ],
    study_guide=StudyGuide(
        overview=(
            "Midterm 1 covers the evolution half of the course: the mechanisms of evolution, Hardy-"
            "Weinberg calculations, speciation and phylogenetics. Expect roughly a third of points from "
            "calculation problems, so practice HW problems until starting from q^2 is automatic."
        ),
        topics=[
            StudyGuideTopic(
                name="Mechanisms of evolution",
                importance="Every short-answer question asks you to name which mechanism explains an observed change.",
                concepts=["Natural selection modes: directional, stabilizing, disruptive",
                          "Genetic drift: bottleneck and founder effects",
                          "Gene flow homogenizes populations",
                          "The Grants' Galapagos finch data"],
            ),
            StudyGuideTopic(
                name="Hardy-Weinberg calculations",
                importance="The professor said at least two exam problems will require HW math.",
                concepts=["Start from the homozygous recessive frequency (q^2)",
                          "Carrier frequency = 2pq",
                          "Chi-square test against HW expectations",
                          "Which violated assumption explains a deviation"],
            ),
            StudyGuideTopic(
                name="Speciation and phylogenies",
                importance="Tree-reading questions are quick points if you can identify clades correctly.",
                concepts=["Prezygotic vs postzygotic barriers",
                          "Allopatric vs sympatric speciation examples",
                          "Monophyletic, paraphyletic and polyphyletic groups",
                          "Rotating nodes does not change relationships"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Natural Selection", difficulty="medium", days_ago=41, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(
                    question="After the 1977 drought on Daphne Major, mean beak depth in Geospiza fortis increased. This is an example of:",
                    options=["Directional selection", "Stabilizing selection", "Disruptive selection", "Genetic drift"],
                    correct_answer="Directional selection",
                    explanation="Large, hard seeds dominated, so birds with deeper beaks survived; the mean shifted in one direction."),
                QuizQuestion(
                    question="Which of the following is required for natural selection to cause evolution?",
                    options=["Heritable variation in a trait affecting fitness", "A very large population",
                             "Random mating", "A new mutation every generation"],
                    correct_answer="Heritable variation in a trait affecting fitness",
                    explanation="Selection acts on phenotypes, but only heritable variation passes to the next generation."),
                QuizQuestion(
                    question="Human birth weight, where very small and very large babies have higher mortality, illustrates:",
                    options=["Stabilizing selection", "Directional selection", "Sexual selection", "Founder effect"],
                    correct_answer="Stabilizing selection",
                    explanation="Selection against both extremes keeps the mean and narrows the variance."),
                QuizQuestion(
                    question="Fitness in evolutionary biology is best measured by:",
                    options=["Relative reproductive success", "Physical strength", "Lifespan", "Body size"],
                    correct_answer="Relative reproductive success",
                    explanation="Fitness is the contribution of offspring to the next generation relative to others."),
            ],
        ),
        QuizAttempt(
            concept="Hardy-Weinberg Equilibrium", difficulty="hard", days_ago=22, correct=[0, 3],
            questions=[
                QuizQuestion(
                    question="In a population in HW equilibrium, 16% of individuals show the recessive phenotype. What is q?",
                    options=["0.4", "0.16", "0.84", "0.6"],
                    correct_answer="0.4",
                    explanation="q^2 = 0.16, so q = 0.4."),
                QuizQuestion(
                    question="Using the same population (16% recessive), what fraction are heterozygous carriers?",
                    options=["0.48", "0.24", "0.36", "0.60"],
                    correct_answer="0.48",
                    explanation="p = 0.6, q = 0.4, so 2pq = 2(0.6)(0.4) = 0.48."),
                QuizQuestion(
                    question="Cystic fibrosis affects about 1 in 2,500 births. Approximately how common are carriers?",
                    options=["1 in 25", "1 in 50", "1 in 100", "1 in 1,250"],
                    correct_answer="1 in 25",
                    explanation="q = 0.02, p = 0.98, 2pq is about 0.039, roughly 1 in 25."),
                QuizQuestion(
                    question="A small island population deviates from HW expectations with no selection detected. The most likely cause is:",
                    options=["Genetic drift", "Random mating", "A large effective population size", "No gene flow"],
                    correct_answer="Genetic drift",
                    explanation="Small populations violate the 'very large population' assumption, so drift changes allele frequencies."),
            ],
        ),
        QuizAttempt(
            concept="Population Ecology", difficulty="easy", days_ago=6, correct=[0, 1, 2],
            questions=[
                QuizQuestion(
                    question="In the logistic model, population growth rate (dN/dt) is highest when N equals:",
                    options=["K/2", "K", "0", "2K"],
                    correct_answer="K/2",
                    explanation="rN(1 - N/K) is maximized at N = K/2."),
                QuizQuestion(
                    question="Which trait is typical of an r-selected species?",
                    options=["Many small offspring with little parental care", "Long lifespan",
                             "Late reproduction", "Few large offspring"],
                    correct_answer="Many small offspring with little parental care",
                    explanation="r-selected species maximize reproductive rate in unstable environments."),
                QuizQuestion(
                    question="What does K represent in the logistic growth equation?",
                    options=["Carrying capacity", "Per capita growth rate", "Initial population size", "Mortality rate"],
                    correct_answer="Carrying capacity",
                    explanation="K is the maximum population size the environment can sustain."),
            ],
        ),
    ],
    session=TutorSession(
        name="HW carrier frequency practice",
        topic="Hardy-Weinberg Equilibrium",
        mode="socratic",
        summary_bullets=[
            "Always start Hardy-Weinberg problems from the homozygous recessive frequency, q^2.",
            "Carrier frequency is 2pq, which is much larger than q^2 for rare alleles.",
            "Taking the square root of the dominant phenotype frequency is a common mistake.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I keep getting HW problems wrong. If 1 in 10,000 people has PKU, how many are carriers? "
                "I did sqrt(9999/10000) and got p = 0.99995 and that seems off.")),
            ChatMessage(role="assistant", content=(
                "Good instinct that it seems off. The 9,999 unaffected people include two genotypes. Which "
                "genotypes are they, and what HW terms describe them?")),
            ChatMessage(role="user", content=(
                "Oh, AA and Aa. So that's p^2 + 2pq, not just p^2. So I can't square-root it.")),
            ChatMessage(role="assistant", content=(
                "Exactly. The only phenotype class with a single genotype is the affected one, aa. So "
                "q^2 = 1/10,000 = 0.0001. What are q and p, and what is 2pq?")),
            ChatMessage(role="user", content="q = 0.01, p = 0.99, so 2pq = 2 x 0.99 x 0.01 = 0.0198. About 1 in 50?"),
            ChatMessage(role="assistant", content=(
                "Right: about 2%, or 1 in 50, are carriers, while only 1 in 10,000 is affected. That gap is "
                "why rare recessive alleles hide mostly in heterozygotes, and why selection against the "
                "affected phenotype removes them so slowly. Try the cystic fibrosis version (1 in 2,500) on "
                "your own next and check whether you get roughly 1 in 25.")),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS BI 108 — Biology 2 (cell/molecular, genetics)
# ---------------------------------------------------------------------------

BI108 = Course(
    code="CAS BI 108",
    name="Biology 2",
    department="Biology",
    nickname="Bio 2 (Mol/Gen)",
    color="#4A7FC1",
    concepts=[
        Concept(name="Mendelian Inheritance", mastery=0.88,
                description="Segregation and independent assortment; monohybrid 3:1, dihybrid 9:3:3:1 "
                            "ratios and the testcross."),
        Concept(name="Transcription", mastery=0.83,
                description="RNA polymerase, promoters and the TATA box, 5' cap, poly-A tail and "
                            "splicing of introns in eukaryotes."),
        Concept(name="DNA Replication", mastery=0.79,
                description="Semiconservative replication (Meselson-Stahl), helicase, primase, DNA "
                            "polymerase III, leading strand and Okazaki fragments."),
        Concept(name="Translation", mastery=0.71,
                description="Ribosome A, P and E sites, tRNA anticodons, the AUG start codon and the "
                            "three stop codons."),
        Concept(name="Meiosis", mastery=0.62,
                description="Two divisions producing haploid gametes; synapsis, crossing over in "
                            "prophase I, and independent orientation in metaphase I."),
        Concept(name="Gene Regulation in Prokaryotes", mastery=0.49,
                description="The lac operon: repressor, operator, allolactose induction, and "
                            "CAP-cAMP positive control under low glucose."),
        Concept(name="Cellular Respiration", mastery=0.41,
                description="Glycolysis, pyruvate oxidation, the citric acid cycle and oxidative "
                            "phosphorylation yielding about 30-32 ATP per glucose."),
        Concept(name="Linkage and Recombination", mastery=0.27,
                description="Genes on the same chromosome; recombination frequency, map units "
                            "(centimorgans), and three-point testcross mapping."),
        Concept(name="Photosynthesis", mastery=0.16,
                description="Light reactions at photosystems II and I, the Calvin cycle, and "
                            "RuBisCO carbon fixation."),
        Concept(name="Eukaryotic Gene Regulation", mastery=0.03,
                description="Chromatin remodeling, histone acetylation, enhancers and transcription "
                            "factors, and alternative splicing."),
    ],
    edges=[
        Edge(source="DNA Replication", target="Transcription", relationship="related", strength=0.5),
        Edge(source="Transcription", target="Translation", relationship="prerequisite", strength=0.9),
        Edge(source="Transcription", target="Gene Regulation in Prokaryotes", relationship="prerequisite", strength=0.8),
        Edge(source="Gene Regulation in Prokaryotes", target="Eukaryotic Gene Regulation", relationship="builds_on", strength=0.7),
        Edge(source="Meiosis", target="Mendelian Inheritance", relationship="prerequisite", strength=0.85),
        Edge(source="Mendelian Inheritance", target="Linkage and Recombination", relationship="prerequisite", strength=0.85),
        Edge(source="Meiosis", target="Linkage and Recombination", relationship="prerequisite", strength=0.75),
        Edge(source="Cellular Respiration", target="Photosynthesis", relationship="related", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Mendelian Inheritance", delta=0.1, reason="Dihybrid cross practice set"),
        MasteryEvent(concept="Linkage and Recombination", delta=-0.1, reason="Missed gene-order question on quiz"),
        MasteryEvent(concept="Linkage and Recombination", delta=0.07, reason="Tutor walkthrough of a three-point cross"),
        MasteryEvent(concept="Transcription", delta=0.12, reason="Midterm short answer on mRNA processing"),
    ],
    categories=[
        Category(name="Exams", weight=0.60),
        Category(name="Lab Reports", weight=0.20),
        Category(name="Quizzes and Problem Sets", weight=0.20, drop_lowest=1),
    ],
    assignments=[
        Assignment(title="Weekly Quiz 1: Meiosis", category="Quizzes and Problem Sets", type="quiz",
                   due_offset_days=12, points_possible=10, points_earned=9),
        Assignment(title="Lab Report 1: Bacterial Transformation with pGLO", category="Lab Reports",
                   type="project", due_offset_days=26, points_possible=40, points_earned=35),
        Assignment(title="Weekly Quiz 2: DNA Replication", category="Quizzes and Problem Sets", type="quiz",
                   due_offset_days=30, points_possible=10, points_earned=8),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=50, points_possible=100, points_earned=78, is_midterm=True),
        Assignment(title="Problem Set: Three-Point Testcross Mapping", category="Quizzes and Problem Sets",
                   type="homework", due_offset_days=63, points_possible=25, points_earned=17),
        Assignment(title="Lab Report 2: Restriction Digest and Gel Electrophoresis", category="Lab Reports",
                   type="project", due_offset_days=80, points_possible=40),
        Assignment(title="Weekly Quiz 3: The lac Operon", category="Quizzes and Problem Sets", type="quiz",
                   due_offset_days=90, points_possible=10),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=113, points_possible=150),
    ],
    notes=[
        Note(
            title="Linkage mapping - how to not panic",
            tags=["genetics", "problem set"],
            concepts=["Linkage and Recombination", "Meiosis", "Mendelian Inheritance"],
            body=(
                "## Three-point testcross recipe\n\n"
                "1. **Parentals** = the two MOST frequent classes.\n"
                "2. **Double crossovers (DCO)** = the two LEAST frequent classes.\n"
                "3. Compare parentals to DCOs: the gene that is *swapped* is the **middle** gene.\n"
                "4. RF between two genes = (single COs in that interval + DCOs) / total.\n"
                "5. 1% recombination = **1 map unit (cM)**.\n\n"
                "### Why it works\n"
                "Crossing over happens between non-sister chromatids in prophase I. The farther apart two "
                "genes are, the more likely a crossover falls between them. RF maxes out at **50%**, which "
                "looks identical to independent assortment, so far-apart genes on one chromosome can look "
                "unlinked.\n\n"
                "### Coefficient of coincidence\n"
                "CoC = observed DCO / expected DCO; interference = 1 - CoC.\n\n"
                "Still confused about when to add DCOs back into each interval. Go to TA office hours "
                "Thursday."
            ),
        ),
        Note(
            title="lac operon cheat sheet",
            tags=["gene regulation", "prokaryotes"],
            concepts=["Gene Regulation in Prokaryotes", "Transcription"],
            body=(
                "## lac operon (E. coli)\n\n"
                "Genes: **lacZ** (beta-galactosidase), **lacY** (permease), **lacA** (transacetylase).\n\n"
                "| Glucose | Lactose | Repressor | CAP-cAMP | Transcription |\n"
                "|---|---|---|---|---|\n"
                "| high | absent | on operator | not bound | off |\n"
                "| high | present | released | not bound | low |\n"
                "| low | present | released | bound | **high** |\n"
                "| low | absent | on operator | bound | off |\n\n"
                "- **Negative control:** LacI repressor binds the operator. Allolactose (an isomer of "
                "lactose) binds the repressor and changes its shape so it falls off.\n"
                "- **Positive control:** low glucose -> high cAMP -> cAMP binds CAP -> CAP helps RNA "
                "polymerase bind the promoter.\n\n"
                "Mutants to remember: lacI- (constitutive), O^c (constitutive, cis-acting only), "
                "lacI^s (super-repressor, can't bind inducer)."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="bi108-syllabus.pdf",
            category="syllabus",
            summary=(
                "BI 108 Biology 2 syllabus covering cell energetics, molecular biology and genetics, "
                "with weekly quizzes, two lab reports and a cumulative final."
            ),
            concept_notes=[
                ConceptNote(name="Cellular Respiration", description="Opening unit on cell energetics, weeks 1-2."),
                ConceptNote(name="Meiosis", description="Start of the genetics unit; weekly quiz 1."),
                ConceptNote(name="DNA Replication", description="Molecular biology unit before the midterm."),
                ConceptNote(name="Gene Regulation in Prokaryotes", description="Post-midterm regulation unit, quiz 3."),
            ],
            extracted_text=(
                "BI 108 BIOLOGY 2 - Spring/Fall Offering\n"
                "Prerequisite: BI 107 or equivalent; CH 101 recommended concurrently.\n\n"
                "COURSE OVERVIEW\n"
                "Biology 2 examines life at the cellular and molecular level. Topics include cellular "
                "respiration and photosynthesis, the cell cycle and meiosis, Mendelian and chromosomal "
                "genetics, DNA replication, transcription and translation, and the regulation of gene "
                "expression in prokaryotes and eukaryotes.\n\n"
                "ASSESSMENT\n"
                "Midterm exam ......................... 25%\n"
                "Cumulative final exam ................ 35%\n"
                "Lab reports (2) ...................... 20%\n"
                "Weekly quizzes and problem sets ...... 20% (lowest dropped)\n\n"
                "LAB SCHEDULE\n"
                "Weeks 2-4: Bacterial transformation with the pGLO plasmid (GFP under the araBAD "
                "promoter; selection on LB/amp plates with and without arabinose).\n"
                "Weeks 9-11: Restriction digest of lambda DNA with EcoRI and HindIII, agarose gel "
                "electrophoresis, and fragment size estimation from a standard curve.\n\n"
                "EXPECTATIONS\n"
                "Quizzes open on Friday and close Monday at 11:59 pm. Bring a calculator and colored "
                "pencils to every discussion section; we draw a lot of chromosomes. Regrade requests "
                "must be submitted in writing within one week of an exam being returned."
            ),
        ),
        Document(
            file_name="bi108-lecture14-transcription.pdf",
            category="lecture_notes",
            summary=(
                "Lecture 14 notes on eukaryotic transcription and RNA processing: promoters, RNA "
                "polymerase II, capping, polyadenylation and splicing."
            ),
            concept_notes=[
                ConceptNote(name="Transcription", description="Initiation, elongation and termination by RNA polymerase II."),
                ConceptNote(name="Translation", description="Processed mRNA exported to the cytoplasm for translation."),
                ConceptNote(name="Eukaryotic Gene Regulation", description="Alternative splicing previewed as a regulatory step."),
            ],
            extracted_text=(
                "LECTURE 14 - TRANSCRIPTION AND RNA PROCESSING\n\n"
                "1. Transcription makes RNA from a DNA template. RNA polymerase reads the template strand "
                "3' to 5' and synthesizes RNA 5' to 3'. No primer is required.\n\n"
                "2. Eukaryotic initiation: general transcription factors (TFIID binds the TATA box about "
                "25 bp upstream of the start site) assemble the transcription initiation complex and "
                "recruit RNA polymerase II.\n\n"
                "3. Elongation proceeds at roughly 40 nucleotides per second. Termination of protein-"
                "coding genes follows the AAUAAA polyadenylation signal; the transcript is cleaved "
                "10-35 nt downstream.\n\n"
                "4. Pre-mRNA processing (all in the nucleus):\n"
                "   - 5' cap: modified guanine (7-methylguanosine) added in a 5'-to-5' linkage; protects "
                "from degradation and helps ribosome binding.\n"
                "   - Poly-A tail: 50-250 adenines added by poly-A polymerase.\n"
                "   - Splicing: the spliceosome (snRNPs) removes introns and joins exons. One gene can "
                "yield several proteins through alternative splicing (e.g. ~38,000 possible Dscam "
                "isoforms in Drosophila).\n\n"
                "Exam tip: know which processing steps are absent in bacteria (all three) and why "
                "bacterial transcription and translation can be coupled."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="What did the Meselson-Stahl experiment show?",
                  back="DNA replication is semiconservative: after one round in 14N, all DNA was hybrid 15N/14N density."),
        Flashcard(front="Leading vs lagging strand",
                  back="Leading is synthesized continuously toward the fork; lagging is made in Okazaki fragments "
                       "away from it and joined by DNA ligase."),
        Flashcard(front="Three stop codons",
                  back="UAA, UAG, UGA."),
        Flashcard(front="What binds the lac repressor to induce the operon?",
                  back="Allolactose, an isomer of lactose, which changes the repressor's shape so it leaves the operator."),
        Flashcard(front="How many map units does 12% recombination correspond to?",
                  back="12 map units (12 cM)."),
        Flashcard(front="Dihybrid cross phenotypic ratio",
                  back="9:3:3:1 for two unlinked genes, each with complete dominance."),
        Flashcard(front="Net ATP from glycolysis",
                  back="2 ATP (4 made, 2 invested) plus 2 NADH per glucose."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The midterm covers energetics through translation: respiration and photosynthesis, meiosis, "
            "Mendelian genetics and the central dogma. Linkage mapping is the heaviest calculation "
            "section, so drill three-point crosses before anything else."
        ),
        topics=[
            StudyGuideTopic(
                name="Chromosomal genetics",
                importance="Pedigree and mapping problems carry the most points on the exam.",
                concepts=["Meiosis I vs meiosis II", "Independent assortment vs linkage",
                          "Recombination frequency and map units", "Finding the middle gene from DCO classes"],
            ),
            StudyGuideTopic(
                name="The central dogma",
                importance="Expect a long-answer question tracing a gene from DNA to protein.",
                concepts=["Semiconservative replication and fork enzymes", "Eukaryotic RNA processing",
                          "Codon reading and the genetic code", "Ribosome A, P and E sites"],
            ),
            StudyGuideTopic(
                name="Cell energetics",
                importance="Multiple-choice questions frequently compare respiration and photosynthesis.",
                concepts=["Where each stage of respiration happens", "Chemiosmosis and ATP synthase",
                          "Light reactions vs Calvin cycle"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Transcription", difficulty="medium", days_ago=33, correct=[0, 1, 3],
            questions=[
                QuizQuestion(
                    question="Which enzyme transcribes protein-coding genes in eukaryotes?",
                    options=["RNA polymerase II", "RNA polymerase I", "DNA polymerase III", "Primase"],
                    correct_answer="RNA polymerase II",
                    explanation="Pol II transcribes mRNA; Pol I makes most rRNA and Pol III makes tRNA."),
                QuizQuestion(
                    question="Which of these modifications is NOT made to eukaryotic pre-mRNA?",
                    options=["Addition of a 3' poly-T tail", "5' cap", "Splicing out introns", "3' poly-A tail"],
                    correct_answer="Addition of a 3' poly-T tail",
                    explanation="RNA has uracil, not thymine; the tail is poly-A."),
                QuizQuestion(
                    question="In which direction is RNA synthesized?",
                    options=["5' to 3'", "3' to 5'", "Both directions", "It depends on the strand"],
                    correct_answer="5' to 3'",
                    explanation="All nucleic acid polymerases add nucleotides to the 3' OH, so synthesis runs 5' to 3'."),
                QuizQuestion(
                    question="Alternative splicing allows one gene to:",
                    options=["Encode multiple protein isoforms", "Skip transcription",
                             "Be replicated twice", "Avoid the 5' cap"],
                    correct_answer="Encode multiple protein isoforms",
                    explanation="Different exon combinations yield different mature mRNAs from one gene."),
            ],
        ),
        QuizAttempt(
            concept="Linkage and Recombination", difficulty="hard", days_ago=14, correct=[2],
            questions=[
                QuizQuestion(
                    question="In a three-point testcross, the two least frequent phenotypic classes are:",
                    options=["Double crossovers", "Parentals", "Single crossovers", "Non-recombinants"],
                    correct_answer="Double crossovers",
                    explanation="Two simultaneous crossovers are the least likely event."),
                QuizQuestion(
                    question="Parentals are ABC and abc; double crossovers are AbC and aBc. Which gene is in the middle?",
                    options=["B", "A", "C", "Cannot be determined"],
                    correct_answer="B",
                    explanation="Only B is swapped relative to the parentals, so B lies between A and C."),
                QuizQuestion(
                    question="Two genes show 50% recombination. This means they:",
                    options=["Assort independently as far as the cross can tell",
                             "Are tightly linked", "Are 100 map units apart exactly", "Are on the Y chromosome"],
                    correct_answer="Assort independently as far as the cross can tell",
                    explanation="50% RF is the maximum and is indistinguishable from unlinked genes."),
            ],
        ),
    ],
    session=TutorSession(
        name="Three-point cross walkthrough",
        topic="Linkage and Recombination",
        mode="socratic",
        summary_bullets=[
            "Identify parentals (most frequent) and double crossovers (least frequent) first.",
            "The allele that differs between parentals and DCOs marks the middle gene.",
            "Each interval's RF counts its single crossovers plus the double crossovers.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "For problem 4 on the mapping set I have 8 classes from a testcross with 1000 offspring. "
                "I don't know where to start.")),
            ChatMessage(role="assistant", content=(
                "Start by sorting the eight classes by count. Which two are the largest and which two are "
                "the smallest? Those pairs tell you the parental and double-crossover genotypes.")),
            ChatMessage(role="user", content=(
                "Largest are v+ cv pr (380) and v cv+ pr+ (365). Smallest are v cv pr (8) and v+ cv+ pr+ (12).")),
            ChatMessage(role="assistant", content=(
                "Good. Now line a parental up against a DCO: v+ cv pr vs v+ cv+ pr+. Change one gene at a "
                "time in the parental. Which single swap turns the parental into a DCO class?")),
            ChatMessage(role="user", content=(
                "Hmm, if I only swap v I get v cv pr, which is a DCO. So v is in the middle?")),
            ChatMessage(role="assistant", content=(
                "Yes, the order is cv - v - pr. For each distance, add the single crossovers in that interval "
                "to the 20 double crossovers, divide by 1000, and multiply by 100 to get map units. Try the "
                "cv-v interval and tell me what you get.")),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS CH 101 — General Chemistry 1
# ---------------------------------------------------------------------------

CH101 = Course(
    code="CAS CH 101",
    name="General Chemistry 1",
    department="Chemistry",
    nickname="Gen Chem",
    color="#D9734E",
    concepts=[
        Concept(name="Mole Concept and Molar Mass", mastery=0.91,
                description="Avogadro's number (6.022 x 10^23), converting between grams, moles and "
                            "particles using molar mass."),
        Concept(name="Stoichiometry", mastery=0.77,
                description="Balancing equations and using mole ratios to predict amounts of products "
                            "and reactants."),
        Concept(name="Electron Configuration", mastery=0.63,
                description="Aufbau principle, Hund's rule and the Pauli exclusion principle; writing "
                            "configurations and orbital diagrams."),
        Concept(name="Limiting Reagents", mastery=0.56,
                description="Identifying the reactant that runs out first, theoretical yield and percent yield."),
        Concept(name="Atomic Structure and Quantum Numbers", mastery=0.49,
                description="Bohr model, the hydrogen emission spectrum, and the n, l, ml and ms quantum numbers."),
        Concept(name="Periodic Trends", mastery=0.46,
                description="Atomic radius, ionization energy, electron affinity and electronegativity "
                            "across periods and down groups; effective nuclear charge."),
        Concept(name="Ideal Gas Law", mastery=0.38,
                description="PV = nRT with R = 0.08206 L atm/(mol K); Boyle's, Charles's and Dalton's laws."),
        Concept(name="Lewis Structures and VSEPR", mastery=0.31,
                description="Drawing Lewis structures, formal charge, resonance, and predicting molecular "
                            "geometry from electron domains."),
        Concept(name="Thermochemistry", mastery=0.12,
                description="Enthalpy, q = mc(delta T), coffee-cup calorimetry, Hess's law and standard "
                            "enthalpies of formation."),
        Concept(name="Intermolecular Forces", mastery=0.04,
                description="London dispersion, dipole-dipole and hydrogen bonding, and their effect on "
                            "boiling points."),
    ],
    edges=[
        Edge(source="Mole Concept and Molar Mass", target="Stoichiometry", relationship="prerequisite", strength=0.9),
        Edge(source="Stoichiometry", target="Limiting Reagents", relationship="prerequisite", strength=0.9),
        Edge(source="Atomic Structure and Quantum Numbers", target="Electron Configuration", relationship="prerequisite", strength=0.85),
        Edge(source="Electron Configuration", target="Periodic Trends", relationship="prerequisite", strength=0.8),
        Edge(source="Electron Configuration", target="Lewis Structures and VSEPR", relationship="prerequisite", strength=0.7),
        Edge(source="Lewis Structures and VSEPR", target="Intermolecular Forces", relationship="prerequisite", strength=0.8),
        Edge(source="Stoichiometry", target="Thermochemistry", relationship="builds_on", strength=0.6),
        Edge(source="Mole Concept and Molar Mass", target="Ideal Gas Law", relationship="related", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Stoichiometry", delta=0.14, reason="Perfect score on the stoichiometry quiz"),
        MasteryEvent(concept="Ideal Gas Law", delta=-0.09, reason="Forgot to convert Celsius to Kelvin on quiz"),
        MasteryEvent(concept="Thermochemistry", delta=0.05, reason="Tutor session on coffee-cup calorimetry"),
        MasteryEvent(concept="Lewis Structures and VSEPR", delta=-0.06, reason="Missed NH3 geometry on quiz"),
    ],
    categories=[
        Category(name="Exams", weight=0.60),
        Category(name="Labs", weight=0.20),
        Category(name="Online Homework", weight=0.20, drop_lowest=2),
    ],
    assignments=[
        Assignment(title="Online Homework 3: Stoichiometry", category="Online Homework", type="homework",
                   due_offset_days=17, points_possible=20, points_earned=18),
        Assignment(title="Lab 2: Empirical Formula of a Hydrate", category="Labs", type="project",
                   due_offset_days=22, points_possible=30, points_earned=26),
        Assignment(title="Online Homework 5: Gas Laws", category="Online Homework", type="homework",
                   due_offset_days=38, points_possible=20, points_earned=13),
        Assignment(title="Midterm Exam 1", category="Exams", type="exam",
                   due_offset_days=44, points_possible=100, points_earned=71, is_midterm=True),
        Assignment(title="Lab 4: Calorimetry and Heat of Neutralization", category="Labs", type="project",
                   due_offset_days=58, points_possible=30, points_earned=23),
        Assignment(title="Online Homework 8: Thermochemistry", category="Online Homework", type="homework",
                   due_offset_days=70, points_possible=20),
        Assignment(title="Lab 6: Molecular Models and VSEPR", category="Labs", type="project",
                   due_offset_days=84, points_possible=30),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=111, points_possible=150),
    ],
    notes=[
        Note(
            title="Gas laws - stop forgetting Kelvin",
            tags=["gases", "exam 1", "mistakes"],
            concepts=["Ideal Gas Law", "Mole Concept and Molar Mass"],
            body=(
                "## PV = nRT\n\n"
                "- R = **0.08206 L atm / (mol K)** (use 8.314 J/(mol K) only for energy problems)\n"
                "- T MUST be in **Kelvin**: K = C + 273.15. I lost 7 points on HW5 for this. Again.\n"
                "- At STP (0 C, 1 atm), 1 mol of ideal gas = **22.4 L**.\n\n"
                "### Special cases (just PV = nRT with things held constant)\n"
                "- Boyle: P1V1 = P2V2 (n, T constant)\n"
                "- Charles: V1/T1 = V2/T2 (n, P constant)\n"
                "- Avogadro: V proportional to n\n\n"
                "### Dalton's law\n"
                "P_total = P_A + P_B + ...; mole fraction X_A = P_A / P_total.\n"
                "Collecting gas over water: subtract the vapor pressure of water at that temperature.\n\n"
                "### Molar mass from gas density\n"
                "M = dRT / P. Showed up on the practice exam."
            ),
        ),
        Note(
            title="VSEPR shapes table",
            tags=["bonding", "geometry"],
            concepts=["Lewis Structures and VSEPR", "Electron Configuration"],
            body=(
                "## Count electron DOMAINS around the central atom\n"
                "(a double or triple bond counts as ONE domain)\n\n"
                "| Domains | Lone pairs | Shape | Angle | Example |\n"
                "|---|---|---|---|---|\n"
                "| 2 | 0 | linear | 180 | CO2 |\n"
                "| 3 | 0 | trigonal planar | 120 | BF3 |\n"
                "| 4 | 0 | tetrahedral | 109.5 | CH4 |\n"
                "| 4 | 1 | trigonal pyramidal | ~107 | NH3 |\n"
                "| 4 | 2 | bent | ~104.5 | H2O |\n"
                "| 5 | 1 | seesaw | - | SF4 |\n"
                "| 6 | 0 | octahedral | 90 | SF6 |\n\n"
                "**Electron geometry vs molecular geometry**: lone pairs count for electron geometry but "
                "you only *name* the shape by the atoms. NH3 is tetrahedral electron geometry but "
                "trigonal pyramidal molecular geometry. This is exactly what I got wrong on the quiz.\n\n"
                "Lone pairs squeeze bond angles below 109.5 because they take up more space."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ch101-syllabus.pdf",
            category="syllabus",
            summary=(
                "CH 101 General Chemistry 1 syllabus: topics from measurement through bonding, the lab "
                "schedule, online homework policy and grading breakdown."
            ),
            concept_notes=[
                ConceptNote(name="Stoichiometry", description="Chapters 3-4, the foundation for every later unit."),
                ConceptNote(name="Ideal Gas Law", description="Chapter 5, the last topic on Midterm 1."),
                ConceptNote(name="Thermochemistry", description="Chapter 6, paired with the calorimetry lab."),
                ConceptNote(name="Lewis Structures and VSEPR", description="Chapters 9-10, final weeks of the course."),
            ],
            extracted_text=(
                "CH 101 GENERAL CHEMISTRY 1\n"
                "Text: Chemistry: The Central Science, 15th ed. (Brown, LeMay et al.)\n\n"
                "TOPICS BY WEEK\n"
                "Wk 1-2 Measurement, significant figures, dimensional analysis\n"
                "Wk 3-4 Atoms, molecules, ions; the mole; stoichiometry (Ch. 2-3)\n"
                "Wk 5 Aqueous reactions and solution stoichiometry (Ch. 4)\n"
                "Wk 6 Gases (Ch. 5) -- MIDTERM 1 covers Ch. 1-5\n"
                "Wk 7-8 Thermochemistry (Ch. 6)\n"
                "Wk 9-10 Electronic structure of atoms; periodic properties (Ch. 7-8)\n"
                "Wk 11-13 Chemical bonding, Lewis structures, VSEPR, intermolecular forces (Ch. 9-11)\n\n"
                "GRADING\n"
                "Midterm exam 25% | Final exam (cumulative) 35% | Laboratory 20% | Online homework 20%\n"
                "The two lowest online homework scores are dropped. Homework is due Sundays at 11:59 pm "
                "and is graded for correctness with three attempts per question.\n\n"
                "LABORATORY\n"
                "Goggles and lab coats are required; you will be sent home without them. Pre-lab "
                "questions must be completed before entering the lab. Experiments: (2) empirical formula "
                "of a hydrate by dehydration of CuSO4 x H2O, (4) coffee-cup calorimetry of HCl + NaOH, "
                "(6) molecular models and VSEPR geometry.\n\n"
                "EXAMS\n"
                "A periodic table and constants sheet are provided. Bring a non-programmable calculator."
            ),
        ),
        Document(
            file_name="ch101-lecture-thermochemistry.pdf",
            category="lecture_notes",
            summary=(
                "Lecture notes on thermochemistry: system vs surroundings, enthalpy, specific heat, "
                "calorimetry and Hess's law with worked examples."
            ),
            concept_notes=[
                ConceptNote(name="Thermochemistry", description="Sign conventions for q and delta H and calorimetry calculations."),
                ConceptNote(name="Stoichiometry", description="Scaling delta H by moles of reaction."),
                ConceptNote(name="Limiting Reagents", description="Calorimetry heat depends on the limiting reactant."),
            ],
            extracted_text=(
                "CH 101 - THERMOCHEMISTRY (Ch. 6)\n\n"
                "System vs surroundings. Energy leaving the system is negative. An exothermic reaction "
                "has delta H < 0 and warms its surroundings; an endothermic reaction has delta H > 0.\n\n"
                "Heat and temperature: q = m c delta T. Specific heat of water c = 4.184 J/(g C). "
                "Example: heating 250. g of water from 22.0 C to 98.0 C requires "
                "q = (250. g)(4.184 J/g C)(76.0 C) = 7.95 x 10^4 J = 79.5 kJ.\n\n"
                "Coffee-cup calorimetry (constant pressure): q_rxn = -q_solution. Assume the solution "
                "has the density and specific heat of water and the cup absorbs negligible heat.\n\n"
                "Worked example: 50.0 mL of 1.00 M HCl + 50.0 mL of 1.00 M NaOH, temperature rises "
                "6.8 C. q_soln = (100. g)(4.184)(6.8) = 2.85 kJ, so q_rxn = -2.85 kJ for 0.0500 mol "
                "H2O formed. delta H = -57 kJ/mol.\n\n"
                "Hess's law: if a reaction is the sum of steps, delta H is the sum of the step enthalpies. "
                "Reverse a reaction -> flip the sign of delta H. Multiply a reaction -> multiply delta H.\n\n"
                "Standard enthalpy of formation: delta H_rxn = sum n delta Hf(products) - sum m "
                "delta Hf(reactants). delta Hf of an element in its standard state is zero."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Avogadro's number", back="6.022 x 10^23 particles per mole."),
        Flashcard(front="Value of R for PV = nRT in L and atm", back="0.08206 L atm / (mol K)."),
        Flashcard(front="Specific heat of liquid water", back="4.184 J/(g C)."),
        Flashcard(front="Sign of delta H for an exothermic reaction", back="Negative: heat flows from the system to the surroundings."),
        Flashcard(front="Molecular geometry of NH3", back="Trigonal pyramidal (4 electron domains, 1 lone pair), bond angle about 107 degrees."),
        Flashcard(front="Trend in first ionization energy across a period",
                  back="Increases left to right because effective nuclear charge increases."),
        Flashcard(front="Percent yield formula", back="(actual yield / theoretical yield) x 100%."),
        Flashcard(front="Hund's rule",
                  back="Electrons fill degenerate orbitals singly with parallel spins before pairing."),
    ],
    study_guide=StudyGuide(
        overview=(
            "Midterm 1 covers chapters 1-5: measurement, the mole, stoichiometry, solution reactions and "
            "gases. Most points come from multi-step calculations, so show units on every line and watch "
            "significant figures and temperature units."
        ),
        topics=[
            StudyGuideTopic(
                name="Moles and stoichiometry",
                importance="Nearly every calculation on the exam runs through a mole ratio.",
                concepts=["Grams to moles to grams", "Balancing combustion reactions",
                          "Limiting reagent and theoretical yield", "Percent yield"],
            ),
            StudyGuideTopic(
                name="Solution chemistry",
                importance="Molarity and titration problems are a guaranteed free-response question.",
                concepts=["Molarity and dilution (M1V1 = M2V2)", "Net ionic equations",
                          "Acid-base titration stoichiometry"],
            ),
            StudyGuideTopic(
                name="Gases",
                importance="This was my weakest homework set and it is the last chapter on the exam.",
                concepts=["PV = nRT with Kelvin temperatures", "Combined gas law",
                          "Dalton's law of partial pressures", "Molar mass from gas density"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Stoichiometry", difficulty="easy", days_ago=48, correct=[0, 1, 2],
            questions=[
                QuizQuestion(
                    question="How many grams of CO2 form when 16.0 g of CH4 burns completely in excess O2?",
                    options=["44.0 g", "22.0 g", "16.0 g", "88.0 g"],
                    correct_answer="44.0 g",
                    explanation="16.0 g CH4 is 1.00 mol; CH4 + 2 O2 -> CO2 + 2 H2O gives 1.00 mol CO2 = 44.0 g."),
                QuizQuestion(
                    question="When C3H8 + O2 -> CO2 + H2O is balanced with smallest whole numbers, the coefficient of O2 is:",
                    options=["5", "3", "4", "7"],
                    correct_answer="5",
                    explanation="C3H8 + 5 O2 -> 3 CO2 + 4 H2O."),
                QuizQuestion(
                    question="What is the molar mass of glucose, C6H12O6?",
                    options=["180.16 g/mol", "174.12 g/mol", "162.14 g/mol", "196.16 g/mol"],
                    correct_answer="180.16 g/mol",
                    explanation="6(12.01) + 12(1.008) + 6(16.00) = 180.16 g/mol."),
            ],
        ),
        QuizAttempt(
            concept="Ideal Gas Law", difficulty="medium", days_ago=27, correct=[0, 3],
            questions=[
                QuizQuestion(
                    question="What volume do 2.00 mol of an ideal gas occupy at 1.00 atm and 300. K?",
                    options=["49.2 L", "4.92 L", "24.6 L", "0.0492 L"],
                    correct_answer="49.2 L",
                    explanation="V = nRT/P = (2.00)(0.08206)(300.)/1.00 = 49.2 L."),
                QuizQuestion(
                    question="A gas at 27 C is heated at constant pressure to 327 C. Its volume:",
                    options=["Doubles", "Increases about 12-fold", "Halves", "Stays the same"],
                    correct_answer="Doubles",
                    explanation="300 K -> 600 K; by Charles's law V doubles. Using Celsius gives the wrong 12x."),
                QuizQuestion(
                    question="A mixture has 0.40 mol N2 and 0.10 mol O2 at a total pressure of 2.0 atm. The partial pressure of O2 is:",
                    options=["0.40 atm", "0.10 atm", "1.6 atm", "0.20 atm"],
                    correct_answer="0.40 atm",
                    explanation="X(O2) = 0.10/0.50 = 0.20; P(O2) = 0.20 x 2.0 atm = 0.40 atm."),
                QuizQuestion(
                    question="At STP, one mole of an ideal gas occupies approximately:",
                    options=["22.4 L", "1.00 L", "24.5 L", "8.31 L"],
                    correct_answer="22.4 L",
                    explanation="At 273.15 K and 1 atm, V = RT/P = 22.4 L."),
            ],
        ),
        QuizAttempt(
            concept="Lewis Structures and VSEPR", difficulty="medium", days_ago=4, correct=[2],
            questions=[
                QuizQuestion(
                    question="What is the molecular geometry of NH3?",
                    options=["Trigonal pyramidal", "Trigonal planar", "Tetrahedral", "Bent"],
                    correct_answer="Trigonal pyramidal",
                    explanation="Four electron domains with one lone pair give a trigonal pyramidal shape."),
                QuizQuestion(
                    question="The H-O-H bond angle in water is closest to:",
                    options=["104.5 degrees", "109.5 degrees", "120 degrees", "180 degrees"],
                    correct_answer="104.5 degrees",
                    explanation="Two lone pairs compress the tetrahedral angle to about 104.5 degrees."),
                QuizQuestion(
                    question="Which molecule is linear?",
                    options=["CO2", "H2O", "SO2", "NH3"],
                    correct_answer="CO2",
                    explanation="Carbon has two electron domains (two double bonds) and no lone pairs."),
            ],
        ),
    ],
    session=TutorSession(
        name="Calorimetry lab prep",
        topic="Thermochemistry",
        mode="expository",
        summary_bullets=[
            "In coffee-cup calorimetry, q_rxn = -q_solution.",
            "Use the total solution mass (both solutions) with water's specific heat.",
            "Divide q_rxn by moles of the limiting reactant to get delta H per mole.",
            "A temperature rise means an exothermic reaction, so delta H is negative.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I have to do the pre-lab for the calorimetry lab and I don't get why q_rxn is the negative "
                "of q_solution. Isn't the heat the same?")),
            ChatMessage(role="assistant", content=(
                "The amount is the same, but the direction differs. Think of the cup as a closed box: "
                "energy released by the reaction (the system) is absorbed by the water (the surroundings). "
                "If the water gains +2.85 kJ, the reaction must have lost 2.85 kJ, so q_rxn = -2.85 kJ. "
                "The minus sign is just bookkeeping for which side lost energy.")),
            ChatMessage(role="user", content=(
                "Ok. So for 50 mL of 1.0 M HCl and 50 mL of 1.0 M NaOH with a 6.8 degree rise, do I use 50 g "
                "or 100 g for m?")),
            ChatMessage(role="assistant", content=(
                "Use 100 g: after mixing, the whole 100 mL of solution warms up, and we assume its density is "
                "1.00 g/mL. So q_soln = (100 g)(4.184 J/g C)(6.8 C) = 2,845 J, about 2.85 kJ. Next, how many "
                "moles of water formed? Both reactants are 0.0500 mol, so neither is in excess.")),
            ChatMessage(role="user", content="So 0.0500 mol, and delta H = -2.85 kJ / 0.0500 mol = -57 kJ/mol?"),
            ChatMessage(role="assistant", content=(
                "Exactly, and the negative sign matches what you saw: the temperature rose, so the reaction "
                "is exothermic. The accepted value is about -56 kJ/mol; in your lab report, heat lost to the "
                "cup and the room is the main reason your measured value will come out a bit smaller in size.")),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS BI 203 — Cell Biology
# ---------------------------------------------------------------------------

BI203 = Course(
    code="CAS BI 203",
    name="Cell Biology",
    department="Biology",
    nickname="Cell Bio",
    color="#8E6CC9",
    concepts=[
        Concept(name="Membrane Structure", mastery=0.82,
                description="The fluid mosaic model: phospholipid bilayer, cholesterol, integral and "
                            "peripheral proteins, and membrane asymmetry."),
        Concept(name="Membrane Transport", mastery=0.76,
                description="Channels, carriers and pumps; the Na+/K+ ATPase (3 Na+ out, 2 K+ in) and "
                            "secondary active transport like the Na+/glucose symporter."),
        Concept(name="Cytoskeleton", mastery=0.61,
                description="Actin filaments, microtubules and intermediate filaments; dynamic instability "
                            "and the motor proteins kinesin, dynein and myosin."),
        Concept(name="Endomembrane System", mastery=0.55,
                description="Co-translational import into the ER via signal sequence and SRP, glycosylation, "
                            "and sorting signals like KDEL and mannose-6-phosphate."),
        Concept(name="Mitochondria and Oxidative Phosphorylation", mastery=0.5,
                description="Electron transport chain complexes, the proton-motive force and ATP synthase "
                            "as a rotary motor."),
        Concept(name="Cell Signaling (GPCRs)", mastery=0.36,
                description="G-protein-coupled receptors, Gs/Gi/Gq, adenylyl cyclase, cAMP and PKA, and "
                            "signal termination."),
        Concept(name="Vesicle Trafficking", mastery=0.29,
                description="COPII, COPI and clathrin coats, Rab GTPases, and SNARE-mediated fusion."),
        Concept(name="Receptor Tyrosine Kinases", mastery=0.18,
                description="Ligand-induced dimerization, autophosphorylation, SH2-domain adaptors (Grb2) "
                            "and the Ras-MAPK cascade."),
        Concept(name="Cell Cycle Regulation", mastery=0.07,
                description="Cyclins and CDKs, the G1/S, G2/M and spindle assembly checkpoints, and p53."),
        Concept(name="Apoptosis", mastery=0.0,
                description="Programmed cell death via caspases; intrinsic (cytochrome c) and extrinsic "
                            "(death receptor) pathways."),
    ],
    edges=[
        Edge(source="Membrane Structure", target="Membrane Transport", relationship="prerequisite", strength=0.9),
        Edge(source="Membrane Transport", target="Mitochondria and Oxidative Phosphorylation", relationship="related", strength=0.55),
        Edge(source="Endomembrane System", target="Vesicle Trafficking", relationship="prerequisite", strength=0.85),
        Edge(source="Cytoskeleton", target="Vesicle Trafficking", relationship="related", strength=0.5),
        Edge(source="Cell Signaling (GPCRs)", target="Receptor Tyrosine Kinases", relationship="related", strength=0.65),
        Edge(source="Receptor Tyrosine Kinases", target="Cell Cycle Regulation", relationship="builds_on", strength=0.6),
        Edge(source="Cell Cycle Regulation", target="Apoptosis", relationship="related", strength=0.6),
        Edge(source="Membrane Structure", target="Cell Signaling (GPCRs)", relationship="prerequisite", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Membrane Transport", delta=0.11, reason="Problem Set 1 on pumps and transporters"),
        MasteryEvent(concept="Endomembrane System", delta=0.08, reason="Palade pulse-chase journal club"),
        MasteryEvent(concept="Receptor Tyrosine Kinases", delta=-0.07, reason="Missed Ras activation question on quiz"),
        MasteryEvent(concept="Cell Signaling (GPCRs)", delta=0.09, reason="Tutor session on the Gs-cAMP pathway"),
    ],
    categories=[
        Category(name="Exams", weight=0.65),
        Category(name="Problem Sets", weight=0.20),
        Category(name="Journal Club", weight=0.15),
    ],
    assignments=[
        Assignment(title="Problem Set 1: Membranes and Transport", category="Problem Sets", type="homework",
                   due_offset_days=15, points_possible=30, points_earned=27),
        Assignment(title="Journal Club 1: Palade's Pulse-Chase Experiment", category="Journal Club",
                   type="reading", due_offset_days=28, points_possible=20, points_earned=18),
        Assignment(title="Problem Set 2: Protein Sorting", category="Problem Sets", type="homework",
                   due_offset_days=36, points_possible=30, points_earned=22),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=52, points_possible=100, points_earned=74, is_midterm=True),
        Assignment(title="Journal Club 2: Rodbell and Gilman on G Proteins", category="Journal Club",
                   type="reading", due_offset_days=67, points_possible=20),
        Assignment(title="Problem Set 3: Signal Transduction", category="Problem Sets", type="homework",
                   due_offset_days=78, points_possible=30),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=114, points_possible=150),
    ],
    notes=[
        Note(
            title="Protein sorting - where does it go?",
            tags=["endomembrane", "midterm"],
            concepts=["Endomembrane System", "Vesicle Trafficking"],
            body=(
                "## Default path: ER -> Golgi -> plasma membrane (secretion)\n\n"
                "1. **Signal sequence** (N-terminal, hydrophobic) emerges from the ribosome.\n"
                "2. **SRP** binds it, pauses translation, docks at the SRP receptor on the ER.\n"
                "3. Ribosome hands off to the **Sec61 translocon**; signal peptidase cleaves the signal.\n"
                "4. N-linked glycosylation on Asn in the ER lumen.\n\n"
                "### Sorting signals to memorize\n"
                "- **KDEL** (C-terminal) -> retrieved back to ER by COPI vesicles\n"
                "- **Mannose-6-phosphate** -> lysosome (added in cis Golgi; recognized by M6P receptor "
                "in trans Golgi). I-cell disease = no M6P tag, enzymes get secreted.\n"
                "- **NLS** (Lys/Arg-rich) -> nucleus through nuclear pores, no vesicles\n"
                "- Mitochondrial targeting = amphipathic N-terminal helix, TOM/TIM complexes\n\n"
                "### Coats (still mixing these up)\n"
                "COPII: ER -> Golgi. COPI: Golgi -> ER (retrograde). Clathrin: plasma membrane and trans "
                "Golgi (endocytosis, lysosomal sorting)."
            ),
        ),
        Note(
            title="Journal club: Palade pulse-chase",
            tags=["experiments", "journal club"],
            concepts=["Endomembrane System", "Vesicle Trafficking"],
            body=(
                "## Jamieson & Palade (1967), guinea pig pancreatic acinar cells\n\n"
                "**Question:** what route do secreted proteins take through the cell?\n\n"
                "**Method:** a short *pulse* of radioactive 3H-leucine, then a *chase* with unlabeled "
                "leucine. Fix cells at time points and do EM autoradiography to see where the silver "
                "grains sit.\n\n"
                "**Results (approx):**\n"
                "- 3 min: label over the rough ER\n"
                "- 20 min: Golgi\n"
                "- 120 min: zymogen (secretory) granules near the apical membrane\n\n"
                "**Why it matters:** first direct evidence for the secretory pathway as an ordered route. "
                "Palade shared the 1974 Nobel Prize.\n\n"
                "My discussion question: why use a short pulse? -> so you follow one cohort of proteins "
                "moving together; a long label would light up every compartment at once."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="bi203-syllabus.pdf",
            category="syllabus",
            summary=(
                "BI 203 Cell Biology syllabus: membranes, organelles and protein sorting before the midterm; "
                "signaling, the cell cycle and cell death after, plus journal club expectations."
            ),
            concept_notes=[
                ConceptNote(name="Membrane Structure", description="First unit, weeks 1-2."),
                ConceptNote(name="Endomembrane System", description="Core midterm topic; problem set 2."),
                ConceptNote(name="Cell Signaling (GPCRs)", description="Post-midterm signaling unit and journal club 2."),
                ConceptNote(name="Apoptosis", description="Closing lectures on cell death."),
            ],
            extracted_text=(
                "BI 203 CELL BIOLOGY\n"
                "Prerequisites: BI 108 and CH 101 (CH 102 recommended)\n"
                "Text: Alberts et al., Molecular Biology of the Cell, 7th ed.\n\n"
                "OVERVIEW\n"
                "This course examines how eukaryotic cells are organized and how they work. Part I: "
                "membranes, transport and bioenergetics. Part II: intracellular compartments, protein "
                "sorting and vesicular traffic. Part III: the cytoskeleton. Part IV: cell signaling, the "
                "cell cycle and programmed cell death. Throughout, we emphasize the classic experiments "
                "that established what we know.\n\n"
                "GRADING\n"
                "Midterm exam 25% | Final exam 40% | Problem sets (3) 20% | Journal club 15%\n\n"
                "JOURNAL CLUB\n"
                "Twice this semester you will read a landmark paper and submit a two-page analysis of its "
                "question, approach, key figure and limitations, then discuss it in section. Paper 1: "
                "Jamieson and Palade (1967), intracellular transport of secretory proteins. Paper 2: "
                "selections from Rodbell and Gilman on the discovery of G proteins.\n\n"
                "POLICIES\n"
                "Problem sets are due at the start of Friday discussion. You may discuss problems with "
                "classmates, but the written answers must be your own. Exams are closed book; the final "
                "is cumulative with emphasis on Parts III and IV."
            ),
        ),
        Document(
            file_name="bi203-lecture07-membrane-transport.pdf",
            category="lecture_notes",
            summary=(
                "Lecture 7 notes on membrane transport: passive vs active transport, ion channels, "
                "the Na+/K+ pump and secondary active transport in the intestinal epithelium."
            ),
            concept_notes=[
                ConceptNote(name="Membrane Transport", description="Classes of transport proteins and the energy behind each."),
                ConceptNote(name="Membrane Structure", description="Why the bilayer is impermeable to ions."),
                ConceptNote(name="Mitochondria and Oxidative Phosphorylation", description="ATP that powers pumps comes from oxidative phosphorylation."),
            ],
            extracted_text=(
                "LECTURE 7 - MEMBRANE TRANSPORT\n\n"
                "Lipid bilayers are permeable to small nonpolar molecules (O2, CO2) and slightly to water, "
                "but essentially impermeable to ions and large polar molecules such as glucose. Cells "
                "therefore rely on two classes of membrane transport proteins:\n"
                "- Channels: form aqueous pores; ions move down their electrochemical gradient; very fast "
                "(up to 10^8 ions/s). Gated by voltage, ligand or mechanical stress.\n"
                "- Transporters (carriers): bind solute and undergo a conformational change; slower; can "
                "be passive (GLUT1 facilitated diffusion) or active.\n\n"
                "Primary active transport: the Na+/K+ ATPase hydrolyzes one ATP to pump 3 Na+ out and "
                "2 K+ in. It is electrogenic and uses about a third of a typical animal cell's ATP. "
                "Ouabain inhibits it by binding the extracellular K+ site.\n\n"
                "Secondary active transport: the Na+-glucose symporter (SGLT1) in the apical membrane of "
                "intestinal epithelial cells uses the Na+ gradient to move glucose INTO the cell against "
                "its gradient. Glucose exits basolaterally through GLUT2 by facilitated diffusion. Tight "
                "junctions keep the apical and basolateral transporters in their separate domains.\n\n"
                "Q for section: what happens to glucose uptake if the Na+/K+ pump is blocked?"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Stoichiometry of the Na+/K+ ATPase", back="3 Na+ pumped out and 2 K+ pumped in per ATP hydrolyzed."),
        Flashcard(front="What does SRP do?",
                  back="Binds the ER signal sequence on a nascent chain, pauses translation and targets the ribosome to the ER."),
        Flashcard(front="Sorting signal that sends enzymes to the lysosome", back="Mannose-6-phosphate, added in the cis Golgi."),
        Flashcard(front="COPII vs COPI vesicles", back="COPII: ER to Golgi (anterograde). COPI: Golgi to ER and between Golgi cisternae (retrograde)."),
        Flashcard(front="How is a Gs signal turned off?",
                  back="G-alpha-s hydrolyzes its GTP to GDP; phosphodiesterase degrades cAMP; the receptor is desensitized by GRK and arrestin."),
        Flashcard(front="What adaptor links an activated RTK to Ras?",
                  back="Grb2 (binds phosphotyrosine via its SH2 domain) recruits Sos, a Ras GEF."),
        Flashcard(front="Which motor walks toward the plus end of microtubules?", back="Kinesin (dynein walks toward the minus end)."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The midterm covers Parts I and II: membranes, transport, bioenergetics and the endomembrane "
            "system. Expect experiment-interpretation questions in the style of the Palade paper, so know "
            "what each classic experiment measured and what result would have disproved its conclusion."
        ),
        topics=[
            StudyGuideTopic(
                name="Membranes and transport",
                importance="Transport questions appear in both multiple-choice and data-analysis form.",
                concepts=["Fluid mosaic model and membrane asymmetry", "Channels vs transporters",
                          "Na+/K+ ATPase stoichiometry", "Secondary active transport in gut epithelium"],
            ),
            StudyGuideTopic(
                name="Protein sorting",
                importance="The professor called signal sequences the single most-tested idea before the midterm.",
                concepts=["SRP-dependent co-translational import", "KDEL retrieval and mannose-6-phosphate",
                          "Nuclear localization signals", "Pulse-chase interpretation"],
            ),
            StudyGuideTopic(
                name="Bioenergetics",
                importance="One long-answer question will ask you to explain chemiosmotic coupling.",
                concepts=["Proton-motive force", "ATP synthase as a rotary motor",
                          "Effects of uncouplers like DNP"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Membrane Transport", difficulty="medium", days_ago=44, correct=[0, 1, 2],
            questions=[
                QuizQuestion(
                    question="Per ATP hydrolyzed, the Na+/K+ ATPase moves:",
                    options=["3 Na+ out and 2 K+ in", "2 Na+ out and 3 K+ in", "1 Na+ out and 1 K+ in", "3 Na+ in and 2 K+ out"],
                    correct_answer="3 Na+ out and 2 K+ in",
                    explanation="The pump is electrogenic because it moves more positive charge out than in."),
                QuizQuestion(
                    question="SGLT1 moves glucose into intestinal cells against its gradient. Its energy source is:",
                    options=["The Na+ gradient", "Direct ATP hydrolysis", "The K+ gradient", "Light"],
                    correct_answer="The Na+ gradient",
                    explanation="It is a secondary active symporter coupled to Na+ moving down its gradient."),
                QuizQuestion(
                    question="Which molecule crosses a pure lipid bilayer most readily?",
                    options=["O2", "Na+", "Glucose", "ATP"],
                    correct_answer="O2",
                    explanation="Small nonpolar molecules diffuse freely through the hydrophobic core."),
                QuizQuestion(
                    question="Ion channels differ from transporters in that channels:",
                    options=["Cannot move solutes against their gradient", "Are always open",
                             "Require ATP", "Bind solute and change conformation"],
                    correct_answer="Cannot move solutes against their gradient",
                    explanation="Channels only allow passive flow down the electrochemical gradient."),
            ],
        ),
        QuizAttempt(
            concept="Endomembrane System", difficulty="medium", days_ago=24, correct=[0, 2],
            questions=[
                QuizQuestion(
                    question="A soluble ER protein whose KDEL sequence is deleted will most likely be:",
                    options=["Secreted from the cell", "Sent to the lysosome", "Retained in the ER", "Imported into the nucleus"],
                    correct_answer="Secreted from the cell",
                    explanation="Without KDEL it is not retrieved and follows the default secretory route."),
                QuizQuestion(
                    question="In I-cell disease, lysosomal enzymes are secreted because they lack:",
                    options=["Mannose-6-phosphate", "A signal sequence", "A KDEL sequence", "A nuclear localization signal"],
                    correct_answer="Mannose-6-phosphate",
                    explanation="The phosphotransferase that adds M6P in the cis Golgi is defective."),
                QuizQuestion(
                    question="In the Palade pulse-chase experiment, label first appeared over the:",
                    options=["Rough ER", "Golgi apparatus", "Secretory granules", "Nucleus"],
                    correct_answer="Rough ER",
                    explanation="Proteins are synthesized into the rough ER before moving to the Golgi and granules."),
            ],
        ),
        QuizAttempt(
            concept="Receptor Tyrosine Kinases", difficulty="hard", days_ago=3, correct=[0],
            questions=[
                QuizQuestion(
                    question="Ligand binding activates most receptor tyrosine kinases by causing:",
                    options=["Dimerization and cross-autophosphorylation", "GDP-GTP exchange on a G protein",
                             "Opening of an ion channel", "Cleavage by gamma-secretase"],
                    correct_answer="Dimerization and cross-autophosphorylation",
                    explanation="Two receptor kinases phosphorylate each other's cytoplasmic tyrosines."),
                QuizQuestion(
                    question="SH2 domains recognize:",
                    options=["Phosphorylated tyrosines", "GTP-bound Ras", "cAMP", "Phosphatidylinositol"],
                    correct_answer="Phosphorylated tyrosines",
                    explanation="SH2 domains bind phosphotyrosine in a specific sequence context."),
                QuizQuestion(
                    question="Sos activates Ras by:",
                    options=["Promoting release of GDP so GTP can bind", "Hydrolyzing GTP on Ras",
                             "Phosphorylating Ras", "Adding a lipid anchor to Ras"],
                    correct_answer="Promoting release of GDP so GTP can bind",
                    explanation="Sos is a guanine nucleotide exchange factor (GEF)."),
                QuizQuestion(
                    question="An oncogenic Ras mutation that blocks GTP hydrolysis results in:",
                    options=["Constitutive MAPK signaling", "No MAPK signaling",
                             "Increased receptor dimerization", "Loss of SH2 binding"],
                    correct_answer="Constitutive MAPK signaling",
                    explanation="Ras stays GTP-bound and keeps activating Raf, MEK and ERK."),
            ],
        ),
    ],
    session=TutorSession(
        name="GPCR and cAMP signaling",
        topic="Cell Signaling (GPCRs)",
        mode="expository",
        summary_bullets=[
            "An activated GPCR acts as a GEF, making G-alpha swap GDP for GTP.",
            "G-alpha-s-GTP activates adenylyl cyclase; cAMP then activates PKA.",
            "Signals end through G-alpha GTPase activity, phosphodiesterase and receptor desensitization.",
            "Cholera toxin locks G-alpha-s in its GTP-bound state.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "Can you walk me through the epinephrine to cAMP pathway? The slides jump around and I "
                "don't know what order things happen in.")),
            ChatMessage(role="assistant", content=(
                "Sure. 1) Epinephrine binds the beta-adrenergic receptor, a GPCR with seven transmembrane "
                "helices. 2) The activated receptor acts as a GEF for the heterotrimeric G protein: the G-alpha-s "
                "subunit releases GDP and binds GTP. 3) GTP-bound G-alpha-s separates from Gβγ and activates "
                "adenylyl cyclase. 4) Adenylyl cyclase converts ATP to cAMP. 5) cAMP binds the regulatory "
                "subunits of PKA, releasing the active catalytic subunits, which phosphorylate targets such "
                "as glycogen phosphorylase kinase in liver.")),
            ChatMessage(role="user", content="Got it. So how does it stop? Does the epinephrine just leave?"),
            ChatMessage(role="assistant", content=(
                "Ligand leaving helps, but the cell has built-in timers. G-alpha-s hydrolyzes its own GTP to GDP "
                "within seconds and re-associates with Gβγ; phosphodiesterase breaks cAMP down to AMP; and "
                "GRK phosphorylates the receptor so arrestin binds and blocks further G-protein activation. "
                "Quick check: cholera toxin chemically modifies G-alpha-s so it cannot hydrolyze GTP. What would "
                "that do to cAMP levels in intestinal cells?")),
            ChatMessage(role="user", content=(
                "cAMP would stay high all the time, since G-alpha-s never turns off. Is that why you get the "
                "diarrhea, from the chloride channel?")),
            ChatMessage(role="assistant", content=(
                "Exactly. Persistently high cAMP keeps PKA phosphorylating the CFTR chloride channel, so Cl- "
                "and then water pour into the gut lumen. That is a nice bridge to journal club 2: Gilman's "
                "work on Gs is part of how we know which subunit the toxin targets.")),
        ],
    ),
)


PACK = MajorPack(
    key="biology",
    label="Biology",
    courses=[BI107, BI108, CH101, BI203],
    total_xp=1480,
    streak_days=9,
)
