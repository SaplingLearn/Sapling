"""BIO110's concept tree: the units and the concepts under them. Its own
module because the class's documents and coursework (``bio110.py``) and its
study guides (``bio110_guides.py``) both read it."""
from __future__ import annotations

from db.local_study_data.spec import Concept

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
