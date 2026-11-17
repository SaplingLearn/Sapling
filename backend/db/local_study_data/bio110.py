"""BIO110, Cell Biology: the local study dataset's third class. Plain content;
``spec.py`` says what each field is."""
from __future__ import annotations

from db.local_study_data.bio110_concepts import (
    CONCEPTS,
    DIVISION,
    ENERGY,
    GENES,
    STRUCTURE,
)
from db.local_study_data.bio110_guides import GUIDES, LEGACY_GUIDES, SECTIONS
from db.local_study_data.spec import (
    Assessment,
    CardSet,
    ClassData,
    Digest,
    Material,
    Quiz,
    Tutoring,
)

MATERIALS = (
    Material("syllabus", "BIO110 Syllabus.pdf", "syllabus", 76,
             "Course plan: weekly labs, two exams, a poster project and a final.",
             ("organelles", "membrane"), (
                 "BIO110 studies the cell: its structure, how it handles energy, how it stores and uses "
                 "genetic information, and how it divides.",
                 "Grading: lab reports 25 percent, two exams 20 percent each, poster project 10 percent, "
                 "final exam 25 percent.",
                 "Exam 1 covers cell structure. Exam 2 covers energy and enzymes. The final exam covers "
                 "the whole course.",
             )),
    Material("lec02", "Lecture 02 - Membranes and Transport.pdf", "lecture_notes", 64,
             "The phospholipid bilayer, membrane proteins, and passive and active transport.",
             ("membrane", "transport"), (
                 "The cell membrane is a bilayer of phospholipids. Their heads face water and their "
                 "tails face each other. Proteins float in it, which is why the model is called fluid mosaic.",
                 "Small nonpolar molecules such as oxygen diffuse straight through. Ions and large polar "
                 "molecules need a channel or carrier protein.",
                 "Passive transport moves a substance down its concentration gradient and costs no "
                 "energy. Active transport moves it against the gradient and spends ATP.",
             )),
    Material("lec04", "Lecture 04 - Organelles and the Cytoskeleton.pptx", "slides", 50,
             "The nucleus, endomembrane system, mitochondria, chloroplasts and the cytoskeleton.",
             ("organelles", "cytoskeleton", "mitochondria"), (
                 "The nucleus holds the DNA. The rough endoplasmic reticulum makes proteins, and the "
                 "Golgi apparatus sorts and ships them.",
                 "A mitochondrion has two membranes. The inner one is folded into cristae, and the "
                 "space inside it is the matrix. Mitochondria carry their own small DNA.",
                 "The cytoskeleton has three kinds of fibre. Microtubules move chromosomes and "
                 "vesicles, actin filaments change the cell's shape, and intermediate filaments give it strength.",
             )),
    Material("reading", "Reading - The Fluid Mosaic Model.pdf", "reading", 41,
             "Textbook chapter on membrane structure and why membranes are selectively permeable.",
             ("membrane",), (
                 "A membrane is fluid because its phospholipids move sideways freely. Cholesterol keeps "
                 "it from becoming too stiff in the cold or too loose in the heat.",
                 "It is a mosaic because many different proteins sit in it. Some span the bilayer and "
                 "form channels. Others sit on one face and act as receptors or markers.",
                 "Selective permeability follows from this structure. The oily middle of the bilayer "
                 "stops charged particles, so the cell decides what crosses by which proteins it makes.",
             )),
    Material("lec06", "Lecture 06 - Enzymes.pdf", "lecture_notes", 25,
             "Activation energy, the active site, and how temperature, pH and inhibitors change enzyme activity.",
             ("enzymes", "atp"), (
                 "An enzyme speeds up a reaction by lowering its activation energy. The substrate binds "
                 "at the active site, and the enzyme is not used up.",
                 "Lab data for catalase activity, in micromoles of product per minute: at 10 degrees the "
                 "rate was 12, at 20 degrees 25, at 30 degrees 48, at 37 degrees 60, at 45 degrees 31 "
                 "and at 55 degrees 4.",
                 "Above its optimum an enzyme denatures: it loses its shape and its active site stops "
                 "fitting the substrate. A competitive inhibitor blocks the active site itself.",
             )),
    Material("lec08", "Lecture 08 - Cellular Respiration.pdf", "lecture_notes", 18,
             "Glycolysis, the citric acid cycle and oxidative phosphorylation, and where each one happens.",
             ("respiration", "mitochondria", "atp"), (
                 "Respiration has three stages. Glycolysis happens in the cytoplasm and splits glucose "
                 "into two pyruvate, with a net gain of 2 ATP.",
                 "The citric acid cycle runs in the mitochondrial matrix. It releases carbon dioxide and "
                 "loads the electron carriers NADH and FADH2. It makes 2 more ATP.",
                 "Oxidative phosphorylation happens on the inner mitochondrial membrane. Electrons pass "
                 "down a chain to oxygen, and the proton gradient this builds drives ATP synthase. It "
                 "makes about 28 ATP, for a total near 32 per glucose.",
             )),
    Material("lab4", "Lab 4 - Enzyme Activity Handout.pdf", "assignment", 13,
             "Lab handout: measure catalase activity at six temperatures and plot the result.",
             ("enzymes",), (
                 "You will measure how fast catalase breaks down hydrogen peroxide at six temperatures. "
                 "The product is oxygen gas, which you collect and measure.",
                 "Keep the enzyme and substrate amounts the same in every tube. Only the temperature "
                 "should change between trials.",
                 "In your report, plot rate against temperature, mark the optimum, and explain the "
                 "shape of the curve on both sides of it.",
             )),
    Material("lec10", "Lecture 10 - Photosynthesis.pptx", "slides", 10,
             "The light reactions and the Calvin cycle, and what limits the rate of photosynthesis.",
             ("photosynthesis", "atp"), (
                 "Photosynthesis has two stages. The light reactions happen in the thylakoid membranes. "
                 "They split water, release oxygen, and make ATP and NADPH.",
                 "The Calvin cycle happens in the stroma. It uses that ATP and NADPH to fix carbon "
                 "dioxide into sugar. It does not need light directly.",
                 "The rate is set by whichever input is scarcest. In dim light, light is the limit. In "
                 "bright light the curve levels off because carbon dioxide runs short.",
             )),
    Material("lec12", "Lecture 12 - DNA Replication.pdf", "lecture_notes", 6,
             "Semiconservative replication, the replication fork, and leading and lagging strands.",
             ("dna",), (
                 "Replication is semiconservative. Each new double helix keeps one old strand and gains "
                 "one new strand.",
                 "Helicase unwinds the helix. Primase lays down a short RNA primer. DNA polymerase then "
                 "adds nucleotides, but only to the 3 prime end of a growing strand.",
                 "So one strand, the leading strand, is made in one piece toward the fork. The lagging "
                 "strand is made away from it in short Okazaki fragments, which ligase joins.",
             )),
    Material("lec13", "Lecture 13 - Transcription.pdf", "lecture_notes", 3,
             "RNA polymerase, promoters, and how a DNA template becomes messenger RNA.",
             ("transcription", "dna"), (
                 "Transcription copies a gene into messenger RNA. RNA polymerase binds at the promoter "
                 "and unwinds a short stretch of DNA.",
                 "It reads the template strand and builds RNA with complementary bases. RNA uses "
                 "uracil where DNA would use thymine.",
                 "In eukaryotes the RNA is then processed: a cap and a tail are added, and the introns "
                 "are spliced out before the message leaves the nucleus.",
             )),
    Material("lec14", "Lecture 14 - The Cell Cycle and Mitosis.pptx", "slides", 1,
             "Interphase, the four phases of mitosis, cytokinesis and the cell cycle checkpoints.",
             ("cellcycle", "mitosis"), (
                 "The cell cycle has four phases. In G1 the cell grows, in S it copies its DNA, in G2 it "
                 "prepares to divide, and in M it divides.",
                 "Mitosis has four steps. In prophase the chromosomes condense. In metaphase they line "
                 "up in the middle. In anaphase the sister chromatids separate. In telophase two nuclei form.",
                 "Checkpoints stop the cycle when something is wrong, such as damaged DNA or a "
                 "chromosome not attached to the spindle.",
             )),
)

ASSESSMENTS = (
    Assessment("exam1", "Exam 1: Cell Structure", "exam", -27, 100, 91, (STRUCTURE,)),
    Assessment("exam2", "Exam 2: Energy and Enzymes", "exam", 12, covers=(ENERGY,)),
    Assessment("final", "Final Exam", "exam", 30, covers=(STRUCTURE, ENERGY, GENES, DIVISION)),
    Assessment("quiz1", "Quiz 1: Transcription", "quiz", 15, 10, concepts=("dna", "transcription")),
    Assessment("lab4", "Lab 4 Report: Enzyme Activity", "homework", -5, 50, 44),
    Assessment("lab5", "Lab 5 Report: Respiration in Yeast", "homework", 3, 50),
    Assessment("reading9", "Chapter 9 Reading Check", "reading", 6, 10),
    Assessment("poster", "Poster Project: A Cell Process", "project", 20, 100),
)

CARDS = {
    "membrane": (
        ("What is the cell membrane made of?", "A phospholipid bilayer with proteins set in it."),
        ("Why is the membrane called a fluid mosaic?", "Its lipids move freely and many different proteins sit among them."),
        ("What does selectively permeable mean?", "Some substances can cross the membrane and others cannot."),
        ("What does cholesterol do in a membrane?", "It keeps the membrane from getting too stiff or too loose."),
    ),
    "organelles": (
        ("What does the nucleus hold?", "The cell's DNA."),
        ("What does the rough endoplasmic reticulum do?", "It makes proteins on its ribosomes."),
        ("What does the Golgi apparatus do?", "It sorts, modifies and ships proteins."),
        ("What do lysosomes do?", "They break down waste and worn-out parts with digestive enzymes."),
    ),
    "transport": (
        ("What is diffusion?", "Movement of a substance from high concentration to low."),
        ("What is osmosis?", "Diffusion of water across a membrane."),
        ("What does active transport need that passive transport does not?", "Energy, usually from ATP."),
        ("What is facilitated diffusion?", "Passive movement through a channel or carrier protein."),
        ("Which way does active transport move a substance?", "Against its concentration gradient."),
    ),
    "enzymes": (
        ("What does an enzyme do to activation energy?", "It lowers it."),
        ("What is the active site?", "The part of an enzyme where the substrate binds."),
        ("Is an enzyme used up by its reaction?", "No, it can be used again and again."),
        ("What happens to an enzyme when it denatures?", "It loses its shape, so the active site no longer fits the substrate."),
        ("What does a competitive inhibitor do?", "It binds the active site and blocks the substrate."),
        ("What is an enzyme's optimum temperature?", "The temperature at which it works fastest."),
    ),
    "atp": (
        ("What does ATP stand for?", "Adenosine triphosphate."),
        ("How does ATP release energy?", "By losing its last phosphate group to become ADP."),
        ("What is energy coupling?", "Using an energy-releasing reaction to drive one that needs energy."),
        ("What does ATP synthase do?", "It makes ATP from ADP and phosphate using a proton gradient."),
    ),
    "mitochondria": (
        ("What are cristae?", "The folds of the inner mitochondrial membrane."),
        ("What is the mitochondrial matrix?", "The space inside the inner membrane."),
        ("Which stage of respiration happens on the inner membrane?", "Oxidative phosphorylation."),
        ("What is unusual about mitochondrial DNA?", "Mitochondria carry their own small genome, separate from the nucleus."),
    ),
    "respiration": (
        ("What are the three stages of cellular respiration?", "Glycolysis, the citric acid cycle and oxidative phosphorylation."),
        ("Where does glycolysis happen?", "In the cytoplasm."),
        ("What is the net ATP gain of glycolysis?", "2 ATP per glucose."),
        ("What is the final electron acceptor in respiration?", "Oxygen."),
        ("Which stage makes the most ATP?", "Oxidative phosphorylation."),
        ("Where does the citric acid cycle run?", "In the mitochondrial matrix."),
    ),
    "photosynthesis": (
        ("What are the two stages of photosynthesis?", "The light reactions and the Calvin cycle."),
        ("Where do the light reactions happen?", "In the thylakoid membranes."),
        ("Where does the oxygen released in photosynthesis come from?", "From water split in the light reactions."),
        ("What does the Calvin cycle make?", "Sugar, from carbon dioxide."),
        ("What do the light reactions supply to the Calvin cycle?", "ATP and NADPH."),
    ),
    "dna": (
        ("What does semiconservative replication mean?", "Each new helix keeps one old strand and gains one new one."),
        ("What does helicase do?", "It unwinds the double helix."),
        ("In which direction does DNA polymerase build a strand?", "From 5 prime to 3 prime."),
        ("What are Okazaki fragments?", "The short pieces the lagging strand is made in."),
        ("What does DNA ligase do?", "It joins DNA fragments into one strand."),
    ),
    "transcription": (
        ("What does transcription produce?", "A strand of messenger RNA."),
        ("Which enzyme carries out transcription?", "RNA polymerase."),
        ("What is a promoter?", "The DNA sequence where RNA polymerase binds to start."),
        ("Which base does RNA use in place of thymine?", "Uracil."),
        ("What happens to introns?", "They are spliced out before the RNA leaves the nucleus."),
    ),
    "cellcycle": (
        ("What are the four phases of the cell cycle?", "G1, S, G2 and M."),
        ("What happens in S phase?", "The cell copies its DNA."),
        ("What is interphase?", "G1, S and G2 together: everything except division."),
        ("What does a checkpoint do?", "It stops the cycle until a problem is fixed."),
    ),
    "mitosis": (
        ("What are the four steps of mitosis, in order?", "Prophase, metaphase, anaphase, telophase."),
        ("What happens in anaphase?", "The sister chromatids separate and move to opposite ends."),
        ("What happens in metaphase?", "The chromosomes line up in the middle of the cell."),
        ("What is cytokinesis?", "The division of the cytoplasm into two cells."),
    ),
}

QUIZZES = (
    Quiz("membrane", 28, 17, 4, total=4, difficulty="easy"),
    Quiz("transport", 23, 19, 4),
    Quiz("enzymes", 14, 20, 3),
    Quiz("enzymes", 5, 17, 4),
    Quiz("respiration", 12, 18, 2),
    Quiz("respiration", 7, 21, 2),
    Quiz("respiration", 1, 20, 3),
    Quiz("photosynthesis", 9, 16, 1),
    Quiz("mitosis", 6, 19, 2, total=4),
    Quiz("dna", 3, 18, 2, difficulty="hard"),
    Quiz("transcription", 0, 0, 2, minutes_ago=50),
)

DIGESTS = (
    Digest("respiration",
           ("Places glycolysis inside the mitochondrion",
            "Credits most of the ATP to the citric acid cycle"),
           ("Matching each stage to where it happens",),
           "Stages and locations, ATP counts, the role of oxygen."),
    Digest("enzymes",
           ("Says the enzyme is used up by the reaction",
            "Says heat kills an enzyme, as if it were alive"),
           (), "Activation energy, active sites, denaturation, inhibitors.", "hard"),
    Digest("dna",
           ("Has DNA polymerase building in both directions",),
           ("Leading and lagging strands",),
           "Enzymes at the fork, Okazaki fragments.", "easy"),
    Digest("transcription",
           ("Pairs adenine with thymine when building RNA",),
           ("Template strand and coding strand",),
           "Base pairing in RNA, promoters, RNA processing."),
    Digest("photosynthesis",
           ("Says the oxygen comes from carbon dioxide",),
           (), "Light reactions and Calvin cycle inputs and outputs.", "easy"),
)

TUTORING = (
    Tutoring("membrane", "membrane", "The Fluid Mosaic Model", 35, 16, (0, 6, 13), ended=True),
    Tutoring("enzymes", "enzymes", "Enzymes and Temperature", 22, 19, (0, 6, 12, 19), ended=True),
    Tutoring("dna", "dna", "Leading and Lagging Strands", 5, 18, (0, 4, 10, 17), "expository", ended=True),
    Tutoring("respiration", "respiration", "Where the ATP Comes From", 3, 20, (0, 5, 11, 18, 25)),
)

CARD_SETS = (
    CardSet("structure", "Cell structure", ("membrane", "organelles", "transport"), 29,
            exam="exam1", shuffle=False),
    CardSet("exam2", "Exam 2: energy", ("atp", "enzymes", "mitochondria", "respiration", "photosynthesis"), 4,
            exam="exam2"),
    CardSet("genes", "DNA to RNA", ("dna", "transcription"), 1),
)

CLASS = ClassData(
    key="bio110",
    course_id="rich-course-bio110",
    concepts=CONCEPTS,
    materials=MATERIALS,
    assessments=ASSESSMENTS,
    cards=CARDS,
    quizzes=QUIZZES,
    digests=DIGESTS,
    tutoring=TUTORING,
    card_sets=CARD_SETS,
    sections=SECTIONS,
    guides=GUIDES,
    legacy_guides=LEGACY_GUIDES,
)
