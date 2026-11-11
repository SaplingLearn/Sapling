"""Psychology major seed pack: a sophomore psychology student.

Strengths vary by course on purpose: confident in the intro survey course
(PS 101) and in developmental theory (PS 241), solid on neuron basics but
weaker on neurotransmitter systems and sensory pathways (PS 231), and
genuinely struggling with inferential statistics in Experimental Design
(PS 211).
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
# CAS PS 101 — General Psychology
# ---------------------------------------------------------------------------

PS101 = Course(
    code="CAS PS 101",
    name="General Psychology",
    department="Psychological and Brain Sciences",
    nickname="Intro Psych",
    color="#E0697B",
    concepts=[
        Concept(name="Classical Conditioning", mastery=0.96,
                description="Pavlov's paradigm: US, UR, CS and CR; acquisition, extinction, spontaneous "
                            "recovery, and Watson and Rayner's Little Albert study."),
        Concept(name="Operant Conditioning", mastery=0.81,
                description="Skinner's reinforcement and punishment (positive and negative), shaping, and "
                            "the four schedules of reinforcement."),
        Concept(name="Research Methods in Psychology", mastery=0.77,
                description="Descriptive, correlational and experimental designs; independent and "
                            "dependent variables, random assignment and confounds."),
        Concept(name="Social Influence", mastery=0.72,
                description="Asch's line-judgment conformity studies, Milgram's obedience experiments, "
                            "and the bystander effect."),
        Concept(name="Memory Encoding and Retrieval", mastery=0.64,
                description="Atkinson-Shiffrin model, levels of processing, encoding specificity, and the "
                            "serial position effect."),
        Concept(name="Neurons and Neurotransmission", mastery=0.5,
                description="Basic neuron anatomy, the action potential, synapses and major "
                            "neurotransmitters at an introductory level."),
        Concept(name="Sensation and Perception", mastery=0.46,
                description="Transduction, absolute and difference thresholds (Weber's law), signal "
                            "detection theory, and Gestalt grouping principles."),
        Concept(name="Personality Theories", mastery=0.33,
                description="Freud's psychodynamic theory, humanistic approaches (Maslow, Rogers), and "
                            "the Big Five trait model."),
        Concept(name="States of Consciousness", mastery=0.19,
                description="Sleep stages and the roughly 90-minute cycle, REM sleep, circadian rhythms, "
                            "and psychoactive drug classes."),
        Concept(name="Psychological Disorders", mastery=0.08,
                description="DSM-5-TR classification, anxiety and mood disorders, schizophrenia, and the "
                            "diathesis-stress model."),
    ],
    edges=[
        Edge(source="Classical Conditioning", target="Operant Conditioning", relationship="related", strength=0.75),
        Edge(source="Classical Conditioning", target="Psychological Disorders", relationship="related", strength=0.45),
        Edge(source="Neurons and Neurotransmission", target="Sensation and Perception", relationship="prerequisite", strength=0.7),
        Edge(source="Neurons and Neurotransmission", target="States of Consciousness", relationship="builds_on", strength=0.55),
        Edge(source="Research Methods in Psychology", target="Social Influence", relationship="related", strength=0.5),
        Edge(source="Sensation and Perception", target="Memory Encoding and Retrieval", relationship="related", strength=0.5),
        Edge(source="Personality Theories", target="Psychological Disorders", relationship="related", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Classical Conditioning", delta=0.15, reason="4/4 on the classical conditioning quiz"),
        MasteryEvent(concept="Personality Theories", delta=-0.06, reason="Mixed up Big Five traits on quiz"),
        MasteryEvent(concept="Memory Encoding and Retrieval", delta=0.08, reason="Tutor session on levels of processing"),
        MasteryEvent(concept="Social Influence", delta=0.1, reason="Milgram reading response"),
    ],
    categories=[
        Category(name="Exams", weight=0.60),
        Category(name="Reading Quizzes", weight=0.25, drop_lowest=2),
        Category(name="Research Participation", weight=0.15),
    ],
    assignments=[
        Assignment(title="Reading Quiz: Ch. 2 Research Methods", category="Reading Quizzes", type="quiz",
                   due_offset_days=10, points_possible=10, points_earned=10),
        Assignment(title="Reading Quiz: Ch. 6 Learning", category="Reading Quizzes", type="quiz",
                   due_offset_days=31, points_possible=10, points_earned=9),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=42, points_possible=100, points_earned=89, is_midterm=True),
        Assignment(title="Reading Quiz: Ch. 7 Memory", category="Reading Quizzes", type="quiz",
                   due_offset_days=52, points_possible=10, points_earned=8),
        Assignment(title="SONA Research Participation (4 credits)", category="Research Participation",
                   type="other", due_offset_days=98, points_possible=4),
        Assignment(title="Reading Quiz: Ch. 14 Psychological Disorders", category="Reading Quizzes", type="quiz",
                   due_offset_days=87, points_possible=10),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=110, points_possible=120),
    ],
    notes=[
        Note(
            title="Conditioning: classical vs operant",
            tags=["learning", "midterm"],
            concepts=["Classical Conditioning", "Operant Conditioning"],
            body=(
                "## Classical (Pavlov) = learning associations between STIMULI\n"
                "- US (food) -> UR (salivation, automatic)\n"
                "- CS (bell) paired with US -> eventually CS alone -> CR\n"
                "- **Extinction**: CS without US, CR fades. **Spontaneous recovery**: CR comes back after a rest.\n"
                "- Little Albert (Watson & Rayner, 1920): white rat (CS) + loud noise (US) -> fear (CR); "
                "generalized to a rabbit and a fur coat. Huge ethics problems.\n\n"
                "## Operant (Skinner) = learning from CONSEQUENCES of behavior\n"
                "- Positive = ADD something; negative = REMOVE something\n"
                "- Reinforcement increases behavior; punishment decreases it\n"
                "- Negative reinforcement is NOT punishment (taking aspirin removes a headache -> you take "
                "it more often)\n\n"
                "### Schedules\n"
                "- Fixed ratio: every nth response (piecework)\n"
                "- Variable ratio: unpredictable count (slot machines) -> **most resistant to extinction**\n"
                "- Fixed interval: scalloped pattern (studying before exams, ha)\n"
                "- Variable interval: steady responding (checking email)"
            ),
        ),
        Note(
            title="Milgram and Asch - numbers to know",
            tags=["social psych", "experiments"],
            concepts=["Social Influence", "Research Methods in Psychology"],
            body=(
                "## Asch (1951) line judgments\n"
                "- 1 real participant + 7 confederates giving obviously wrong answers\n"
                "- Conformed on about **37%** of critical trials\n"
                "- About **75%** conformed at least once\n"
                "- One dissenting confederate cut conformity sharply -> unanimity matters\n\n"
                "## Milgram (1963) obedience\n"
                "- 'Teacher' told to shock a 'learner' (confederate) for wrong answers, 15 V to 450 V\n"
                "- **65%** went all the way to 450 V\n"
                "- Obedience dropped when the experimenter gave orders by phone or when the teacher had "
                "to physically place the learner's hand on the plate\n\n"
                "## Why these matter for methods\n"
                "Both use deception, so they raise informed consent and debriefing issues. Milgram is a "
                "big reason IRBs exist. Neither is a true experiment in the basic version (no comparison "
                "group), but the variations are, since the situational factor is manipulated."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ps101-syllabus.pdf",
            category="syllabus",
            summary=(
                "PS 101 General Psychology syllabus: survey of the field from research methods and the "
                "brain through learning, memory, social and clinical psychology, with grading and SONA policy."
            ),
            concept_notes=[
                ConceptNote(name="Research Methods in Psychology", description="Week 1-2 foundation for reading every study in the course."),
                ConceptNote(name="Classical Conditioning", description="Learning unit, heavily tested on the midterm."),
                ConceptNote(name="Social Influence", description="Social psychology unit after the midterm."),
                ConceptNote(name="Psychological Disorders", description="Clinical unit at the end of the term."),
            ],
            extracted_text=(
                "PS 101 GENERAL PSYCHOLOGY\n"
                "Lecture: Mon/Wed/Fri 11:15-12:05, Tsai Performance Center\n"
                "Text: Myers & DeWall, Psychology, 13th edition\n\n"
                "COURSE GOALS\n"
                "This course surveys the science of behavior and mental processes. By the end of the "
                "semester you should be able to evaluate a psychological claim by asking how it was "
                "tested, describe the major perspectives in the field, and apply core findings about "
                "learning, memory and social influence to everyday life.\n\n"
                "SCHEDULE (abbreviated)\n"
                "Weeks 1-2 Thinking critically with psychological science; research methods\n"
                "Weeks 3-4 Biology of behavior; sensation and perception\n"
                "Weeks 5-6 Learning; memory -- MIDTERM\n"
                "Weeks 8-9 Consciousness; motivation and emotion\n"
                "Weeks 10-11 Social psychology; personality\n"
                "Weeks 12-14 Psychological disorders and therapies\n\n"
                "GRADING\n"
                "Midterm 25% | Final (cumulative) 35% | Reading quizzes 25% (two lowest dropped) | "
                "Research participation 15%\n\n"
                "RESEARCH PARTICIPATION\n"
                "You must earn 4 credits through the SONA system by the last day of classes. One credit "
                "equals one hour of participation. An alternative written assignment is available for "
                "students who prefer not to participate."
            ),
        ),
        Document(
            file_name="ps101-lecture-memory.pdf",
            category="lecture_notes",
            summary=(
                "Lecture notes on memory: the three-stage model, working memory capacity, levels of "
                "processing, encoding specificity and forgetting."
            ),
            concept_notes=[
                ConceptNote(name="Memory Encoding and Retrieval", description="Stages of memory and what makes encoding durable."),
                ConceptNote(name="Research Methods in Psychology", description="Godden and Baddeley as a factorial design."),
                ConceptNote(name="Neurons and Neurotransmission", description="Hippocampus and long-term potentiation previewed."),
            ],
            extracted_text=(
                "PS 101 - MEMORY\n\n"
                "Three-stage model (Atkinson & Shiffrin, 1968): sensory memory -> short-term memory -> "
                "long-term memory. Sensory memory: iconic (about 1/4 to 1/2 second, Sperling's partial-"
                "report task) and echoic (3-4 seconds). Short-term memory span is about 7 +/- 2 items "
                "(Miller, 1956); later research suggests closer to 4 chunks. Baddeley's working memory "
                "model adds a central executive, phonological loop and visuospatial sketchpad.\n\n"
                "Encoding. Levels of processing (Craik & Lockhart, 1972): semantic processing (does the "
                "word fit this sentence?) produces better recall than shallow structural processing (is "
                "the word in capital letters?). The self-reference effect is an especially deep form.\n\n"
                "Retrieval. Recall vs recognition vs relearning (Ebbinghaus's savings). Encoding "
                "specificity: retrieval is best when cues match the encoding context. Godden & Baddeley "
                "(1975) had divers learn words on land or 10 feet underwater; recall was better in the "
                "matching environment. Serial position effect: primacy and recency.\n\n"
                "Forgetting. Ebbinghaus's forgetting curve drops steeply then levels off. Proactive "
                "interference (old blocks new) vs retroactive interference (new blocks old).\n\n"
                "Takeaway for studying: spaced retrieval practice beats rereading."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Negative reinforcement", back="Removing an aversive stimulus to INCREASE a behavior (e.g. a seatbelt chime stops when you buckle up)."),
        Flashcard(front="Which reinforcement schedule is most resistant to extinction?", back="Variable ratio."),
        Flashcard(front="Spontaneous recovery", back="Reappearance of an extinguished conditioned response after a rest period."),
        Flashcard(front="Encoding specificity principle", back="Memory retrieval is best when retrieval cues match the context at encoding (Godden & Baddeley's divers)."),
        Flashcard(front="Percent of Milgram's participants who reached 450 V", back="65% in the original 1963 study."),
        Flashcard(front="Big Five personality traits (OCEAN)", back="Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism."),
        Flashcard(front="Weber's law", back="The just-noticeable difference is a constant proportion of the original stimulus intensity."),
        Flashcard(front="Independent vs dependent variable", back="IV is manipulated by the experimenter; DV is measured to see the effect."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The midterm covers chapters 1-7: research methods, biology of behavior, sensation and "
            "perception, learning and memory. Questions are mostly applied multiple choice, so practice "
            "classifying new scenarios rather than memorizing definitions."
        ),
        topics=[
            StudyGuideTopic(
                name="Learning",
                importance="Scenario questions asking you to label CS, US, or the type of reinforcement are worth the most points.",
                concepts=["Identifying US, UR, CS and CR in a new example",
                          "Positive vs negative reinforcement vs punishment",
                          "Reinforcement schedules and their response patterns",
                          "Extinction and spontaneous recovery"],
            ),
            StudyGuideTopic(
                name="Memory",
                importance="The professor said memory gets the most questions of any single chapter.",
                concepts=["Atkinson-Shiffrin stages and capacities", "Levels of processing",
                          "Encoding specificity and context effects", "Proactive vs retroactive interference"],
            ),
            StudyGuideTopic(
                name="Research methods",
                importance="Every chapter's questions assume you can tell a correlation from an experiment.",
                concepts=["Correlation does not imply causation", "Random assignment vs random sampling",
                          "Operational definitions", "Confounding variables"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Classical Conditioning", difficulty="easy", days_ago=40, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(
                    question="In Pavlov's experiments, the bell before conditioning is a:",
                    options=["Neutral stimulus", "Unconditioned stimulus", "Conditioned response", "Unconditioned response"],
                    correct_answer="Neutral stimulus",
                    explanation="The bell elicits no salivation until it has been paired with food."),
                QuizQuestion(
                    question="In the Little Albert study, the loud noise was the:",
                    options=["Unconditioned stimulus", "Conditioned stimulus", "Conditioned response", "Neutral stimulus"],
                    correct_answer="Unconditioned stimulus",
                    explanation="The noise naturally produced fear without any learning."),
                QuizQuestion(
                    question="A conditioned response that returns after extinction and a rest period shows:",
                    options=["Spontaneous recovery", "Generalization", "Discrimination", "Higher-order conditioning"],
                    correct_answer="Spontaneous recovery",
                    explanation="Extinction suppresses rather than erases the association."),
                QuizQuestion(
                    question="Albert also feared a white rabbit after conditioning with a white rat. This is:",
                    options=["Stimulus generalization", "Stimulus discrimination", "Extinction", "Shaping"],
                    correct_answer="Stimulus generalization",
                    explanation="The CR spread to stimuli similar to the original CS."),
            ],
        ),
        QuizAttempt(
            concept="Social Influence", difficulty="medium", days_ago=15, correct=[0, 1, 3],
            questions=[
                QuizQuestion(
                    question="In Milgram's original study, about what percentage of participants delivered the maximum 450 V shock?",
                    options=["65%", "10%", "35%", "90%"],
                    correct_answer="65%",
                    explanation="26 of 40 participants obeyed to the end."),
                QuizQuestion(
                    question="In Asch's studies, conformity dropped most when:",
                    options=["One confederate gave the correct answer", "The group grew from 7 to 15",
                             "The lines were harder to judge", "Participants answered last"],
                    correct_answer="One confederate gave the correct answer",
                    explanation="Breaking the majority's unanimity sharply reduced conformity."),
                QuizQuestion(
                    question="The bystander effect predicts that a person is LESS likely to help when:",
                    options=["More bystanders are present", "They are alone", "The victim is a friend", "The emergency is unambiguous"],
                    correct_answer="More bystanders are present",
                    explanation="Diffusion of responsibility grows with the number of bystanders."),
                QuizQuestion(
                    question="Changing your behavior because you want to be liked by a group is:",
                    options=["Normative social influence", "Informational social influence", "Obedience", "Social facilitation"],
                    correct_answer="Normative social influence",
                    explanation="Normative influence comes from the desire for acceptance; informational from wanting to be correct."),
            ],
        ),
        QuizAttempt(
            concept="Personality Theories", difficulty="medium", days_ago=5, correct=[1, 2],
            questions=[
                QuizQuestion(
                    question="In Freud's theory, the part of personality operating on the reality principle is the:",
                    options=["Ego", "Id", "Superego", "Libido"],
                    correct_answer="Ego",
                    explanation="The ego mediates between the id's demands and reality."),
                QuizQuestion(
                    question="Which Big Five trait is most associated with emotional instability and anxiety?",
                    options=["Neuroticism", "Openness", "Agreeableness", "Conscientiousness"],
                    correct_answer="Neuroticism",
                    explanation="High neuroticism means more frequent negative emotions."),
                QuizQuestion(
                    question="Carl Rogers emphasized that growth requires:",
                    options=["Unconditional positive regard", "Resolving the Oedipus complex",
                             "Reinforcement of desired traits", "High self-monitoring"],
                    correct_answer="Unconditional positive regard",
                    explanation="Rogers' person-centered approach centers acceptance, genuineness and empathy."),
                QuizQuestion(
                    question="The top of Maslow's hierarchy of needs is:",
                    options=["Self-actualization", "Esteem", "Belongingness and love", "Safety"],
                    correct_answer="Self-actualization",
                    explanation="Self-transcendence was added later, but the classic pyramid tops out at self-actualization."),
            ],
        ),
    ],
    session=TutorSession(
        name="Why deep processing works",
        topic="Memory Encoding and Retrieval",
        mode="socratic",
        summary_bullets=[
            "Semantic (meaning-based) encoding produces better recall than shallow encoding.",
            "Encoding specificity: match retrieval cues to the study context.",
            "Spaced retrieval practice beats rereading for exam prep.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I reread the memory chapter three times and still blanked on the quiz. Why doesn't "
                "rereading work?")),
            ChatMessage(role="assistant", content=(
                "Let's use the chapter itself to explain it. In Craik and Lockhart's study, which task "
                "led to better recall: deciding if a word was in capital letters, or deciding if it fit "
                "a sentence?")),
            ChatMessage(role="user", content="The sentence one, because you have to think about what the word means."),
            ChatMessage(role="assistant", content=(
                "Right, semantic processing is deeper. Now compare that to rereading: when you reread a "
                "familiar page, how much are you processing meaning, versus just recognizing that the "
                "words look familiar?")),
            ChatMessage(role="user", content=(
                "Mostly recognizing, I guess. It feels like I know it because it looks familiar.")),
            ChatMessage(role="assistant", content=(
                "That feeling is the trap: recognition is easier than recall, so familiarity fools you. "
                "The quiz asked you to recall. A better plan: close the book and write out the "
                "three-stage model from memory, then check it, and repeat a couple of days later. That "
                "uses deep processing, practices the same kind of retrieval the exam requires, and adds "
                "spacing, which fights the steep early drop in Ebbinghaus's forgetting curve.")),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS PS 211 — Introduction to Experimental Design
# ---------------------------------------------------------------------------

PS211 = Course(
    code="CAS PS 211",
    name="Introduction to Experimental Design",
    department="Psychological and Brain Sciences",
    nickname="Exp Design (Stats)",
    color="#3E7CB1",
    concepts=[
        Concept(name="Scales of Measurement", mastery=0.96,
                description="Nominal, ordinal, interval and ratio scales and which statistics each allows."),
        Concept(name="Descriptive Statistics", mastery=0.79,
                description="Mean, median, mode, range, variance and standard deviation; skew and its "
                            "effect on the mean."),
        Concept(name="Normal Distribution and z-Scores", mastery=0.58,
                description="Standardizing scores with z = (X - mean) / SD, the 68-95-99.7 rule, and "
                            "finding percentiles from the unit normal table."),
        Concept(name="Hypothesis Testing", mastery=0.47,
                description="Null and alternative hypotheses, alpha, p-values, critical regions and the "
                            "logic of rejecting H0."),
        Concept(name="Sampling Distributions", mastery=0.42,
                description="Distribution of sample means, the central limit theorem, and the standard "
                            "error sigma / sqrt(n)."),
        Concept(name="Type I and Type II Errors", mastery=0.35,
                description="False positives (alpha) vs misses (beta) and how the two trade off."),
        Concept(name="Independent-Samples t-Test", mastery=0.24,
                description="Comparing two group means with pooled variance; df = n1 + n2 - 2; Cohen's d "
                            "as effect size."),
        Concept(name="Correlation and Regression", mastery=0.13,
                description="Pearson's r, r-squared as variance explained, and the least-squares line "
                            "Y-hat = a + bX."),
        Concept(name="Statistical Power", mastery=0.06,
                description="Power = 1 - beta; how sample size, effect size and alpha change it."),
        Concept(name="One-Way ANOVA", mastery=0.02,
                description="Comparing three or more means with the F ratio of between- to within-group "
                            "variance, and post hoc tests."),
    ],
    edges=[
        Edge(source="Scales of Measurement", target="Descriptive Statistics", relationship="prerequisite", strength=0.7),
        Edge(source="Descriptive Statistics", target="Normal Distribution and z-Scores", relationship="prerequisite", strength=0.85),
        Edge(source="Normal Distribution and z-Scores", target="Sampling Distributions", relationship="prerequisite", strength=0.85),
        Edge(source="Sampling Distributions", target="Hypothesis Testing", relationship="prerequisite", strength=0.9),
        Edge(source="Type I and Type II Errors", target="Hypothesis Testing", relationship="part_of", strength=0.8),
        Edge(source="Hypothesis Testing", target="Independent-Samples t-Test", relationship="prerequisite", strength=0.9),
        Edge(source="Independent-Samples t-Test", target="One-Way ANOVA", relationship="builds_on", strength=0.8),
        Edge(source="Type I and Type II Errors", target="Statistical Power", relationship="prerequisite", strength=0.85),
        Edge(source="Descriptive Statistics", target="Correlation and Regression", relationship="prerequisite", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Descriptive Statistics", delta=0.12, reason="Full marks on SPSS Lab 1"),
        MasteryEvent(concept="Sampling Distributions", delta=-0.1, reason="Confused SD with standard error on quiz"),
        MasteryEvent(concept="Independent-Samples t-Test", delta=-0.05, reason="Wrong degrees of freedom on SPSS Lab 3"),
        MasteryEvent(concept="Type I and Type II Errors", delta=0.08, reason="Tutor session on alpha and beta"),
    ],
    categories=[
        Category(name="Exams", weight=0.50),
        Category(name="SPSS Labs", weight=0.30),
        Category(name="Research Proposal", weight=0.20),
    ],
    assignments=[
        Assignment(title="SPSS Lab 1: Frequency Distributions and Descriptives", category="SPSS Labs",
                   type="homework", due_offset_days=13, points_possible=20, points_earned=19),
        Assignment(title="SPSS Lab 2: z-Scores and Percentiles", category="SPSS Labs",
                   type="homework", due_offset_days=27, points_possible=20, points_earned=16),
        Assignment(title="Research Proposal Draft: Hypothesis and Design", category="Research Proposal",
                   type="project", due_offset_days=38, points_possible=30, points_earned=24),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=49, points_possible=100, points_earned=68, is_midterm=True),
        Assignment(title="SPSS Lab 3: Independent-Samples t-Test", category="SPSS Labs",
                   type="homework", due_offset_days=62, points_possible=20, points_earned=14),
        Assignment(title="SPSS Lab 4: Correlation and Regression", category="SPSS Labs",
                   type="homework", due_offset_days=79, points_possible=20),
        Assignment(title="Final Research Proposal", category="Research Proposal",
                   type="project", due_offset_days=98, points_possible=70),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=112, points_possible=100),
    ],
    notes=[
        Note(
            title="SD vs standard error (finally)",
            tags=["stats", "midterm", "confusing"],
            concepts=["Sampling Distributions", "Descriptive Statistics", "Normal Distribution and z-Scores"],
            body=(
                "## Two different spreads, two different distributions\n\n"
                "- **Standard deviation (SD, sigma or s)**: how spread out *individual scores* are "
                "around the mean of ONE sample or population.\n"
                "- **Standard error (SE = sigma / sqrt(n))**: how spread out *sample means* are around "
                "mu, if you took sample after sample of size n.\n\n"
                "### Central limit theorem\n"
                "The distribution of sample means:\n"
                "1. has mean = mu\n"
                "2. has SD = sigma / sqrt(n) (that IS the standard error)\n"
                "3. approaches normal as n gets big (n >= 30 rule of thumb), even if the population "
                "isn't normal\n\n"
                "### Worked example from section\n"
                "IQ: mu = 100, sigma = 15. Sample of n = 25 -> SE = 15/5 = 3.\n"
                "Probability a sample mean > 106: z = (106 - 100)/3 = 2.00 -> p = .0228.\n"
                "For ONE person scoring > 106, z = 6/15 = 0.40 -> p = .3446. Totally different!\n\n"
                "**Bigger n -> smaller SE -> sample means hug mu more tightly.**"
            ),
        ),
        Note(
            title="Research proposal brainstorm",
            tags=["proposal", "project"],
            concepts=["Hypothesis Testing", "Independent-Samples t-Test", "Statistical Power"],
            body=(
                "## Idea: does phone presence hurt working memory?\n"
                "Based on Ward et al. (2017) \"Brain Drain\" paper: just having your phone on the desk "
                "lowered working memory capacity.\n\n"
                "**IV:** phone location (on desk, face down vs in another room) - between subjects\n"
                "**DV:** operation span (OSPAN) score\n"
                "**H0:** mu_desk = mu_other room\n"
                "**H1:** mu_desk < mu_other room (one-tailed? TA said justify it or use two-tailed)\n\n"
                "### Design notes\n"
                "- Random assignment to condition (NOT just letting people choose)\n"
                "- Control: same room, same instructions, phones silenced in both conditions\n"
                "- Analysis: independent-samples t-test, alpha = .05, df = n1 + n2 - 2\n\n"
                "### Power - need to figure this out\n"
                "Feedback on draft: \"How many participants do you need?\" Ward's effect was roughly "
                "d = 0.4. Need to look up a power table or use G*Power for 80% power. I think it's "
                "around 100 per group for one-tailed, which is a lot for SONA."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ps211-syllabus.pdf",
            category="syllabus",
            summary=(
                "PS 211 syllabus: descriptive and inferential statistics for psychology with weekly SPSS "
                "labs, a semester-long research proposal and two exams."
            ),
            concept_notes=[
                ConceptNote(name="Descriptive Statistics", description="Weeks 1-3, with SPSS Lab 1."),
                ConceptNote(name="Hypothesis Testing", description="Core logic introduced before the midterm."),
                ConceptNote(name="Independent-Samples t-Test", description="First inferential test, SPSS Lab 3."),
                ConceptNote(name="One-Way ANOVA", description="Final unit of the semester."),
            ],
            extracted_text=(
                "PS 211 INTRODUCTION TO EXPERIMENTAL DESIGN IN PSYCHOLOGY\n"
                "Prerequisite: PS 101. Lecture Tu/Th 12:30-1:45; lab sections meet weekly in the SPSS "
                "computer lab.\n\n"
                "DESCRIPTION\n"
                "An introduction to the logic of experimental design and the statistics psychologists "
                "use to evaluate data. Topics: scales of measurement, frequency distributions, measures "
                "of central tendency and variability, z-scores and the normal distribution, sampling "
                "distributions, hypothesis testing, t-tests, correlation and regression, and one-way "
                "analysis of variance. Students design an original study and write an APA-style "
                "research proposal.\n\n"
                "GRADING\n"
                "Midterm 20% | Final 30% | SPSS labs 30% | Research proposal 20% (draft 30 points, "
                "final 70 points)\n\n"
                "CALCULATORS AND TABLES\n"
                "Bring a scientific calculator to every exam. Unit normal, t and F tables are provided. "
                "Exams require you to show the formula, the numbers substituted, and a sentence stating "
                "the conclusion in APA format, e.g. t(38) = 2.41, p < .05.\n\n"
                "LAB POLICY\n"
                "Labs are due the following week before your section meets. Submit the SPSS output and "
                "the written interpretation; output alone earns no credit. Missed labs can be made up "
                "within one week with documentation."
            ),
        ),
        Document(
            file_name="ps211-lecture-hypothesis-testing.pdf",
            category="lecture_notes",
            summary=(
                "Lecture notes on the four steps of hypothesis testing, alpha and critical regions, "
                "one- vs two-tailed tests, and Type I and Type II errors."
            ),
            concept_notes=[
                ConceptNote(name="Hypothesis Testing", description="The four-step procedure with a z-test example."),
                ConceptNote(name="Type I and Type II Errors", description="The 2x2 decision table and the meaning of alpha and beta."),
                ConceptNote(name="Statistical Power", description="Power previewed as the probability of correctly rejecting H0."),
                ConceptNote(name="Sampling Distributions", description="Critical regions are defined on the distribution of sample means."),
            ],
            extracted_text=(
                "LECTURE 8 - HYPOTHESIS TESTING\n\n"
                "Step 1. State the hypotheses. H0: the treatment has no effect (mu = 80). H1: the "
                "treatment has an effect (mu not equal to 80).\n"
                "Step 2. Set the criterion. With alpha = .05 two-tailed, the critical region is z > 1.96 "
                "or z < -1.96.\n"
                "Step 3. Collect data and compute the test statistic. z = (M - mu) / SE, where "
                "SE = sigma / sqrt(n).\n"
                "Step 4. Decide. If z falls in the critical region, reject H0.\n\n"
                "Example: A sample of n = 16 students who used a new study app scored M = 86 on a test "
                "with mu = 80, sigma = 12. SE = 12 / 4 = 3. z = (86 - 80) / 3 = 2.00. Since 2.00 > 1.96, "
                "reject H0: the app had a significant effect, z = 2.00, p < .05.\n\n"
                "Errors in hypothesis testing:\n"
                "                 H0 true            H0 false\n"
                "Reject H0        Type I (alpha)     Correct (power)\n"
                "Retain H0        Correct            Type II (beta)\n\n"
                "Lowering alpha to .01 makes a Type I error less likely but a Type II error more likely. "
                "A p-value is the probability of data this extreme IF H0 is true. It is NOT the "
                "probability that H0 is true.\n\n"
                "One-tailed tests put the entire alpha in one tail (critical z = 1.65) and must be "
                "justified before seeing the data."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Formula for the standard error of the mean", back="SE = sigma / sqrt(n)."),
        Flashcard(front="Type I error", back="Rejecting H0 when it is actually true (a false positive); probability = alpha."),
        Flashcard(front="Type II error", back="Failing to reject H0 when it is false (a miss); probability = beta."),
        Flashcard(front="df for an independent-samples t-test", back="n1 + n2 - 2."),
        Flashcard(front="Critical z for alpha = .05, two-tailed", back="+/- 1.96."),
        Flashcard(front="What does r-squared tell you?", back="The proportion of variance in Y explained by its linear relationship with X."),
        Flashcard(front="Which scale of measurement has a true zero?", back="Ratio (e.g. reaction time in ms)."),
        Flashcard(front="What is a p-value?", back="The probability of obtaining results at least this extreme if the null hypothesis is true."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The midterm covers descriptive statistics through the logic of hypothesis testing with "
            "z-scores. Every computation question also asks for an interpretation sentence, so practice "
            "writing the APA-style conclusion along with the number."
        ),
        topics=[
            StudyGuideTopic(
                name="z-scores and the normal distribution",
                importance="Percentile and probability questions from the unit normal table are about a quarter of the exam.",
                concepts=["Converting raw scores to z and back", "Using the unit normal table for proportions",
                          "The 68-95-99.7 rule", "Percentile ranks"],
            ),
            StudyGuideTopic(
                name="Sampling distributions",
                importance="I lost the most points here on the quiz and it underlies every test after the midterm.",
                concepts=["Standard deviation vs standard error", "Central limit theorem",
                          "z for a sample mean uses SE, not sigma"],
            ),
            StudyGuideTopic(
                name="Logic of hypothesis testing",
                importance="Expect a full four-step hypothesis test as the main free-response problem.",
                concepts=["Stating H0 and H1", "Alpha and critical regions",
                          "Type I vs Type II errors", "What a p-value does and does not mean"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Descriptive Statistics", difficulty="easy", days_ago=50, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(
                    question="In a strongly positively skewed distribution, which is typically largest?",
                    options=["Mean", "Median", "Mode", "They are all equal"],
                    correct_answer="Mean",
                    explanation="Extreme high scores pull the mean toward the tail."),
                QuizQuestion(
                    question="Which measure of central tendency is most appropriate for nominal data?",
                    options=["Mode", "Mean", "Median", "Standard deviation"],
                    correct_answer="Mode",
                    explanation="Nominal categories have no order, so only the mode makes sense."),
                QuizQuestion(
                    question="If every score in a data set is increased by 5 points, the standard deviation:",
                    options=["Stays the same", "Increases by 5", "Increases by 25", "Doubles"],
                    correct_answer="Stays the same",
                    explanation="Adding a constant shifts every score equally, so the spread is unchanged."),
                QuizQuestion(
                    question="Why does the sample variance divide by n - 1 instead of n?",
                    options=["To correct the tendency of samples to underestimate population variability",
                             "To make the arithmetic easier", "Because one score is always an outlier",
                             "To convert variance into standard deviation"],
                    correct_answer="To correct the tendency of samples to underestimate population variability",
                    explanation="Using n - 1 (degrees of freedom) gives an unbiased estimate of the population variance."),
            ],
        ),
        QuizAttempt(
            concept="Sampling Distributions", difficulty="medium", days_ago=29, correct=[2, 3],
            questions=[
                QuizQuestion(
                    question="A population has mu = 100 and sigma = 15. What is the standard error for samples of n = 25?",
                    options=["3", "15", "0.6", "5"],
                    correct_answer="3",
                    explanation="SE = 15 / sqrt(25) = 15 / 5 = 3."),
                QuizQuestion(
                    question="Using the same population, what is the z-score for a sample mean of 106 (n = 25)?",
                    options=["2.00", "0.40", "6.00", "1.06"],
                    correct_answer="2.00",
                    explanation="z = (106 - 100) / 3 = 2.00. Using sigma instead of SE gives the wrong 0.40."),
                QuizQuestion(
                    question="As sample size increases, the standard error:",
                    options=["Decreases", "Increases", "Stays the same", "Equals the population SD"],
                    correct_answer="Decreases",
                    explanation="SE = sigma / sqrt(n), so larger n gives a smaller SE."),
                QuizQuestion(
                    question="The central limit theorem says the distribution of sample means approaches normal when:",
                    options=["The sample size is large", "The population is normal only",
                             "The standard deviation is small", "The mean equals the median"],
                    correct_answer="The sample size is large",
                    explanation="For large n (about 30 or more) the sampling distribution is approximately normal regardless of population shape."),
            ],
        ),
        QuizAttempt(
            concept="Independent-Samples t-Test", difficulty="hard", days_ago=8, correct=[1],
            questions=[
                QuizQuestion(
                    question="A study compares 20 participants in a control group with 20 in a treatment group. The df for an independent-samples t-test is:",
                    options=["38", "39", "19", "40"],
                    correct_answer="38",
                    explanation="df = n1 + n2 - 2 = 20 + 20 - 2 = 38."),
                QuizQuestion(
                    question="Which assumption does the pooled-variance t-test make?",
                    options=["Homogeneity of variance", "Equal means in both populations",
                             "Sample sizes larger than 100", "A correlation between groups"],
                    correct_answer="Homogeneity of variance",
                    explanation="Pooling assumes both populations share the same variance (check with Levene's test)."),
                QuizQuestion(
                    question="Group means differ by 6 points and the pooled SD is 12. Cohen's d is:",
                    options=["0.50", "2.00", "0.20", "6.00"],
                    correct_answer="0.50",
                    explanation="d = mean difference / pooled SD = 6 / 12 = 0.50, a medium effect."),
                QuizQuestion(
                    question="With everything else equal, increasing the sample size in each group will:",
                    options=["Make it more likely to reject H0 for a real effect", "Increase Cohen's d",
                             "Increase the standard error", "Increase alpha"],
                    correct_answer="Make it more likely to reject H0 for a real effect",
                    explanation="Larger n shrinks the standard error and raises power; d is unaffected."),
            ],
        ),
    ],
    session=TutorSession(
        name="Alpha, beta and power",
        topic="Type I and Type II Errors",
        mode="socratic",
        summary_bullets=[
            "A Type I error rejects a true null; its probability is alpha.",
            "A Type II error misses a real effect; its probability is beta, and power = 1 - beta.",
            "Lowering alpha trades fewer false positives for more misses unless n increases.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I always mix up Type I and Type II errors. Is there a way to actually remember which is which?")),
            ChatMessage(role="assistant", content=(
                "Let's anchor it to a concrete case. Picture a COVID test where the null hypothesis is "
                "'this person is not infected.' If the test says positive but the person is healthy, "
                "did we wrongly reject the null or wrongly keep it?")),
            ChatMessage(role="user", content="We rejected it when it was true. So that's a false positive."),
            ChatMessage(role="assistant", content=(
                "Right, and that is a Type I error, with probability alpha. A trick: Type I is the first "
                "mistake a hasty researcher makes, claiming an effect that is not there. Now, what would "
                "a Type II error be in the COVID example?")),
            ChatMessage(role="user", content=(
                "The test says negative but the person actually has it. So a miss. And that's beta?")),
            ChatMessage(role="assistant", content=(
                "Exactly. Power is 1 - beta, the chance of catching an effect that really exists. Here is "
                "the trade-off that shows up on exams: if you drop alpha from .05 to .01 without changing "
                "anything else, you make false positives rarer, but your critical region shrinks, so "
                "beta goes up and power goes down. The usual fix is a bigger sample, which is exactly the "
                "question your proposal feedback asked about.")),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS PS 231 — Physiological Psychology
# ---------------------------------------------------------------------------

PS231 = Course(
    code="CAS PS 231",
    name="Physiological Psychology",
    department="Psychological and Brain Sciences",
    nickname="Physio Psych",
    color="#2FA38B",
    concepts=[
        Concept(name="Neuron Structure", mastery=0.96,
                description="Dendrites, soma, axon hillock, myelinated axon and terminals; glial cells "
                            "including oligodendrocytes, Schwann cells and astrocytes."),
        Concept(name="Neuroanatomy: Brain Regions", mastery=0.8,
                description="Lobes of the cortex, the limbic system, thalamus, hypothalamus, basal "
                            "ganglia, cerebellum and brainstem."),
        Concept(name="Resting Membrane Potential", mastery=0.77,
                description="About -70 mV, maintained by K+ leak channels and the Na+/K+ pump; the "
                            "balance of diffusion and electrostatic pressure."),
        Concept(name="Action Potential", mastery=0.69,
                description="Threshold near -55 mV, voltage-gated Na+ then K+ channels, refractory "
                            "periods, and saltatory conduction at nodes of Ranvier."),
        Concept(name="Synaptic Transmission", mastery=0.57,
                description="Ca2+-triggered vesicle release, ionotropic vs metabotropic receptors, EPSPs, "
                            "IPSPs and spatial and temporal summation."),
        Concept(name="Neurotransmitter Systems", mastery=0.41,
                description="Dopamine, serotonin, norepinephrine, acetylcholine, GABA and glutamate: "
                            "their source nuclei, pathways and drug targets."),
        Concept(name="Visual System", mastery=0.3,
                description="Rods and cones, retinal ganglion cells, the optic chiasm, LGN and V1, and "
                            "the dorsal and ventral streams."),
        Concept(name="Hypothalamus and Motivated Behavior", mastery=0.14,
                description="Hunger and satiety signals (ghrelin, leptin), the arcuate nucleus, and "
                            "lateral vs ventromedial hypothalamus lesion studies."),
        Concept(name="Sleep and Circadian Rhythms", mastery=0.05,
                description="The suprachiasmatic nucleus as master clock, melatonin, and the neural "
                            "control of REM and non-REM sleep."),
        Concept(name="Synaptic Plasticity and LTP", mastery=0.0,
                description="Long-term potentiation in the hippocampus, NMDA receptors as coincidence "
                            "detectors, and AMPA receptor insertion."),
    ],
    edges=[
        Edge(source="Neuron Structure", target="Resting Membrane Potential", relationship="prerequisite", strength=0.8),
        Edge(source="Resting Membrane Potential", target="Action Potential", relationship="prerequisite", strength=0.9),
        Edge(source="Action Potential", target="Synaptic Transmission", relationship="prerequisite", strength=0.85),
        Edge(source="Synaptic Transmission", target="Neurotransmitter Systems", relationship="prerequisite", strength=0.85),
        Edge(source="Synaptic Transmission", target="Synaptic Plasticity and LTP", relationship="builds_on", strength=0.8),
        Edge(source="Neuroanatomy: Brain Regions", target="Hypothalamus and Motivated Behavior", relationship="prerequisite", strength=0.7),
        Edge(source="Neuroanatomy: Brain Regions", target="Visual System", relationship="related", strength=0.6),
        Edge(source="Hypothalamus and Motivated Behavior", target="Sleep and Circadian Rhythms", relationship="related", strength=0.55),
    ],
    mastery_events=[
        MasteryEvent(concept="Resting Membrane Potential", delta=0.1, reason="Quiz 2 on membrane potentials"),
        MasteryEvent(concept="Neurotransmitter Systems", delta=-0.08, reason="Mixed up dopamine pathways on quiz"),
        MasteryEvent(concept="Neurotransmitter Systems", delta=0.06, reason="Tutor session on DA and 5-HT pathways"),
        MasteryEvent(concept="Neuroanatomy: Brain Regions", delta=0.12, reason="Phineas Gage case write-up"),
    ],
    categories=[
        Category(name="Exams", weight=0.70),
        Category(name="Quizzes", weight=0.15, drop_lowest=1),
        Category(name="Case Write-ups", weight=0.15),
    ],
    assignments=[
        Assignment(title="Quiz 1: Neurons and Glia", category="Quizzes", type="quiz",
                   due_offset_days=11, points_possible=15, points_earned=14),
        Assignment(title="Quiz 2: Membrane and Action Potentials", category="Quizzes", type="quiz",
                   due_offset_days=25, points_possible=15, points_earned=12),
        Assignment(title="Case Write-up: Phineas Gage and the Frontal Lobes", category="Case Write-ups",
                   type="homework", due_offset_days=35, points_possible=25, points_earned=22),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=46, points_possible=100, points_earned=81, is_midterm=True),
        Assignment(title="Quiz 3: Neurotransmitter Systems", category="Quizzes", type="quiz",
                   due_offset_days=60, points_possible=15, points_earned=10),
        Assignment(title="Case Write-up: Patient H.M. and Memory", category="Case Write-ups",
                   type="homework", due_offset_days=82, points_possible=25),
        Assignment(title="Quiz 4: Visual Pathways", category="Quizzes", type="quiz",
                   due_offset_days=94, points_possible=15),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=113, points_possible=150),
    ],
    notes=[
        Note(
            title="Action potential step by step",
            tags=["neurophysiology", "midterm"],
            concepts=["Action Potential", "Resting Membrane Potential"],
            body=(
                "## Resting: about -70 mV\n"
                "- Lots of K+ inside, Na+ outside (Na+/K+ pump: 3 Na+ out, 2 K+ in)\n"
                "- Membrane at rest is mostly permeable to K+ -> close to K+'s equilibrium potential\n\n"
                "## The spike\n"
                "1. EPSPs summate at the **axon hillock** and reach threshold (~-55 mV)\n"
                "2. **Voltage-gated Na+ channels** open -> Na+ rushes in -> depolarization to ~+40 mV\n"
                "3. Na+ channels **inactivate**; voltage-gated K+ channels open -> K+ flows out -> "
                "repolarization\n"
                "4. K+ channels close slowly -> **hyperpolarization** (undershoot)\n"
                "5. Pump + leak channels restore resting state\n\n"
                "## Refractory periods\n"
                "- Absolute: Na+ channels inactivated, NO stimulus can fire another AP\n"
                "- Relative: needs a stronger-than-normal stimulus (during hyperpolarization)\n"
                "- This is why APs travel one way down the axon\n\n"
                "## All-or-none\n"
                "Intensity is coded by **firing rate**, not AP size.\n\n"
                "Myelin -> saltatory conduction, jumping node to node (nodes of Ranvier). MS = "
                "demyelination in the CNS."
            ),
        ),
        Note(
            title="Neurotransmitter cheat sheet",
            tags=["neurotransmitters", "drugs", "quiz 3"],
            concepts=["Neurotransmitter Systems", "Synaptic Transmission"],
            body=(
                "| NT | Main source | Notes |\n"
                "|---|---|---|\n"
                "| Dopamine | substantia nigra, VTA | nigrostriatal = movement (Parkinson's); mesolimbic = reward |\n"
                "| Serotonin | raphe nuclei | mood, sleep; SSRIs block SERT reuptake |\n"
                "| Norepinephrine | locus coeruleus | arousal, attention |\n"
                "| Acetylcholine | nucleus basalis, NMJ | memory (Alzheimer's), muscle contraction |\n"
                "| GABA | interneurons everywhere | main inhibitory; GABA-A = Cl- channel; benzos boost it |\n"
                "| Glutamate | everywhere | main excitatory; AMPA + NMDA receptors |\n\n"
                "## Agonist vs antagonist\n"
                "- Agonist mimics/enhances (e.g. L-DOPA raises dopamine synthesis)\n"
                "- Antagonist blocks (e.g. haloperidol blocks D2 receptors; curare blocks nicotinic ACh "
                "receptors)\n\n"
                "Missed on quiz: I said the mesolimbic pathway runs from substantia nigra. WRONG: "
                "mesolimbic starts in the **VTA** and goes to the nucleus accumbens."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ps231-syllabus.pdf",
            category="syllabus",
            summary=(
                "PS 231 Physiological Psychology syllabus: cellular neuroscience before the midterm, then "
                "sensory systems, motivation, sleep and memory, with quizzes and two clinical case write-ups."
            ),
            concept_notes=[
                ConceptNote(name="Neuron Structure", description="Opening unit on cells of the nervous system."),
                ConceptNote(name="Action Potential", description="Core of the midterm."),
                ConceptNote(name="Visual System", description="First sensory system after the midterm, quiz 4."),
                ConceptNote(name="Synaptic Plasticity and LTP", description="Final unit, linked to the H.M. case write-up."),
            ],
            extracted_text=(
                "PS 231 PHYSIOLOGICAL PSYCHOLOGY\n"
                "Prerequisite: PS 101 (BI 107 or BI 108 recommended)\n"
                "Text: Carlson & Birkett, Physiology of Behavior, 13th ed.\n\n"
                "COURSE DESCRIPTION\n"
                "How does the nervous system produce behavior? We start at the level of single neurons "
                "-- membrane potentials, action potentials and synaptic transmission -- and the drugs "
                "that act on them. We then move to systems: neuroanatomy, vision, motivated behaviors "
                "such as eating, sleep and biological rhythms, and the neural basis of learning and "
                "memory.\n\n"
                "GRADING\n"
                "Midterm 30% | Final (cumulative) 40% | Quizzes 15% (lowest dropped) | Case "
                "write-ups 15%\n\n"
                "CASE WRITE-UPS\n"
                "Two 3-page papers analyzing a classic clinical case using course material. Case 1: "
                "Phineas Gage (1848), the railroad foreman whose left frontal lobe was pierced by a "
                "tamping iron. Case 2: Henry Molaison (H.M.), whose bilateral medial temporal lobe "
                "resection in 1953 left him with profound anterograde amnesia. Each write-up must "
                "identify the damaged structures, the resulting deficits, and what the case taught us "
                "about brain function.\n\n"
                "OFFICE HOURS\n"
                "Thursdays 3-5 pm in the Psychological and Brain Sciences building. Brain models are "
                "available in the department lounge for review before exams."
            ),
        ),
        Document(
            file_name="ps231-lecture-synaptic-transmission.pdf",
            category="lecture_notes",
            summary=(
                "Lecture notes on chemical synaptic transmission: vesicle release, receptor types, "
                "postsynaptic potentials, summation and termination by reuptake or enzymes."
            ),
            concept_notes=[
                ConceptNote(name="Synaptic Transmission", description="Sequence of events from AP arrival to postsynaptic response."),
                ConceptNote(name="Neurotransmitter Systems", description="Termination mechanisms differ by transmitter."),
                ConceptNote(name="Action Potential", description="AP arrival opens voltage-gated Ca2+ channels."),
            ],
            extracted_text=(
                "LECTURE 6 - SYNAPTIC TRANSMISSION\n\n"
                "1. An action potential reaches the terminal button and opens voltage-gated Ca2+ "
                "channels. Ca2+ influx triggers synaptic vesicles to fuse with the presynaptic membrane "
                "(SNARE proteins) and release neurotransmitter into the synaptic cleft by exocytosis.\n\n"
                "2. Neurotransmitter binds postsynaptic receptors.\n"
                "   Ionotropic receptors are ligand-gated ion channels: fast, short-lasting (e.g. "
                "nicotinic ACh, AMPA, GABA-A).\n"
                "   Metabotropic receptors act through G proteins and second messengers: slower, "
                "longer-lasting (e.g. muscarinic ACh, D2, most 5-HT receptors).\n\n"
                "3. Postsynaptic potentials. Na+ influx -> depolarizing EPSP. Cl- influx or K+ efflux "
                "-> hyperpolarizing IPSP. PSPs are graded and decay with distance.\n\n"
                "4. Integration. Spatial summation combines PSPs from different synapses; temporal "
                "summation combines PSPs arriving in rapid succession at one synapse. If the net "
                "depolarization at the axon hillock reaches threshold, the neuron fires.\n\n"
                "5. Termination. Reuptake by transporters (dopamine via DAT, serotonin via SERT) or "
                "enzymatic deactivation (acetylcholinesterase breaks ACh into choline and acetate).\n\n"
                "Drug examples: cocaine blocks DAT; fluoxetine (Prozac) blocks SERT; nerve agents "
                "inhibit acetylcholinesterase."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Approximate resting membrane potential of a neuron", back="About -70 mV."),
        Flashcard(front="What triggers neurotransmitter release?", back="Ca2+ entry through voltage-gated calcium channels at the terminal."),
        Flashcard(front="Ionotropic vs metabotropic receptors", back="Ionotropic: ligand-gated ion channel, fast. Metabotropic: G-protein coupled, slower and longer-lasting."),
        Flashcard(front="Which pathway degenerates in Parkinson's disease?", back="The nigrostriatal dopamine pathway (substantia nigra to striatum)."),
        Flashcard(front="Where do optic nerve fibers cross?", back="At the optic chiasm; fibers from the nasal half of each retina cross to the opposite side."),
        Flashcard(front="What did H.M. lose after his surgery?", back="The ability to form new declarative memories (anterograde amnesia); procedural learning like mirror tracing was spared."),
        Flashcard(front="Master circadian clock", back="The suprachiasmatic nucleus (SCN) of the hypothalamus."),
        Flashcard(front="Why is the NMDA receptor a coincidence detector?", back="It needs glutamate binding AND postsynaptic depolarization to expel its Mg2+ block."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The midterm covers cellular neuroscience and neuroanatomy: neurons and glia, membrane and "
            "action potentials, synaptic transmission, neurotransmitters and drugs, and major brain "
            "structures. Expect diagrams to label and sequence-of-events questions."
        ),
        topics=[
            StudyGuideTopic(
                name="Electrical signaling",
                importance="Sequence questions on the action potential are worth the most points on the exam.",
                concepts=["Ionic basis of the resting potential", "Voltage-gated Na+ and K+ channel timing",
                          "Absolute vs relative refractory period", "Saltatory conduction"],
            ),
            StudyGuideTopic(
                name="Chemical signaling",
                importance="Drug mechanism questions require knowing exactly where each step can be blocked.",
                concepts=["Ca2+-dependent vesicle release", "Ionotropic vs metabotropic receptors",
                          "EPSPs, IPSPs and summation", "Reuptake vs enzymatic deactivation"],
            ),
            StudyGuideTopic(
                name="Neuroanatomy",
                importance="A blank brain diagram to label appears on every exam in this course.",
                concepts=["Cortical lobes and their functions", "Limbic system structures",
                          "Basal ganglia and cerebellum in movement", "Planes of section"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Action Potential", difficulty="medium", days_ago=36, correct=[0, 1, 3],
            questions=[
                QuizQuestion(
                    question="The rising phase of the action potential is caused by:",
                    options=["Na+ entering through voltage-gated channels", "K+ leaving through leak channels",
                             "Cl- entering the cell", "The Na+/K+ pump speeding up"],
                    correct_answer="Na+ entering through voltage-gated channels",
                    explanation="Opening of voltage-gated Na+ channels drives rapid depolarization."),
                QuizQuestion(
                    question="During the absolute refractory period, a second action potential:",
                    options=["Cannot be generated", "Requires a stronger stimulus", "Is larger than normal", "Travels backward"],
                    correct_answer="Cannot be generated",
                    explanation="Voltage-gated Na+ channels are inactivated and cannot reopen yet."),
                QuizQuestion(
                    question="Saltatory conduction refers to the action potential:",
                    options=["Jumping between nodes of Ranvier", "Spreading into dendrites",
                             "Summing at the axon hillock", "Being converted to a chemical signal"],
                    correct_answer="Jumping between nodes of Ranvier",
                    explanation="Myelin insulates the internodes, so the AP regenerates only at the nodes."),
                QuizQuestion(
                    question="A stronger stimulus is encoded by:",
                    options=["A higher firing rate", "A larger action potential", "A longer action potential", "A slower action potential"],
                    correct_answer="A higher firing rate",
                    explanation="Action potentials are all-or-none, so intensity is coded by frequency."),
            ],
        ),
        QuizAttempt(
            concept="Neurotransmitter Systems", difficulty="hard", days_ago=17, correct=[1, 3],
            questions=[
                QuizQuestion(
                    question="The mesolimbic dopamine pathway projects from the:",
                    options=["Ventral tegmental area to the nucleus accumbens",
                             "Substantia nigra to the striatum", "Raphe nuclei to the cortex",
                             "Locus coeruleus to the hippocampus"],
                    correct_answer="Ventral tegmental area to the nucleus accumbens",
                    explanation="Substantia nigra to striatum is the nigrostriatal (motor) pathway."),
                QuizQuestion(
                    question="Fluoxetine (Prozac) increases synaptic serotonin by:",
                    options=["Blocking serotonin reuptake", "Stimulating serotonin synthesis",
                             "Inhibiting MAO", "Blocking 5-HT receptors"],
                    correct_answer="Blocking serotonin reuptake",
                    explanation="It is a selective serotonin reuptake inhibitor acting on SERT."),
                QuizQuestion(
                    question="Most norepinephrine-releasing neurons in the brain originate in the:",
                    options=["Locus coeruleus", "Raphe nuclei", "Nucleus basalis", "Ventral tegmental area"],
                    correct_answer="Locus coeruleus",
                    explanation="The locus coeruleus in the pons supplies norepinephrine to most of the forebrain."),
                QuizQuestion(
                    question="Benzodiazepines reduce anxiety mainly by:",
                    options=["Enhancing GABA-A receptor activity", "Blocking glutamate receptors",
                             "Increasing dopamine release", "Inhibiting acetylcholinesterase"],
                    correct_answer="Enhancing GABA-A receptor activity",
                    explanation="They bind a modulatory site and increase Cl- channel opening when GABA binds."),
            ],
        ),
    ],
    session=TutorSession(
        name="Dopamine and serotonin pathways",
        topic="Neurotransmitter Systems",
        mode="expository",
        summary_bullets=[
            "Mesolimbic dopamine runs from the VTA to the nucleus accumbens (reward).",
            "Nigrostriatal dopamine runs from the substantia nigra to the striatum (movement).",
            "Serotonin comes from the raphe nuclei; SSRIs block SERT reuptake.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I got the dopamine pathway question wrong on quiz 3. How do I keep mesolimbic, "
                "mesocortical and nigrostriatal straight?")),
            ChatMessage(role="assistant", content=(
                "The names tell you the route. 'Meso' means the midbrain, specifically the ventral "
                "tegmental area (VTA). Mesolimbic: VTA to limbic targets like the nucleus accumbens, "
                "central to reward and reinforcement. Mesocortical: VTA to the prefrontal cortex, "
                "involved in working memory and planning. Nigrostriatal: substantia nigra to the "
                "striatum (caudate and putamen), part of the basal ganglia motor loop. That last one is "
                "the pathway that degenerates in Parkinson's disease.")),
            ChatMessage(role="user", content=(
                "Ok that helps. So why does L-DOPA help Parkinson's but not just giving dopamine?")),
            ChatMessage(role="assistant", content=(
                "Dopamine itself cannot cross the blood-brain barrier, but its precursor L-DOPA can. "
                "Surviving nigrostriatal neurons convert L-DOPA to dopamine using DOPA decarboxylase, "
                "boosting release in the striatum. It is often paired with carbidopa, which blocks that "
                "conversion outside the brain so more L-DOPA reaches its target.")),
            ChatMessage(role="user", content="And serotonin is the raphe nuclei, and Prozac blocks reuptake?"),
            ChatMessage(role="assistant", content=(
                "Yes. Raphe nuclei in the brainstem project widely to the forebrain. Fluoxetine blocks "
                "the serotonin transporter (SERT), so serotonin stays in the cleft longer. For the final, "
                "practice predicting a drug's effect from where it acts: synthesis, release, receptor, or "
                "reuptake.")),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS PS 241 — Developmental Psychology
# ---------------------------------------------------------------------------

PS241 = Course(
    code="CAS PS 241",
    name="Developmental Psychology",
    department="Psychological and Brain Sciences",
    nickname="Dev Psych",
    color="#F2A541",
    concepts=[
        Concept(name="Piaget's Stages of Cognitive Development", mastery=0.96,
                description="Sensorimotor, preoperational, concrete operational and formal operational "
                            "stages; object permanence, conservation and egocentrism."),
        Concept(name="Attachment Theory", mastery=0.83,
                description="Bowlby's internal working models, Harlow's contact comfort, and Ainsworth's "
                            "Strange Situation attachment classifications."),
        Concept(name="Erikson's Psychosocial Stages", mastery=0.76,
                description="Eight stages defined by psychosocial crises, from trust vs mistrust to "
                            "integrity vs despair."),
        Concept(name="Theory of Mind", mastery=0.71,
                description="Understanding that others have beliefs that can differ from reality; the "
                            "Sally-Anne false-belief task, typically passed around age 4."),
        Concept(name="Vygotsky's Sociocultural Theory", mastery=0.66,
                description="The zone of proximal development, scaffolding, and private speech as a tool "
                            "for self-regulation."),
        Concept(name="Language Acquisition", mastery=0.52,
                description="Babbling, perceptual narrowing of phoneme discrimination by about 10-12 months, "
                            "the vocabulary spurt, and overregularization."),
        Concept(name="Prenatal Development and Teratogens", mastery=0.39,
                description="Germinal, embryonic and fetal periods; critical periods and teratogens such "
                            "as alcohol and thalidomide."),
        Concept(name="Infant Research Methods", mastery=0.28,
                description="Habituation, preferential looking and violation-of-expectation paradigms "
                            "used to study what preverbal infants know."),
        Concept(name="Adolescent Development", mastery=0.09,
                description="Puberty, the imaginary audience and personal fable, prefrontal maturation "
                            "and identity formation (Marcia's statuses)."),
        Concept(name="Moral Development", mastery=0.0,
                description="Kohlberg's preconventional, conventional and postconventional levels, the "
                            "Heinz dilemma, and Gilligan's critique."),
    ],
    edges=[
        Edge(source="Piaget's Stages of Cognitive Development", target="Theory of Mind", relationship="related", strength=0.6),
        Edge(source="Piaget's Stages of Cognitive Development", target="Vygotsky's Sociocultural Theory", relationship="related", strength=0.7),
        Edge(source="Infant Research Methods", target="Piaget's Stages of Cognitive Development", relationship="related", strength=0.55),
        Edge(source="Piaget's Stages of Cognitive Development", target="Moral Development", relationship="builds_on", strength=0.65),
        Edge(source="Attachment Theory", target="Erikson's Psychosocial Stages", relationship="related", strength=0.55),
        Edge(source="Erikson's Psychosocial Stages", target="Adolescent Development", relationship="builds_on", strength=0.7),
        Edge(source="Vygotsky's Sociocultural Theory", target="Language Acquisition", relationship="related", strength=0.5),
        Edge(source="Prenatal Development and Teratogens", target="Infant Research Methods", relationship="related", strength=0.35),
    ],
    mastery_events=[
        MasteryEvent(concept="Piaget's Stages of Cognitive Development", delta=0.12, reason="Perfect score on the Piaget quiz"),
        MasteryEvent(concept="Theory of Mind", delta=0.1, reason="Response paper on the Sally-Anne task"),
        MasteryEvent(concept="Prenatal Development and Teratogens", delta=-0.07, reason="Missed critical-period timing on quiz"),
        MasteryEvent(concept="Infant Research Methods", delta=0.08, reason="Tutor session on habituation designs"),
    ],
    categories=[
        Category(name="Exams", weight=0.60),
        Category(name="Response Papers", weight=0.25),
        Category(name="Observation Project", weight=0.15),
    ],
    assignments=[
        Assignment(title="Response Paper 1: Harlow's Monkeys and Contact Comfort", category="Response Papers",
                   type="homework", due_offset_days=16, points_possible=20, points_earned=19),
        Assignment(title="Response Paper 2: The Strange Situation Across Cultures", category="Response Papers",
                   type="homework", due_offset_days=30, points_possible=20, points_earned=18),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=45, points_possible=100, points_earned=88, is_midterm=True),
        Assignment(title="Child Observation Proposal", category="Observation Project",
                   type="project", due_offset_days=55, points_possible=15, points_earned=14),
        Assignment(title="Response Paper 3: False-Belief and Theory of Mind", category="Response Papers",
                   type="homework", due_offset_days=64, points_possible=20, points_earned=17),
        Assignment(title="Child Observation Final Report", category="Observation Project",
                   type="project", due_offset_days=92, points_possible=50),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=110, points_possible=100),
    ],
    notes=[
        Note(
            title="Piaget's stages - with the classic tasks",
            tags=["cognitive development", "midterm"],
            concepts=["Piaget's Stages of Cognitive Development", "Infant Research Methods"],
            body=(
                "## 1. Sensorimotor (0-2)\n"
                "- Learning through senses + actions; circular reactions\n"
                "- **Object permanence** emerges ~8 months; **A-not-B error** at 8-12 months\n"
                "- Critique: Baillargeon's violation-of-expectation studies suggest earlier knowledge "
                "(~3.5-5 months)\n\n"
                "## 2. Preoperational (2-7)\n"
                "- Symbolic thought, pretend play\n"
                "- **Egocentrism**: three mountains task\n"
                "- Fails **conservation** (liquid in tall vs wide glass): centration + no reversibility\n\n"
                "## 3. Concrete operational (7-11)\n"
                "- Conservation, classification, seriation\n"
                "- Logic works on concrete objects, not hypotheticals\n\n"
                "## 4. Formal operational (11+)\n"
                "- Abstract and hypothetical-deductive reasoning (pendulum task)\n"
                "- Not everyone reaches it in every domain\n\n"
                "**Big critiques:** underestimated infants; stages less uniform than claimed; ignored "
                "culture (-> Vygotsky)."
            ),
        ),
        Note(
            title="Strange Situation classifications",
            tags=["attachment", "response paper"],
            concepts=["Attachment Theory", "Erikson's Psychosocial Stages"],
            body=(
                "## Ainsworth's Strange Situation (12-18 months)\n"
                "8 short episodes: caregiver and infant in a playroom, a stranger enters, caregiver "
                "leaves twice and returns. The key measure is behavior at **reunion**.\n\n"
                "| Type | Approx. % (US samples) | Reunion behavior |\n"
                "|---|---|---|\n"
                "| Secure | ~60-65% | distressed when caregiver leaves, comforted on return |\n"
                "| Insecure-avoidant | ~20% | little distress, ignores caregiver on return |\n"
                "| Insecure-resistant | ~10-15% | very distressed, clingy but angry on return |\n"
                "| Disorganized | ~5-10% | contradictory, freezing (Main & Solomon) |\n\n"
                "### For response paper 2\n"
                "- German samples (Grossmann) had more avoidant infants; parents valued early independence.\n"
                "- Japanese samples had more resistant infants; babies were rarely left with strangers, so "
                "the procedure itself was more stressful.\n"
                "- Argument: the procedure may not measure the same thing in every culture.\n\n"
                "Link to Erikson: secure attachment ~ resolving **trust vs mistrust** in infancy."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ps241-syllabus.pdf",
            category="syllabus",
            summary=(
                "PS 241 Developmental Psychology syllabus: development from conception through adolescence, "
                "with three response papers, a child observation project and two exams."
            ),
            concept_notes=[
                ConceptNote(name="Prenatal Development and Teratogens", description="First unit of the course."),
                ConceptNote(name="Piaget's Stages of Cognitive Development", description="Central theory for the midterm."),
                ConceptNote(name="Theory of Mind", description="Social cognition unit, response paper 3."),
                ConceptNote(name="Adolescent Development", description="Final unit before the final exam."),
            ],
            extracted_text=(
                "PS 241 DEVELOPMENTAL PSYCHOLOGY\n"
                "Prerequisite: PS 101\n"
                "Text: Siegler, Saffran, Gershoff & Eisenberg, How Children Develop, 6th ed.\n\n"
                "DESCRIPTION\n"
                "A survey of human development from conception through adolescence. We examine "
                "physical, cognitive, linguistic, social and emotional development and the major "
                "theories that explain them (Piaget, Vygotsky, information processing, attachment "
                "theory, Erikson). Throughout, we focus on how researchers study children who cannot "
                "yet tell us what they know.\n\n"
                "UNITS\n"
                "1. Prenatal development, birth and the newborn\n"
                "2. Infant perception and research methods\n"
                "3. Theories of cognitive development -- MIDTERM\n"
                "4. Language development\n"
                "5. Attachment and emotional development\n"
                "6. Social cognition and theory of mind\n"
                "7. Moral development and adolescence\n\n"
                "GRADING\n"
                "Midterm 25% | Final 35% | Response papers (3 x 20 pts) 25% | Child observation "
                "project 15%\n\n"
                "OBSERVATION PROJECT\n"
                "Observe a child between 2 and 10 years old for at least two hours in a naturalistic "
                "setting (with written parental permission) and relate what you see to at least two "
                "theories from the course. The proposal is due before the observation; the final "
                "report is 6-8 pages."
            ),
        ),
        Document(
            file_name="ps241-lecture-infant-cognition.pdf",
            category="lecture_notes",
            summary=(
                "Lecture notes on how researchers study infant cognition: habituation, preferential "
                "looking and violation of expectation, with Baillargeon's drawbridge study as the key example."
            ),
            concept_notes=[
                ConceptNote(name="Infant Research Methods", description="Three core paradigms and the logic behind each."),
                ConceptNote(name="Piaget's Stages of Cognitive Development", description="Evidence that object permanence appears earlier than Piaget claimed."),
                ConceptNote(name="Language Acquisition", description="High-amplitude sucking used to test phoneme discrimination."),
            ],
            extracted_text=(
                "LECTURE 5 - STUDYING INFANT MINDS\n\n"
                "Problem: infants cannot follow instructions or answer questions. Researchers instead "
                "measure behaviors infants control well: looking time, sucking rate and heart rate.\n\n"
                "Preferential looking (Fantz, 1961): show two stimuli side by side. If the infant "
                "looks longer at one, they can tell the two apart. Newborns prefer patterned stimuli "
                "and face-like configurations.\n\n"
                "Habituation / dishabituation: present a stimulus repeatedly until looking time drops "
                "(habituation), then present a new one. Recovery of looking (dishabituation) shows the "
                "infant perceives the difference. The same logic underlies high-amplitude sucking "
                "studies of phoneme discrimination.\n\n"
                "Violation of expectation: infants look longer at events that seem impossible. "
                "Baillargeon (1985): 5-month-olds habituated to a screen rotating 180 degrees like a "
                "drawbridge. A box was then placed behind it. Infants looked longer when the screen "
                "appeared to pass through the hidden box (impossible event) than when it stopped at "
                "112 degrees (possible event), suggesting they represented the box even though they "
                "could not see it -- object permanence months earlier than Piaget proposed.\n\n"
                "Critique: longer looking might reflect perceptual novelty rather than surprise "
                "(Bogartz). Interpreting looking time is the central debate in this literature."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="A-not-B error", back="An 8-12 month old keeps searching at location A after watching a toy hidden at B."),
        Flashcard(front="Four Strange Situation classifications", back="Secure, insecure-avoidant, insecure-resistant (ambivalent), disorganized."),
        Flashcard(front="Zone of proximal development", back="The gap between what a child can do alone and what they can do with guidance (Vygotsky)."),
        Flashcard(front="Most vulnerable period for major structural birth defects", back="The embryonic period, about weeks 3-8, when organs form."),
        Flashcard(front="Age most children pass the Sally-Anne false-belief task", back="Around 4 years old."),
        Flashcard(front="Erikson's adolescent crisis", back="Identity vs role confusion."),
        Flashcard(front="Perceptual narrowing in speech", back="Infants discriminate non-native phonemes at 6-8 months but mostly lose this by 10-12 months (Werker & Tees)."),
        Flashcard(front="Conservation", back="Understanding that quantity stays the same despite changes in shape; typically achieved in the concrete operational stage."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The midterm covers prenatal development, infant perception and research methods, and the "
            "major theories of cognitive development. Expect to compare Piaget and Vygotsky and to "
            "explain how a looking-time study supports a claim about infant knowledge."
        ),
        topics=[
            StudyGuideTopic(
                name="Theories of cognitive development",
                importance="The essay question will almost certainly compare Piaget and Vygotsky.",
                concepts=["Piaget's four stages and their hallmark tasks", "Assimilation and accommodation",
                          "Zone of proximal development and scaffolding", "Critiques of stage theory"],
            ),
            StudyGuideTopic(
                name="Infant research methods",
                importance="Multiple questions give a study description and ask what the infants' looking pattern shows.",
                concepts=["Preferential looking", "Habituation and dishabituation",
                          "Violation of expectation (Baillargeon's drawbridge)", "Looking-time interpretation debates"],
            ),
            StudyGuideTopic(
                name="Prenatal development",
                importance="This is my weakest unit and accounts for roughly a fifth of the exam.",
                concepts=["Germinal, embryonic and fetal periods", "Critical periods for teratogen exposure",
                          "Fetal alcohol spectrum disorder", "Thalidomide and limb defects"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Piaget's Stages of Cognitive Development", difficulty="easy", days_ago=47, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(
                    question="A 4-year-old says a tall thin glass holds more juice than a short wide glass with the same amount. She has not yet mastered:",
                    options=["Conservation", "Object permanence", "Abstract reasoning", "Symbolic thought"],
                    correct_answer="Conservation",
                    explanation="Preoperational children center on height and cannot mentally reverse the pour."),
                QuizQuestion(
                    question="Which stage is characterized by hypothetical-deductive reasoning?",
                    options=["Formal operational", "Concrete operational", "Preoperational", "Sensorimotor"],
                    correct_answer="Formal operational",
                    explanation="From about age 11, adolescents can reason systematically about hypotheticals."),
                QuizQuestion(
                    question="The three mountains task was designed to test:",
                    options=["Egocentrism", "Conservation", "Object permanence", "Seriation"],
                    correct_answer="Egocentrism",
                    explanation="Preoperational children tend to report their own view as the doll's view."),
                QuizQuestion(
                    question="Changing an existing scheme to fit new information is called:",
                    options=["Accommodation", "Assimilation", "Equilibration", "Centration"],
                    correct_answer="Accommodation",
                    explanation="Assimilation fits new information into an existing scheme; accommodation changes the scheme."),
            ],
        ),
        QuizAttempt(
            concept="Attachment Theory", difficulty="medium", days_ago=26, correct=[0, 1, 3],
            questions=[
                QuizQuestion(
                    question="Harlow's infant monkeys spent most of their time with the cloth mother because:",
                    options=["Contact comfort matters more than feeding for attachment",
                             "The cloth mother provided milk", "The wire mother was aggressive",
                             "They were conditioned to the cloth"],
                    correct_answer="Contact comfort matters more than feeding for attachment",
                    explanation="Even when only the wire mother gave milk, the monkeys clung to the cloth mother."),
                QuizQuestion(
                    question="In the Strange Situation, the episodes most important for classification are the:",
                    options=["Reunions with the caregiver", "Moments alone with the stranger",
                             "First minutes of free play", "Departures of the stranger"],
                    correct_answer="Reunions with the caregiver",
                    explanation="How the infant responds when the caregiver returns defines the classification."),
                QuizQuestion(
                    question="An infant who is extremely upset at separation and both clings to and pushes away the returning caregiver is classified as:",
                    options=["Insecure-resistant", "Insecure-avoidant", "Secure", "Disorganized"],
                    correct_answer="Insecure-resistant",
                    explanation="Resistant (ambivalent) infants seek contact but are angry and hard to soothe."),
                QuizQuestion(
                    question="Bowlby's 'internal working model' refers to:",
                    options=["Expectations about relationships built from early caregiving",
                             "A stage of cognitive development", "A measure of infant temperament",
                             "The amount of time spent with caregivers"],
                    correct_answer="Expectations about relationships built from early caregiving",
                    explanation="These mental representations guide later relationships."),
            ],
        ),
        QuizAttempt(
            concept="Prenatal Development and Teratogens", difficulty="medium", days_ago=7, correct=[0, 3],
            questions=[
                QuizQuestion(
                    question="The period from conception until implantation (about 2 weeks) is the:",
                    options=["Germinal period", "Embryonic period", "Fetal period", "Neonatal period"],
                    correct_answer="Germinal period",
                    explanation="The germinal period ends when the blastocyst implants in the uterine wall."),
                QuizQuestion(
                    question="Exposure to a teratogen is most likely to cause major structural defects during:",
                    options=["Weeks 3-8", "Weeks 1-2", "Weeks 20-30", "The final month"],
                    correct_answer="Weeks 3-8",
                    explanation="Organogenesis happens in the embryonic period, the critical period for most structures."),
                QuizQuestion(
                    question="Thalidomide, prescribed for morning sickness in the late 1950s, primarily caused:",
                    options=["Limb malformations", "Heart murmurs only", "Increased birth weight", "Color blindness"],
                    correct_answer="Limb malformations",
                    explanation="Exposure during limb-bud formation produced missing or shortened limbs."),
                QuizQuestion(
                    question="Which statement about fetal alcohol spectrum disorder is accurate?",
                    options=["No amount of alcohol during pregnancy is known to be safe",
                             "It only occurs with daily heavy drinking", "Its effects disappear by school age",
                             "It affects only physical appearance"],
                    correct_answer="No amount of alcohol during pregnancy is known to be safe",
                    explanation="Effects are dose-dependent but no safe threshold has been established; cognitive effects persist."),
            ],
        ),
    ],
    session=TutorSession(
        name="How do we know what babies know?",
        topic="Infant Research Methods",
        mode="socratic",
        summary_bullets=[
            "Habituation-dishabituation shows infants can discriminate two stimuli.",
            "Violation of expectation infers knowledge from longer looking at impossible events.",
            "Longer looking could also mean perceptual novelty, so controls matter.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I don't get the drawbridge study. How does looking longer prove the baby knows the box "
                "is there?")),
            ChatMessage(role="assistant", content=(
                "Let's build it up. Before the box appears, babies watch the screen rotate a full 180 "
                "degrees again and again. What happens to their looking time over those trials, and why?")),
            ChatMessage(role="user", content="It goes down because they get bored. That's habituation."),
            ChatMessage(role="assistant", content=(
                "Right. Now the box goes behind the screen. In one test event the screen stops at 112 "
                "degrees, where it would hit the box. In the other it keeps going to 180 degrees, "
                "apparently right through the box. Which one is perceptually more like what they "
                "habituated to?")),
            ChatMessage(role="user", content=(
                "The 180 one, since it's the same motion. Oh, so if they look longer at that one, it's "
                "not because it's new. It's because it shouldn't be possible.")),
            ChatMessage(role="assistant", content=(
                "Exactly. That is the clever part: novelty predicts longer looking at the 112-degree "
                "event, but 5-month-olds looked longer at the familiar-looking 180-degree event. "
                "Baillargeon argued that only makes sense if they represented the hidden box. For your "
                "exam, also know the critique: some researchers argue other perceptual differences could "
                "explain the looking times, which is why later studies added more controls.")),
        ],
    ),
)


PACK = MajorPack(
    key="psychology",
    label="Psychology",
    courses=[PS101, PS211, PS231, PS241],
    total_xp=1120,
    streak_days=4,
)
