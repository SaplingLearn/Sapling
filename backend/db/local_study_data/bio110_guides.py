"""BIO110's study guides: one section draft per concept, and the guides that
pick from them. A draft is written once at every length it is read at
(``spec.LENGTHS``): its opening passage is the cram version, and the
``standard`` and ``deep`` passages are what the longer versions add."""
from __future__ import annotations

from db.local_study_data import blocks as b
from db.local_study_data.bio110_concepts import CONCEPTS
from db.local_study_data.spec import GuideSpec, LegacyGuide, SectionDraft

_C = {c.key: c for c in CONCEPTS}

SECTIONS = {
    "transport": SectionDraft(
        "Membrane transport",
        "Down the gradient is free; against it costs ATP.",
        (
            b.prose(
                ("Whether a substance can cross the cell membrane depends on what it is. Small "
                 "nonpolar molecules such as oxygen diffuse straight through the bilayer. Ions and "
                 "large polar molecules cannot, because the oily middle of the membrane turns them "
                 "back. They need a protein to cross: a **channel** that opens a path, or a "
                 "**carrier** that takes them across.", "lec02"),
                ("How a substance crosses is one question. Which way it moves is the other, and it "
                 "decides the cost. **Passive transport** moves a substance down its concentration "
                 "gradient, from where there is more of it to where there is less, and costs no "
                 "energy. **Active transport** moves it against the gradient and spends ATP.",
                 "lec02"),
                summary="Small nonpolar molecules cross the bilayer directly; ions and polar molecules "
                        "need proteins. Moving down a gradient is free, and moving against it costs ATP.",
            ),
            b.prose(
                ("The rule about who can cross comes straight from how the membrane is built. It is "
                 "a bilayer of phospholipids whose heads face the water on either side and whose "
                 "tails face each other, so the middle of the membrane is a layer of oil. A small "
                 "nonpolar molecule mixes with oil and passes through. An ion carries a charge, "
                 "water molecules cling to it, and the oily layer has nothing to offer in exchange, "
                 "so it stays out. Size matters as well: a large polar molecule is stopped even "
                 "without a charge. The proteins that float in the bilayer are the cell's answer, "
                 "one kind of protein for each kind of passenger.", "lec02"),
                summary="The oily middle of the bilayer lets small nonpolar molecules through and "
                        "stops ions and large polar molecules, which need proteins.",
                at="deep",
            ),
            b.prose(
                "Keep those two questions separate, because mixing them causes most wrong answers. "
                "Needing a protein does not make transport active. An ion flowing through a channel "
                "from the crowded side to the empty side is still passive, since the gradient is "
                "doing the work and the protein is only a doorway. This is called facilitated "
                "diffusion. Transport is active only when the substance ends up more concentrated "
                "where it was already concentrated. That takes a pump and a supply of ATP. So decide "
                "the direction first, and only then ask what route the substance took. The table "
                "compares the two on exactly those points.",
                summary="Using a protein does not make transport active. Only movement against the "
                        "gradient is active, and that needs ATP.",
                at="standard",
            ),
            b.compare(
                "Passive and active transport", ("Passive", "Active"),
                ("Direction", "Down the gradient", "Against the gradient"),
                ("Energy", "None", "ATP"),
                ("Example", "Oxygen diffusing into a cell", "The sodium-potassium pump"),
                emphasis=1,
            ),
            b.prose(
                "A gradient is a store of energy, and that is why the direction matters so much. "
                "Substances spread out on their own, so a difference in concentration is something "
                "the cell had to build and has to keep paying for. The energy row of the table "
                "follows from that. Movement that lets a gradient run down gives energy up, and "
                "movement that builds one takes energy in, which the cell supplies as ATP. A cell "
                "that runs out of ATP does not hold its gradients for long: its pumps stop, and "
                "passive movement slowly evens everything out.",
                summary="A concentration gradient stores energy. Letting it run down is free, and "
                        "building or keeping one costs ATP.",
                at="standard",
            ),
            b.prose(
                "This section is in a guide about energy for a reason. The last stage of respiration "
                "is membrane transport put to work. The electron transport chain pumps protons "
                "across the inner mitochondrial membrane, against their gradient, which is active "
                "transport paid for by the energy of the electrons. The protons then flow back down "
                "the gradient through ATP synthase, which is passive, and that flow is what makes "
                "ATP. So the two kinds of transport in the table are also the two halves of how a "
                "cell charges its ATP. If you can say which way the protons are moving at each step, "
                "and whether that movement costs energy or releases it, you understand both topics.",
                summary="In respiration, protons are pumped against their gradient and then flow back "
                        "through ATP synthase, so both kinds of transport help make ATP.",
                at="deep",
            ),
            b.prose(
                "You should now be able to say whether a substance needs a protein to cross, decide "
                "from the gradient whether its movement is passive or active, and say which of the "
                "two costs ATP and why. The question below turns on the direction of movement.",
                summary="You can now tell passive from active transport by the direction of the gradient.",
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
                ("**ATP** is the molecule cells use to carry energy from where it is released to "
                 "where it is needed. It stores that energy in the bonds between its three phosphate "
                 "groups. Breaking off the last phosphate leaves ADP and releases energy the cell "
                 "can use.", "lec06"),
                ("Cells do not let that energy drift away as heat. They pair the breakdown of ATP "
                 "with a reaction that needs energy, so that one pays for the other. This pairing is "
                 "called **energy coupling**, and respiration exists to keep it supplied.", "lec08"),
                summary="ATP releases energy when it loses a phosphate and becomes ADP. Cells couple "
                        "that release to work that needs energy.",
                at="brief",
            ),
            b.formula(
                "ATP hydrolysis",
                r"\mathrm{ATP} + \mathrm{H_2O} \rightarrow \mathrm{ADP} + \mathrm{P_i} + \text{energy}",
                "ATP plus water gives ADP plus a phosphate group plus energy.",
            ),
            b.prose(
                "Read the equation in both directions, because the cell runs it both ways all the "
                "time. From left to right, ATP is spent: a phosphate comes off and energy is "
                "released for work. From right to left, ATP is rebuilt: ADP and a phosphate are "
                "joined again, and that takes energy in. A cell holds only a small stock of ATP and "
                "recycles it constantly, so think of ATP less as a fuel tank and more as a "
                "rechargeable battery that is drained and charged over and over. Food is the fuel. "
                "ATP is how the energy in it gets spent.",
                summary="Spending ATP releases energy and rebuilding it takes energy in. The cell "
                        "recycles a small stock of ATP constantly.",
                at="standard",
            ),
            b.prose(
                ("The rest of this unit is about the two halves of that cycle. Respiration is the "
                 "charging side. Glycolysis nets 2 ATP, and oxidative phosphorylation makes most of "
                 "the rest, for a total near 32 per glucose. In a chloroplast the light reactions "
                 "make ATP too, and the Calvin cycle spends it at once to build sugar. On the "
                 "spending side are the jobs that will not run on their own: pumping a substance "
                 "against its gradient, building large molecules from small ones, and moving things "
                 "around inside the cell. When a question asks whether a process needs energy, ask "
                 "whether ATP is being spent.", "lec08", "lec10"),
                summary="Respiration and the light reactions make ATP. Pumps, building molecules and "
                        "movement spend it.",
                at="standard",
            ),
            b.prose(
                "You should now be able to say where the energy in ATP is held, what is released when "
                "it becomes ADP, and how a cell uses that release to pay for work that would not "
                "happen on its own. The question below asks what the cell gains.",
                summary="You can now explain how ATP stores energy and how spending it pays for work.",
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
                ("An **enzyme** is a protein that speeds up one reaction by lowering its **activation "
                 "energy**. The substrate binds at the active site, the reaction happens there, and "
                 "the enzyme comes out unchanged, ready to take the next substrate molecule that "
                 "arrives.", "lec06"),
                ("An enzyme works only while it holds its shape. Catalase, the enzyme in Lab 4, was "
                 "fastest at 37 degrees. Above that optimum it **denatures**: the active site stops "
                 "fitting the substrate and the rate collapses, as the lecture's data below shows.",
                 "lec06", "lab4"),
                summary="An enzyme lowers activation energy and is reused. Above its optimum it "
                        "denatures and the rate collapses.",
                upto="cram",
            ),
            b.prose(
                ("An **enzyme** is a protein that speeds up one reaction by lowering its "
                 "**activation energy**, the push a reaction needs before it will start. The "
                 "**substrate** binds at the enzyme's active site, the reaction happens there, and "
                 "the products leave. The enzyme is not used up. It comes out unchanged and takes "
                 "the next substrate molecule.", "lec06"),
                ("An enzyme works only while it holds its shape. Each one has an optimum temperature "
                 "at which it is fastest. Above the optimum it **denatures**: it loses its folded "
                 "shape, the active site stops fitting the substrate, and the rate collapses. Lab 4 "
                 "measures exactly this, with catalase at six temperatures.", "lec06", "lab4"),
                summary="An enzyme lowers activation energy at its active site and is reused. Above "
                        "its optimum it denatures and stops working.",
                at="standard",
            ),
            b.terms(_C["enzymes"],
                    ("Active site", "The pocket on an enzyme where its substrate binds."),
                    ("Denature", "To lose the folded shape that a protein needs to work.")),
            b.prose(
                ("The lecture's catalase data shows both halves of the story. The rate was 12 "
                 "micromoles of product per minute at 10 degrees, 25 at 20 degrees and 48 at 30 "
                 "degrees, and it peaked at 60 at 37 degrees. Then it fell to 31 at 45 degrees and "
                 "to 4 at 55. Read the chart as two different curves that meet at the optimum. On "
                 "the left, warmer molecules move faster and meet the active site more often, so "
                 "the rate climbs steadily. On the right, the enzyme itself is coming apart, and "
                 "the rate drops far more sharply than it rose.", "lec06"),
                summary="Catalase sped up from 12 at 10 degrees to a peak of 60 at 37 degrees, then "
                        "fell to 4 at 55 as it denatured.",
                at="standard",
            ),
            b.at("cram", b.chart(
                "Catalase activity against temperature", "Temperature (°C)", "Rate (µmol per minute)",
                b.line("Catalase", (10, 12), (20, 25), (30, 48), (37, 60), (45, 31), (55, 4)),
                alt="The rate climbs to a peak near body temperature and then falls sharply as the enzyme denatures.",
                source="lec06",
                markers=(b.marker(37, 60, "37", "60"),),
            )),
            b.prose(
                ("That lopsided shape is what the Lab 4 report asks you to explain, on both sides of "
                 "the optimum, and the wording matters. Below the optimum the enzyme is intact and "
                 "simply slow. Above it the enzyme is denatured, which is a change of shape and not "
                 "a death: an enzyme is a molecule and was never alive. And at every temperature "
                 "the enzyme is a catalyst, so it is never consumed, however much product it has "
                 "made. The two slips below are the ones your quizzes show, and both are slips of "
                 "language that cost marks in a written answer.", "lab4"),
                summary="Below the optimum the enzyme is slow but intact; above it, it is denatured. "
                        "It is never killed and never used up.",
                at="standard",
            ),
            b.mistakes(
                (0, "Saying the enzyme is used up",
                 "An enzyme comes out of the reaction unchanged. Only the substrate is converted."),
                (1, "Saying heat kills the enzyme",
                 "Enzymes are molecules, not organisms. The word is denature: the shape is lost."),
            ),
            b.prose(
                ("Temperature is only one way to stop an enzyme, and the others follow the same "
                 "logic: anything that keeps the substrate out of the active site slows the "
                 "reaction. The wrong pH changes the enzyme's shape much as heat does. A "
                 "**competitive inhibitor** leaves the shape alone and blocks the active site "
                 "itself, by sitting where the substrate should. The difference shows in what "
                 "happens next. A blocked enzyme is undamaged, so adding more substrate crowds the "
                 "inhibitor out and the rate recovers. A denatured enzyme has no working active "
                 "site left, and no amount of substrate will bring the rate back.", "lec06"),
                summary="A competitive inhibitor blocks the active site without damaging the enzyme. "
                        "Denaturing destroys the site, and extra substrate cannot fix that.",
                at="deep",
            ),
            b.prose(
                ("The lab handout adds a second way to think about all this: as an experiment. It "
                 "tells you to keep the amounts of enzyme and substrate the same in every tube, so "
                 "that temperature is the only thing that changes between trials. That is what lets "
                 "you put the change in rate down to temperature. If one tube had more catalase, it "
                 "would make oxygen faster for a reason that has nothing to do with heat. If you "
                 "are shown a flawed version of this design and asked what is wrong with it, look "
                 "for the second thing that changed between the tubes.", "lab4"),
                summary="Lab 4 changes only the temperature and holds the enzyme and substrate "
                        "amounts fixed, so any change in rate is due to temperature.",
                at="deep",
            ),
            b.prose(
                "You should now be able to say what an enzyme does to a reaction, explain both sides "
                "of the temperature curve in the right words, and tell a slowed enzyme from a "
                "denatured one. The question below asks about the falling side of the curve.",
                summary="You can now explain how enzymes work and why the rate falls above the optimum.",
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
                ("A **mitochondrion** is the organelle where most of a cell's ATP is made. It has "
                 "two membranes. The outer one is smooth and encloses the whole organelle. The "
                 "inner one is folded again and again into **cristae**, and the space it encloses "
                 "is the **matrix**. Mitochondria also carry their own small DNA, separate from the "
                 "DNA in the nucleus.", "lec04"),
                ("Those two membranes divide the work of respiration. The citric acid cycle runs in "
                 "the matrix. Oxidative phosphorylation, the stage that makes nearly all the ATP, "
                 "happens on the inner membrane itself. So when a question names a place inside the "
                 "mitochondrion, it is really asking which stage of respiration happens there.",
                 "lec08"),
                summary="A mitochondrion has a smooth outer membrane and a folded inner one around "
                        "the matrix. The inner membrane is where most ATP is made.",
            ),
            b.terms(_C["mitochondria"],
                    ("Cristae", "The folds of the inner mitochondrial membrane."),
                    ("Matrix", "The space inside the inner membrane, where the citric acid cycle runs.")),
            b.prose(
                ("Follow one glucose molecule and the layout falls into place. It is split in the "
                 "cytoplasm, outside the mitochondrion altogether: that is glycolysis, and it needs "
                 "no organelle. The two pyruvate that result are what enter the mitochondrion. In "
                 "the matrix the citric acid cycle strips them down, releases carbon dioxide and "
                 "loads the electron carriers NADH and FADH2. The carriers then hand their "
                 "electrons to the chain in the inner membrane, a short trip from the matrix. Each "
                 "step happens next to the place where its products are needed, which is the point "
                 "of having compartments at all.", "lec08"),
                summary="Glycolysis happens outside the mitochondrion, the citric acid cycle in the "
                        "matrix, and the electron transport chain in the inner membrane.",
                at="deep",
            ),
            b.prose(
                ("The inner membrane is not just a wall to hang machinery on. Oxidative "
                 "phosphorylation works by building a proton gradient: electrons pass down a chain "
                 "to oxygen, and the energy they give up is used to pile protons up on one side of "
                 "the inner membrane. A gradient can exist only if something keeps the two sides "
                 "apart, and the inner membrane is that barrier. The protons can flow back through "
                 "one route, ATP synthase, and that flow is what drives the making of ATP. Take the "
                 "membrane away, or make it leaky, and the gradient is gone, and almost all the ATP "
                 "with it.", "lec08"),
                summary="The inner membrane holds a proton gradient apart, and protons flowing back "
                        "through ATP synthase make the ATP.",
                at="standard",
            ),
            b.prose(
                "That explains the folds. The electron transport chain and ATP synthase are built "
                "into the inner membrane, so the amount of ATP a mitochondrion can make depends on "
                "how much inner membrane it has. Folding packs far more membrane into the same "
                "small organelle than a smooth lining would, in the same way that a crumpled sheet "
                "of paper fits into a space a flat one could not. When a diagram shows cristae, "
                "read them as surface area for making ATP, and expect a cell that spends a lot of "
                "energy to need a lot of that surface.",
                summary="Cristae pack more inner membrane into the organelle, and more inner "
                        "membrane holds more of the machinery that makes ATP.",
                at="standard",
            ),
            b.prose(
                ("Two details from the organelles lecture are easy to lose. First, a mitochondrion "
                 "has two membranes of its own and the cell membrane makes a third, so something "
                 "made in the matrix has several layers to cross before it leaves the cell. Second, "
                 "mitochondria carry their own small DNA. It is separate from the DNA in the "
                 "nucleus, so the nucleus is where the cell keeps its DNA but not the only place "
                 "DNA is found. When you label a diagram, name the outer membrane, the inner "
                 "membrane, the cristae and the matrix, and say in a few words what happens at "
                 "each.", "lec04"),
                summary="A mitochondrion has two membranes of its own and its own small DNA, "
                        "separate from the DNA in the nucleus.",
                at="deep",
            ),
            b.prose(
                "You should now be able to label the outer membrane, the inner membrane, the cristae "
                "and the matrix, say which stage of respiration happens at each, and explain why the "
                "inner membrane has to be both sealed and folded. The question below asks about the "
                "folding.",
                summary="You can now label a mitochondrion and say what happens at each part.",
            ),
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
                ("**Cellular respiration** takes glucose apart in three stages. **Glycolysis** "
                 "happens in the cytoplasm and has a net gain of 2 ATP. The **citric acid cycle** "
                 "runs in the mitochondrial matrix and makes 2 more. Both mainly load the electron "
                 "carriers NADH and FADH2.", "lec08"),
                ("**Oxidative phosphorylation** happens on the inner mitochondrial membrane. "
                 "Electrons from the carriers pass down a chain to oxygen, and the proton gradient "
                 "this builds drives ATP synthase. It makes about 28 ATP, for a total near 32 per "
                 "glucose. Without oxygen the chain stops, and only the 2 ATP of glycolysis are left. "
                 "The example adds it up.", "lec08"),
                summary="Glycolysis and the citric acid cycle make 2 ATP each. Oxidative "
                        "phosphorylation, which needs oxygen, makes about 28.",
                upto="cram",
            ),
            b.prose(
                ("**Cellular respiration** takes glucose apart in three stages and captures the "
                 "energy as ATP. **Glycolysis** happens in the cytoplasm and splits glucose into two "
                 "pyruvate, with a net gain of 2 ATP. The **citric acid cycle** runs in the "
                 "mitochondrial matrix, releases carbon dioxide and makes 2 more ATP. Its main "
                 "product is loaded electron carriers, NADH and FADH2. Each stage has its own place "
                 "in the cell, and knowing the place is half of knowing the stage.", "lec08"),
                ("**Oxidative phosphorylation** is where the payoff comes. On the inner "
                 "mitochondrial membrane, electrons from the carriers pass down a chain to oxygen. "
                 "That builds a proton gradient, and the gradient drives ATP synthase. This stage "
                 "makes about 28 ATP, for a total near 32 per glucose. Without oxygen to take the "
                 "electrons the chain stops, and the cell is left with the 2 ATP of glycolysis.",
                 "lec08"),
                summary="Glycolysis in the cytoplasm and the citric acid cycle in the matrix make 2 "
                        "ATP each. Oxidative phosphorylation on the inner membrane makes about 28.",
                at="standard",
            ),
            b.formula(
                "Respiration, overall",
                r"\mathrm{C_6H_{12}O_6} + 6\,\mathrm{O_2} \rightarrow 6\,\mathrm{CO_2} + 6\,\mathrm{H_2O} + \text{energy}",
                "One glucose plus six oxygen gives six carbon dioxide plus six water plus energy.",
                "lec08",
            ),
            b.prose(
                ("The overall equation hides the order of events, so match each term to a stage. "
                 "Glucose is used up first, in glycolysis. Carbon dioxide comes off in the citric "
                 "acid cycle. Oxygen is not used until the very end, where it accepts the electrons "
                 "at the bottom of the chain, and that is where the water forms. So the oxygen you "
                 "breathe in never touches glucose directly. Keeping the stages and their places "
                 "straight is where your quiz answers have slipped, and the two notes below are "
                 "worth reading before you go on.", "lec08"),
                summary="Glucose is used in glycolysis, carbon dioxide leaves in the citric acid "
                        "cycle, and oxygen is used only at the end of the chain.",
                at="standard",
            ),
            b.mistakes(
                (0, "Putting glycolysis in the mitochondrion",
                 "Glycolysis happens in the cytoplasm. Only what follows it happens inside the mitochondrion."),
                (1, "Giving the citric acid cycle most of the ATP",
                 "The cycle makes 2 ATP. Its main product is NADH and FADH2 for the last stage."),
            ),
            b.prose(
                ("The ATP count tells you what each stage is for. Glycolysis and the citric acid "
                 "cycle make only 2 ATP each, so neither is the cell's main source of energy. Their "
                 "job is to strip electrons from the fuel and hand them to carriers. Those carriers "
                 "are a kind of stored value, and oxidative phosphorylation cashes them in: about "
                 "28 ATP, seven times what the first two stages make together. Work through the "
                 "example and notice how the total divides, because where most of the ATP comes "
                 "from is one of the most direct questions this topic allows.", "lec08"),
                summary="The first two stages make 4 ATP between them and load the carriers. "
                        "Oxidative phosphorylation turns the carriers into about 28 more.",
                at="standard",
            ),
            b.at("cram", b.example(
                "Count the ATP from one glucose",
                "About how much ATP does one glucose yield when oxygen is present, stage by stage?",
                ("Glycolysis", "2 ATP", "Net gain, made in the cytoplasm."),
                ("Citric acid cycle", "2 ATP", "Made in the matrix, one per turn and two turns per glucose."),
                ("Oxidative phosphorylation", "about 28 ATP", "Driven by the proton gradient across the inner membrane."),
                ("Total", "about 32 ATP", "Nearly all of it depends on oxygen."),
                source="lec08",
            )),
            b.prose(
                ("Why does everything depend on oxygen, when oxygen appears only at the last step? "
                 "Because the chain is a queue. Each electron can move along only if the one ahead of "
                 "it has moved off the end, and oxygen is what takes electrons off the end. Remove "
                 "oxygen and the chain fills up and stops. The carriers can no longer unload, so the "
                 "citric acid cycle, which needs empty carriers to load, stops as well. Glycolysis is "
                 "the only stage left running, and the yield falls from about 32 ATP per glucose to "
                 "2.", "lec08"),
                ("A second way to see the last stage is to follow the energy and not the molecules. "
                 "The energy starts in the bonds of glucose. The first two stages move it onto the "
                 "electron carriers. The chain then spends it a little at a time to pump protons "
                 "across the inner membrane, so for a moment the energy is stored as a gradient, a "
                 "crowd of protons on one side that would flow back if they could. ATP synthase is "
                 "the only door, and the protons pushing through it supply the energy that joins ADP "
                 "to phosphate. So ATP is made by that flow and not by the chain itself, which is why "
                 "the inner membrane has to stay sealed.", "lec08"),
                summary="Oxygen clears electrons off the end of the chain, so without it everything "
                        "but glycolysis stops. Protons flowing through ATP synthase make the ATP.",
                at="deep",
            ),
            b.prose(
                "Respiration pulls together most of this unit, which is what the map shows. ATP is "
                "its product. Every step is run by an enzyme, so everything you know about "
                "temperature and enzyme shape applies to respiration as a whole. The mitochondrion "
                "is where two of the three stages happen, and its folded inner membrane is what "
                "makes the last stage possible. Photosynthesis comes next, and it runs the overall "
                "equation in the opposite direction.",
                summary="Respiration makes ATP, runs on enzymes and depends on the mitochondrion. "
                        "Photosynthesis runs the same equation in reverse.",
                at="deep",
            ),
            b.at("deep", b.concept_map(
                "What respiration draws on",
                (_C["atp"], "Foundations"), (_C["enzymes"], "Foundations"),
                (_C["mitochondria"], "Before this"), (_C["respiration"], "This section"),
                (_C["photosynthesis"], "Up next"),
            )),
            b.prose(
                "You should now be able to name the three stages in order, say where in the cell each "
                "one happens, give the ATP each one makes, and explain why nearly all of it depends "
                "on oxygen. The question below asks for one of those places.",
                summary="You can now place each stage, give its ATP yield and say why oxygen matters.",
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
                ("**Photosynthesis** uses light energy to build sugar from carbon dioxide and water, "
                 "and it runs in two stages. The **light reactions** happen in the thylakoid "
                 "membranes of the chloroplast. They split water, release oxygen, and store the "
                 "light's energy in two short-lived molecules, ATP and NADPH. Nothing has been "
                 "built yet at this point. The energy has only changed form.", "lec10"),
                ("The **Calvin cycle** happens in the stroma, the fluid around the thylakoids. It "
                 "uses that ATP and NADPH to fix carbon dioxide into sugar. It does not need light "
                 "directly, but it stops soon after the light does, because it runs on what the "
                 "light reactions supply. One stage captures energy and the other spends it on "
                 "building.", "lec10"),
                summary="The light reactions split water and make ATP, NADPH and oxygen. The Calvin "
                        "cycle uses the ATP and NADPH to turn carbon dioxide into sugar.",
            ),
            b.formula(
                "Photosynthesis, overall",
                r"6\,\mathrm{CO_2} + 6\,\mathrm{H_2O} + \text{light} \rightarrow \mathrm{C_6H_{12}O_6} + 6\,\mathrm{O_2}",
                "Six carbon dioxide plus six water plus light gives one glucose plus six oxygen.",
                "lec10",
            ),
            b.prose(
                ("Use the two stages to take the overall equation apart, because the equation on "
                 "its own misleads. Water goes in at the light reactions, where it is split, and "
                 "the oxygen gas a plant gives off is what is left of that water. Carbon dioxide "
                 "goes in at the Calvin cycle, and its carbon and oxygen end up in the sugar. So "
                 "the oxygen released does not come from carbon dioxide, even though the equation "
                 "puts carbon dioxide on one side and oxygen on the other. Ask of each term which "
                 "stage handles it, and the question answers itself.", "lec10"),
                summary="Water is split in the light reactions and its oxygen is released. Carbon "
                        "dioxide enters at the Calvin cycle and ends up in sugar.",
                at="standard",
            ),
            b.prose(
                ("What sets the rate is whichever input is scarcest. In dim light, light is the "
                 "limit: give the plant more and it speeds up. In bright light the curve levels "
                 "off, because the light reactions are now supplying ATP and NADPH faster than the "
                 "Calvin cycle can use them, and carbon dioxide has become the scarce input. Past "
                 "that point more light changes nothing. The chart shows the shape of this, not "
                 "measured values. Switch it to Extra CO2 and see which part of the curve moves and "
                 "which part stays where it was.", "lec10"),
                summary="In dim light, light limits the rate. In bright light the curve levels off "
                        "because carbon dioxide runs short.",
                at="standard",
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
            b.prose(
                "Take one idea away from the chart: a limiting factor is found by what happens when "
                "you add more of something. The left end of the curve barely moves when carbon "
                "dioxide is added, so light was the limit there. The plateau rises, so carbon "
                "dioxide was the limit there. The same test works on any graph of this kind. The "
                "table then sets photosynthesis beside respiration. Its gas rows are the ones to "
                "learn, since the gas each process uses is the gas the other releases.",
                summary="Adding more of an input raises the rate only where that input was the "
                        "limit. Photosynthesis and respiration swap gases.",
                at="standard",
            ),
            b.compare(
                "Photosynthesis and respiration", ("Photosynthesis", "Respiration"),
                ("Energy", "Stores light energy in sugar", "Releases the energy in sugar as ATP"),
                ("Gas used", "Carbon dioxide", "Oxygen"),
                ("Gas released", "Oxygen", "Carbon dioxide"),
                ("Organelle", "Chloroplast", "Mitochondrion"),
                emphasis=2,
            ),
            b.prose(
                "The table makes the two processes look like one film run forwards and backwards, and "
                "for the overall equation that is right. It is not right in the details. They happen "
                "in different organelles, the chloroplast and the mitochondrion. Each uses its own "
                "electron carrier, NADPH in photosynthesis and NADH and FADH2 in respiration. And a "
                "plant does not choose between them. Its cells respire all the time, in light and in "
                "darkness, because the sugar made in the chloroplast is only stored energy until "
                "respiration turns it into ATP that the rest of the cell can spend.",
                "Why two stages and two carriers? Building sugar from carbon dioxide needs two things "
                "that light cannot hand over directly: energy, and electrons to add to the carbon. "
                "ATP brings the energy and NADPH brings the electrons, and both are made in the "
                "thylakoid membranes and used a short distance away in the stroma. This is the "
                "pattern of respiration turned around. There, carriers are loaded by breaking fuel "
                "down and unloaded at a membrane to make ATP. Here, carriers are loaded at a membrane "
                "using light and unloaded to build fuel.",
                ("One phrase from the slides needs care: the Calvin cycle does not need light "
                 "directly. That does not make it a night-time process. It means only that none of "
                 "its steps absorbs light. It still depends on a steady supply of ATP and NADPH, and "
                 "the cell keeps no large store of them, so in a real leaf the cycle runs in daylight "
                 "beside the light reactions and slows to a stop in the dark. The reason is the "
                 "missing ATP and NADPH, not the missing light itself.", "lec10"),
                summary="The two processes mirror each other overall but use different organelles and "
                        "carriers. The Calvin cycle absorbs no light, yet stops in the dark.",
                at="deep",
            ),
            b.prose(
                "You should now be able to say what each stage takes in and gives out, trace the "
                "atoms of the overall equation to the right stage, and read a rate graph for its "
                "limiting factor. The question below is the classic one for this topic, so answer it "
                "from the stages and not from the equation.",
                summary="You can now give each stage's inputs and outputs and find a limiting factor on a graph.",
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
                ("DNA replication copies both strands of the double helix so that each new cell gets "
                 "a full copy. It is **semiconservative**: each new double helix keeps one old "
                 "strand and gains one new strand. The old strand is the template and the new one "
                 "is built against it base by base, so every new strand has an original to be "
                 "matched against.", "lec12"),
                ("Three enzymes do the work at the **replication fork**. **Helicase** unwinds the "
                 "helix. Primase lays down a short RNA primer, because the next enzyme cannot start "
                 "from nothing. **DNA polymerase** then adds nucleotides, but only to the 3 prime "
                 "end of a growing strand. That one restriction shapes everything else about "
                 "replication.", "lec12"),
                summary="Each new helix keeps one old strand and gains a new one. Helicase unwinds, "
                        "primase primes, and DNA polymerase extends only a 3 prime end.",
            ),
            b.prose(
                ("Here is why the restriction matters. The two strands of a helix run in opposite "
                 "directions, and the fork opens along both at once. On one template, polymerase "
                 "can follow the fork as it opens and build without stopping. That new strand is "
                 "the **leading strand**, made in one piece toward the fork. On the other template "
                 "the only direction polymerase can build in points away from the fork. So it has "
                 "to wait for a stretch to open, build back across it, and start again further "
                 "along. That is the **lagging strand**, made in short Okazaki fragments, which "
                 "ligase then joins into one.", "lec12"),
                summary="The leading strand is built continuously toward the fork. The lagging "
                        "strand is built away from it in Okazaki fragments that ligase joins.",
                at="standard",
            ),
            b.compare(
                "Leading and lagging strands", ("Leading strand", "Lagging strand"),
                ("Built", "Continuously", "In Okazaki fragments"),
                ("Direction", "Toward the fork", "Away from the fork"),
                ("Primers needed", "One", "One per fragment"),
                emphasis=0,
            ),
            b.prose(
                "Every row of the table is the same fact seen from a different side, and the row "
                "about how each strand is built is the one to be able to explain. Continuous or in "
                "fragments is not a property of the strand itself. It follows from the direction "
                "the template runs in and the one direction polymerase works in. The primer row "
                "follows too: each fragment is a fresh start, and every start needs its own primer. "
                "If you find yourself drawing polymerase building toward the fork on both strands, "
                "stop, because that picture is the slip your quiz history shows.",
                summary="Whether a strand is continuous or in fragments follows from polymerase's "
                        "one direction. Each fragment needs its own primer.",
                at="standard",
            ),
            b.mistakes(
                (0, "Letting polymerase build both ways",
                 "DNA polymerase only extends a 3 prime end. That one rule explains the lagging strand."),
            ),
            b.prose(
                "A good way to hold all this is to learn to draw the fork. Mark the direction of each "
                "template strand. Put helicase at the point where the helix opens. Draw the leading "
                "strand as one long arrow pointing into the fork, and the lagging strand as several "
                "short arrows pointing away from it, each beginning with a primer. Then add ligase at "
                "the gaps between fragments. If the arrows on the new strands all point from 5 prime "
                "to 3 prime, the drawing is right. You should now be able to answer most questions "
                "about replication by reading it, starting with the one below.",
                summary="Draw the fork: one long arrow into it for the leading strand and short arrows "
                        "away from it for the lagging strand.",
                at="standard",
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
                ("**Transcription** copies one gene from DNA into a strand of messenger RNA. The "
                 "enzyme that does it, **RNA polymerase**, binds at the **promoter**, a stretch of DNA "
                 "that marks where a gene begins, and unwinds a short stretch of the helix. Only that "
                 "stretch opens. The rest of the DNA stays closed and is not copied.", "lec13"),
                ("The polymerase then reads one of the two strands, the **template strand**, and "
                 "builds RNA with complementary bases. The pairing follows the usual rules with one "
                 "change: RNA uses uracil where DNA would use thymine. So an A on the template is "
                 "matched by a U in the RNA, and the finished message has no T in it at all.", "lec13"),
                "Writing out a transcript by hand takes three steps, and the example goes through "
                "them. Pair each base of the template with its partner, using U in place of T. Write "
                "those partners in order. Then label the ends, which is the step that gets skipped: "
                "the new strand runs in the opposite direction to its template, so a template written "
                "3 prime to 5 prime gives RNA written 5 prime to 3 prime. The same letters read "
                "backwards are a different message.",
                summary="RNA polymerase starts at a promoter and builds mRNA complementary to the "
                        "template, with U for T. Write the RNA 5 prime to 3 prime.",
            ),
            b.example(
                "Transcribe a template",
                "The DNA template strand reads 3'-TACGGT-5'. What mRNA is made?",
                ("Pair each base", "T-A, A-U, C-G, G-C, G-C, T-A", "RNA pairs A with U, never with T."),
                ("Write the RNA", "AUGCCA", "Read the pairs in order."),
                ("Add the direction", "5'-AUGCCA-3'", "The new strand runs opposite to the template."),
                source="lec13",
            ),
            b.prose(
                "It helps to compare this with replication, since the two are easy to blur. Both "
                "read a DNA template and build a complementary strand. But replication copies all "
                "of the DNA, both strands, once for each cell division, and its product is DNA. "
                "Transcription copies one gene, from one strand, as often as the cell needs the "
                "message, and its product is RNA. That last difference is where the uracil comes "
                "in, and writing a T into a transcript is the slip from your quizzes. Check every "
                "RNA sequence you write for a stray T before you move on.",
                summary="Replication copies all the DNA into DNA. Transcription copies one gene from "
                        "one strand into RNA, which has U and no T.",
                at="standard",
            ),
            b.mistakes(
                (0, "Writing T into the RNA",
                 "RNA has no thymine. Wherever the template has A, the RNA gets U."),
            ),
            b.prose(
                ("In eukaryotes the transcript is not ready to use as soon as it is made. It is "
                 "processed first: a cap is added at one end and a tail at the other, and the "
                 "introns are spliced out before the message leaves the nucleus. Only then does it "
                 "go on to be read. The map shows the chain this belongs to. Replication keeps the "
                 "DNA, transcription copies a gene out of it, and translation, which comes next, "
                 "reads that copy to build a protein.", "lec13"),
                summary="In eukaryotes the RNA gets a cap and a tail and has its introns spliced out "
                        "before it leaves the nucleus.",
                at="standard",
            ),
            b.concept_map(
                "From gene to protein",
                (_C["dna"], "Before this"), (_C["transcription"], "This section"),
                (_C["translation"], "Up next"), (_C["regulation"], "Later"),
            ),
            b.prose(
                "You should now be able to say where transcription starts, write the RNA for a given "
                "template with its direction marked, and list what happens to the transcript before "
                "it leaves the nucleus. The question below checks the one base that changes.",
                summary="You can now transcribe a template and describe how the transcript is processed.",
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
                ("The **cell cycle** is the ordered series of steps that makes two cells from one. "
                 "It has four phases, always in the same order. In **G1** the cell grows. In **S** "
                 "it copies its DNA. In **G2** it prepares to divide. In **M** it divides. The "
                 "first three together are called interphase, and they take up most of the cycle.",
                 "lec14"),
                ("The cycle does not simply run on a timer. **Checkpoints** stop it when something "
                 "is wrong, such as damaged DNA or a chromosome that is not attached to the "
                 "spindle. A cell held at a checkpoint has time to repair the problem before it "
                 "moves on, so that a fault is not passed to both daughter cells.", "lec14"),
                summary="The cycle runs G1, S, G2, then M: grow, copy the DNA, prepare, divide. "
                        "Checkpoints stop it when something is wrong.",
            ),
            b.terms(_C["cellcycle"],
                    ("Interphase", "G1, S and G2 together: all of the cycle except division."),
                    ("S phase", "The phase in which the cell copies its DNA."),
                    ("Checkpoint", "A control point that stops the cycle until a condition is met.")),
            b.prose(
                "The order is not arbitrary, and you can rebuild it by asking what each phase needs "
                "from the one before. A cell has to grow before it copies its DNA, or each division "
                "would leave smaller cells. It has to copy its DNA before it divides, or one "
                "daughter would go without. And it needs a pause between copying and dividing, to "
                "check the copy and get the machinery for division ready. That is G1, S, G2 and M "
                "in order. If you can say why S must come before M, you do not need to memorise "
                "the sequence.",
                summary="Each phase supplies what the next one needs: growth before copying, copying "
                        "before dividing, and a check in between.",
                at="standard",
            ),
            b.prose(
                ("The two checkpoints the slides mention guard the two things that must not go "
                 "wrong. Damaged DNA must not be copied or handed on, so the cycle stops until it "
                 "is repaired. And every chromosome must be attached to the spindle before the "
                 "copies are pulled apart, or the two new cells will not get equal sets. The cycle "
                 "also links the last two topics of the course: the S phase is DNA replication, and "
                 "the M phase is the mitosis described in the next section. Keep the difference in "
                 "view. The cell cycle is the whole loop, and mitosis is one part of it.", "lec14"),
                summary="Checkpoints catch damaged DNA and unattached chromosomes. The cell cycle is "
                        "the whole loop; mitosis is only its M phase.",
                at="standard",
            ),
            b.prose(
                "You should now be able to name the four phases in order, say what happens in each, "
                "and explain what a checkpoint is for. The question below asks for one phase by what "
                "it does, so think about what the letter stands for.",
                summary="You can now name the four phases and say what each is for.",
            ),
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
                ("**Mitosis** separates the copied chromosomes into two identical nuclei, and it has "
                 "four steps. In prophase the chromosomes condense into compact, visible shapes. In "
                 "metaphase they line up across the middle of the cell. In anaphase the sister "
                 "chromatids separate and move to opposite ends. In telophase a nucleus forms around "
                 "each group.", "lec14"),
                "By the time mitosis begins, the DNA has already been copied. Each chromosome is "
                "therefore two identical **sister chromatids**, joined together. Mitosis makes no new "
                "DNA. Its whole job is to pull each pair of sisters apart and send one to each side, "
                "so that the two new nuclei get exactly the same set. The cytoplasm then divides, in "
                "**cytokinesis**, and there are two cells.",
                "The counting is where this topic gets hard, and it turns on two words. A chromatid "
                "is one copy of a chromosome's DNA. Two sister chromatids that are still joined count "
                "as one chromosome, and once anaphase pulls them apart each counts as a chromosome of "
                "its own. That is why the chromosome count seems to double for a moment and then "
                "returns to where it started in each new cell. Keep two running totals as you work "
                "the example, one for chromosomes and one for chromatids.",
                summary="Mitosis runs prophase, metaphase, anaphase, telophase and separates the sister "
                        "chromatids. Joined sisters count as one chromosome, separated ones as one each.",
            ),
            b.example(
                "Follow the chromosomes",
                "A human cell has 46 chromosomes. How many does each daughter cell have after mitosis?",
                ("After S phase", "46 chromosomes, 92 chromatids", "Each chromosome is now two sister chromatids."),
                ("Anaphase", "92 separate chromatids", "The sisters are pulled to opposite ends, 46 each way."),
                ("After cytokinesis", "46 in each cell", "Both cells match the parent."),
                source="lec14",
            ),
            b.prose(
                "To tell the steps apart, in a diagram or under a microscope, look at where the "
                "chromosomes are and ignore everything else at first. Scattered threads that are "
                "just becoming visible mean prophase. A single row across the middle means "
                "metaphase. Two groups moving apart mean anaphase. Two separate clusters, with the "
                "cell starting to pinch in, mean telophase. The table gives each step with its "
                "tell-tale sign. Anaphase is the row to know best, because it is the moment the "
                "copies part, and questions about what goes wrong in mitosis nearly always come "
                "back to it.",
                summary="Identify a step by where the chromosomes are: scattered, in a row, moving "
                        "apart, or in two clusters.",
                at="standard",
            ),
            b.compare(
                "The four steps", ("What happens", "How to spot it"),
                ("Prophase", "Chromosomes condense", "Visible threads, nucleus fading"),
                ("Metaphase", "Chromosomes line up", "A row across the middle"),
                ("Anaphase", "Sister chromatids separate", "Two groups moving apart"),
                ("Telophase", "Two nuclei form", "Two clusters, cell pinching"),
                emphasis=2,
            ),
            b.prose(
                ("The checkpoints from the last section explain the order of these steps. The "
                 "chromosomes line up in metaphase so that every one of them can be attached to the "
                 "spindle from both sides, and the cell waits there until they all are, because a "
                 "chromosome that is not attached cannot be pulled apart evenly. Only then does "
                 "anaphase begin. The row across the middle is the checkpoint doing its work, and it "
                 "is why the two new cells end up with matching sets.", "lec14"),
                summary="Chromosomes line up in metaphase so each can be attached to the spindle, and "
                        "anaphase waits until all of them are.",
                at="standard",
            ),
            b.prose(
                "You should now be able to put the four steps in order, recognise each from where the "
                "chromosomes are, and keep count of chromosomes and chromatids from one cell to two. "
                "The question below asks for the step in which the copies part.",
                summary="You can now order the four steps, recognise each and count the chromosomes.",
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
