"""BIO110, Cell Biology: the local study dataset's third class. Plain content;
``spec.py`` says what each field is."""
from __future__ import annotations

from db.local_study_data import blocks as b
from db.local_study_data.spec import (
    Assessment,
    CardSet,
    ClassData,
    Concept,
    Digest,
    GuideSpec,
    LegacyGuide,
    Material,
    Quiz,
    SectionDraft,
    Tutoring,
)

STRUCTURE = "Cell Structure"
ENERGY = "Energy"
GENES = "Genetic Information"
DIVISION = "Cell Division"

CONCEPTS = (
    Concept("membrane", "Cell Membrane", STRUCTURE,
            "The cell membrane is a phospholipid bilayer with proteins in it that controls what enters and leaves the cell.",
            0.84, 7, 13, ("organelles",)),
    Concept("organelles", "Organelles", STRUCTURE,
            "Organelles are the membrane-bound compartments of a eukaryotic cell, each with its own job.",
            0.90, 6, 18),
    Concept("transport", "Membrane Transport", STRUCTURE,
            "Substances cross the membrane passively down a gradient or actively against one, which costs energy.",
            0.62, 5, 5, ("membrane",)),
    Concept("cytoskeleton", "Cytoskeleton", STRUCTURE,
            "The cytoskeleton is a network of protein fibres that gives the cell its shape and moves things inside it.",
            0.46, 2, 16, ("organelles",)),
    Concept("atp", "ATP and Energy Coupling", ENERGY,
            "ATP stores energy in its phosphate bonds, and cells spend it to drive reactions that would not run on their own.",
            0.77, 4, 11),
    Concept("enzymes", "Enzymes", ENERGY,
            "An enzyme is a protein that speeds up one reaction by lowering its activation energy.",
            0.70, 5, 2, ("atp",)),
    Concept("mitochondria", "Mitochondria", ENERGY,
            "The mitochondrion is the organelle where most of a cell's ATP is made.",
            0.55, 4, 4, ("organelles",)),
    Concept("respiration", "Cellular Respiration", ENERGY,
            "Cellular respiration breaks glucose down in steps and captures the released energy as ATP.",
            0.33, 4, 1, ("enzymes", "atp", "mitochondria")),
    Concept("photosynthesis", "Photosynthesis", ENERGY,
            "Photosynthesis uses light energy to build sugar from carbon dioxide and water.",
            0.12, 2, 9, ("enzymes", "atp")),
    Concept("dna", "DNA Replication", GENES,
            "DNA replication copies both strands of the double helix so that each new cell gets a full copy.",
            0.15, 3, 3),
    Concept("transcription", "Transcription", GENES,
            "Transcription copies one gene from DNA into a strand of messenger RNA.",
            0.38, 3, 0, ("dna",)),
    Concept("translation", "Translation", GENES,
            "Translation reads messenger RNA three bases at a time to build a protein.",
            0.0, needs=("transcription",)),
    Concept("regulation", "Gene Regulation", GENES,
            "Gene regulation decides which genes a cell transcribes, and how much.",
            0.0, needs=("transcription",)),
    Concept("cellcycle", "Cell Cycle", DIVISION,
            "The cell cycle is the ordered series of growth, DNA copying and division that makes two cells from one.",
            0.50, 2, 7, ("dna",)),
    Concept("mitosis", "Mitosis", DIVISION,
            "Mitosis separates copied chromosomes into two identical nuclei.",
            0.28, 2, 6, ("cellcycle", "cytoskeleton")),
    Concept("meiosis", "Meiosis", DIVISION,
            "Meiosis divides a cell twice to make four cells with half the chromosomes each.",
            0.0, needs=("mitosis",)),
)
_C = {c.key: c for c in CONCEPTS}

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

SECTIONS = {
    "transport": SectionDraft(
        "Membrane transport",
        "Down the gradient is free; against it costs ATP.",
        (
            b.prose(
                ("The membrane's oily middle stops ions and large polar molecules. They cross through "
                 "**channel** and **carrier proteins** instead.", "lec02"),
                ("**Passive transport** moves a substance down its concentration gradient and needs no "
                 "energy. **Active transport** pumps it against the gradient and spends ATP.", "lec02"),
                summary="Passive transport follows the gradient for free. Active transport goes against it and costs ATP.",
            ),
            b.compare(
                "Passive and active transport", ("Passive", "Active"),
                ("Direction", "Down the gradient", "Against the gradient"),
                ("Energy", "None", "ATP"),
                ("Example", "Oxygen diffusing into a cell", "The sodium-potassium pump"),
                emphasis=1,
            ),
            b.check(
                "A cell moves sodium ions out even though there is already more sodium outside. What kind of transport is this?",
                ("Simple diffusion", "Facilitated diffusion", "Active transport"), 2,
                "The ions are moving against their gradient, which only a pump spending ATP can do.",
                "Compare the direction of movement with the direction of the gradient.",
            ),
        ),
    ),
    "atp": SectionDraft(
        "ATP and energy coupling",
        "ATP is the cell's spendable energy: breaking off a phosphate pays for work.",
        (
            b.prose(
                ("**ATP** carries energy in the bonds between its three phosphate groups. Removing the "
                 "last one leaves ADP and releases energy the cell can use.", "lec06"),
                ("Cells pair that release with reactions that need energy. This **energy coupling** is "
                 "how pumps, muscle fibres and enzymes that build molecules are paid for.", "lec08"),
                summary="ATP releases energy when it becomes ADP, and cells couple that to work that needs energy.",
            ),
            b.formula(
                "ATP hydrolysis",
                r"\mathrm{ATP} + \mathrm{H_2O} \rightarrow \mathrm{ADP} + \mathrm{P_i} + \text{energy}",
                "ATP plus water gives ADP plus a phosphate group plus energy.",
            ),
            b.check(
                "What does a cell get when ATP is converted to ADP?",
                ("Energy it can use for work", "A new molecule of glucose", "Oxygen"), 0,
                "Removing the last phosphate releases energy, which the cell couples to work.",
                "Think about which direction of the ATP and ADP cycle releases energy.",
            ),
        ),
    ),
    "enzymes": SectionDraft(
        "Enzymes",
        "Enzymes lower activation energy at an active site, and they stop working when they lose their shape.",
        (
            b.prose(
                ("An **enzyme** speeds up one reaction by lowering its **activation energy**. The "
                 "**substrate** binds at the active site, reacts, and leaves. The enzyme is unchanged.", "lec06"),
                ("Shape is everything. Heat or the wrong pH **denatures** the enzyme, and the active "
                 "site stops fitting. Lab 4 measures exactly this with catalase.", "lab4"),
                summary="Enzymes lower activation energy and are reused. Past the optimum they denature and the rate collapses.",
            ),
            b.terms(_C["enzymes"],
                    ("Active site", "The pocket on an enzyme where its substrate binds."),
                    ("Denature", "To lose the folded shape that a protein needs to work.")),
            b.chart(
                "Catalase activity against temperature", "Temperature (°C)", "Rate (µmol per minute)",
                b.line("Catalase", (10, 12), (20, 25), (30, 48), (37, 60), (45, 31), (55, 4)),
                alt="The rate climbs to a peak near body temperature and then falls sharply as the enzyme denatures.",
                source="lec06",
                markers=(b.marker(37, 60, "37", "60"),),
            ),
            b.mistakes(
                (0, "Saying the enzyme is used up",
                 "An enzyme comes out of the reaction unchanged. Only the substrate is converted."),
                (1, "Saying heat kills the enzyme",
                 "Enzymes are molecules, not organisms. The word is denature: the shape is lost."),
            ),
            b.check(
                "Why does the rate fall above an enzyme's optimum temperature?",
                ("The substrate runs out", "The enzyme denatures and its active site no longer fits",
                 "The activation energy rises to its old value"), 1,
                "Heat breaks the weak bonds that hold the enzyme's shape, so the substrate can no longer bind.",
                "Ask what high temperature does to the shape of a protein.",
            ),
        ),
    ),
    "mitochondria": SectionDraft(
        "Mitochondria",
        "Two membranes, a folded inner one, and most of the cell's ATP made across it.",
        (
            b.prose(
                ("A **mitochondrion** has an outer membrane and a folded inner one. The folds are "
                 "**cristae**, and the space they enclose is the **matrix**.", "lec04"),
                ("The folding matters. The last stage of respiration happens on the inner membrane, so "
                 "more membrane means more ATP.", "lec08"),
                summary="Inner membrane folded into cristae around the matrix. More inner membrane, more ATP.",
            ),
            b.terms(_C["mitochondria"],
                    ("Cristae", "The folds of the inner mitochondrial membrane."),
                    ("Matrix", "The space inside the inner membrane, where the citric acid cycle runs.")),
            b.check(
                "Why is the inner mitochondrial membrane folded?",
                ("To protect the DNA inside", "To give more surface for making ATP", "To let glucose in faster"), 1,
                "The electron transport chain and ATP synthase sit in that membrane, so more area holds more of them.",
                "Think about what is built into the inner membrane.",
            ),
        ),
    ),
    "respiration": SectionDraft(
        "Cellular respiration",
        "Glucose is taken apart in three stages, and nearly all the ATP comes from the last one.",
        (
            b.prose(
                ("**Cellular respiration** has three stages. **Glycolysis** splits glucose in the "
                 "cytoplasm. The **citric acid cycle** finishes the job in the mitochondrial matrix.", "lec08"),
                ("Those two stages make little ATP directly. Their real product is loaded electron "
                 "carriers, which feed **oxidative phosphorylation** on the inner membrane.", "lec08"),
                ("Oxygen waits at the end of the electron transport chain. Without it the chain backs "
                 "up, and the cell is left with the 2 ATP of glycolysis.", "lec08"),
                summary="Glycolysis in the cytoplasm, the citric acid cycle in the matrix, and most ATP from the inner membrane.",
            ),
            b.formula(
                "Respiration, overall",
                r"\mathrm{C_6H_{12}O_6} + 6\,\mathrm{O_2} \rightarrow 6\,\mathrm{CO_2} + 6\,\mathrm{H_2O} + \text{energy}",
                "One glucose plus six oxygen gives six carbon dioxide plus six water plus energy.",
                "lec08",
            ),
            b.mistakes(
                (0, "Putting glycolysis in the mitochondrion",
                 "Glycolysis happens in the cytoplasm. Only what follows it happens inside the mitochondrion."),
                (1, "Giving the citric acid cycle most of the ATP",
                 "The cycle makes 2 ATP. Its main product is NADH and FADH2 for the last stage."),
            ),
            b.example(
                "Count the ATP from one glucose",
                "About how much ATP does one glucose yield when oxygen is present, stage by stage?",
                ("Glycolysis", "2 ATP", "Net gain, made in the cytoplasm."),
                ("Citric acid cycle", "2 ATP", "Made in the matrix, one per turn and two turns per glucose."),
                ("Oxidative phosphorylation", "about 28 ATP", "Driven by the proton gradient across the inner membrane."),
                ("Total", "about 32 ATP", "Nearly all of it depends on oxygen."),
                source="lec08",
            ),
            b.concept_map(
                "What respiration draws on",
                (_C["atp"], "Foundations"), (_C["enzymes"], "Foundations"),
                (_C["mitochondria"], "Before this"), (_C["respiration"], "This section"),
                (_C["photosynthesis"], "Up next"),
            ),
            b.check(
                "Where does glycolysis take place?",
                ("In the cytoplasm", "In the mitochondrial matrix", "On the inner mitochondrial membrane"), 0,
                "Glycolysis needs no organelle. It runs in the cytoplasm of every cell.",
                "Only two of the three stages happen inside the mitochondrion.",
            ),
        ),
    ),
    "photosynthesis": SectionDraft(
        "Photosynthesis",
        "Light reactions make ATP and NADPH, and the Calvin cycle spends them to build sugar.",
        (
            b.prose(
                ("The **light reactions** happen in the thylakoid membranes. They split water, release "
                 "oxygen, and store light energy as ATP and NADPH.", "lec10"),
                ("The **Calvin cycle** runs in the stroma and uses that ATP and NADPH to fix carbon "
                 "dioxide into sugar. The rate of the whole process is set by the scarcest input.", "lec10"),
                summary="Light reactions make ATP, NADPH and oxygen. The Calvin cycle uses them to turn carbon dioxide into sugar.",
            ),
            b.formula(
                "Photosynthesis, overall",
                r"6\,\mathrm{CO_2} + 6\,\mathrm{H_2O} + \text{light} \rightarrow \mathrm{C_6H_{12}O_6} + 6\,\mathrm{O_2}",
                "Six carbon dioxide plus six water plus light gives one glucose plus six oxygen.",
                "lec10",
            ),
            b.chart(
                "Light and the rate of photosynthesis", "Light intensity", "Rate of photosynthesis",
                b.line("Normal carbon dioxide", (0, 0), (100, 20), (200, 35), (400, 45), (800, 48)),
                b.line("Extra carbon dioxide", (0, 0), (100, 22), (200, 42), (400, 62), (800, 70), after=True),
                alt="Both curves rise with light and then level off. With extra carbon dioxide the plateau is higher.",
                source="lec10",
                markers=(b.marker(800, 48, "Bright light", "Plateau"),
                         b.marker(800, 70, "Bright light", "Higher plateau", after=True)),
                readouts=(b.readout("Plateau", "48", "70", "Rises"),
                          b.readout("Limit in bright light", "Carbon dioxide", "Light", "Shifts")),
                after_label="Extra CO2",
            ),
            b.compare(
                "Photosynthesis and respiration", ("Photosynthesis", "Respiration"),
                ("Energy", "Stores light energy in sugar", "Releases the energy in sugar as ATP"),
                ("Gas used", "Carbon dioxide", "Oxygen"),
                ("Gas released", "Oxygen", "Carbon dioxide"),
                ("Organelle", "Chloroplast", "Mitochondrion"),
                emphasis=2,
            ),
            b.check(
                "Where does the oxygen released by a plant come from?",
                ("Carbon dioxide", "Water", "Glucose"), 1,
                "The light reactions split water, and oxygen is what is left over.",
                "Find the step of the light reactions that takes a molecule apart.",
            ),
        ),
    ),
    "dna": SectionDraft(
        "DNA replication",
        "Each strand is a template, and polymerase can only build in one direction.",
        (
            b.prose(
                ("Replication is **semiconservative**: each new helix has one old strand and one new "
                 "one. **Helicase** opens the helix, and **DNA polymerase** builds the new strands.", "lec12"),
                ("Polymerase only adds to the 3 prime end. So the **leading strand** is made in one "
                 "piece, and the **lagging strand** is made backwards in Okazaki fragments.", "lec12"),
                summary="Each old strand templates a new one. One is made continuously and the other in fragments.",
            ),
            b.compare(
                "Leading and lagging strands", ("Leading strand", "Lagging strand"),
                ("Built", "Continuously", "In Okazaki fragments"),
                ("Direction", "Toward the fork", "Away from the fork"),
                ("Primers needed", "One", "One per fragment"),
                emphasis=0,
            ),
            b.mistakes(
                (0, "Letting polymerase build both ways",
                 "DNA polymerase only extends a 3 prime end. That one rule explains the lagging strand."),
            ),
            b.check(
                "Why is the lagging strand made in fragments?",
                ("It has more errors to fix", "Polymerase can only build 5 prime to 3 prime",
                 "Helicase works more slowly on it"), 1,
                "That strand runs the wrong way for continuous synthesis, so it is built in pieces away from the fork.",
                "Recall the one direction DNA polymerase can add nucleotides in.",
            ),
        ),
    ),
    "transcription": SectionDraft(
        "Transcription",
        "RNA polymerase reads one DNA strand and writes the matching RNA, with U in place of T.",
        (
            b.prose(
                ("**Transcription** copies one gene into messenger RNA. **RNA polymerase** binds at the "
                 "**promoter**, opens the DNA, and reads the template strand.", "lec13"),
                ("The RNA it builds is complementary to the template, with uracil where DNA has "
                 "thymine. In eukaryotes the message is capped, tailed and spliced before it leaves the nucleus.", "lec13"),
                summary="RNA polymerase starts at the promoter and builds mRNA complementary to the template, using U for T.",
            ),
            b.example(
                "Transcribe a template",
                "The DNA template strand reads 3'-TACGGT-5'. What mRNA is made?",
                ("Pair each base", "T-A, A-U, C-G, G-C, G-C, T-A", "RNA pairs A with U, never with T."),
                ("Write the RNA", "AUGCCA", "Read the pairs in order."),
                ("Add the direction", "5'-AUGCCA-3'", "The new strand runs opposite to the template."),
                source="lec13",
            ),
            b.mistakes(
                (0, "Writing T into the RNA",
                 "RNA has no thymine. Wherever the template has A, the RNA gets U."),
            ),
            b.concept_map(
                "From gene to protein",
                (_C["dna"], "Before this"), (_C["transcription"], "This section"),
                (_C["translation"], "Up next"), (_C["regulation"], "Later"),
            ),
            b.check(
                "A DNA template has the base A. Which base does RNA polymerase add opposite it?",
                ("T", "U", "A"), 1,
                "RNA uses uracil where DNA would use thymine, so A on the template pairs with U.",
                "Remember which base RNA does not have.",
            ),
        ),
    ),
    "cellcycle": SectionDraft(
        "The cell cycle",
        "Grow, copy the DNA, prepare, divide, with checkpoints between.",
        (
            b.prose(
                ("The **cell cycle** has four phases. The cell grows in **G1**, copies its DNA in **S**, "
                 "prepares in **G2** and divides in **M**.", "lec14"),
                ("**Checkpoints** hold the cycle until the cell is ready. A cell with damaged DNA should "
                 "stop at one, and a cell that ignores them is on the way to cancer.", "lec14"),
                summary="G1, S, G2, then M. Checkpoints stop the cycle when something is wrong.",
            ),
            b.terms(_C["cellcycle"],
                    ("Interphase", "G1, S and G2 together: all of the cycle except division."),
                    ("S phase", "The phase in which the cell copies its DNA."),
                    ("Checkpoint", "A control point that stops the cycle until a condition is met.")),
            b.check(
                "In which phase does a cell copy its DNA?",
                ("G1", "S", "M"), 1,
                "S stands for synthesis: this is when every chromosome is copied.",
                "One phase is named for making new DNA.",
            ),
        ),
    ),
    "mitosis": SectionDraft(
        "Mitosis",
        "Copied chromosomes line up, split apart and end up in two identical nuclei.",
        (
            b.prose(
                ("**Mitosis** has four steps: prophase, metaphase, anaphase and telophase. The "
                 "chromosomes condense, line up, separate and are wrapped in two new nuclei.", "lec14"),
                ("The spindle, built from microtubules, does the pulling. **Cytokinesis** then splits "
                 "the cytoplasm, leaving two cells with identical DNA.", "lec14"),
                summary="Prophase, metaphase, anaphase, telophase, then cytokinesis. Two identical cells result.",
            ),
            b.example(
                "Follow the chromosomes",
                "A human cell has 46 chromosomes. How many does each daughter cell have after mitosis?",
                ("After S phase", "46 chromosomes, 92 chromatids", "Each chromosome is now two sister chromatids."),
                ("Anaphase", "92 separate chromatids", "The sisters are pulled to opposite ends, 46 each way."),
                ("After cytokinesis", "46 in each cell", "Both cells match the parent."),
                source="lec14",
            ),
            b.compare(
                "The four steps", ("What happens", "How to spot it"),
                ("Prophase", "Chromosomes condense", "Visible threads, nucleus fading"),
                ("Metaphase", "Chromosomes line up", "A row across the middle"),
                ("Anaphase", "Sister chromatids separate", "Two groups moving apart"),
                ("Telophase", "Two nuclei form", "Two clusters, cell pinching"),
                emphasis=2,
            ),
            b.check(
                "In which step of mitosis do the sister chromatids separate?",
                ("Metaphase", "Anaphase", "Telophase"), 1,
                "In anaphase the spindle pulls the sisters to opposite ends of the cell.",
                "Think of the step where the chromosomes move apart.",
            ),
        ),
    ),
}

GUIDES = (
    GuideSpec(
        "exam2", "Enzymes and energy",
        "Exam 2 in six sections, with the most room for respiration and photosynthesis, your weakest topics here.",
        ("Enzymes lower activation energy and are never used up.",
         "Most ATP comes from oxidative phosphorylation, not the citric acid cycle.",
         "Photosynthesis stores energy in sugar and respiration releases it."),
        "exam2", "exam_prep", "deep",
        ("atp", "enzymes", "mitochondria", "respiration", "photosynthesis", "transport"),
        made_hours_ago=5 * 24, saved_hours_ago=4 * 24,
        read=("atp", "enzymes", "mitochondria"),
        answers={"enzymes": "b", "respiration": "b"},
    ),
    GuideSpec(
        "lab5", "Respiration for the yeast lab",
        "A short practice guide for the Lab 5 report: where ATP comes from and what yeast does without oxygen.",
        ("ATP is the cell's spendable energy.",
         "Glycolysis alone yields 2 ATP per glucose.",
         "Oxygen is the final electron acceptor."),
        "lab5", "practice", "cram", ("atp", "enzymes", "respiration"),
        made_hours_ago=5,
    ),
    GuideSpec(
        "final", "Genetic information and cell division",
        "The last two units before the final: copying DNA, reading it, and dividing the cell.",
        ("DNA polymerase only builds 5 prime to 3 prime.",
         "RNA uses U where DNA uses T.",
         "DNA is copied in S phase and separated in anaphase."),
        "final", "review", "standard", ("dna", "transcription", "cellcycle", "mitosis"),
        made_hours_ago=12, saved_hours_ago=11,
    ),
)

LEGACY_GUIDES = (
    LegacyGuide(
        "exam1", "exam1", 30 * 24,
        "Exam 1 covers the structure of the cell. Know what each organelle does and how the membrane "
        "controls what crosses it. Expect diagrams to label. Transport questions usually ask for the "
        "direction of movement and whether it costs energy.",
        (
            ("Cell membrane", "The membrane is on every exam because everything else depends on it.",
             ("Phospholipid bilayer", "Fluid mosaic model", "Selective permeability")),
            ("Organelles", "Match each organelle to its job; expect a diagram.",
             ("Nucleus", "Endoplasmic reticulum and Golgi", "Mitochondria and chloroplasts")),
            ("Membrane transport", "Know which way a substance moves and what it costs.",
             ("Diffusion and osmosis", "Facilitated diffusion", "Active transport")),
            ("Cytoskeleton", "Three fibre types and what each one does.",
             ("Microtubules", "Actin filaments", "Intermediate filaments")),
        ),
    ),
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
