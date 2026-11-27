"""Business Administration seed pack: a Questrom sophomore's semester.

Strength profile: strongest in MO 221 (people and teams), comfortable in
MK 323 and SM 131, struggling with the mechanics of AC 221 (accounting).
"""
from __future__ import annotations

from textwrap import dedent

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


def _t(text: str) -> str:
    return dedent(text).strip()


# ---------------------------------------------------------------------------
# QST SM 131 — Business, Markets, and Society
# ---------------------------------------------------------------------------

SM131 = Course(
    code="QST SM 131",
    name="Business, Markets, and Society",
    department="Strategy and Innovation",
    nickname="SM 131 Biz & Society",
    color="#0EA5E9",
    concepts=[
        Concept(name="Stakeholder Theory", mastery=0.96,
                description="Freeman's view that firms create value for customers, employees, suppliers, communities and financiers, not only shareholders."),
        Concept(name="Supply and Demand", mastery=0.83,
                description="How market price and quantity are set where supply meets demand, and how shifts in either curve move the equilibrium."),
        Concept(name="Corporate Social Responsibility", mastery=0.76,
                description="Carroll's pyramid of economic, legal, ethical and philanthropic responsibilities, and the debate with Friedman's shareholder view."),
        Concept(name="Market Structures", mastery=0.61,
                description="Perfect competition, monopolistic competition, oligopoly and monopoly, and how each affects pricing power and profits."),
        Concept(name="Externalities", mastery=0.52,
                description="Costs or benefits that fall on third parties outside a transaction, such as pollution, and remedies like Pigouvian taxes and cap-and-trade."),
        Concept(name="Business Ethics Frameworks", mastery=0.47,
                description="Utilitarian, rights-based, justice and virtue approaches to judging a business decision."),
        Concept(name="Price Elasticity of Demand", mastery=0.34,
                description="%change in quantity demanded / %change in price; elastic (|E| > 1) vs inelastic goods and the effect on total revenue."),
        Concept(name="Corporate Governance", mastery=0.2,
                description="How boards, executives and shareholders share control: agency problems, board independence, and executive pay."),
        Concept(name="Globalization and Trade", mastery=0.06,
                description="Comparative advantage, tariffs, global supply chains, and the costs and benefits of offshoring."),
        Concept(name="ESG Reporting", mastery=0.0,
                description="Environmental, social and governance disclosure: frameworks like SASB and GRI, materiality, and greenwashing risk."),
    ],
    edges=[
        Edge(source="Supply and Demand", target="Price Elasticity of Demand", relationship="prerequisite", strength=0.85),
        Edge(source="Supply and Demand", target="Market Structures", relationship="prerequisite", strength=0.75),
        Edge(source="Stakeholder Theory", target="Corporate Social Responsibility", relationship="builds_on", strength=0.8),
        Edge(source="Externalities", target="Corporate Social Responsibility", relationship="related", strength=0.6),
        Edge(source="Business Ethics Frameworks", target="Corporate Social Responsibility", relationship="related", strength=0.65),
        Edge(source="Stakeholder Theory", target="Corporate Governance", relationship="related", strength=0.6),
        Edge(source="Corporate Social Responsibility", target="ESG Reporting", relationship="builds_on", strength=0.7),
        Edge(source="Market Structures", target="Globalization and Trade", relationship="related", strength=0.4),
    ],
    mastery_events=[
        MasteryEvent(concept="Stakeholder Theory", delta=0.1, reason="Strong Patagonia case write-up"),
        MasteryEvent(concept="Price Elasticity of Demand", delta=-0.07, reason="Mixed up elastic and inelastic in Case 2"),
        MasteryEvent(concept="Externalities", delta=0.08, reason="Carbon pricing case discussion"),
        MasteryEvent(concept="Corporate Governance", delta=0.05, reason="Read Boeing board chapter for Case 4"),
    ],
    categories=[
        Category(name="Case Write-ups", weight=0.3),
        Category(name="Team Project", weight=0.25),
        Category(name="Exams", weight=0.45),
    ],
    assignments=[
        Assignment(title="Case 1: Patagonia and the Stakeholder Model", category="Case Write-ups", type="homework",
                   due_offset_days=14, points_possible=20, points_earned=18),
        Assignment(title="Case 2: Uber Surge Pricing and Elasticity", category="Case Write-ups", type="homework",
                   due_offset_days=28, points_possible=20, points_earned=15),
        Assignment(title="Case 3: Carbon Pricing and the Externality Problem", category="Case Write-ups", type="homework",
                   due_offset_days=41, points_possible=20, points_earned=17),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=50, points_possible=100, points_earned=85, is_midterm=True),
        Assignment(title="Team Project Proposal: Industry Analysis", category="Team Project", type="project",
                   due_offset_days=61, points_possible=25, points_earned=23),
        Assignment(title="Case 4: Boeing 737 MAX and Board Oversight", category="Case Write-ups", type="homework",
                   due_offset_days=78, points_possible=20),
        Assignment(title="Team Project Final Presentation", category="Team Project", type="project",
                   due_offset_days=98, points_possible=75),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=106, points_possible=100),
    ],
    notes=[
        Note(
            title="Friedman vs Freeman — the core debate",
            tags=["csr", "stakeholders", "midterm"],
            concepts=["Stakeholder Theory", "Corporate Social Responsibility", "Business Ethics Frameworks"],
            body=_t("""
                ## Friedman (1970, NYT Magazine)
                "The social responsibility of business is to increase its profits."
                - Managers are **agents** of shareholders; spending company money on social causes is spending someone else's money.
                - Social goals belong to government and individuals.
                - Caveat people forget: *"while conforming to the basic rules of the society, both those embodied in law and those embodied in ethical custom."*

                ## Freeman (stakeholder theory, 1984)
                - A stakeholder = any group that can affect or is affected by the firm.
                - Managing for stakeholders is how you create long-run value, not a charity add-on.

                ## Carroll's CSR pyramid (bottom -> top)
                1. Economic (be profitable)
                2. Legal (obey the law)
                3. Ethical (do what is right beyond the law)
                4. Philanthropic (be a good corporate citizen)

                **Patagonia** is the class example of all four. Prof's midterm tip: don't just say "stakeholders matter" — name *which* stakeholder, *what* trade-off, and which framework justifies it.
            """),
        ),
        Note(
            title="Elasticity — finally getting it",
            tags=["economics", "elasticity"],
            concepts=["Price Elasticity of Demand", "Supply and Demand"],
            body=_t("""
                **Formula:** E = (% change in Qd) / (% change in P)

                Use the midpoint method so the answer is the same in both directions:
                %dQ = (Q2 - Q1) / ((Q1 + Q2)/2)

                | |E| | Name | Raise price -> total revenue |
                |---|---|---|
                | > 1 | elastic | falls |
                | < 1 | inelastic | rises |
                | = 1 | unit elastic | unchanged |

                **Example from Case 2:** surge pricing raises Uber's fare from $20 to $30 and rides drop from 100 to 80.
                %dP = 10/25 = 40%, %dQ = -20/90 = -22%. |E| = 0.56 -> **inelastic**, so revenue goes up ($2,000 -> $2,400).

                I wrote "elastic" on the case because demand *did* drop. Wrong idea: elasticity is about how much it drops **relative** to the price change.

                What makes demand inelastic: few substitutes, necessity, small share of budget, short time horizon (late at night, raining, no subway = inelastic ride demand).
            """),
        ),
    ],
    documents=[
        Document(
            file_name="sm131-syllabus.pdf",
            category="syllabus",
            summary="SM 131 syllabus: introduces how businesses operate within markets and society, covering markets and pricing, stakeholders and CSR, ethics, governance and globalization, graded on case write-ups, a team project and two exams.",
            concept_notes=[
                ConceptNote(name="Grading", description="Case write-ups 30%, team industry project 25%, midterm and final 45%."),
                ConceptNote(name="Case write-ups", description="Two-page memos answering the case questions, due before the class discussion."),
                ConceptNote(name="Team project", description="Teams of five analyze one industry's economics and its social impact, with a proposal and a final presentation."),
            ],
            extracted_text=_t("""
                QST SM 131: Business, Markets, and Society
                Questrom School of Business, Boston University

                Course Overview
                Business does not operate in a vacuum. This course introduces the economic, social and political environment in which firms compete. We study how markets set prices, when markets fail, how firms balance the interests of shareholders and other stakeholders, and how companies are governed and held accountable.

                Learning Goals
                1. Apply basic microeconomic tools (supply, demand, elasticity) to business decisions.
                2. Analyze a company's responsibilities to its stakeholders using ethical frameworks.
                3. Evaluate corporate governance structures and their failures.
                4. Assess the opportunities and risks of operating in a global economy.

                Assessment
                Case Write-ups (30%): four short memos, due at the start of the case discussion.
                Team Industry Project (25%): proposal (week 9) and final presentation (week 14).
                Midterm Exam (20%) and Final Exam (25%).

                Weekly Topics
                Weeks 1-2: What is a business? Value creation and stakeholders
                Weeks 3-4: Markets, supply and demand, elasticity
                Weeks 5-6: Market structures and market failure; externalities
                Week 7: Midterm exam
                Weeks 8-9: Ethics frameworks and corporate social responsibility
                Weeks 10-11: Corporate governance; case: Boeing 737 MAX
                Weeks 12-13: Globalization, trade, and ESG reporting
                Week 14: Team presentations

                Participation
                Come prepared to discuss the assigned case. Cold calls are part of the course.
            """),
        ),
        Document(
            file_name="sm131-week6-externalities-slides.pdf",
            category="lecture_notes",
            summary="Week 6 lecture slides on market failure: negative and positive externalities, the gap between private and social cost, and policy responses such as Pigouvian taxes, cap-and-trade and the Coase theorem.",
            concept_notes=[
                ConceptNote(name="Negative externality", description="A cost imposed on third parties, so the market produces more than the socially optimal quantity."),
                ConceptNote(name="Pigouvian tax", description="A tax equal to the external cost per unit, which makes producers internalize it."),
                ConceptNote(name="Cap-and-trade", description="Government caps total emissions and lets firms trade permits, so cuts happen where they are cheapest."),
                ConceptNote(name="Coase theorem", description="With clear property rights and low transaction costs, private bargaining can reach the efficient outcome."),
            ],
            extracted_text=_t("""
                Week 6: When Markets Fail - Externalities

                Definition
                An externality is a cost or benefit of an economic activity that falls on someone who is not part of the transaction.
                Negative: a factory's emissions raise asthma rates in the surrounding neighborhood.
                Positive: a homeowner's vaccination reduces disease risk for neighbors.

                Private vs. Social Cost
                Marginal Social Cost = Marginal Private Cost + Marginal External Cost.
                When firms only pay the private cost, the supply curve sits too low and the market produces more than the socially efficient quantity. The difference is a deadweight loss to society.

                Policy Responses
                1. Pigouvian tax: set a per-unit tax equal to the marginal external cost. Example: a carbon tax of $50 per ton of CO2.
                2. Cap-and-trade: set a total emissions cap and issue tradable permits. Firms that can cut emissions cheaply sell permits to firms that cannot. Example: the EU Emissions Trading System, RGGI in the northeastern U.S.
                3. Regulation: direct limits or technology standards.
                4. Coase theorem: if property rights are clear and bargaining is cheap, the affected parties can negotiate an efficient outcome without government.

                Discussion Question for Case 3
                Why might a firm voluntarily support a carbon price that raises its own costs? Consider reputation, regulatory certainty, and competitors with dirtier operations.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="Price elasticity of demand formula?", back="% change in quantity demanded / % change in price. |E| > 1 is elastic, |E| < 1 is inelastic."),
        Flashcard(front="If demand is inelastic and a firm raises its price, what happens to total revenue?", back="It rises, because quantity falls proportionally less than price rises."),
        Flashcard(front="What is a negative externality?", back="A cost of an activity borne by third parties outside the transaction (e.g. pollution)."),
        Flashcard(front="What is a Pigouvian tax?", back="A per-unit tax equal to the marginal external cost, forcing producers to internalize it."),
        Flashcard(front="Carroll's CSR pyramid, bottom to top?", back="Economic, legal, ethical, philanthropic."),
        Flashcard(front="Friedman's view of corporate social responsibility?", back="A business's social responsibility is to increase its profits within the rules of the game (law and ethical custom)."),
        Flashcard(front="What is an agency problem?", back="Conflict when managers (agents) act in their own interest rather than the shareholders' (principals)."),
        Flashcard(front="Which market structure has a few large firms whose decisions depend on each other?", back="Oligopoly (e.g. U.S. airlines, wireless carriers)."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers weeks 1-6: value creation and stakeholders, supply and demand, elasticity, market structures and externalities. Format: 25 multiple choice questions plus one short case analysis applying a stakeholder or ethics framework.",
        topics=[
            StudyGuideTopic(name="Markets and pricing",
                            importance="About half the multiple choice; expect at least one elasticity calculation with the midpoint method.",
                            concepts=["Supply and Demand", "Price Elasticity of Demand", "Market Structures"]),
            StudyGuideTopic(name="Stakeholders and CSR",
                            importance="The short case analysis is graded on naming specific stakeholders and trade-offs.",
                            concepts=["Stakeholder Theory", "Corporate Social Responsibility"]),
            StudyGuideTopic(name="Market failure",
                            importance="Know the difference between a Pigouvian tax and cap-and-trade, with an example of each.",
                            concepts=["Externalities"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Price Elasticity of Demand", difficulty="medium", days_ago=33,
            questions=[
                QuizQuestion(
                    question="A coffee shop raises its latte price by 10% and sells 25% fewer lattes. Demand is:",
                    options=["Elastic", "Inelastic", "Unit elastic", "Perfectly inelastic"], correct_answer="Elastic",
                    explanation="|E| = 25% / 10% = 2.5 > 1."),
                QuizQuestion(
                    question="Which good is most likely to have inelastic demand?",
                    options=["Insulin", "A specific brand of potato chips", "Movie tickets", "Restaurant meals"], correct_answer="Insulin",
                    explanation="Necessities with few substitutes have inelastic demand."),
                QuizQuestion(
                    question="If demand for a product is elastic, a price increase will:",
                    options=["Decrease total revenue", "Increase total revenue", "Leave total revenue unchanged", "Shift the demand curve right"],
                    correct_answer="Decrease total revenue",
                    explanation="Quantity falls by a larger percentage than price rises."),
                QuizQuestion(
                    question="Using the midpoint method, price rises from $4 to $6 and quantity falls from 120 to 80. What is |E|?",
                    options=["1.0", "0.5", "2.0", "1.5"], correct_answer="1.0",
                    explanation="%dQ = 40/100 = 40%, %dP = 2/5 = 40%, so |E| = 1."),
            ],
            correct=[0, 1],
        ),
        QuizAttempt(
            concept="Stakeholder Theory", difficulty="easy", days_ago=19,
            questions=[
                QuizQuestion(
                    question="According to Freeman, a stakeholder is:",
                    options=["Any group that can affect or is affected by the firm's objectives", "Only those who own shares",
                             "Only employees and customers", "Government regulators"],
                    correct_answer="Any group that can affect or is affected by the firm's objectives",
                    explanation="Freeman's definition is deliberately broad."),
                QuizQuestion(
                    question="Which statement best reflects Milton Friedman's 1970 essay?",
                    options=["The social responsibility of business is to increase its profits within the rules of the game",
                             "Firms should donate a fixed share of profits to charity",
                             "Managers owe equal duties to all stakeholders",
                             "Corporations should replace governments in solving social problems"],
                    correct_answer="The social responsibility of business is to increase its profits within the rules of the game",
                    explanation="Friedman argued social spending by managers is a tax on shareholders."),
                QuizQuestion(
                    question="In Carroll's pyramid, which responsibility sits at the base?",
                    options=["Economic", "Legal", "Ethical", "Philanthropic"], correct_answer="Economic",
                    explanation="A firm must be profitable before it can meet the other responsibilities."),
            ],
            correct=[0, 1, 2],
        ),
    ],
    session=TutorSession(
        name="Is surge pricing elastic?",
        topic="Price Elasticity of Demand",
        mode="socratic",
        summary_bullets=[
            "Recomputed the Case 2 elasticity with the midpoint method (|E| about 0.56).",
            "Separated 'demand fell' from 'demand is elastic'.",
            "Linked inelastic demand to higher revenue under surge pricing.",
        ],
        messages=[
            ChatMessage(role="user", content="I lost points on the Uber case for saying demand is elastic. Rides went down when surge pricing kicked in, so isn't that elastic?"),
            ChatMessage(role="assistant", content="Almost every demand curve slopes down, so quantity falling is expected. Elasticity asks how big that fall is compared to the price change. In the case, what were the price and quantity before and after surge?"),
            ChatMessage(role="user", content="Price went from $20 to $30 and rides went from 100 to 80."),
            ChatMessage(role="assistant", content="Use the midpoint method. What percent did the price change, and what percent did quantity change? Divide each change by the average of the two values."),
            ChatMessage(role="user", content="Price: 10 / 25 = 40%. Quantity: 20 / 90 = about 22%. So 22 / 40 = 0.56?"),
            ChatMessage(role="assistant", content="Right, |E| is about 0.56, which is less than 1, so demand is inelastic. Check total revenue: $20 x 100 = $2,000 before and $30 x 80 = $2,400 after. When demand is inelastic, raising the price raises revenue. Why might riders late on a rainy night be so unresponsive to price?"),
            ChatMessage(role="user", content="Because there aren't good substitutes then, like the T stopped running and it's raining."),
            ChatMessage(role="assistant", content="Exactly: few substitutes and an urgent need. Put that reasoning in your rewrite and you'll have both the number and the economics behind it."),
        ],
    ),
)


# ---------------------------------------------------------------------------
# QST AC 221 — Financial Accounting
# ---------------------------------------------------------------------------

AC221 = Course(
    code="QST AC 221",
    name="Financial Accounting",
    department="Accounting",
    nickname="AC 221 Fin Acct",
    color="#EF4444",
    concepts=[
        Concept(name="The Accounting Equation", mastery=0.96,
                description="Assets = Liabilities + Stockholders' Equity; every transaction keeps both sides in balance."),
        Concept(name="Income Statement", mastery=0.79,
                description="Revenues minus expenses for a period, from gross profit to operating income to net income."),
        Concept(name="Debits and Credits", mastery=0.68,
                description="Debits increase assets, expenses and dividends; credits increase liabilities, equity and revenues."),
        Concept(name="Journal Entries and T-Accounts", mastery=0.62,
                description="Recording each transaction as equal debits and credits, posting to T-accounts, and preparing a trial balance."),
        Concept(name="Balance Sheet", mastery=0.56,
                description="A point-in-time statement of assets, liabilities and equity, split into current and non-current items."),
        Concept(name="Accrual vs Cash Basis", mastery=0.49,
                description="Revenue recognition when earned and expense matching under accrual accounting, versus recording only when cash moves."),
        Concept(name="Adjusting Entries", mastery=0.31,
                description="End-of-period entries for accrued revenues and expenses, deferred (unearned) revenue, prepaid expenses and depreciation."),
        Concept(name="Inventory Costing", mastery=0.24,
                description="FIFO, LIFO and weighted-average methods and how each affects cost of goods sold and ending inventory."),
        Concept(name="Depreciation", mastery=0.13,
                description="Allocating an asset's cost over its useful life: straight-line (cost - salvage) / life and double-declining balance."),
        Concept(name="Statement of Cash Flows", mastery=0.02,
                description="Cash from operating, investing and financing activities; the indirect method starting from net income."),
    ],
    edges=[
        Edge(source="The Accounting Equation", target="Debits and Credits", relationship="prerequisite", strength=0.9),
        Edge(source="Debits and Credits", target="Journal Entries and T-Accounts", relationship="prerequisite", strength=0.9),
        Edge(source="Journal Entries and T-Accounts", target="Adjusting Entries", relationship="builds_on", strength=0.8),
        Edge(source="Accrual vs Cash Basis", target="Adjusting Entries", relationship="prerequisite", strength=0.85),
        Edge(source="Depreciation", target="Adjusting Entries", relationship="part_of", strength=0.6),
        Edge(source="Inventory Costing", target="Income Statement", relationship="related", strength=0.65),
        Edge(source="Income Statement", target="Statement of Cash Flows", relationship="prerequisite", strength=0.75),
        Edge(source="Balance Sheet", target="Statement of Cash Flows", relationship="prerequisite", strength=0.75),
        Edge(source="The Accounting Equation", target="Balance Sheet", relationship="related", strength=0.7),
    ],
    mastery_events=[
        MasteryEvent(concept="Adjusting Entries", delta=-0.09, reason="Missed unearned revenue adjustment on HW 3"),
        MasteryEvent(concept="Debits and Credits", delta=0.1, reason="Connect practice set on normal balances"),
        MasteryEvent(concept="Accrual vs Cash Basis", delta=0.06, reason="Tutor session on revenue recognition"),
        MasteryEvent(concept="Inventory Costing", delta=0.05, reason="Worked FIFO example from lecture"),
    ],
    categories=[
        Category(name="Homework", weight=0.25, drop_lowest=1),
        Category(name="Quizzes", weight=0.15),
        Category(name="Exams", weight=0.6),
    ],
    assignments=[
        Assignment(title="HW 1: The Accounting Equation", category="Homework", type="homework",
                   due_offset_days=9, points_possible=30, points_earned=29),
        Assignment(title="HW 2: Recording Transactions", category="Homework", type="homework",
                   due_offset_days=19, points_possible=30, points_earned=24),
        Assignment(title="Quiz 1: Journal Entries", category="Quizzes", type="quiz",
                   due_offset_days=24, points_possible=20, points_earned=14),
        Assignment(title="HW 3: Adjusting Entries and the Trial Balance", category="Homework", type="homework",
                   due_offset_days=35, points_possible=30, points_earned=20),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=49, points_possible=100, points_earned=72, is_midterm=True),
        Assignment(title="HW 5: Inventory and Cost of Goods Sold", category="Homework", type="homework",
                   due_offset_days=70, points_possible=30),
        Assignment(title="Quiz 3: Depreciation Methods", category="Quizzes", type="quiz",
                   due_offset_days=84, points_possible=20),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=105, points_possible=100),
    ],
    notes=[
        Note(
            title="Debits and credits — DEALER",
            tags=["debits-credits", "journal-entries"],
            concepts=["Debits and Credits", "Journal Entries and T-Accounts", "The Accounting Equation"],
            body=_t("""
                ## DEALER mnemonic
                - **D**ividends, **E**xpenses, **A**ssets -> increase with a **debit** (left side)
                - **L**iabilities, **E**quity, **R**evenues -> increase with a **credit** (right side)

                Debit just means LEFT. It is not "good" or "bad."

                ## Example entries
                1. Issued stock for $10,000 cash
                   - Dr Cash 10,000 / Cr Common Stock 10,000
                2. Bought supplies on account, $800
                   - Dr Supplies 800 / Cr Accounts Payable 800
                3. Provided services, client will pay next month, $2,500
                   - Dr Accounts Receivable 2,500 / Cr Service Revenue 2,500
                4. Paid rent for this month, $1,200
                   - Dr Rent Expense 1,200 / Cr Cash 1,200

                ## Checks
                - Every entry: total debits = total credits.
                - After posting, trial balance debits = credits (but that does NOT prove every entry is right, e.g. the wrong account with the right amount).

                Quiz 1 mistake: I credited Cash when the customer PAID me. Cash goes UP so it's a debit.
            """),
        ),
        Note(
            title="Adjusting entries — four types",
            tags=["adjusting-entries", "accrual", "midterm"],
            concepts=["Adjusting Entries", "Accrual vs Cash Basis", "Depreciation"],
            body=_t("""
                Adjusting entries happen at period end so revenue is recorded when **earned** and expenses when **incurred** (accrual basis). They never touch Cash.

                | Type | Before adjusting | Adjusting entry |
                |---|---|---|
                | Prepaid expense | Paid cash in advance (asset) | Dr Expense / Cr Prepaid asset |
                | Unearned revenue | Received cash in advance (liability) | Dr Unearned Revenue / Cr Revenue |
                | Accrued expense | Incurred, not yet paid | Dr Expense / Cr Payable |
                | Accrued revenue | Earned, not yet billed | Dr Receivable / Cr Revenue |

                **Depreciation** is a prepaid-style adjustment: Dr Depreciation Expense / Cr Accumulated Depreciation (contra-asset).

                ### HW 3 problem I got wrong
                Customer paid $6,000 on Oct 1 for 6 months of service. By Dec 31, 3 months are earned.
                Dr Unearned Revenue 3,000 / Cr Service Revenue 3,000.
                I recorded all $6,000 as revenue in October. That's cash basis thinking.

                Need to redo the textbook's practice set on accrued wages before the midterm.
            """),
        ),
    ],
    documents=[
        Document(
            file_name="ac221-syllabus.pdf",
            category="syllabus",
            summary="AC 221 syllabus: introductory financial accounting covering the accounting cycle, financial statements, accruals, inventory, long-lived assets and cash flows, graded on homework, quizzes and exams.",
            concept_notes=[
                ConceptNote(name="Grading", description="Homework 25% (lowest dropped), quizzes 15%, exams 60%."),
                ConceptNote(name="Homework platform", description="Homework is completed online in McGraw Hill Connect; three attempts per problem."),
                ConceptNote(name="Calculator policy", description="Only basic non-programmable calculators are allowed on exams."),
            ],
            extracted_text=_t("""
                QST AC 221: Financial Accounting
                Questrom School of Business, Boston University

                Course Description
                Financial accounting is the language of business. This course teaches students how companies record economic events and communicate their financial position and performance to investors, lenders and other external users through the financial statements.

                Course Objectives
                - Analyze transactions using the accounting equation and record them in journal entries.
                - Complete the accounting cycle, including adjusting and closing entries.
                - Prepare and interpret the income statement, balance sheet, statement of stockholders' equity and statement of cash flows.
                - Apply GAAP rules for receivables, inventory, and long-lived assets.

                Required Materials
                Spiceland, Thomas and Herrmann, Financial Accounting, with McGraw Hill Connect access.

                Grading
                Connect Homework 25% (lowest score dropped)
                In-class Quizzes 15%
                Midterm Exam 25%
                Final Exam (cumulative) 35%

                Schedule
                Weeks 1-2: The accounting equation and financial statements (Ch. 1)
                Weeks 3-4: The accounting cycle: debits, credits, journal entries (Ch. 2)
                Weeks 5-6: Accrual accounting and adjusting entries (Ch. 3)
                Week 7: Midterm
                Weeks 8-9: Receivables and inventory: FIFO, LIFO, weighted average (Ch. 5-6)
                Weeks 10-11: Long-lived assets and depreciation (Ch. 7)
                Weeks 12-13: Liabilities, equity, and the statement of cash flows (Ch. 8-11)

                Note: accounting builds cumulatively. Falling behind on journal entries makes later chapters very difficult.
            """),
        ),
        Document(
            file_name="ac221-ch3-accrual-accounting-notes.pdf",
            category="lecture_notes",
            summary="Chapter 3 lecture notes on accrual accounting: the revenue recognition and expense matching principles and the four categories of adjusting entries, with worked examples.",
            concept_notes=[
                ConceptNote(name="Revenue recognition principle", description="Record revenue when the company satisfies its performance obligation, not when cash is received."),
                ConceptNote(name="Matching principle", description="Record expenses in the same period as the revenues they helped generate."),
                ConceptNote(name="Unearned revenue", description="A liability for cash received before the service is performed."),
                ConceptNote(name="Accumulated depreciation", description="A contra-asset account that reduces the book value of equipment."),
            ],
            extracted_text=_t("""
                Chapter 3: The Accounting Cycle - End of the Period

                Accrual-Basis vs. Cash-Basis Accounting
                Under cash-basis accounting, revenues are recorded when cash is received and expenses when cash is paid. GAAP requires accrual-basis accounting, which records revenues when earned and expenses when incurred, regardless of when cash changes hands.

                Revenue Recognition Principle: record revenue when goods or services are provided to customers.
                Expense Recognition (Matching) Principle: record expenses in the same period as the revenues they help produce.

                Adjusting Entries
                Adjusting entries are recorded at the end of each period to update account balances. There are two broad categories:

                Prepayments
                1. Prepaid expenses: cash paid before the expense is incurred. Example: on Oct 1 the company pays $2,400 for one year of insurance. On Dec 31, three months have expired.
                   Dr Insurance Expense 600; Cr Prepaid Insurance 600
                2. Unearned revenues: cash received before the service is provided.
                3. Depreciation of equipment: Dr Depreciation Expense; Cr Accumulated Depreciation.

                Accruals
                4. Accrued expenses: incurred but not yet paid, such as salaries earned by employees in the last week of December.
                   Dr Salaries Expense; Cr Salaries Payable
                5. Accrued revenues: earned but not yet received, such as interest receivable.

                Key point: adjusting entries never involve the Cash account. Each one affects one balance sheet account and one income statement account.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="State the accounting equation.", back="Assets = Liabilities + Stockholders' Equity"),
        Flashcard(front="Which accounts increase with a debit?", back="Assets, expenses and dividends (DEA in DEALER)."),
        Flashcard(front="Journal entry: company receives $5,000 cash in advance for services next month.", back="Dr Cash 5,000 / Cr Unearned Revenue 5,000"),
        Flashcard(front="Is unearned revenue an asset, liability or revenue?", back="A liability: the company owes the customer a service."),
        Flashcard(front="Straight-line depreciation formula?", back="(Cost - Salvage value) / Useful life"),
        Flashcard(front="In a period of rising prices, which method gives the higher cost of goods sold, FIFO or LIFO?", back="LIFO, because the most recent (higher) costs are expensed first."),
        Flashcard(front="Do adjusting entries ever involve Cash?", back="No. Each adjusts one balance sheet account and one income statement account."),
        Flashcard(front="What are the three sections of the statement of cash flows?", back="Operating, investing and financing activities."),
        Flashcard(front="What is a contra-asset account? Give an example.", back="An account that reduces an asset's balance, e.g. Accumulated Depreciation or Allowance for Uncollectible Accounts."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers Chapters 1-3: the accounting equation, the four financial statements, debits and credits, journal entries, the trial balance, and adjusting entries. Most points come from recording entries and preparing statements from an adjusted trial balance.",
        topics=[
            StudyGuideTopic(name="Recording transactions",
                            importance="Roughly 40% of the exam is writing journal entries; debits and credits must balance.",
                            concepts=["Debits and Credits", "Journal Entries and T-Accounts", "The Accounting Equation"]),
            StudyGuideTopic(name="Adjusting entries",
                            importance="Always a multi-part problem; this is where I've lost the most points so far.",
                            concepts=["Adjusting Entries", "Accrual vs Cash Basis"]),
            StudyGuideTopic(name="Preparing the financial statements",
                            importance="Build an income statement and balance sheet from an adjusted trial balance; know which accounts go where.",
                            concepts=["Income Statement", "Balance Sheet"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Debits and Credits", difficulty="easy", days_ago=38,
            questions=[
                QuizQuestion(
                    question="Which of the following increases with a credit?",
                    options=["Service Revenue", "Cash", "Rent Expense", "Equipment"], correct_answer="Service Revenue",
                    explanation="Revenues, liabilities and equity increase with credits."),
                QuizQuestion(
                    question="A company pays $500 on an account payable. The journal entry is:",
                    options=["Dr Accounts Payable 500 / Cr Cash 500", "Dr Cash 500 / Cr Accounts Payable 500",
                             "Dr Expense 500 / Cr Cash 500", "Dr Accounts Payable 500 / Cr Revenue 500"],
                    correct_answer="Dr Accounts Payable 500 / Cr Cash 500",
                    explanation="Both a liability and an asset decrease."),
                QuizQuestion(
                    question="What is the normal balance of the Dividends account?",
                    options=["Debit", "Credit", "Zero", "It depends on net income"], correct_answer="Debit",
                    explanation="Dividends reduce equity, so they carry a debit balance."),
            ],
            correct=[0, 2],
        ),
        QuizAttempt(
            concept="Adjusting Entries", difficulty="medium", days_ago=14,
            questions=[
                QuizQuestion(
                    question="On Nov 1, a company receives $3,000 for three months of service. What is the Dec 31 adjusting entry?",
                    options=["Dr Unearned Revenue 2,000 / Cr Service Revenue 2,000",
                             "Dr Cash 3,000 / Cr Service Revenue 3,000",
                             "Dr Service Revenue 1,000 / Cr Unearned Revenue 1,000",
                             "Dr Unearned Revenue 3,000 / Cr Service Revenue 3,000"],
                    correct_answer="Dr Unearned Revenue 2,000 / Cr Service Revenue 2,000",
                    explanation="Two of the three months ($1,000 each) have been earned by Dec 31."),
                QuizQuestion(
                    question="Employees earned $1,800 of wages in the last week of December, to be paid January 5. The Dec 31 adjusting entry is:",
                    options=["Dr Wages Expense 1,800 / Cr Wages Payable 1,800", "Dr Wages Payable 1,800 / Cr Cash 1,800",
                             "No entry until the wages are paid", "Dr Wages Expense 1,800 / Cr Cash 1,800"],
                    correct_answer="Dr Wages Expense 1,800 / Cr Wages Payable 1,800",
                    explanation="An accrued expense: incurred in December, paid later."),
                QuizQuestion(
                    question="Equipment costing $12,000 with a $2,000 salvage value and a 5-year life is depreciated straight-line. Annual depreciation is:",
                    options=["$2,000", "$2,400", "$2,800", "$10,000"], correct_answer="$2,000",
                    explanation="(12,000 - 2,000) / 5 = 2,000."),
                QuizQuestion(
                    question="Failing to record an accrued expense at year end will cause:",
                    options=["Expenses understated and net income overstated", "Assets overstated and net income understated",
                             "Liabilities overstated and expenses understated", "No effect on the financial statements"],
                    correct_answer="Expenses understated and net income overstated",
                    explanation="The expense and the liability are both missing, so net income is too high."),
            ],
            correct=[1],
        ),
        QuizAttempt(
            concept="Inventory Costing", difficulty="hard", days_ago=2,
            questions=[
                QuizQuestion(
                    question="A store buys 10 units at $5, then 10 units at $7, and sells 12 units. Under FIFO, what is cost of goods sold?",
                    options=["$64", "$74", "$72", "$60"], correct_answer="$64",
                    explanation="10 x $5 + 2 x $7 = $64."),
                QuizQuestion(
                    question="Same purchases and sale, under LIFO. What is cost of goods sold?",
                    options=["$80", "$74", "$64", "$72"], correct_answer="$80",
                    explanation="10 x $7 + 2 x $5 = $80."),
                QuizQuestion(
                    question="In a period of rising costs, which method reports the highest net income?",
                    options=["FIFO", "LIFO", "Weighted average", "They are always identical"], correct_answer="FIFO",
                    explanation="FIFO expenses the older, cheaper costs, so COGS is lowest."),
            ],
            correct=[0, 2],
        ),
    ],
    session=TutorSession(
        name="Unearned revenue confusion",
        topic="Adjusting Entries",
        mode="expository",
        summary_bullets=[
            "Explained why cash received in advance is a liability, not revenue.",
            "Walked through the initial entry and the period-end adjustment for a 6-month contract.",
            "Previewed accrued expenses as the mirror-image case.",
        ],
        messages=[
            ChatMessage(role="user", content="Why is unearned revenue a liability? The company got the cash, so isn't that good for them?"),
            ChatMessage(role="assistant", content="Getting cash is good, but at that moment the company hasn't done the work yet. It owes the customer either the service or a refund, and an obligation like that is exactly what a liability is. So when $6,000 arrives on Oct 1 for six months of service, the entry is Dr Cash 6,000 / Cr Unearned Revenue 6,000. Assets up, liabilities up, equation still balances."),
            ChatMessage(role="user", content="Ok so when does it become actual revenue?"),
            ChatMessage(role="assistant", content="As the service is performed. Under the revenue recognition principle, each month the company earns $1,000. At the Dec 31 year end, three months are done, so the adjusting entry is Dr Unearned Revenue 3,000 / Cr Service Revenue 3,000. The liability shrinks to $3,000 for the three months still owed, and $3,000 of revenue lands on this year's income statement."),
            ChatMessage(role="user", content="That's what I got wrong on HW 3. I put the whole $6,000 as revenue in October."),
            ChatMessage(role="assistant", content="That's the cash-basis instinct, and it's the most common mistake in Chapter 3. A quick self-check for any adjusting entry: it should touch one balance sheet account and one income statement account, and never Cash. Accrued expenses are the mirror image: you've used a service but haven't paid yet, so you debit an expense and credit a payable."),
        ],
    ),
)


# ---------------------------------------------------------------------------
# QST MK 323 — Marketing Management
# ---------------------------------------------------------------------------

MK323 = Course(
    code="QST MK 323",
    name="Marketing Management",
    department="Marketing",
    nickname="MK 323 Marketing",
    color="#EC4899",
    concepts=[
        Concept(name="The Marketing Mix", mastery=0.96,
                description="The 4Ps — product, price, place and promotion — as the levers a manager sets to deliver a positioning."),
        Concept(name="Segmentation, Targeting and Positioning", mastery=0.8,
                description="Dividing a market by demographic, psychographic or behavioral variables, choosing target segments, and owning a position in their minds."),
        Concept(name="Product Life Cycle", mastery=0.77,
                description="Introduction, growth, maturity and decline stages, and how marketing strategy shifts across them."),
        Concept(name="Consumer Decision Process", mastery=0.72,
                description="Need recognition, information search, evaluation of alternatives, purchase, and post-purchase behavior."),
        Concept(name="Brand Equity", mastery=0.63,
                description="The value a brand name adds beyond the product itself; Keller's customer-based brand equity pyramid."),
        Concept(name="Pricing Strategy", mastery=0.55,
                description="Cost-plus, value-based and competitive pricing; skimming vs penetration; tiered and psychological pricing."),
        Concept(name="Customer Lifetime Value", mastery=0.41,
                description="The present value of the margin a customer generates over the relationship: CLV = m x r / (1 + i - r)."),
        Concept(name="Market Research Methods", mastery=0.27,
                description="Qualitative (interviews, focus groups) vs quantitative (surveys, conjoint analysis) research, and sampling bias."),
        Concept(name="Digital Marketing Funnel", mastery=0.08,
                description="Awareness, consideration, conversion and loyalty stages measured with CTR, conversion rate and customer acquisition cost."),
        Concept(name="Channel Strategy", mastery=0.0,
                description="Direct vs indirect distribution, intermediaries, omnichannel retail, and channel conflict."),
    ],
    edges=[
        Edge(source="Market Research Methods", target="Segmentation, Targeting and Positioning", relationship="prerequisite", strength=0.7),
        Edge(source="Segmentation, Targeting and Positioning", target="The Marketing Mix", relationship="prerequisite", strength=0.85),
        Edge(source="Consumer Decision Process", target="Segmentation, Targeting and Positioning", relationship="related", strength=0.55),
        Edge(source="Pricing Strategy", target="The Marketing Mix", relationship="part_of", strength=0.8),
        Edge(source="Channel Strategy", target="The Marketing Mix", relationship="part_of", strength=0.8),
        Edge(source="Brand Equity", target="Pricing Strategy", relationship="related", strength=0.6),
        Edge(source="Product Life Cycle", target="Pricing Strategy", relationship="related", strength=0.5),
        Edge(source="Customer Lifetime Value", target="Digital Marketing Funnel", relationship="related", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Segmentation, Targeting and Positioning", delta=0.12, reason="Oatly positioning map in Case 1"),
        MasteryEvent(concept="Customer Lifetime Value", delta=-0.05, reason="Forgot the discount rate in CLV practice"),
        MasteryEvent(concept="Pricing Strategy", delta=0.08, reason="Netflix tiered pricing case discussion"),
        MasteryEvent(concept="Market Research Methods", delta=0.04, reason="Drafted survey for marketing plan"),
    ],
    categories=[
        Category(name="Case Analyses", weight=0.3),
        Category(name="Marketing Plan Project", weight=0.3),
        Category(name="Exams", weight=0.4),
    ],
    assignments=[
        Assignment(title="Case 1: Positioning Oatly in the U.S. Dairy Aisle", category="Case Analyses", type="homework",
                   due_offset_days=16, points_possible=25, points_earned=23),
        Assignment(title="Case 2: Netflix and Tiered Subscription Pricing", category="Case Analyses", type="homework",
                   due_offset_days=30, points_possible=25, points_earned=21),
        Assignment(title="Marketing Plan Milestone 1: Situation Analysis", category="Marketing Plan Project", type="project",
                   due_offset_days=38, points_possible=40, points_earned=36),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=53, points_possible=100, points_earned=88, is_midterm=True),
        Assignment(title="Case 3: Customer Lifetime Value at a Meal-Kit Startup", category="Case Analyses", type="homework",
                   due_offset_days=67, points_possible=25),
        Assignment(title="Marketing Plan Milestone 2: STP and Positioning Map", category="Marketing Plan Project", type="project",
                   due_offset_days=80, points_possible=40),
        Assignment(title="Final Marketing Plan Presentation", category="Marketing Plan Project", type="project",
                   due_offset_days=100, points_possible=100),
    ],
    notes=[
        Note(
            title="STP → positioning statement",
            tags=["stp", "positioning", "midterm"],
            concepts=["Segmentation, Targeting and Positioning", "The Marketing Mix", "Consumer Decision Process"],
            body=_t("""
                ## Segmentation bases
                - **Demographic:** age, income, household size
                - **Geographic:** region, urban vs rural
                - **Psychographic:** values, lifestyle, personality
                - **Behavioral:** usage rate, occasion, benefits sought, loyalty

                Good segments are **measurable, substantial, accessible, differentiable, actionable**.

                ## Targeting
                Undifferentiated (mass) -> differentiated (several segments) -> concentrated (one niche) -> micromarketing.

                ## Positioning statement template
                > For **[target]** who **[need]**, **[brand]** is the **[frame of reference]** that **[point of difference]** because **[reason to believe]**.

                **Oatly (Case 1):** For eco-conscious urban coffee drinkers who want a creamy plant-based option, Oatly is the oat milk that foams like dairy because it was developed with baristas.

                Positioning drives the 4Ps: premium price, coffee-shop distribution first (place), quirky packaging and ads (promotion). Prof said the exam essay is graded on whether the mix is *consistent* with the positioning.
            """),
        ),
        Note(
            title="CLV formula + worked example",
            tags=["clv", "metrics"],
            concepts=["Customer Lifetime Value", "Pricing Strategy"],
            body=_t("""
                ## Simple CLV (infinite horizon, constant margin and retention)

                **CLV = m x r / (1 + i - r)**
                - m = annual margin per customer
                - r = retention rate (probability they stay another year)
                - i = discount rate

                Some versions add the first-year margin up front: CLV = m x (1 + i) / (1 + i - r). Check which one the problem uses!

                ### Example
                Meal-kit customer: m = $120/yr, r = 0.6, i = 0.1
                CLV = 120 x 0.6 / (1.1 - 0.6) = 72 / 0.5 = **$144**

                If acquisition cost (CAC) is $150, each customer **loses** money. Options: raise retention, raise margin, or cut CAC.

                ### Sensitivity
                Raising r from 0.6 to 0.7: 120 x 0.7 / 0.4 = $210. Retention matters a lot!

                I keep forgetting the discount rate and just doing m / (1 - r). Practice problems 3-5 in the packet before Case 3.
            """),
        ),
    ],
    documents=[
        Document(
            file_name="mk323-syllabus.pdf",
            category="syllabus",
            summary="MK 323 syllabus: core marketing management course on customer analysis, STP, the marketing mix, branding, pricing and marketing metrics, assessed through case analyses, a team marketing plan and a midterm.",
            concept_notes=[
                ConceptNote(name="Grading", description="Case analyses 30%, team marketing plan 30%, midterm exam 40%."),
                ConceptNote(name="Marketing plan", description="Teams build a full marketing plan for a real local business across two milestones and a final presentation."),
                ConceptNote(name="Case prep", description="Each case analysis is a 3-page memo with exhibits, submitted before class."),
                ConceptNote(name="Participation", description="Case discussions rely on cold calls; preparation is expected."),
            ],
            extracted_text=_t("""
                QST MK 323: Marketing Management
                Questrom School of Business, Boston University

                Course Description
                Marketing is the process of creating, communicating and delivering value to customers in a way that also captures value for the firm. This course develops the analytical tools managers use to understand customers, select target markets, and design an integrated marketing program.

                Learning Outcomes
                Students will be able to:
                - Conduct a situation analysis (5Cs: company, customers, competitors, collaborators, context).
                - Segment a market, select targets, and write a positioning statement.
                - Design a consistent marketing mix (product, price, place, promotion).
                - Evaluate marketing decisions using metrics such as customer lifetime value and break-even.

                Readings
                Kotler and Keller, Marketing Management, plus Harvard Business School cases available in the course pack.

                Evaluation
                Case Analyses 30%
                Team Marketing Plan 30% (Milestone 1: 10%, Milestone 2: 10%, Final Presentation: 10%)
                Midterm Exam 40%

                Course Outline
                Module 1: Marketing strategy and the 5Cs
                Module 2: Consumer behavior and market research
                Module 3: Segmentation, targeting and positioning
                Module 4: Product and brand management; the product life cycle
                Module 5: Pricing strategy
                Module 6: Distribution channels and integrated marketing communications
                Module 7: Customer lifetime value and digital marketing metrics

                Professionalism
                Laptops closed during case discussion unless the case requires analysis.
            """),
        ),
        Document(
            file_name="mk323-module5-pricing-slides.pdf",
            category="lecture_notes",
            summary="Module 5 slides on pricing strategy: the three Cs of pricing, value-based versus cost-plus pricing, skimming and penetration strategies, and tiered pricing illustrated with streaming services.",
            concept_notes=[
                ConceptNote(name="Three Cs of pricing", description="Costs set the floor, customer value sets the ceiling, competitors shape where you land between them."),
                ConceptNote(name="Price skimming", description="Launch at a high price to capture early adopters' willingness to pay, then lower it over time."),
                ConceptNote(name="Penetration pricing", description="Launch at a low price to build share quickly, useful with network effects or economies of scale."),
                ConceptNote(name="Tiered pricing", description="Several versions at different prices so customers self-select by willingness to pay."),
            ],
            extracted_text=_t("""
                Module 5: Pricing Strategy

                Why pricing matters
                Price is the only element of the marketing mix that produces revenue; all others produce costs. A 1% price improvement typically has a larger effect on operating profit than a 1% increase in volume.

                The Three Cs of Pricing
                Costs: the price floor. Below it, each sale loses money.
                Customers: perceived value sets the price ceiling.
                Competitors: alternatives determine where between floor and ceiling you can price.

                Approaches
                Cost-plus pricing: unit cost x (1 + markup). Simple but ignores what customers will pay.
                Value-based pricing: start from the customer's economic value and price to capture part of it.
                Competition-based pricing: price relative to the closest alternatives.

                New Product Strategies
                Skimming: high initial price for early adopters (e.g. new gaming consoles). Works when demand is inelastic and the product is hard to copy.
                Penetration: low initial price to grow share fast. Works when demand is price-sensitive or network effects matter.

                Tiered Pricing Example: Streaming Services
                Ad-supported tier, standard tier, premium tier. The ad-supported plan brings in price-sensitive customers; the premium tier captures heavy users. Each tier's features must be different enough that customers sort themselves correctly without cannibalizing the higher tiers.

                Psychological Pricing
                Charm prices ($9.99), anchoring with a high reference price, and decoy options.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="What are the 4Ps?", back="Product, price, place (distribution), promotion."),
        Flashcard(front="What are the 5Cs of a situation analysis?", back="Company, customers, competitors, collaborators, context."),
        Flashcard(front="Positioning statement template?", back="For [target] who [need], [brand] is the [frame of reference] that [point of difference] because [reason to believe]."),
        Flashcard(front="CLV formula (infinite horizon)?", back="CLV = m x r / (1 + i - r), with margin m, retention r and discount rate i."),
        Flashcard(front="Price skimming vs penetration?", back="Skimming launches high to capture early adopters; penetration launches low to win share fast."),
        Flashcard(front="Stages of the product life cycle?", back="Introduction, growth, maturity, decline."),
        Flashcard(front="Five stages of the consumer decision process?", back="Need recognition, information search, evaluation of alternatives, purchase decision, post-purchase behavior."),
        Flashcard(front="What does conjoint analysis measure?", back="How much customers value each product attribute, by having them choose between bundles of attributes."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers Modules 1-4: the 5Cs, consumer behavior, market research, STP, and product/brand management. Format: short-answer definitions plus a mini-case where you segment a market, write a positioning statement and propose a consistent 4P mix.",
        topics=[
            StudyGuideTopic(name="STP and positioning",
                            importance="The mini-case is worth 40% and is built around a positioning statement.",
                            concepts=["Segmentation, Targeting and Positioning", "The Marketing Mix"]),
            StudyGuideTopic(name="Customers and research",
                            importance="Short answers on the decision process and when to use qualitative vs quantitative research.",
                            concepts=["Consumer Decision Process", "Market Research Methods"]),
            StudyGuideTopic(name="Products and brands",
                            importance="Expect a question applying the product life cycle and Keller's brand equity pyramid.",
                            concepts=["Product Life Cycle", "Brand Equity"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Segmentation, Targeting and Positioning", difficulty="medium", days_ago=36,
            questions=[
                QuizQuestion(
                    question="Segmenting customers by how often they use a product is an example of which basis?",
                    options=["Behavioral", "Demographic", "Psychographic", "Geographic"], correct_answer="Behavioral",
                    explanation="Usage rate, occasions and benefits sought are behavioral variables."),
                QuizQuestion(
                    question="A firm that focuses all its resources on one small, well-defined segment is using:",
                    options=["Concentrated targeting", "Undifferentiated targeting", "Differentiated targeting", "Mass marketing"],
                    correct_answer="Concentrated targeting",
                    explanation="Also called niche marketing."),
                QuizQuestion(
                    question="Which element of a positioning statement explains why customers should believe the claim?",
                    options=["Reason to believe", "Frame of reference", "Target segment", "Point of difference"], correct_answer="Reason to believe",
                    explanation="The reason to believe provides proof for the point of difference."),
                QuizQuestion(
                    question="Which is NOT a criterion for an effective segment?",
                    options=["Identical to competitors' segments", "Measurable", "Substantial", "Actionable"],
                    correct_answer="Identical to competitors' segments",
                    explanation="Segments should be measurable, substantial, accessible, differentiable and actionable."),
            ],
            correct=[0, 1, 2, 3],
        ),
        QuizAttempt(
            concept="Customer Lifetime Value", difficulty="hard", days_ago=7,
            questions=[
                QuizQuestion(
                    question="With margin $100/year, retention 0.8 and discount rate 0.1, what is CLV = m x r / (1 + i - r)?",
                    options=["$266.67", "$500.00", "$80.00", "$400.00"], correct_answer="$266.67",
                    explanation="100 x 0.8 / (1.1 - 0.8) = 80 / 0.3 = 266.67."),
                QuizQuestion(
                    question="Holding everything else constant, increasing the retention rate will:",
                    options=["Increase CLV", "Decrease CLV", "Have no effect on CLV", "Increase CLV only if the discount rate is zero"],
                    correct_answer="Increase CLV",
                    explanation="Higher r raises the numerator and shrinks the denominator."),
                QuizQuestion(
                    question="A customer's CLV is $144 and the cost to acquire them is $150. What should the firm conclude?",
                    options=["Each new customer destroys value at current economics", "The firm should double its acquisition spending",
                             "CLV is irrelevant to acquisition decisions", "The firm is profitable on each customer"],
                    correct_answer="Each new customer destroys value at current economics",
                    explanation="CAC above CLV means acquisition loses money unless retention or margin improves."),
            ],
            correct=[1, 2],
        ),
    ],
    session=TutorSession(
        name="Netflix tiers and price discrimination",
        topic="Pricing Strategy",
        mode="socratic",
        summary_bullets=[
            "Identified tiered pricing as a way to let customers self-select by willingness to pay.",
            "Discussed fencing: features must differ enough to avoid cannibalization.",
            "Connected the ad tier to penetration of price-sensitive segments.",
        ],
        messages=[
            ChatMessage(role="user", content="For Case 2, why does Netflix have three tiers instead of just one fair price for everyone?"),
            ChatMessage(role="assistant", content="Think about two customers: a student who watches occasionally and a family that streams in 4K on three TVs. If Netflix had to pick one price, what goes wrong with each customer at a high price, and at a low price?"),
            ChatMessage(role="user", content="At a high price the student cancels. At a low price the family would have paid more, so Netflix leaves money on the table."),
            ChatMessage(role="assistant", content="Exactly. Tiers let each customer pick the version that matches their willingness to pay. But Netflix can't ask people how much they'd pay. What stops the family from just buying the cheapest plan?"),
            ChatMessage(role="user", content="The cheap plan doesn't have 4K and limits screens, so it wouldn't work for them."),
            ChatMessage(role="assistant", content="That's called a fence: a feature difference that heavy users actually care about. If the fences are too weak, high-value customers trade down and the cheaper tier cannibalizes revenue. For your memo, evaluate whether the ad-supported tier is a good penetration move for price-sensitive segments, and whether its fences protect the standard plan."),
        ],
    ),
)


# ---------------------------------------------------------------------------
# QST MO 221 — Leading People and Teams
# ---------------------------------------------------------------------------

MO221 = Course(
    code="QST MO 221",
    name="Leading People and Teams",
    department="Management and Organizations",
    nickname="MO 221 Teams",
    color="#14B8A6",
    concepts=[
        Concept(name="Stages of Group Development", mastery=0.96,
                description="Tuckman's forming, storming, norming, performing and adjourning, and what a leader should do in each stage."),
        Concept(name="Psychological Safety", mastery=0.87,
                description="Edmondson's shared belief that a team is safe for interpersonal risk-taking, such as admitting mistakes or asking questions."),
        Concept(name="Big Five Personality Traits", mastery=0.8,
                description="Openness, conscientiousness, extraversion, agreeableness and neuroticism (OCEAN), and their links to job performance."),
        Concept(name="Motivation Theories", mastery=0.73,
                description="Expectancy theory (expectancy x instrumentality x valence), self-determination theory (autonomy, competence, relatedness), and goal setting."),
        Concept(name="Social Loafing", mastery=0.68,
                description="The tendency to put in less effort in a group than alone, and remedies like identifiable contributions and smaller teams."),
        Concept(name="Groupthink", mastery=0.56,
                description="Janis's model of cohesive groups suppressing dissent; symptoms like illusion of unanimity, and remedies like a devil's advocate."),
        Concept(name="Transformational Leadership", mastery=0.46,
                description="Leading through idealized influence, inspirational motivation, intellectual stimulation and individualized consideration."),
        Concept(name="Conflict Management Styles", mastery=0.37,
                description="Thomas-Kilmann styles (competing, collaborating, compromising, avoiding, accommodating); task vs relationship conflict."),
        Concept(name="Negotiation and BATNA", mastery=0.14,
                description="Best alternative to a negotiated agreement, reservation price, the ZOPA, and integrative vs distributive bargaining."),
        Concept(name="Organizational Culture", mastery=0.05,
                description="Schein's three levels: artifacts, espoused values, and basic underlying assumptions; how leaders shape culture."),
    ],
    edges=[
        Edge(source="Stages of Group Development", target="Conflict Management Styles", relationship="related", strength=0.6),
        Edge(source="Psychological Safety", target="Groupthink", relationship="related", strength=0.65),
        Edge(source="Motivation Theories", target="Social Loafing", relationship="related", strength=0.6),
        Edge(source="Conflict Management Styles", target="Negotiation and BATNA", relationship="builds_on", strength=0.75),
        Edge(source="Big Five Personality Traits", target="Transformational Leadership", relationship="related", strength=0.5),
        Edge(source="Motivation Theories", target="Transformational Leadership", relationship="prerequisite", strength=0.6),
        Edge(source="Transformational Leadership", target="Organizational Culture", relationship="related", strength=0.55),
        Edge(source="Psychological Safety", target="Stages of Group Development", relationship="related", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Big Five Personality Traits", delta=0.1, reason="Reflection 1 on my own OCEAN profile"),
        MasteryEvent(concept="Psychological Safety", delta=0.08, reason="Led team discussion on the Google Aristotle study"),
        MasteryEvent(concept="Conflict Management Styles", delta=0.06, reason="Mapped team conflict to Thomas-Kilmann"),
        MasteryEvent(concept="Groupthink", delta=-0.04, reason="Mixed up groupthink and group polarization on quiz"),
    ],
    categories=[
        Category(name="Reflection Papers", weight=0.25),
        Category(name="Team Project", weight=0.35),
        Category(name="Exams", weight=0.4),
    ],
    assignments=[
        Assignment(title="Reflection 1: My Big Five Profile", category="Reflection Papers", type="homework",
                   due_offset_days=12, points_possible=20, points_earned=19),
        Assignment(title="Team Charter", category="Team Project", type="project",
                   due_offset_days=20, points_possible=15, points_earned=15),
        Assignment(title="Reflection 2: What Motivated Me at My Summer Job", category="Reflection Papers", type="homework",
                   due_offset_days=33, points_possible=20, points_earned=18),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=47, points_possible=100, points_earned=91, is_midterm=True),
        Assignment(title="Interim Peer Evaluation", category="Team Project", type="other",
                   due_offset_days=58, points_possible=15, points_earned=14),
        Assignment(title="Reflection 3: Navigating Conflict on Our Team", category="Reflection Papers", type="homework",
                   due_offset_days=75, points_possible=20),
        Assignment(title="Team Consulting Project Final Report", category="Team Project", type="project",
                   due_offset_days=99, points_possible=100),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=106, points_possible=100),
    ],
    notes=[
        Note(
            title="Tuckman + what the leader should do",
            tags=["teams", "tuckman", "midterm"],
            concepts=["Stages of Group Development", "Conflict Management Styles", "Psychological Safety"],
            body=_t("""
                | Stage | What it looks like | Leader's job |
                |---|---|---|
                | **Forming** | Polite, unclear roles, looking to the leader | Set goals, clarify roles, write a team charter |
                | **Storming** | Disagreement over direction and roles | Surface conflict, keep it about the task, not people |
                | **Norming** | Shared norms and trust emerge | Reinforce norms, step back a little |
                | **Performing** | Self-managing, focused on results | Delegate, remove obstacles |
                | **Adjourning** | Wrapping up | Recognize contributions, capture lessons |

                Our consulting team hit **storming** in week 6 when two people wanted totally different project scopes. What helped: going back to the team charter and voting on criteria *before* voting on the scope.

                **Link to psychological safety:** storming is productive only if people feel safe disagreeing. Edmondson: safety isn't about being nice, it's about being able to say "I think this is wrong" without being punished.

                Task conflict (about ideas) can help performance; relationship conflict (personal) almost always hurts it.
            """),
        ),
        Note(
            title="Motivation theories side-by-side",
            tags=["motivation"],
            concepts=["Motivation Theories", "Social Loafing", "Transformational Leadership"],
            body=_t("""
                ## Expectancy theory (Vroom)
                Motivation = **Expectancy** (effort -> performance) x **Instrumentality** (performance -> reward) x **Valence** (do I value the reward?)
                Multiplicative: if any is zero, motivation is zero.

                ## Self-determination theory (Deci & Ryan)
                Intrinsic motivation needs **autonomy, competence, relatedness**. Big extrinsic rewards can *crowd out* intrinsic motivation.

                ## Goal setting (Locke & Latham)
                Specific + difficult goals beat "do your best," as long as there is commitment and feedback.

                ## Applying it: my summer job (Reflection 2)
                Expectancy was high, but instrumentality was low. Good shifts didn't change anything (flat pay, no recognition). That's why everyone did the minimum.

                ## Social loafing fix
                Make individual contributions **identifiable** (our peer evals do this), keep teams small, and make the task meaningful. Ties back to expectancy: if my effort isn't visible, instrumentality drops.
            """),
        ),
    ],
    documents=[
        Document(
            file_name="mo221-syllabus.pdf",
            category="syllabus",
            summary="MO 221 syllabus: organizational behavior course on individual differences, motivation, team dynamics, leadership, conflict, negotiation and culture, assessed with reflection papers, a team consulting project and two exams.",
            concept_notes=[
                ConceptNote(name="Grading", description="Reflection papers 25%, team consulting project 35% (adjusted by peer evaluations), exams 40%."),
                ConceptNote(name="Team project", description="Semester-long consulting engagement with a BU student organization, ending in a written report."),
                ConceptNote(name="Peer evaluations", description="Interim and final peer ratings can move an individual's project grade up or down."),
            ],
            extracted_text=_t("""
                QST MO 221: Leading People and Teams
                Questrom School of Business, Boston University

                Course Purpose
                Most of the work you will do in organizations happens with and through other people. This course draws on organizational behavior research to help you understand yourself, motivate others, build effective teams, and lead through conflict and change.

                Learning Objectives
                1. Use evidence on personality and motivation to diagnose individual behavior at work.
                2. Explain how teams develop and why they succeed or fail.
                3. Compare leadership approaches and develop your own leadership style.
                4. Manage conflict and negotiate effectively.

                Assignments and Weights
                Reflection Papers (25%): three 2-3 page papers connecting course concepts to your own experience.
                Team Consulting Project (35%): team charter, interim peer evaluation, and final report for a client organization. Individual grades are adjusted by peer evaluations.
                Midterm Exam (20%) and Final Exam (20%).

                Weekly Schedule
                Week 1: Introduction; why organizational behavior matters
                Weeks 2-3: Personality (Big Five) and perception
                Weeks 4-5: Motivation: expectancy theory, self-determination, goal setting
                Week 6: Team development and team charters
                Week 7: Midterm
                Weeks 8-9: Team processes: psychological safety, groupthink, social loafing
                Weeks 10-11: Leadership: trait, behavioral, transformational
                Week 12: Conflict and negotiation
                Week 13: Organizational culture and change
                Week 14: Team presentations

                Readings come from the course pack, including Edmondson's work on psychological safety.
            """),
        ),
        Document(
            file_name="mo221-week8-team-processes-notes.pdf",
            category="lecture_notes",
            summary="Week 8 lecture notes on team processes: Edmondson's psychological safety research, Janis's groupthink symptoms and remedies, and social loafing.",
            concept_notes=[
                ConceptNote(name="Psychological safety", description="A shared belief that the team is safe for interpersonal risk-taking."),
                ConceptNote(name="Groupthink symptoms", description="Illusion of invulnerability, self-censorship, illusion of unanimity, and pressure on dissenters."),
                ConceptNote(name="Groupthink remedies", description="Assign a devil's advocate, have the leader speak last, and invite outside experts."),
                ConceptNote(name="Social loafing", description="Reduced individual effort in groups when contributions are not identifiable."),
            ],
            extracted_text=_t("""
                Week 8: Team Processes

                Psychological Safety
                Amy Edmondson studied hospital nursing teams and found that the best teams reported MORE medication errors, not fewer. The better teams were not making more mistakes; they felt safe enough to report them. Psychological safety is a shared belief that the team is safe for interpersonal risk-taking. Google's Project Aristotle found it was the strongest predictor of team effectiveness.

                Leaders build psychological safety by framing work as a learning problem, acknowledging their own fallibility, and modeling curiosity by asking questions.

                Groupthink (Janis, 1972)
                Highly cohesive groups can prioritize agreement over critical thinking. Classic examples: the Bay of Pigs invasion and the Challenger launch decision.
                Symptoms:
                - Illusion of invulnerability
                - Collective rationalization of warnings
                - Self-censorship of doubts
                - Illusion of unanimity
                - Direct pressure on dissenters
                Remedies: leader states their view last, assign a rotating devil's advocate, break into subgroups, hold a second-chance meeting before final decisions.

                Social Loafing
                Ringelmann's rope-pulling studies: individual effort declined as group size grew. Loafing increases when contributions are not identifiable and the task feels meaningless.
                Remedies: smaller teams, identifiable roles, peer evaluation, and meaningful tasks.

                Discussion: How might high psychological safety reduce the risk of groupthink?
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="Tuckman's five stages?", back="Forming, storming, norming, performing, adjourning."),
        Flashcard(front="What is psychological safety?", back="A shared belief that the team is safe for interpersonal risk-taking (Edmondson)."),
        Flashcard(front="Big Five traits (OCEAN)?", back="Openness, conscientiousness, extraversion, agreeableness, neuroticism."),
        Flashcard(front="Which Big Five trait most consistently predicts job performance?", back="Conscientiousness."),
        Flashcard(front="Expectancy theory formula?", back="Motivation = Expectancy x Instrumentality x Valence."),
        Flashcard(front="Two remedies for groupthink?", back="Assign a devil's advocate; have the leader share their opinion last."),
        Flashcard(front="What is a BATNA?", back="Best Alternative To a Negotiated Agreement: what you do if the deal falls through. It sets your walk-away point."),
        Flashcard(front="What is the ZOPA?", back="Zone of possible agreement: the overlap between the buyer's and seller's reservation prices."),
        Flashcard(front="Four I's of transformational leadership?", back="Idealized influence, inspirational motivation, intellectual stimulation, individualized consideration."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers weeks 1-6: personality and perception, motivation theories, and team development. Format: multiple choice plus two short essays that apply a theory to a scenario.",
        topics=[
            StudyGuideTopic(name="Motivation theories applied",
                            importance="One essay always gives a demotivated employee and asks which theory explains it and what to change.",
                            concepts=["Motivation Theories", "Social Loafing"]),
            StudyGuideTopic(name="Team development",
                            importance="Know each Tuckman stage and the leader's role; expect a scenario to classify.",
                            concepts=["Stages of Group Development", "Psychological Safety"]),
            StudyGuideTopic(name="Personality at work",
                            importance="Multiple choice on the Big Five and which traits predict performance and leadership.",
                            concepts=["Big Five Personality Traits"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Motivation Theories", difficulty="medium", days_ago=42,
            questions=[
                QuizQuestion(
                    question="An employee believes hard work will lead to a great sales number but that the company never rewards top sellers. Which expectancy component is low?",
                    options=["Instrumentality", "Expectancy", "Valence", "Self-efficacy"], correct_answer="Instrumentality",
                    explanation="Instrumentality is the belief that performance leads to rewards."),
                QuizQuestion(
                    question="According to self-determination theory, which three needs support intrinsic motivation?",
                    options=["Autonomy, competence, relatedness", "Pay, security, status", "Achievement, power, affiliation", "Expectancy, instrumentality, valence"],
                    correct_answer="Autonomy, competence, relatedness",
                    explanation="Deci and Ryan's three basic psychological needs."),
                QuizQuestion(
                    question="Goal-setting research finds the highest performance comes from goals that are:",
                    options=["Specific and difficult", "Vague and easy", "Do-your-best", "Set only by the manager"], correct_answer="Specific and difficult",
                    explanation="Locke and Latham: specific, challenging goals with commitment and feedback."),
            ],
            correct=[0, 1, 2],
        ),
        QuizAttempt(
            concept="Groupthink", difficulty="medium", days_ago=16,
            questions=[
                QuizQuestion(
                    question="Which is a symptom of groupthink?",
                    options=["Illusion of unanimity", "Frequent task conflict", "High social loafing", "Low cohesion"], correct_answer="Illusion of unanimity",
                    explanation="Members assume silence means agreement."),
                QuizQuestion(
                    question="Which practice best reduces the risk of groupthink?",
                    options=["The leader shares their opinion last", "Increasing team cohesion", "Making decisions faster", "Removing outside experts"],
                    correct_answer="The leader shares their opinion last",
                    explanation="Early leader opinions anchor the group and suppress dissent."),
                QuizQuestion(
                    question="A group's final decision is more extreme than members' individual initial views. This is called:",
                    options=["Group polarization", "Groupthink", "Social loafing", "Escalation of commitment"], correct_answer="Group polarization",
                    explanation="Polarization is about the shift toward extremes; groupthink is about suppressed dissent."),
                QuizQuestion(
                    question="Edmondson found that better-led nursing teams reported more errors because:",
                    options=["They felt safe admitting mistakes", "They actually made more mistakes", "They had less training", "They were larger"],
                    correct_answer="They felt safe admitting mistakes",
                    explanation="Higher psychological safety increased reporting, not errors."),
            ],
            correct=[0, 1, 3],
        ),
    ],
    session=TutorSession(
        name="Prepping my BATNA for the negotiation exercise",
        topic="Negotiation and BATNA",
        mode="expository",
        summary_bullets=[
            "Defined BATNA, reservation price and ZOPA with the class job-offer exercise.",
            "Explained why improving your BATNA is the strongest source of leverage.",
            "Introduced integrative bargaining: trading on issues valued differently.",
        ],
        messages=[
            ChatMessage(role="user", content="We have a negotiation role-play next week where I'm the job candidate. I keep hearing BATNA but don't really know how to use it."),
            ChatMessage(role="assistant", content="BATNA is your Best Alternative To a Negotiated Agreement: what you'll actually do if this deal falls through. In your role, if you have another offer at $62,000, that offer is your BATNA. It sets your reservation price, the worst deal you'd accept. Anything below $62,000 is worse than walking away."),
            ChatMessage(role="user", content="And the employer has one too?"),
            ChatMessage(role="assistant", content="Yes. If their next-best candidate would cost them $70,000, they shouldn't pay you more than that. The range between your reservation price ($62k) and theirs ($70k) is the ZOPA, the zone of possible agreement. Any deal in that range beats both sides' alternatives; the negotiation decides where in it you land."),
            ChatMessage(role="user", content="So should I just tell them my other offer?"),
            ChatMessage(role="assistant", content="Mentioning a strong alternative can anchor them upward, but don't reveal your exact reservation price. Also look beyond salary: your role sheet probably lists start date, remote days and a signing bonus. If you care more about remote days and they care more about an early start date, trading those is integrative bargaining, and it creates value for both of you instead of just splitting the salary range."),
        ],
    ),
)


PACK = MajorPack(
    key="business",
    label="Business Administration",
    year="Sophomore",
    courses=[SM131, AC221, MK323, MO221],
    total_xp=1120,
    streak_days=4,
)
