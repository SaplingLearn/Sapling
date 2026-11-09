"""Health Science seed pack (BU Sargent pre-nursing / health track).

Student profile: strong on the people-and-systems side (Health Professions,
Nutrition), shaky on the quantitative side of Epidemiology, and mid-way
through the memorisation grind of Gross Anatomy.
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
# SAR HP 151 — Introduction to Health Professions
# ---------------------------------------------------------------------------

HP151 = Course(
    code="SAR HP 151",
    name="Introduction to Health Professions",
    department="Health Sciences",
    nickname="Health Professions",
    color="#0EA5A4",
    concepts=[
        Concept(name="Interprofessional Collaboration", mastery=0.96,
                description="How nurses, PTs, OTs, SLPs, dietitians and physicians share a care plan, "
                            "communicate with SBAR, and divide responsibility on a patient team."),
        Concept(name="Scope of Practice", mastery=0.81,
                description="The legally defined set of procedures and decisions a licensed professional "
                            "may perform, set by state practice acts and professional boards."),
        Concept(name="HIPAA and Patient Privacy", mastery=0.78,
                description="The Privacy Rule's protection of PHI, the minimum-necessary standard, and when "
                            "disclosure is allowed for treatment, payment and operations."),
        Concept(name="Social Determinants of Health", mastery=0.66,
                description="Non-medical conditions — housing, income, education, food access, transportation "
                            "— that drive most variation in health outcomes."),
        Concept(name="Healthcare Delivery Systems", mastery=0.55,
                description="Levels of care (primary, secondary, tertiary, post-acute), care settings, and how "
                            "a patient moves between them."),
        Concept(name="Evidence-Based Practice", mastery=0.48,
                description="Integrating best research evidence with clinical expertise and patient values; "
                            "PICO questions and the levels-of-evidence pyramid."),
        Concept(name="Health Insurance and Payers", mastery=0.31,
                description="Medicare Parts A–D, Medicaid, private insurance, deductibles vs copays vs "
                            "coinsurance, and fee-for-service vs value-based payment."),
        Concept(name="Licensure and Credentialing", mastery=0.18,
                description="The difference between licensure, certification and registration, and the "
                            "accrediting bodies and board exams behind each profession."),
        Concept(name="Quality Improvement and PDSA", mastery=0.05,
                description="Plan-Do-Study-Act cycles, process measures vs outcome measures, and how "
                            "hospitals track patient-safety indicators."),
    ],
    edges=[
        Edge(source="Scope of Practice", target="Interprofessional Collaboration", relationship="prerequisite", strength=0.8),
        Edge(source="Licensure and Credentialing", target="Scope of Practice", relationship="related", strength=0.85),
        Edge(source="Healthcare Delivery Systems", target="Health Insurance and Payers", relationship="related", strength=0.7),
        Edge(source="Evidence-Based Practice", target="Quality Improvement and PDSA", relationship="prerequisite", strength=0.75),
        Edge(source="Social Determinants of Health", target="Healthcare Delivery Systems", relationship="related", strength=0.5),
        Edge(source="HIPAA and Patient Privacy", target="Interprofessional Collaboration", relationship="related", strength=0.55),
    ],
    mastery_events=[
        MasteryEvent(concept="Interprofessional Collaboration", delta=0.15, reason="Aced the team case study"),
        MasteryEvent(concept="HIPAA and Patient Privacy", delta=0.12, reason="Quiz: 4/4 on privacy scenarios"),
        MasteryEvent(concept="Health Insurance and Payers", delta=-0.08, reason="Mixed up coinsurance and copay on quiz"),
        MasteryEvent(concept="Evidence-Based Practice", delta=0.1, reason="Tutor session on PICO questions"),
    ],
    categories=[
        Category(name="Assignments", weight=0.4),
        Category(name="Exams", weight=0.45),
        Category(name="Participation", weight=0.15),
    ],
    assignments=[
        Assignment(title="Profession Shadowing Reflection", category="Assignments", type="homework",
                   due_offset_days=14, points_possible=20, points_earned=19),
        Assignment(title="HIPAA Case Scenarios Worksheet", category="Assignments", type="homework",
                   due_offset_days=28, points_possible=25, points_earned=23),
        Assignment(title="Interprofessional Team Case Study", category="Assignments", type="project",
                   due_offset_days=42, points_possible=50, points_earned=47),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=55, points_possible=100, points_earned=86, is_midterm=True),
        Assignment(title="Health Professions Panel Reflection", category="Participation", type="other",
                   due_offset_days=63, points_possible=10, points_earned=10),
        Assignment(title="Insurance and Payer Systems Worksheet", category="Assignments", type="homework",
                   due_offset_days=74, points_possible=25),
        Assignment(title="Career Pathway Portfolio", category="Assignments", type="project",
                   due_offset_days=95, points_possible=50),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=108, points_possible=100),
    ],
    notes=[
        Note(
            title="Scope of practice — who can do what",
            tags=["scope", "licensure", "midterm"],
            concepts=["Scope of Practice", "Licensure and Credentialing"],
            body=(
                "## Scope of practice\n\n"
                "Defined by **state practice acts**, not by the hospital. Same title can mean different "
                "scope in different states (e.g. NP full practice authority in MA since 2021 vs reduced "
                "practice elsewhere).\n\n"
                "**Examples from lecture**\n"
                "- RN: assess, plan, administer meds under an order, educate. Cannot diagnose medically.\n"
                "- LPN: works under RN supervision, no initial assessments.\n"
                "- PT: evaluate and treat movement dysfunction; direct access in MA (no referral needed).\n"
                "- OT: ADLs and IADLs, adaptive equipment, return to work.\n"
                "- RD: medical nutrition therapy, can write diet orders where delegated.\n\n"
                "## Licensure vs certification vs registration\n"
                "- **Licensure** = state permission to practice; illegal to practice without it (RN, PT).\n"
                "- **Certification** = voluntary, from a professional body, shows advanced competence "
                "(CCRN, board-certified specialist).\n"
                "- **Registration** = listing on an official roster (RD via CDR).\n\n"
                "Still fuzzy: which bodies *accredit programs* (CCNE, CAPTE, ACOTE) vs which *license people*. "
                "Ask in office hours."
            ),
        ),
        Note(
            title="Social determinants — Healthy People 2030 domains",
            tags=["SDOH", "equity"],
            concepts=["Social Determinants of Health", "Healthcare Delivery Systems"],
            body=(
                "Healthy People 2030 groups SDOH into **five domains**:\n\n"
                "1. Economic stability — employment, food insecurity, housing instability\n"
                "2. Education access and quality — health literacy, early childhood education\n"
                "3. Health care access and quality — insurance coverage, primary care access\n"
                "4. Neighborhood and built environment — air/water quality, transportation, violence\n"
                "5. Social and community context — discrimination, incarceration, civic participation\n\n"
                "Key stat from lecture: medical care accounts for roughly **10–20%** of modifiable "
                "contributors to health outcomes; the rest is behavior, social and economic factors, and "
                "environment.\n\n"
                "Boston example: the life-expectancy gap between Back Bay and Roxbury is about "
                "**20+ years** despite being a few miles apart. Both neighborhoods are close to major "
                "academic medical centers, so access to hospitals alone doesn't explain it.\n\n"
                "Connection to practice: screening tools like the PRAPARE questionnaire let clinics ask "
                "about housing and food at intake and refer to community health workers."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="hp151-syllabus.pdf",
            category="syllabus",
            summary="Course syllabus for SAR HP 151: an overview of the health professions, the US healthcare "
                    "system, ethics and privacy, and interprofessional practice, with grading breakdown and "
                    "weekly schedule.",
            concept_notes=[
                ConceptNote(name="Interprofessional Collaboration", description="Anchors the team case study in weeks 5–6."),
                ConceptNote(name="Scope of Practice", description="Covered with professional panels in weeks 2–4."),
                ConceptNote(name="Health Insurance and Payers", description="Weeks 9–10 on financing the US system."),
                ConceptNote(name="HIPAA and Patient Privacy", description="Week 4, with a case-scenario worksheet."),
            ],
            extracted_text=(
                "SAR HP 151 Introduction to Health Professions — Fall Syllabus\n"
                "Boston University, College of Health & Rehabilitation Sciences: Sargent College\n\n"
                "Course Description: This course introduces students to the roles, education, and scope of "
                "practice of health professionals including nursing, physical therapy, occupational therapy, "
                "speech-language pathology, nutrition, athletic training, and public health. Students examine "
                "how the US health care system is organized and financed, the ethical and legal framework "
                "for practice, and the skills required for effective interprofessional teamwork.\n\n"
                "Learning Objectives: By the end of the course students will be able to (1) compare the "
                "education, licensure, and scope of practice of at least six health professions; "
                "(2) describe the levels of care and major payers in the US system; (3) apply HIPAA and "
                "core ethical principles (autonomy, beneficence, nonmaleficence, justice) to case "
                "scenarios; (4) explain how social determinants of health shape outcomes.\n\n"
                "Grading: Assignments 40% | Exams 45% | Participation 15%\n\n"
                "Schedule (abbreviated)\n"
                "Wk 1  The health care workforce; why teams matter\n"
                "Wk 2-3  Professional panels: Nursing, PT, OT, SLP\n"
                "Wk 4  Ethics, HIPAA and patient privacy\n"
                "Wk 5-6  Interprofessional collaboration; SBAR communication\n"
                "Wk 7  Social determinants of health\n"
                "Wk 8  MIDTERM EXAM\n"
                "Wk 9-10  Financing care: Medicare, Medicaid, private insurance\n"
                "Wk 11  Evidence-based practice and quality improvement\n"
                "Wk 12-13  Licensure, credentialing, career pathways\n"
                "Wk 14  Review; portfolio due"
            ),
        ),
        Document(
            file_name="hp151-week9-financing-care.pdf",
            category="lecture_notes",
            summary="Lecture slides on how US health care is paid for: the parts of Medicare, Medicaid "
                    "eligibility, cost-sharing terms, and the shift from fee-for-service to value-based payment.",
            concept_notes=[
                ConceptNote(name="Health Insurance and Payers", description="Medicare A/B/C/D and Medicaid eligibility."),
                ConceptNote(name="Cost sharing", description="Deductible, copay and coinsurance defined with a worked example."),
                ConceptNote(name="Value-based payment", description="ACOs and bundled payments versus fee-for-service."),
            ],
            extracted_text=(
                "Week 9 — Financing Health Care in the United States\n\n"
                "Medicare (federal, age 65+ or qualifying disability, ESRD)\n"
                "  Part A: hospital insurance — inpatient stays, skilled nursing after a 3-day admission, hospice\n"
                "  Part B: medical insurance — physician visits, outpatient care, PT/OT, durable equipment\n"
                "  Part C: Medicare Advantage — private plans that bundle A and B (often D)\n"
                "  Part D: outpatient prescription drugs\n\n"
                "Medicaid (joint federal-state, means-tested)\n"
                "  Eligibility varies by state; ACA expansion covers adults up to 138% of the federal poverty level\n"
                "  Largest single payer for births and long-term nursing home care\n\n"
                "Cost sharing — know these for the worksheet\n"
                "  Premium: what you pay monthly to have the plan\n"
                "  Deductible: what you pay out of pocket before the plan pays\n"
                "  Copay: fixed amount per service (e.g. $25 per PT visit)\n"
                "  Coinsurance: percentage you pay after the deductible (e.g. 20%)\n"
                "  Example: $1,000 deductible, 20% coinsurance, $3,000 bill -> patient pays $1,000 + 0.20 x $2,000 = $1,400\n\n"
                "Payment models\n"
                "  Fee-for-service rewards volume\n"
                "  Value-based care ties payment to outcomes: Accountable Care Organizations, bundled payments "
                "for a joint replacement episode, readmission penalties (HRRP)"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="What does SBAR stand for?", back="Situation, Background, Assessment, Recommendation — a structured handoff format."),
        Flashcard(front="Licensure vs certification?", back="Licensure is state permission required to practice; certification is voluntary recognition of advanced competence by a professional body."),
        Flashcard(front="HIPAA minimum-necessary standard", back="Use or disclose only the least PHI needed for the purpose — does not apply to disclosures for treatment."),
        Flashcard(front="Medicare Part A vs Part B", back="Part A = hospital/inpatient, SNF, hospice. Part B = physician and outpatient services, including outpatient PT/OT."),
        Flashcard(front="Coinsurance", back="The percentage of a covered cost the patient pays after meeting the deductible (e.g. 20%)."),
        Flashcard(front="Five Healthy People 2030 SDOH domains", back="Economic stability; education access; health care access; neighborhood and built environment; social and community context."),
        Flashcard(front="PICO", back="Population/Patient, Intervention, Comparison, Outcome — the template for a searchable clinical question."),
        Flashcard(front="Direct access (PT)", back="A patient can see a physical therapist without a physician referral; allowed in Massachusetts."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers weeks 1–7: the professions and their scopes, ethics and HIPAA, "
                 "interprofessional teamwork, and social determinants of health. Expect short case "
                 "scenarios where you identify which professional acts and whether a disclosure is allowed.",
        topics=[
            StudyGuideTopic(name="Professions and scope", importance="Roughly a third of the exam; panel content is fair game.",
                            concepts=["Scope of Practice", "Licensure and Credentialing"]),
            StudyGuideTopic(name="Privacy and ethics", importance="Case scenarios — know when PHI can be shared.",
                            concepts=["HIPAA and Patient Privacy"]),
            StudyGuideTopic(name="Teams and communication", importance="One long-answer question on the team case.",
                            concepts=["Interprofessional Collaboration"]),
            StudyGuideTopic(name="Social determinants", importance="Short answer applying the five domains to a patient.",
                            concepts=["Social Determinants of Health"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="HIPAA and Patient Privacy", difficulty="medium", days_ago=40, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(question="A nurse calls a patient's cardiologist to coordinate discharge meds. Under HIPAA this disclosure is:",
                             options=["Permitted as treatment without written authorization", "Allowed only with signed authorization",
                                      "Prohibited unless the patient is present", "Permitted only to family members"],
                             correct_answer="Permitted as treatment without written authorization",
                             explanation="Treatment, payment and health care operations disclosures do not need authorization."),
                QuizQuestion(question="Which is NOT protected health information?",
                             options=["A patient's diagnosis in the chart", "A billing record with the patient's name",
                                      "Aggregate de-identified admission counts", "A voicemail with an appointment reminder and name"],
                             correct_answer="Aggregate de-identified admission counts",
                             explanation="Properly de-identified data is no longer PHI."),
                QuizQuestion(question="The minimum-necessary standard does NOT apply to disclosures for:",
                             options=["Treatment", "Payment", "Health care operations", "Research"],
                             correct_answer="Treatment",
                             explanation="Providers treating the patient may need the full record."),
                QuizQuestion(question="A student posts a de-identified-looking story about a rare case on social media. The main risk is:",
                             options=["Re-identification from rare details", "Copyright infringement", "Violating scope of practice", "None, it is anonymous"],
                             correct_answer="Re-identification from rare details",
                             explanation="Rare conditions plus dates or locations can identify a patient."),
            ],
        ),
        QuizAttempt(
            concept="Health Insurance and Payers", difficulty="medium", days_ago=6, correct=[0, 2],
            questions=[
                QuizQuestion(question="Medicare Part D covers:",
                             options=["Outpatient prescription drugs", "Inpatient hospital stays", "Physician visits", "Long-term custodial care"],
                             correct_answer="Outpatient prescription drugs",
                             explanation="Part D is the drug benefit."),
                QuizQuestion(question="A plan has a $500 deductible (already met) and 20% coinsurance. For a $300 visit the patient pays:",
                             options=["$60", "$300", "$240", "$25"],
                             correct_answer="$60",
                             explanation="With the deductible met, the patient pays 20% of $300."),
                QuizQuestion(question="Which program is the largest payer for long-term nursing home care?",
                             options=["Medicaid", "Medicare Part A", "Private insurance", "Medicare Advantage"],
                             correct_answer="Medicaid",
                             explanation="Medicare covers only short skilled-nursing stays; Medicaid pays for long-term care."),
                QuizQuestion(question="An Accountable Care Organization is an example of:",
                             options=["Value-based payment", "Fee-for-service", "A Medicaid waiver", "A copay structure"],
                             correct_answer="Value-based payment",
                             explanation="ACOs share savings when they meet quality and cost targets."),
            ],
        ),
    ],
    session=TutorSession(
        name="Writing a PICO question",
        topic="Evidence-Based Practice",
        mode="socratic",
        summary_bullets=[
            "Broke a vague question into Population, Intervention, Comparison, Outcome",
            "Practised narrowing the population and choosing a measurable outcome",
            "Linked PICO to where RCTs and systematic reviews sit in the evidence pyramid",
        ],
        messages=[
            ChatMessage(role="user", content="For the EBP assignment I wrote 'Does exercise help older people?' and the TA said it's not a PICO question. What's wrong with it?"),
            ChatMessage(role="assistant", content="It's a good starting curiosity, it just isn't searchable yet. Let's take it one letter at a time. Who exactly are the 'older people' — what age, and do they have a particular condition or setting?"),
            ChatMessage(role="user", content="Maybe adults over 65 living in the community who have had a fall?"),
            ChatMessage(role="assistant", content="Much sharper — that's your P. Now 'exercise' is very broad. What specific intervention would a PT actually prescribe for fall prevention, and what would you compare it against?"),
            ChatMessage(role="user", content="Balance training, like tai chi, compared to usual care?"),
            ChatMessage(role="assistant", content="Exactly — I is tai chi, C is usual care. Last piece: what outcome would you count? 'Help' can't be measured, but something like 'rate of falls over 12 months' can. Your question becomes: 'In community-dwelling adults over 65 with a prior fall, does tai chi compared with usual care reduce the rate of falls over 12 months?' That wording maps straight onto search terms, and the best evidence to look for is a systematic review of RCTs, the top of the pyramid."),
        ],
    ),
)

# ---------------------------------------------------------------------------
# SAR HS 201 — Introduction to Nutrition
# ---------------------------------------------------------------------------

HS201 = Course(
    code="SAR HS 201",
    name="Introduction to Nutrition",
    department="Health Sciences",
    nickname="Nutrition",
    color="#F59E0B",
    concepts=[
        Concept(name="Macronutrients", mastery=0.96,
                description="Carbohydrate, protein and fat as energy sources: 4, 4 and 9 kcal per gram "
                            "(alcohol 7), and the AMDR ranges of 45–65%, 10–35% and 20–35%."),
        Concept(name="Dietary Reference Intakes", mastery=0.83,
                description="EAR, RDA, AI and UL: the RDA covers 97–98% of healthy people, the UL is the "
                            "highest intake unlikely to cause harm."),
        Concept(name="Energy Balance and BMR", mastery=0.77,
                description="Total energy expenditure = BMR + thermic effect of food (~10%) + physical "
                            "activity; estimating needs with Mifflin-St Jeor."),
        Concept(name="Carbohydrate Digestion and Glycemic Index", mastery=0.7,
                description="Salivary and pancreatic amylase, brush-border disaccharidases, and how fiber "
                            "and food form change the glycemic response."),
        Concept(name="Protein Quality and Amino Acids", mastery=0.61,
                description="The nine essential amino acids, complementary proteins, and scoring protein "
                            "quality with PDCAAS and DIAAS."),
        Concept(name="Lipids and Lipoproteins", mastery=0.5,
                description="Saturated, mono- and polyunsaturated fats, omega-3 vs omega-6, and how "
                            "chylomicrons, LDL and HDL transport lipids."),
        Concept(name="Fat-Soluble Vitamins", mastery=0.34,
                description="Vitamins A, D, E and K: absorption with dietary fat, storage in liver and "
                            "adipose tissue, and toxicity risk."),
        Concept(name="Water-Soluble Vitamins", mastery=0.22,
                description="B vitamins as coenzymes in energy metabolism (thiamin, riboflavin, niacin, B6, "
                            "folate, B12) and vitamin C in collagen synthesis."),
        Concept(name="Minerals and Electrolytes", mastery=0.06,
                description="Major vs trace minerals; sodium, potassium and chloride balance; iron, calcium "
                            "and zinc absorption."),
        Concept(name="Nutrition Across the Lifespan", mastery=0.0,
                description="Changing needs in pregnancy (folate, iron), infancy, adolescence and older "
                            "adulthood (vitamin D, B12, protein)."),
    ],
    edges=[
        Edge(source="Macronutrients", target="Carbohydrate Digestion and Glycemic Index", relationship="prerequisite", strength=0.8),
        Edge(source="Macronutrients", target="Protein Quality and Amino Acids", relationship="prerequisite", strength=0.8),
        Edge(source="Macronutrients", target="Lipids and Lipoproteins", relationship="prerequisite", strength=0.8),
        Edge(source="Energy Balance and BMR", target="Macronutrients", relationship="builds_on", strength=0.7),
        Edge(source="Lipids and Lipoproteins", target="Fat-Soluble Vitamins", relationship="prerequisite", strength=0.65),
        Edge(source="Dietary Reference Intakes", target="Water-Soluble Vitamins", relationship="related", strength=0.5),
        Edge(source="Water-Soluble Vitamins", target="Minerals and Electrolytes", relationship="related", strength=0.45),
        Edge(source="Dietary Reference Intakes", target="Nutrition Across the Lifespan", relationship="prerequisite", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Macronutrients", delta=0.12, reason="Perfect score on label-reading problem set"),
        MasteryEvent(concept="Energy Balance and BMR", delta=0.1, reason="Mifflin-St Jeor practice in diet project"),
        MasteryEvent(concept="Water-Soluble Vitamins", delta=-0.06, reason="Confused thiamin and riboflavin deficiencies"),
        MasteryEvent(concept="Lipids and Lipoproteins", delta=0.08, reason="Flashcard review of lipoproteins"),
    ],
    categories=[
        Category(name="Problem Sets", weight=0.25),
        Category(name="Diet Analysis Project", weight=0.3),
        Category(name="Exams", weight=0.45),
    ],
    assignments=[
        Assignment(title="Problem Set 1: Reading Nutrition Facts Labels", category="Problem Sets", type="homework",
                   due_offset_days=12, points_possible=20, points_earned=20),
        Assignment(title="Problem Set 2: Calculating Energy Needs", category="Problem Sets", type="homework",
                   due_offset_days=26, points_possible=20, points_earned=18),
        Assignment(title="3-Day Diet Record (Cronometer)", category="Diet Analysis Project", type="project",
                   due_offset_days=40, points_possible=50, points_earned=48),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=52, points_possible=100, points_earned=91, is_midterm=True),
        Assignment(title="Problem Set 3: Vitamin Functions and Deficiencies", category="Problem Sets", type="homework",
                   due_offset_days=74, points_possible=20),
        Assignment(title="Diet Analysis Final Report", category="Diet Analysis Project", type="project",
                   due_offset_days=92, points_possible=100),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=110, points_possible=100),
    ],
    notes=[
        Note(
            title="Energy needs — Mifflin-St Jeor worked example",
            tags=["energy", "problem set 2"],
            concepts=["Energy Balance and BMR", "Macronutrients"],
            body=(
                "## Mifflin-St Jeor (REE, kcal/day)\n"
                "- Men: `10 x wt(kg) + 6.25 x ht(cm) - 5 x age + 5`\n"
                "- Women: `10 x wt(kg) + 6.25 x ht(cm) - 5 x age - 161`\n\n"
                "**Me (practice):** 20 y/o woman, 60 kg, 165 cm\n"
                "10(60) + 6.25(165) - 5(20) - 161 = 600 + 1031.25 - 100 - 161 = **1370 kcal**\n\n"
                "Multiply by an activity factor: lightly active ~1.375 -> **~1885 kcal/day**.\n\n"
                "## TEE components\n"
                "- BMR/REE: 60–75% (biggest chunk)\n"
                "- Physical activity: 15–30% (most variable)\n"
                "- Thermic effect of food: ~10% (protein has the highest TEF)\n\n"
                "## Quick macro check\n"
                "A snack with 10 g protein, 30 g carb, 8 g fat = 40 + 120 + 72 = **232 kcal**. "
                "Fat share = 72/232 = 31% — inside the 20–35% AMDR.\n\n"
                "Remember: kcal/g is **4 / 4 / 9**, alcohol **7**."
            ),
        ),
        Note(
            title="Vitamins — I keep mixing these up",
            tags=["vitamins", "review"],
            concepts=["Water-Soluble Vitamins", "Fat-Soluble Vitamins"],
            body=(
                "## Water-soluble: deficiency diseases\n"
                "| Vitamin | Role | Deficiency |\n|---|---|---|\n"
                "| B1 thiamin | carb metabolism (pyruvate -> acetyl-CoA) | beriberi, Wernicke-Korsakoff |\n"
                "| B2 riboflavin | FAD/FMN | ariboflavinosis — cracked lips (cheilosis) |\n"
                "| B3 niacin | NAD/NADP | pellagra: dermatitis, diarrhea, dementia (death) |\n"
                "| Folate | DNA synthesis | megaloblastic anemia, neural tube defects |\n"
                "| B12 | needs intrinsic factor | megaloblastic anemia + nerve damage |\n"
                "| C | collagen synthesis | scurvy (bleeding gums) |\n\n"
                "Mnemonic attempt: **B1 = Beriberi, B3 = the 3 Ds**.\n\n"
                "## Fat-soluble (A, D, E, K)\n"
                "- Absorbed with fat in micelles -> chylomicrons\n"
                "- Stored, so toxicity is possible (A and D especially)\n"
                "- A: vision (night blindness); D: calcium absorption (rickets / osteomalacia); "
                "E: antioxidant; K: clotting factors (newborns get a shot)\n\n"
                "TODO: re-do the PS3 practice questions on folate vs B12 — the masking thing."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="hs201-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for SAR HS 201 Introduction to Nutrition: macronutrients, micronutrients, energy "
                    "balance and lifespan nutrition, with a semester-long diet analysis project.",
            concept_notes=[
                ConceptNote(name="Macronutrients", description="Weeks 2–5, foundation for the whole course."),
                ConceptNote(name="Energy Balance and BMR", description="Week 6; used in the diet project."),
                ConceptNote(name="Fat-Soluble Vitamins", description="Weeks 9–10 micronutrient unit."),
                ConceptNote(name="Nutrition Across the Lifespan", description="Final unit, weeks 13–14."),
            ],
            extracted_text=(
                "SAR HS 201 Introduction to Nutrition\n"
                "Sargent College of Health & Rehabilitation Sciences\n\n"
                "Course Description: An introduction to the science of human nutrition. Topics include the "
                "digestion, absorption and metabolism of carbohydrates, proteins and lipids; the functions "
                "and food sources of vitamins and minerals; energy balance and weight regulation; and "
                "nutrition needs from pregnancy through older adulthood. Students apply the Dietary "
                "Reference Intakes and the Dietary Guidelines for Americans to evaluate their own diets.\n\n"
                "Required Text: Whitney & Rolfes, Understanding Nutrition. Cronometer (free) for diet records.\n\n"
                "Grading\n"
                "  Problem sets (3)  25%\n"
                "  Diet analysis project (3-day record + final report)  30%\n"
                "  Midterm exam  20%\n"
                "  Final exam (cumulative)  25%\n\n"
                "Diet Analysis Project: Record everything you eat and drink for three days (two weekdays, "
                "one weekend day). Enter the record into Cronometer and compare your intake against your "
                "RDA/AI values and the AMDR. The final report interprets the gaps and proposes realistic "
                "food-based changes.\n\n"
                "Schedule\n"
                "  Wk 1  Nutrition science, DRIs, food labels\n"
                "  Wk 2-3  Carbohydrates and fiber; digestion\n"
                "  Wk 4  Lipids\n"
                "  Wk 5  Protein\n"
                "  Wk 6  Energy balance; MIDTERM end of week 7\n"
                "  Wk 9-10  Vitamins\n"
                "  Wk 11-12  Water and minerals\n"
                "  Wk 13-14  Lifespan nutrition"
            ),
        ),
        Document(
            file_name="hs201-lecture-lipids.pdf",
            category="lecture_notes",
            summary="Lecture notes on lipid structure, essential fatty acids, and lipoprotein transport from "
                    "chylomicrons through LDL and HDL, with dietary recommendations for heart health.",
            concept_notes=[
                ConceptNote(name="Lipids and Lipoproteins", description="Chylomicron, VLDL, LDL, HDL pathway."),
                ConceptNote(name="Essential fatty acids", description="Linoleic (omega-6) and alpha-linolenic (omega-3)."),
                ConceptNote(name="Fat-Soluble Vitamins", description="Absorbed in micelles alongside dietary fat."),
            ],
            extracted_text=(
                "Lecture 8 — Lipids: Structure, Digestion and Transport\n\n"
                "1. Classes of lipids\n"
                "   Triglycerides (~95% of dietary fat): glycerol backbone + 3 fatty acids\n"
                "   Phospholipids (lecithin) — emulsifiers, cell membranes\n"
                "   Sterols (cholesterol) — made by the liver; precursor to bile, vitamin D, steroid hormones\n\n"
                "2. Fatty acids\n"
                "   Saturated: no double bonds, solid at room temp (butter, coconut oil)\n"
                "   Monounsaturated: one double bond (olive oil, avocado)\n"
                "   Polyunsaturated: two or more; omega-3 (ALA, EPA, DHA) and omega-6 (linoleic)\n"
                "   Essential fatty acids: linoleic and alpha-linolenic — must come from the diet\n"
                "   Trans fats: partial hydrogenation; raise LDL and lower HDL\n\n"
                "3. Digestion\n"
                "   Bile emulsifies fat in the small intestine; pancreatic lipase yields monoglycerides + "
                "free fatty acids; these form micelles, are absorbed, re-esterified, and packaged into "
                "chylomicrons that enter the lymph. Vitamins A, D, E and K travel the same route.\n\n"
                "4. Lipoproteins\n"
                "   Chylomicrons: dietary fat from intestine\n"
                "   VLDL: triglycerides made in the liver\n"
                "   LDL: delivers cholesterol to cells — high levels linked to atherosclerosis\n"
                "   HDL: reverse cholesterol transport back to liver — protective\n\n"
                "Recommendation: saturated fat < 10% of kcal; replace with unsaturated fats"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="kcal per gram: carbohydrate, protein, fat, alcohol", back="4, 4, 9, 7"),
        Flashcard(front="RDA vs EAR", back="EAR meets the needs of 50% of healthy people; RDA meets 97–98% (EAR + 2 SD)."),
        Flashcard(front="AMDR for fat", back="20–35% of total kcal."),
        Flashcard(front="Mifflin-St Jeor for women", back="10 x weight(kg) + 6.25 x height(cm) - 5 x age - 161"),
        Flashcard(front="What does HDL do?", back="Reverse cholesterol transport — carries cholesterol from tissues back to the liver."),
        Flashcard(front="Niacin deficiency", back="Pellagra: the 3 Ds — dermatitis, diarrhea, dementia (fourth D: death)."),
        Flashcard(front="Why are vitamins A and D a toxicity risk?", back="They are fat-soluble and stored in liver and adipose tissue, so excess accumulates."),
        Flashcard(front="Complementary proteins", back="Two incomplete plant proteins whose limiting amino acids offset each other — e.g. rice (low lysine) + beans (low methionine)."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers weeks 1–6: DRIs and labels, the three macronutrients from digestion "
                 "to function, and energy balance. Calculations are a large share — bring a calculator.",
        topics=[
            StudyGuideTopic(name="Macronutrient math", importance="Label and AMDR calculations appear on every past exam.",
                            concepts=["Macronutrients", "Dietary Reference Intakes"]),
            StudyGuideTopic(name="Digestion pathways", importance="Know the enzyme and site for each macronutrient.",
                            concepts=["Carbohydrate Digestion and Glycemic Index", "Lipids and Lipoproteins"]),
            StudyGuideTopic(name="Protein quality", importance="Short answer on complementary proteins.",
                            concepts=["Protein Quality and Amino Acids"]),
            StudyGuideTopic(name="Energy balance", importance="One Mifflin-St Jeor problem with an activity factor.",
                            concepts=["Energy Balance and BMR"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Macronutrients", difficulty="medium", days_ago=48, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(question="A granola bar has 4 g protein, 25 g carbohydrate and 7 g fat. Its energy content is about:",
                             options=["179 kcal", "144 kcal", "207 kcal", "36 kcal"],
                             correct_answer="179 kcal",
                             explanation="4x4 + 25x4 + 7x9 = 16 + 100 + 63 = 179 kcal."),
                QuizQuestion(question="The AMDR for carbohydrate is:",
                             options=["45–65% of kcal", "10–35% of kcal", "20–35% of kcal", "5–10% of kcal"],
                             correct_answer="45–65% of kcal",
                             explanation="Protein is 10–35%, fat 20–35%."),
                QuizQuestion(question="Which macronutrient provides the most energy per gram?",
                             options=["Fat", "Protein", "Carbohydrate", "Fiber"],
                             correct_answer="Fat",
                             explanation="Fat provides 9 kcal/g."),
                QuizQuestion(question="Lactose is broken down by lactase into:",
                             options=["Glucose and galactose", "Glucose and fructose", "Two glucose molecules", "Galactose and fructose"],
                             correct_answer="Glucose and galactose",
                             explanation="Sucrose gives glucose + fructose; maltose gives two glucose."),
            ],
        ),
        QuizAttempt(
            concept="Water-Soluble Vitamins", difficulty="medium", days_ago=4, correct=[0, 3],
            questions=[
                QuizQuestion(question="Pellagra results from a deficiency of:",
                             options=["Niacin", "Thiamin", "Riboflavin", "Vitamin C"],
                             correct_answer="Niacin",
                             explanation="Pellagra presents as dermatitis, diarrhea and dementia."),
                QuizQuestion(question="Why can high folate intake mask a vitamin B12 deficiency?",
                             options=["It corrects the anemia while nerve damage progresses", "It blocks intrinsic factor",
                                      "It increases B12 excretion", "It causes pernicious anemia"],
                             correct_answer="It corrects the anemia while nerve damage progresses",
                             explanation="Folate fixes the megaloblastic anemia but not the neurological damage of B12 deficiency."),
                QuizQuestion(question="Wernicke-Korsakoff syndrome in chronic alcohol use is linked to which vitamin?",
                             options=["Thiamin", "Niacin", "Folate", "Vitamin B6"],
                             correct_answer="Thiamin",
                             explanation="Alcohol impairs thiamin absorption and use."),
                QuizQuestion(question="Vitamin C is required for the synthesis of:",
                             options=["Collagen", "Rhodopsin", "Clotting factors", "Hemoglobin"],
                             correct_answer="Collagen",
                             explanation="Scurvy symptoms come from weak collagen."),
            ],
        ),
    ],
    session=TutorSession(
        name="Folate vs B12",
        topic="Water-Soluble Vitamins",
        mode="expository",
        summary_bullets=[
            "Both folate and B12 deficiency cause megaloblastic anemia",
            "Only B12 deficiency causes neurological damage",
            "Folate supplements can hide B12 deficiency by fixing the blood picture",
        ],
        messages=[
            ChatMessage(role="user", content="I keep missing questions about folate and B12. Why do they both cause the same anemia?"),
            ChatMessage(role="assistant", content="Because they work in the same pathway. B12 is needed to convert methyl-folate into the active form of folate that the cell uses to make DNA. If either one is missing, rapidly dividing cells like red blood cell precursors can't finish DNA synthesis, so they keep growing without dividing. That gives you large, immature cells: megaloblastic anemia."),
            ChatMessage(role="user", content="Okay, so what's the difference between them then?"),
            ChatMessage(role="assistant", content="B12 has a second job that folate doesn't: it's needed to maintain the myelin sheath around nerves. So B12 deficiency adds numbness, tingling, balance problems and eventually irreversible nerve damage. Folate deficiency does not."),
            ChatMessage(role="user", content="And that's why taking a lot of folate is a problem?"),
            ChatMessage(role="assistant", content="Exactly. Large doses of folic acid can push enough DNA synthesis through to correct the anemia, so blood tests look normal, while the nerve damage from B12 deficiency keeps progressing undetected. It's why the UL for folic acid exists and why older adults, who absorb B12 poorly because of low stomach acid and intrinsic factor, get screened for B12 directly."),
        ],
    ),
)

# ---------------------------------------------------------------------------
# SAR HS 300 — Epidemiology 1
# ---------------------------------------------------------------------------

HS300 = Course(
    code="SAR HS 300",
    name="Epidemiology 1",
    department="Health Sciences",
    nickname="Epi 1",
    color="#6366F1",
    concepts=[
        Concept(name="Incidence and Prevalence", mastery=0.96,
                description="Incidence = new cases / population at risk over time; prevalence = existing "
                            "cases at a point in time. P ≈ I x D for a steady-state disease."),
        Concept(name="Study Designs", mastery=0.77,
                description="Cross-sectional, case-control, cohort (prospective and retrospective) and "
                            "randomized trials — and which measure of association each can estimate."),
        Concept(name="Risk Ratio", mastery=0.6,
                description="Cumulative incidence in the exposed divided by the unexposed, a/(a+b) over "
                            "c/(c+d), estimated from cohort studies and trials."),
        Concept(name="Sensitivity and Specificity", mastery=0.55,
                description="Sensitivity = TP/(TP+FN), specificity = TN/(TN+FP); properties of the test "
                            "that do not depend on prevalence."),
        Concept(name="Odds Ratio", mastery=0.46,
                description="ad/bc from a 2x2 table; the only measure available from a case-control study, "
                            "approximating the risk ratio when the outcome is rare."),
        Concept(name="Bias", mastery=0.4,
                description="Systematic error from selection (who gets into the study) or information "
                            "(recall bias, misclassification) that shifts the estimate away from the truth."),
        Concept(name="Attributable Risk", mastery=0.32,
                description="Risk difference (Ie − Iu) and population attributable fraction — the excess "
                            "disease that removing the exposure would prevent."),
        Concept(name="Confounding", mastery=0.27,
                description="A third variable associated with both exposure and outcome, not on the causal "
                            "path, that distorts the crude association; controlled by stratification or adjustment."),
        Concept(name="Positive Predictive Value", mastery=0.15,
                description="TP/(TP+FP): the probability a positive test is a true case. Falls sharply when "
                            "disease prevalence is low, even with a specific test."),
        Concept(name="Effect Modification", mastery=0.03,
                description="When the exposure–outcome association genuinely differs across levels of a third "
                            "variable; stratum-specific estimates differ and should be reported separately."),
    ],
    edges=[
        Edge(source="Incidence and Prevalence", target="Risk Ratio", relationship="prerequisite", strength=0.85),
        Edge(source="Study Designs", target="Odds Ratio", relationship="prerequisite", strength=0.75),
        Edge(source="Risk Ratio", target="Attributable Risk", relationship="builds_on", strength=0.7),
        Edge(source="Odds Ratio", target="Risk Ratio", relationship="related", strength=0.7),
        Edge(source="Sensitivity and Specificity", target="Positive Predictive Value", relationship="prerequisite", strength=0.85),
        Edge(source="Incidence and Prevalence", target="Positive Predictive Value", relationship="related", strength=0.6),
        Edge(source="Bias", target="Confounding", relationship="related", strength=0.55),
        Edge(source="Confounding", target="Effect Modification", relationship="related", strength=0.7),
    ],
    mastery_events=[
        MasteryEvent(concept="Incidence and Prevalence", delta=0.1, reason="Problem Set 1: 23/25"),
        MasteryEvent(concept="Positive Predictive Value", delta=-0.1, reason="Missed PPV-at-low-prevalence on quiz"),
        MasteryEvent(concept="Confounding", delta=-0.05, reason="Mixed up confounding and effect modification"),
        MasteryEvent(concept="Odds Ratio", delta=0.09, reason="Tutor session on 2x2 tables"),
    ],
    categories=[
        Category(name="Problem Sets", weight=0.3),
        Category(name="Exams", weight=0.5),
        Category(name="Journal Club and Project", weight=0.2),
    ],
    assignments=[
        Assignment(title="Problem Set 1: Rates, Incidence and Prevalence", category="Problem Sets", type="homework",
                   due_offset_days=15, points_possible=25, points_earned=23),
        Assignment(title="Problem Set 2: 2x2 Tables and Measures of Association", category="Problem Sets", type="homework",
                   due_offset_days=30, points_possible=25, points_earned=18),
        Assignment(title="Journal Club: Framingham Heart Study Critique", category="Journal Club and Project", type="reading",
                   due_offset_days=38, points_possible=10, points_earned=9),
        Assignment(title="Problem Set 3: Screening Test Accuracy", category="Problem Sets", type="homework",
                   due_offset_days=45, points_possible=25, points_earned=17),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=58, points_possible=100, points_earned=74, is_midterm=True),
        Assignment(title="Problem Set 4: Confounding and Stratified Analysis", category="Problem Sets", type="homework",
                   due_offset_days=78, points_possible=25),
        Assignment(title="Outbreak Investigation Project", category="Journal Club and Project", type="project",
                   due_offset_days=96, points_possible=50),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=112, points_possible=100),
    ],
    notes=[
        Note(
            title="2x2 table cheat sheet",
            tags=["measures of association", "midterm"],
            concepts=["Risk Ratio", "Odds Ratio", "Attributable Risk"],
            body=(
                "Always set it up the same way (exposure on rows, disease on columns):\n\n"
                "|  | Disease + | Disease − |\n|---|---|---|\n"
                "| Exposed | a | b |\n| Unexposed | c | d |\n\n"
                "- **Risk ratio** = [a/(a+b)] / [c/(c+d)] — cohort or RCT only\n"
                "- **Odds ratio** = (a/b)/(c/d) = **ad/bc** — works for case-control\n"
                "- **Risk difference (AR)** = a/(a+b) − c/(c+d)\n"
                "- **AR%** among exposed = (RR − 1)/RR\n\n"
                "**PS2 example (smoking and lung cancer cohort):** a=60, b=940, c=10, d=990\n"
                "Ie = 0.06, Iu = 0.01 -> RR = **6.0**, RD = **0.05** (50 per 1000)\n"
                "OR = (60x990)/(940x10) = **6.32** — close to RR because the outcome is rare.\n\n"
                "Mistake I made on PS2: computed OR from a cohort with a *common* outcome and called it "
                "the risk — OR overstates RR when the outcome isn't rare.\n\n"
                "Interpretation template: \"Exposed individuals had 6.0 times the risk of ___ compared "
                "with unexposed individuals over ___ years.\""
            ),
        ),
        Note(
            title="Screening — why PPV keeps tripping me up",
            tags=["screening", "PPV"],
            concepts=["Sensitivity and Specificity", "Positive Predictive Value"],
            body=(
                "Sens and spec belong to the **test**. PPV and NPV depend on the **population** (prevalence).\n\n"
                "Worked example from lecture: test with 90% sens, 95% spec, population of 10,000.\n\n"
                "**Prevalence 10%** -> 1,000 diseased\n"
                "- TP = 900, FN = 100; 9,000 healthy -> FP = 450, TN = 8,550\n"
                "- PPV = 900 / (900 + 450) = **67%**\n\n"
                "**Prevalence 1%** -> 100 diseased\n"
                "- TP = 90, FN = 10; 9,900 healthy -> FP = 495\n"
                "- PPV = 90 / (90 + 495) = **15%**\n\n"
                "Same test, PPV collapses. This is why we don't screen low-risk groups for rare diseases "
                "— most positives would be false positives.\n\n"
                "Steps that work for me: 1) pick N = 10,000, 2) fill the disease column from prevalence, "
                "3) apply sens to the diseased, spec to the healthy, 4) read PPV across the T+ row."
            ),
        ),
        Note(
            title="Confounding vs effect modification",
            tags=["confounding", "stratification"],
            concepts=["Confounding", "Effect Modification", "Bias"],
            body=(
                "### Confounding (a nuisance to remove)\n"
                "Criteria for a confounder C:\n"
                "1. Associated with the exposure\n"
                "2. Independent risk factor for the outcome\n"
                "3. **Not** on the causal pathway\n\n"
                "Classic: coffee and pancreatic cancer — smoking confounds it.\n"
                "Check: crude OR differs from the Mantel-Haenszel adjusted OR by > ~10%, and the "
                "stratum-specific ORs are **similar to each other**.\n\n"
                "### Effect modification (a finding to report)\n"
                "Stratum-specific estimates are **different from each other** (e.g. OR 1.1 in women, "
                "OR 3.4 in men). Don't average them — report each.\n\n"
                "Still not sure how to tell which one is happening when both seem possible. Bring to "
                "office hours before PS4."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="hs300-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for SAR HS 300 Epidemiology 1, covering disease frequency, study designs, "
                    "measures of association, screening, bias and confounding, with an outbreak investigation project.",
            concept_notes=[
                ConceptNote(name="Incidence and Prevalence", description="Weeks 1–2, measures of disease frequency."),
                ConceptNote(name="Study Designs", description="Weeks 3–5, cohort, case-control and trials."),
                ConceptNote(name="Positive Predictive Value", description="Week 7 screening unit."),
                ConceptNote(name="Confounding", description="Weeks 10–11, stratified analysis after the midterm."),
            ],
            extracted_text=(
                "SAR HS 300 Epidemiology 1\n\n"
                "Course Description: Epidemiology is the study of the distribution and determinants of "
                "health-related states in populations and the application of this study to control health "
                "problems. This course introduces the core methods: measuring disease frequency, comparing "
                "groups with measures of association, evaluating screening tests, and judging whether an "
                "observed association is causal. Emphasis is on reading and critiquing published studies.\n\n"
                "Prerequisites: an introductory statistics course is recommended.\n\n"
                "Assessment\n"
                "  Problem sets (4)  30%\n"
                "  Midterm exam  20%\n"
                "  Final exam  30%\n"
                "  Journal club critique + outbreak investigation project  20%\n\n"
                "Calculators are required on exams. Formula sheets are NOT provided.\n\n"
                "Topics by week\n"
                "  1-2  History of epidemiology; rates, incidence, prevalence\n"
                "  3-5  Study designs: cross-sectional, case-control, cohort, randomized controlled trials\n"
                "  6  Measures of association: risk ratio, odds ratio, risk difference, attributable fraction\n"
                "  7  Screening and diagnostic tests: sensitivity, specificity, predictive values\n"
                "  8  MIDTERM EXAM (weeks 1-7)\n"
                "  9  Random error and statistical significance\n"
                "  10-11  Bias; confounding; stratification and Mantel-Haenszel adjustment\n"
                "  12  Effect modification\n"
                "  13  Causal inference: Bradford Hill criteria\n"
                "  14  Outbreak investigation presentations"
            ),
        ),
        Document(
            file_name="hs300-lecture07-screening.pdf",
            category="lecture_notes",
            summary="Lecture on screening test accuracy: building the 2x2 table against a gold standard, "
                    "computing sensitivity, specificity, PPV and NPV, and how prevalence drives predictive value.",
            concept_notes=[
                ConceptNote(name="Sensitivity and Specificity", description="Fixed test properties, computed down the columns."),
                ConceptNote(name="Positive Predictive Value", description="Computed across the T+ row; depends on prevalence."),
                ConceptNote(name="Screening criteria", description="Wilson-Jungner principles for a worthwhile screening program."),
            ],
            extracted_text=(
                "Lecture 7 — Evaluating Screening and Diagnostic Tests\n\n"
                "Compare the screening test against a gold standard and arrange results in a 2x2 table:\n"
                "               Disease+   Disease-\n"
                "  Test+          TP          FP\n"
                "  Test-          FN          TN\n\n"
                "Sensitivity = TP / (TP + FN)  — ability to correctly identify those WITH disease\n"
                "Specificity = TN / (TN + FP)  — ability to correctly identify those WITHOUT disease\n"
                "PPV = TP / (TP + FP)  — probability of disease given a positive test\n"
                "NPV = TN / (TN + FN)  — probability of no disease given a negative test\n\n"
                "Key point: sensitivity and specificity are characteristics of the test. Predictive values "
                "depend on the prevalence of disease in the population being screened. As prevalence "
                "falls, PPV falls and NPV rises.\n\n"
                "Trade-off: moving the cutoff (e.g. PSA > 4.0 ng/mL vs > 2.5 ng/mL) increases sensitivity at "
                "the cost of specificity. A ROC curve plots sensitivity against 1 − specificity across "
                "cutoffs.\n\n"
                "Use a highly SENSITIVE test when missing a case is dangerous (SnNout: a negative result "
                "rules out). Use a highly SPECIFIC test to confirm (SpPin: a positive result rules in).\n\n"
                "Wilson-Jungner criteria: the condition is an important health problem, has a detectable "
                "early stage, effective treatment exists, the test is acceptable, and benefits outweigh harms."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Incidence vs prevalence", back="Incidence = new cases over a period / population at risk. Prevalence = all existing cases at a point in time / population."),
        Flashcard(front="Odds ratio formula from a 2x2 table", back="ad / bc"),
        Flashcard(front="Which measure can a case-control study estimate?", back="Only the odds ratio — you fixed the number of cases, so you can't compute risk."),
        Flashcard(front="Sensitivity", back="TP / (TP + FN): the proportion of people with the disease who test positive."),
        Flashcard(front="What happens to PPV when prevalence decreases?", back="PPV decreases (more of the positives are false positives); NPV increases."),
        Flashcard(front="Three criteria for a confounder", back="Associated with the exposure, a risk factor for the outcome, and not on the causal pathway."),
        Flashcard(front="Recall bias", back="Cases remember past exposures differently than controls — a form of information bias common in case-control studies."),
        Flashcard(front="SnNout / SpPin", back="A highly Sensitive test, when Negative, rules out. A highly Specific test, when Positive, rules in."),
        Flashcard(front="Population attributable fraction", back="The proportion of disease in the whole population that would be eliminated if the exposure were removed."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers weeks 1–7: disease frequency, study designs, measures of association "
                 "and screening. Most points come from calculations off a 2x2 table, so practise building "
                 "tables quickly and interpreting each number in a full sentence.",
        topics=[
            StudyGuideTopic(name="Measures of disease frequency", importance="Warm-up calculations; easy points.",
                            concepts=["Incidence and Prevalence"]),
            StudyGuideTopic(name="Study designs and their measures", importance="Matching design to measure is always tested.",
                            concepts=["Study Designs", "Odds Ratio", "Risk Ratio"]),
            StudyGuideTopic(name="Attributable risk", importance="One multi-part interpretation question.",
                            concepts=["Attributable Risk"]),
            StudyGuideTopic(name="Screening tests", importance="Your weakest area: drill PPV at two prevalences.",
                            concepts=["Sensitivity and Specificity", "Positive Predictive Value"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Odds Ratio", difficulty="medium", days_ago=33, correct=[0, 2, 3],
            questions=[
                QuizQuestion(question="In a case-control study, 40 of 100 cases and 20 of 100 controls were exposed. The odds ratio is:",
                             options=["2.67", "2.00", "0.38", "1.50"],
                             correct_answer="2.67",
                             explanation="OR = (40x80)/(60x20) = 3200/1200 = 2.67."),
                QuizQuestion(question="The odds ratio approximates the risk ratio when:",
                             options=["The outcome is rare", "The exposure is rare", "The study is a cohort", "The sample is large"],
                             correct_answer="The outcome is rare",
                             explanation="The rare-disease assumption makes a/(a+b) close to a/b."),
                QuizQuestion(question="Which design is best suited to studying a rare disease?",
                             options=["Case-control", "Prospective cohort", "Cross-sectional", "Randomized trial"],
                             correct_answer="Case-control",
                             explanation="Sampling on the outcome guarantees enough cases."),
                QuizQuestion(question="An OR of 0.5 for exercise and heart disease means:",
                             options=["Exercisers had half the odds of heart disease", "Exercise doubles the odds",
                                      "There is no association", "Half of exercisers developed heart disease"],
                             correct_answer="Exercisers had half the odds of heart disease",
                             explanation="An OR below 1 indicates a protective association."),
            ],
        ),
        QuizAttempt(
            concept="Positive Predictive Value", difficulty="hard", days_ago=14, correct=[0],
            questions=[
                QuizQuestion(question="A test has 90% sensitivity and 90% specificity. In a population with 2% prevalence, PPV is closest to:",
                             options=["16%", "90%", "50%", "2%"],
                             correct_answer="16%",
                             explanation="Per 1,000: TP = 18, FP = 98; PPV = 18/116 ≈ 16%."),
                QuizQuestion(question="Lowering the cutoff for a positive test will usually:",
                             options=["Increase sensitivity and decrease specificity", "Increase both sensitivity and specificity",
                                      "Decrease sensitivity and increase specificity", "Not affect sensitivity"],
                             correct_answer="Increase sensitivity and decrease specificity",
                             explanation="More people are called positive, catching more cases and more false positives."),
                QuizQuestion(question="Screening is moved from a high-risk clinic to the general population. Which value changes?",
                             options=["PPV", "Sensitivity", "Specificity", "None of them"],
                             correct_answer="PPV",
                             explanation="Predictive values depend on prevalence; sensitivity and specificity do not."),
            ],
        ),
    ],
    session=TutorSession(
        name="Odds ratios from a case-control study",
        topic="Odds Ratio",
        mode="socratic",
        summary_bullets=[
            "Set up the 2x2 table with exposure on rows and disease on columns",
            "Computed OR = ad/bc and interpreted it in a sentence",
            "Explained why a case-control study can't give a risk ratio",
        ],
        messages=[
            ChatMessage(role="user", content="PS2 question: 150 cases of bladder cancer, 90 smoked; 300 controls, 120 smoked. Why can't I just compute a risk ratio?"),
            ChatMessage(role="assistant", content="Good instinct to question it. To compute risk you need the number of exposed people who went on to get the disease out of all exposed people. In this study, who decided how many people had bladder cancer — nature, or the investigators?"),
            ChatMessage(role="user", content="The investigators, they picked 150 cases and 300 controls."),
            ChatMessage(role="assistant", content="Right. Since the 1:2 case-to-control ratio was chosen, the 'proportion with disease' in this sample is meaningless; it would change if they'd picked 600 controls instead. What doesn't change with that choice is the odds of exposure. Can you fill in a, b, c and d?"),
            ChatMessage(role="user", content="a = 90 smokers with cancer, b = 120 smokers without, c = 60 nonsmokers with, d = 180 nonsmokers without. So OR = (90x180)/(120x60) = 2.25?"),
            ChatMessage(role="assistant", content="Exactly right. In a sentence: smokers had 2.25 times the odds of bladder cancer compared with nonsmokers. And because bladder cancer is rare in the general population, this OR is a reasonable estimate of the risk ratio too. That's the rare-disease assumption."),
        ],
    ),
)

# ---------------------------------------------------------------------------
# SAR HS 369 — Gross Human Anatomy
# ---------------------------------------------------------------------------

HS369 = Course(
    code="SAR HS 369",
    name="Gross Human Anatomy",
    department="Health Sciences",
    nickname="Gross Anatomy",
    color="#DC2626",
    concepts=[
        Concept(name="Anatomical Terminology and Planes", mastery=0.96,
                description="Anatomical position, sagittal/coronal/transverse planes, and directional terms "
                            "(proximal/distal, superficial/deep, medial/lateral)."),
        Concept(name="Rotator Cuff Muscles", mastery=0.79,
                description="Supraspinatus, infraspinatus, teres minor and subscapularis (SITS): attachments, "
                            "actions and innervation (suprascapular, axillary, subscapular nerves)."),
        Concept(name="Vertebral Column", mastery=0.68,
                description="Cervical, thoracic, lumbar, sacral and coccygeal regions; typical vertebra parts; "
                            "intervertebral discs and the ligaments that stabilise the column."),
        Concept(name="Forearm Compartments", mastery=0.52,
                description="Anterior flexor-pronator compartment (median and ulnar nerves) vs posterior "
                            "extensor-supinator compartment (radial nerve), and the cubital fossa contents."),
        Concept(name="Coronary Circulation", mastery=0.47,
                description="Right and left coronary arteries, LAD and circumflex branches, the territories "
                            "they supply, and venous drainage via the coronary sinus."),
        Concept(name="Brachial Plexus", mastery=0.38,
                description="Roots C5–T1, trunks, divisions, cords and the five terminal branches; classic "
                            "lesions such as Erb's palsy and wrist drop."),
        Concept(name="Mediastinum", mastery=0.25,
                description="Superior vs inferior (anterior, middle, posterior) mediastinum and their "
                            "contents: heart, great vessels, trachea, esophagus, phrenic and vagus nerves."),
        Concept(name="Lumbosacral Plexus", mastery=0.12,
                description="Roots L1–S4 forming the femoral, obturator and sciatic nerves (tibial and common "
                            "fibular divisions) that supply the lower limb."),
        Concept(name="Femoral Triangle", mastery=0.05,
                description="Borders (inguinal ligament, sartorius, adductor longus) and contents NAVEL — "
                            "femoral nerve, artery, vein, empty space, lymphatics."),
        Concept(name="Cranial Nerves", mastery=0.0,
                description="The twelve cranial nerves, their foramina, and their sensory, motor and "
                            "parasympathetic functions."),
    ],
    edges=[
        Edge(source="Anatomical Terminology and Planes", target="Vertebral Column", relationship="prerequisite", strength=0.6),
        Edge(source="Vertebral Column", target="Brachial Plexus", relationship="prerequisite", strength=0.65),
        Edge(source="Brachial Plexus", target="Rotator Cuff Muscles", relationship="related", strength=0.6),
        Edge(source="Brachial Plexus", target="Forearm Compartments", relationship="prerequisite", strength=0.8),
        Edge(source="Coronary Circulation", target="Mediastinum", relationship="part_of", strength=0.75),
        Edge(source="Lumbosacral Plexus", target="Femoral Triangle", relationship="prerequisite", strength=0.75),
        Edge(source="Brachial Plexus", target="Lumbosacral Plexus", relationship="related", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Rotator Cuff Muscles", delta=0.14, reason="Identified all four SITS on lab practical"),
        MasteryEvent(concept="Brachial Plexus", delta=-0.07, reason="Quiz 2: missed lesion questions"),
        MasteryEvent(concept="Brachial Plexus", delta=0.11, reason="Drew the plexus from memory in tutor session"),
        MasteryEvent(concept="Mediastinum", delta=0.08, reason="Flashcard review before midterm"),
    ],
    categories=[
        Category(name="Lab Practicals", weight=0.4),
        Category(name="Exams", weight=0.45),
        Category(name="Quizzes", weight=0.15, drop_lowest=1),
    ],
    assignments=[
        Assignment(title="Quiz 1: Back and Vertebral Column", category="Quizzes", type="quiz",
                   due_offset_days=14, points_possible=20, points_earned=18),
        Assignment(title="Lab Practical 1: Upper Limb", category="Lab Practicals", type="exam",
                   due_offset_days=35, points_possible=50, points_earned=41),
        Assignment(title="Quiz 2: Brachial Plexus Lesions", category="Quizzes", type="quiz",
                   due_offset_days=40, points_possible=20, points_earned=13),
        Assignment(title="Midterm Exam: Back, Upper Limb and Thorax", category="Exams", type="exam",
                   due_offset_days=56, points_possible=100, points_earned=80, is_midterm=True),
        Assignment(title="Lab Practical 2: Thorax and Lower Limb", category="Lab Practicals", type="exam",
                   due_offset_days=80, points_possible=50),
        Assignment(title="Quiz 3: Lower Limb Innervation", category="Quizzes", type="quiz",
                   due_offset_days=88, points_possible=20),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=110, points_possible=100),
    ],
    notes=[
        Note(
            title="Brachial plexus — Randy Travis Drinks Cold Beer",
            tags=["upper limb", "nerves", "practical"],
            concepts=["Brachial Plexus", "Forearm Compartments", "Rotator Cuff Muscles"],
            body=(
                "**Roots -> Trunks -> Divisions -> Cords -> Branches** (Randy Travis Drinks Cold Beer)\n\n"
                "- Roots: C5, C6, C7, C8, T1\n"
                "- Trunks: superior (C5–6), middle (C7), inferior (C8–T1)\n"
                "- Cords named by relation to the **axillary artery**: lateral, posterior, medial\n\n"
                "## Terminal branches (MARMU)\n"
                "- **Musculocutaneous** (lateral cord): biceps, brachialis, coracobrachialis\n"
                "- **Axillary** (posterior): deltoid, teres minor — at risk with surgical neck fracture\n"
                "- **Radial** (posterior): all posterior arm + forearm extensors — mid-shaft humerus fracture -> **wrist drop**\n"
                "- **Median** (lateral + medial): most forearm flexors, thenar muscles — carpal tunnel\n"
                "- **Ulnar** (medial): FCU, medial half FDP, most intrinsic hand muscles — 'claw hand'\n\n"
                "## Lesions I got wrong on Quiz 2\n"
                "- **Erb's palsy** = upper trunk C5–6 -> 'waiter's tip' (arm adducted, medially rotated, forearm pronated)\n"
                "- **Klumpke's** = lower trunk C8–T1 -> claw hand\n\n"
                "Rotator cuff tie-in: suprascapular nerve (from upper trunk) supplies supraspinatus + infraspinatus."
            ),
        ),
        Note(
            title="Coronary arteries — who supplies what",
            tags=["thorax", "heart"],
            concepts=["Coronary Circulation", "Mediastinum"],
            body=(
                "Both coronaries arise from the aortic sinuses just above the aortic valve and fill during "
                "**diastole**.\n\n"
                "**Right coronary artery (RCA)**\n"
                "- Runs in the right coronary sulcus\n"
                "- Supplies right atrium, most of right ventricle, **SA node (~60%)** and **AV node (~80%)**\n"
                "- Gives the posterior interventricular (descending) artery in right-dominant hearts (~70%)\n\n"
                "**Left coronary artery (LCA)** — short trunk, splits into:\n"
                "- **LAD** (anterior interventricular): anterior 2/3 of septum, anterior LV wall, apex. "
                "'Widow maker' when occluded proximally.\n"
                "- **Circumflex**: left atrium, lateral and posterior LV\n\n"
                "Venous return: great, middle and small cardiac veins -> **coronary sinus** -> right atrium.\n\n"
                "Heart sits in the **middle mediastinum** inside the pericardium. Still need to review "
                "posterior mediastinum contents (esophagus, descending aorta, azygos, thoracic duct)."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="hs369-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for SAR HS 369 Gross Human Anatomy: regional anatomy with cadaver prosection lab, "
                    "two lab practicals, quizzes, a midterm and a cumulative final.",
            concept_notes=[
                ConceptNote(name="Vertebral Column", description="Unit 1 with the back musculature."),
                ConceptNote(name="Brachial Plexus", description="Unit 2 upper limb; heavily tested on Practical 1."),
                ConceptNote(name="Mediastinum", description="Unit 3 thorax before the midterm."),
                ConceptNote(name="Lumbosacral Plexus", description="Unit 4 lower limb after the midterm."),
                ConceptNote(name="Cranial Nerves", description="Final unit, head and neck."),
            ],
            extracted_text=(
                "SAR HS 369 Gross Human Anatomy — Lecture and Laboratory\n\n"
                "Course Description: A regional study of the gross structure of the human body with emphasis "
                "on the musculoskeletal, nervous and cardiovascular systems as they relate to movement and "
                "clinical practice in the health professions. Laboratory sessions use prosected human "
                "cadavers, bones and models. Respectful conduct in the anatomy laboratory is required at all "
                "times; photography in the lab is prohibited.\n\n"
                "Prerequisites: an introductory human anatomy and physiology course.\n\n"
                "Evaluation\n"
                "  Lab practicals (2)  40% — timed stations, identify tagged structures\n"
                "  Midterm exam  20%\n"
                "  Final exam (cumulative)  25%\n"
                "  Quizzes (3, lowest dropped)  15%\n\n"
                "Units\n"
                "  1  Introduction, terminology, back and vertebral column\n"
                "  2  Upper limb: shoulder, axilla, brachial plexus, arm, forearm, hand\n"
                "  3  Thorax: thoracic wall, lungs, mediastinum, heart and coronary circulation\n"
                "  MIDTERM EXAM covers Units 1-3\n"
                "  4  Lower limb: gluteal region, femoral triangle, lumbosacral plexus, leg and foot\n"
                "  5  Head and neck: cranial nerves, triangles of the neck\n\n"
                "Lab expectations: come having read the dissector chapter. For every muscle, know its "
                "proximal attachment, distal attachment, action and innervation. Practical stations allow "
                "60 seconds each; spelling counts when it changes meaning (e.g. ulnar vs ulna)."
            ),
        ),
        Document(
            file_name="hs369-lab05-forearm.pdf",
            category="lecture_notes",
            summary="Lab handout for the forearm: boundaries and contents of the cubital fossa, the flexor and "
                    "extensor compartments in layers, and their innervation from the brachial plexus.",
            concept_notes=[
                ConceptNote(name="Forearm Compartments", description="Superficial, intermediate and deep flexor layers."),
                ConceptNote(name="Cubital fossa", description="Contents lateral to medial: tendon, artery, nerve (TAN)."),
                ConceptNote(name="Brachial Plexus", description="Median, ulnar and radial nerve courses through the forearm."),
            ],
            extracted_text=(
                "Lab 5 — The Cubital Fossa and Forearm\n\n"
                "Cubital fossa boundaries: superior — line between the humeral epicondyles; lateral — "
                "brachioradialis; medial — pronator teres. Floor: brachialis and supinator. Roof: bicipital "
                "aponeurosis. Contents, lateral to medial: biceps Tendon, brachial Artery, median Nerve "
                "(TAN). The median cubital vein lies superficial to the roof — common venipuncture site.\n\n"
                "Anterior (flexor-pronator) compartment\n"
                "  Superficial layer, from the common flexor origin on the medial epicondyle: pronator teres, "
                "flexor carpi radialis, palmaris longus (absent in ~15%), flexor carpi ulnaris\n"
                "  Intermediate: flexor digitorum superficialis\n"
                "  Deep: flexor digitorum profundus, flexor pollicis longus, pronator quadratus\n"
                "  Innervation: median nerve, EXCEPT flexor carpi ulnaris and the medial half of FDP (ulnar nerve)\n\n"
                "Posterior (extensor-supinator) compartment\n"
                "  From the common extensor origin on the lateral epicondyle: extensor carpi radialis brevis, "
                "extensor digitorum, extensor digiti minimi, extensor carpi ulnaris; plus brachioradialis and "
                "extensor carpi radialis longus from the supracondylar ridge\n"
                "  Innervation: radial nerve and its deep branch (posterior interosseous nerve)\n\n"
                "Clinical: lateral epicondylitis ('tennis elbow') involves the ECRB origin. Identify each "
                "tagged tendon at the wrist for the practical."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Rotator cuff muscles (SITS)", back="Supraspinatus, infraspinatus, teres minor, subscapularis."),
        Flashcard(front="Which rotator cuff muscle initiates abduction?", back="Supraspinatus (first ~15°); deltoid takes over."),
        Flashcard(front="Wrist drop — which nerve?", back="Radial nerve, often from a mid-shaft humerus fracture in the radial groove."),
        Flashcard(front="Erb's palsy", back="Upper trunk (C5–C6) injury: arm adducted, medially rotated, forearm pronated — 'waiter's tip'."),
        Flashcard(front="Contents of the cubital fossa (lateral to medial)", back="Biceps tendon, brachial artery, median nerve (TAN)."),
        Flashcard(front="LAD supplies…", back="Anterior two-thirds of the interventricular septum, anterior wall of the left ventricle and the apex."),
        Flashcard(front="Femoral triangle contents (lateral to medial)", back="NAVEL: femoral Nerve, Artery, Vein, Empty space (femoral canal), Lymphatics."),
        Flashcard(front="Posterior mediastinum contents", back="Esophagus, descending thoracic aorta, azygos and hemiazygos veins, thoracic duct, vagus nerves."),
        Flashcard(front="Number of vertebrae by region", back="7 cervical, 12 thoracic, 5 lumbar, 5 fused sacral, ~4 coccygeal."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers Units 1–3: back, upper limb and thorax. Expect a mix of "
                 "attachment/action/innervation questions and short clinical vignettes asking you to "
                 "localise a nerve lesion or coronary occlusion.",
        topics=[
            StudyGuideTopic(name="Shoulder and rotator cuff", importance="Reliable points; keep reviewing.",
                            concepts=["Rotator Cuff Muscles", "Anatomical Terminology and Planes"]),
            StudyGuideTopic(name="Brachial plexus and its lesions", importance="Highest-yield and your weakest unit — draw it daily.",
                            concepts=["Brachial Plexus", "Forearm Compartments"]),
            StudyGuideTopic(name="Thorax", importance="Coronary territories and mediastinal contents are a full page of the exam.",
                            concepts=["Coronary Circulation", "Mediastinum"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Brachial Plexus", difficulty="hard", days_ago=42, correct=[0, 3],
            questions=[
                QuizQuestion(question="A patient cannot extend the wrist after a mid-shaft humerus fracture. Which nerve is injured?",
                             options=["Radial", "Median", "Ulnar", "Musculocutaneous"],
                             correct_answer="Radial",
                             explanation="The radial nerve runs in the radial groove of the humeral shaft."),
                QuizQuestion(question="Erb's palsy results from injury to the:",
                             options=["Upper trunk", "Lower trunk", "Posterior cord", "Medial cord"],
                             correct_answer="Upper trunk",
                             explanation="C5–C6 roots / upper trunk, often from a birth injury."),
                QuizQuestion(question="The cords of the brachial plexus are named for their relation to the:",
                             options=["Axillary artery", "Clavicle", "Humerus", "Axillary vein"],
                             correct_answer="Axillary artery",
                             explanation="Lateral, posterior and medial to the second part of the axillary artery."),
                QuizQuestion(question="Which nerve supplies the deltoid and teres minor?",
                             options=["Axillary", "Suprascapular", "Radial", "Thoracodorsal"],
                             correct_answer="Axillary",
                             explanation="The axillary nerve wraps around the surgical neck of the humerus."),
            ],
        ),
        QuizAttempt(
            concept="Rotator Cuff Muscles", difficulty="medium", days_ago=30, correct=[0, 1, 2],
            questions=[
                QuizQuestion(question="Which rotator cuff muscle is a medial rotator of the humerus?",
                             options=["Subscapularis", "Infraspinatus", "Teres minor", "Supraspinatus"],
                             correct_answer="Subscapularis",
                             explanation="The other three abduct or laterally rotate."),
                QuizQuestion(question="The supraspinatus tendon passes beneath the:",
                             options=["Acromion", "Coracoid process", "Glenoid labrum", "Greater tubercle"],
                             correct_answer="Acromion",
                             explanation="Its subacromial course explains impingement."),
                QuizQuestion(question="Infraspinatus is innervated by the:",
                             options=["Suprascapular nerve", "Axillary nerve", "Upper subscapular nerve", "Dorsal scapular nerve"],
                             correct_answer="Suprascapular nerve",
                             explanation="The suprascapular nerve supplies both supraspinatus and infraspinatus."),
            ],
        ),
        QuizAttempt(
            concept="Mediastinum", difficulty="medium", days_ago=9, correct=[1, 2],
            questions=[
                QuizQuestion(question="The boundary between the superior and inferior mediastinum is the plane through the:",
                             options=["Sternal angle and T4–T5 disc", "Xiphoid process and T10", "Jugular notch and T2", "Diaphragm"],
                             correct_answer="Sternal angle and T4–T5 disc",
                             explanation="The transverse thoracic plane at the sternal angle of Louis."),
                QuizQuestion(question="The heart lies in which subdivision?",
                             options=["Anterior mediastinum", "Middle mediastinum", "Posterior mediastinum", "Superior mediastinum"],
                             correct_answer="Middle mediastinum",
                             explanation="The middle mediastinum holds the pericardium and heart."),
                QuizQuestion(question="Which structure is in the posterior mediastinum?",
                             options=["Thymus", "Ascending aorta", "Esophagus", "Pulmonary trunk"],
                             correct_answer="Esophagus",
                             explanation="Esophagus, descending aorta, azygos vein and thoracic duct are posterior."),
                QuizQuestion(question="The phrenic nerves pass anterior to the lung root and supply the:",
                             options=["Diaphragm", "Intercostal muscles", "Heart rate", "Esophagus"],
                             correct_answer="Diaphragm",
                             explanation="C3, 4, 5 keeps the diaphragm alive; the vagus passes posterior to the root."),
            ],
        ),
    ],
    session=TutorSession(
        name="Localising upper limb nerve lesions",
        topic="Brachial Plexus",
        mode="socratic",
        summary_bullets=[
            "Worked from clinical sign back to nerve to plexus level",
            "Distinguished wrist drop (radial) from claw hand (ulnar)",
            "Linked Erb's palsy posture to the muscles that lose innervation",
        ],
        messages=[
            ChatMessage(role="user", content="I memorised the plexus diagram but I freeze on the lesion questions. How do I approach them?"),
            ChatMessage(role="assistant", content="Work backwards: sign -> muscle that's weak -> nerve -> where on the plexus. Try one. A newborn after a difficult delivery holds the arm adducted, medially rotated, forearm pronated. Which movements are missing?"),
            ChatMessage(role="user", content="Abduction, lateral rotation and supination?"),
            ChatMessage(role="assistant", content="Yes. Which muscles do those — and what root levels do they share?"),
            ChatMessage(role="user", content="Deltoid and supraspinatus abduct, infraspinatus laterally rotates, biceps supinates... they're all C5 and C6."),
            ChatMessage(role="assistant", content="That's the whole trick. All C5–C6 means the upper trunk, which is Erb's palsy. The unopposed muscles pull the arm into the 'waiter's tip' posture. Use the same steps for a hand that can't extend at the wrist: the extensors fail, they're all radial nerve, so look for a mid-shaft humerus fracture. Next time try it on claw hand and see if you land on the ulnar nerve."),
        ],
    ),
)

PACK = MajorPack(
    key="health",
    label="Health Science",
    year="Sophomore",
    courses=[HP151, HS201, HS300, HS369],
    total_xp=1380,
    streak_days=9,
)
