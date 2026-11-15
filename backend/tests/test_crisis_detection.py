"""services/crisis_detection.py: the pure crisis-language screen.

Every EXPLICIT phrase and MENTION list entry has pinned positive examples
(`test_every_listed_phrase_has_an_example` fails when a new phrase lands
without one), every phrase CLASS (category) is covered, and every academic or
idiomatic false positive the owner named — plus the ones the guard lists
exist for — is pinned as a non-match.
"""

from __future__ import annotations

import pytest

from services import crisis_detection
from services.crisis_detection import CATEGORIES, EXPLICIT, MENTIONS, detect, detect_any, normalize
from tests import crisis_corpus

# (text, category, label) — the label is the EXPLICIT/MENTIONS entry that must fire.
POSITIVES: list[tuple[str, str, str]] = [
    # acute_danger
    ("I'm going to hang myself tonight", "acute_danger", "self-directed method"),
    ("i keep thinking i should just shoot myself", "acute_danger", "self-directed method"),
    ("I want to drown myself", "acute_danger", "self-directed method"),
    ("thinking about how to slit my wrists", "acute_danger", "wrists"),
    ("I'm going to jump off a bridge", "acute_danger", "jump with intent"),
    ("i want to jump off the roof of my dorm", "acute_danger", "jump with intent"),
    ("I took a bunch of pills", "acute_danger", "took pills"),
    ("i swallowed a whole bottle of tylenol", "acute_danger", "took pills"),
    ("I'm going to take a handful of sleeping pills", "acute_danger", "pills with intent"),
    ("I'm going to overdose", "acute_danger", "overdose with intent"),
    ("i want to od", "acute_danger", "overdose with intent"),
    ("I think I overdosed", "acute_danger", "overdosed"),
    ("how do i kill myself", "acute_danger", "method seeking"),
    ("what's the most painless way to die", "acute_danger", "method seeking"),
    ("my dad keeps hitting me", "acute_danger", "hurt by someone"),
    ("someone is hurting me", "acute_danger", "hurt by someone"),
    ("I don't feel safe at home", "acute_danger", "not safe"),
    ("I'm in danger right now", "acute_danger", "in danger"),
    ("I'm in danger.", "acute_danger", "in danger"),
    # suicidal_ideation
    ("I want to kill myself", "suicidal_ideation", "kill myself"),
    ("ill kill my self", "suicidal_ideation", "kill myself"),  # spacing
    ("killmyself", "suicidal_ideation", "kill myself"),  # no space
    ("KILLLL MYSELFFF", "suicidal_ideation", "kill myself"),  # case + stretched letters
    ("I want to kill myslef", "suicidal_ideation", "kill myself"),  # misspelling
    ("i keep thinking about killing myself", "suicidal_ideation", "kill myself"),
    ("this class makes me want to kms", "suicidal_ideation", "kms"),
    ("im gonna unalive myself", "suicidal_ideation", "unalive"),
    ("thinking about sewer slide", "suicidal_ideation", "sewer slide"),
    ("I want to end my life", "suicidal_ideation", "end my life"),
    ("I've thought about taking my own life", "suicidal_ideation", "end my life"),
    ("I just want to end it all", "suicidal_ideation", "end it all"),
    ("i want to die", "suicidal_ideation", "want to die"),
    ("i wanna die lol", "suicidal_ideation", "want to die"),
    ("i want 2 die", "suicidal_ideation", "want to die"),
    ("why do i want to die", "suicidal_ideation", "want to die"),
    ("honestly I just want to stop existing", "suicidal_ideation", "want to die"),
    ("I wish I was dead", "suicidal_ideation", "wish I were dead"),
    ("i wish i had never been born", "suicidal_ideation", "wish I were dead"),
    ("I hope I don't wake up tomorrow", "suicidal_ideation", "not wake up"),
    ("everyone would be better off without me", "suicidal_ideation", "better off dead"),
    ("I'd be better off dead", "suicidal_ideation", "better off dead"),
    ("I don't want to live anymore", "suicidal_ideation", "dont want to live"),
    ("i dont want to be alive", "suicidal_ideation", "dont want to live"),
    ("I don't want to exist.", "suicidal_ideation", "dont want to live"),
    ("there's no reason to live", "suicidal_ideation", "no reason to live"),
    ("I have nothing left to live for", "suicidal_ideation", "no reason to live"),
    ("life isn't worth living", "suicidal_ideation", "no reason to live"),
    ("I can't go on.", "suicidal_ideation", "cant go on"),
    ("i cant go on like this", "suicidal_ideation", "cant go on"),
    ("I can't go on anymore", "suicidal_ideation", "cant go on"),
    ("I'm suicidal", "suicidal_ideation", "feeling suicidal"),
    ("feeling suicidal again", "suicidal_ideation", "feeling suicidal"),
    ("I've been really suicidal lately", "suicidal_ideation", "feeling suicidal"),
    ("I've been thinking about suicide", "suicidal_ideation", "suicide thoughts"),
    ("im considering suicide", "suicidal_ideation", "suicide thoughts"),
    ("been thinking about suicide a lot", "suicidal_ideation", "suicide thoughts (no subject)"),
    ("I'm going to commit suicide", "suicidal_ideation", "suicide intent"),
    ("suicide is the only way out", "suicidal_ideation", "suicide intent"),
    # self_harm
    ("I keep hurting myself", "self_harm", "hurting myself"),
    ("I've been cutting myself", "self_harm", "hurting myself"),
    ("sometimes I harm myself when I'm stressed", "self_harm", "harm myself"),
    ("i want to hurt myself", "self_harm", "hurt myself with intent"),
    ("i want to cut myself", "self_harm", "hurt myself with intent"),
    ("I hurt myself on purpose", "self_harm", "hurt myself on purpose"),
    ("i cut myself again", "self_harm", "hurt myself on purpose"),
    ("I started self harming", "self_harm", "self-harm with intent"),
    ("selfharm again", "self_harm", "self-harm with intent"),
    # MENTIONS: the word plus a first-person sentence
    ("suicide hotline please help me", "suicidal_ideation", "suicide (mention)"),
    ("I'm scared of my suicidal thoughts", "suicidal_ideation", "suicide (mention)"),
    ("sucide has been on my mind", "suicidal_ideation", "suicide (mention)"),  # misspelling
    ("i self harm", "self_harm", "self-harm (mention)"),
    ("my self-injury is getting worse", "self_harm", "self-harm (mention)"),
]

#: Academic and idiomatic text that must never fire (the owner's list first).
NEGATIVES: list[str] = [
    # the owner's named academic false positives
    "this problem is killing me",
    "kill the process",
    "suicide squad",
    "dying to know",
    "dead code",
    "kill switch",
    "die roll",
    # coding / STEM
    "kill -9 the child process",
    "send SIGKILL to the worker",
    "What is a suicide inhibitor?",
    "the rocket does a suicide burn to land",
    "AWS KMS key rotation",
    "the car went 50 kms",
    "a patient could overdose on acetaminophen",
    "Is it possible to die from too much caffeine?",
    "apoptosis is cell suicide",
    # humanities / social science
    "Why did Romeo commit suicide?",
    "Explain Durkheim's theory of suicide",
    "can you explain to me Durkheim's types of suicide",
    "physician-assisted suicide ethics",
    "suicide rates in Japan",
    "self-harm statistics among adolescents",
    "nonsuicidal self-injury",
    "suicidal ideation is a symptom",
    "suicide",  # a bare word, no first person (a concept name can be just this)
    "why does hamlet want to die",
    "why do people want to die",
    "My essay is on suicide in Romantic poetry",
    "the Constitution is not a suicide pact",
    "she shot herself",
    "he killed himself in the novel",
    # hyperbole and idioms
    "the deadline is killing me",
    "I'm dying lol this is so hard",
    "killing myself laughing",
    "I could kill myself laughing at this meme",
    "I'm killing myself studying for this exam",
    "cut myself some slack",
    "I can't go on to the next problem",
    "there's no reason to live in the dorms",
    "not the hill I want to die on",
    "I almost died laughing",
    "I'll die if I fail",
    "I want to dye my hair",
    "I'm going to take my life back",
    "this will kill my self-esteem",
    "shot myself an email",
    "I'm drowning myself in coffee",
    "burning myself out",
    "my roommate keeps hitting me up for notes",
    "my brother keeps beating me at chess",
    "I'm in danger of failing",
    "I don't want to live in the dorms",
    "I hurt myself playing soccer",
    "I need to take all of the medication",
    # one per guard that would otherwise fire (each first-person on purpose)
    "I'm cutting myself some slack this week",
    "I'm cutting myself off from social media during finals",
    "I'm cutting myself a slice of cake",
    "I keep cutting myself shaving",
    "I'm shooting myself in the foot by skipping lectures",
    "I'm only hurting myself by not studying",
    "I want to die on this hill",
    "I want to die my hair blue",
    "there's no point going on to part b",
    "I loved suicide squad",
    "I think the constitution is not a suicide pact",
    "I made a suicidal move in chess",
    "I'm reading about nonsuicidal self-injury",
    "I support physician-assisted suicide",
    "I need self-harm statistics for my paper",
    # one per TOPIC_GUARD: a first-person sentence about coursework
    "I don't get Durkheim's view of suicide",
    "I'm writing about euthanasia and suicide",
    "I read that seppuku was an honorable suicide",
    "I learned hara-kiri means suicide by disembowelment",
    "I'm studying why kamikaze pilots accepted suicide",
    "I think apoptosis is like suicide for cells",
    "I'm reading Werther and the suicide at the end",
    "I don't understand why Hamlet thinks about suicide",
    "I think Ophelia's death was a suicide",
    "I cried when Romeo chose suicide",
    "I think Juliet's suicide was inevitable",
    "I wrote about Cleopatra's suicide",
    "I think Socrates' death was a kind of suicide",
    "I'm reading Sylvia Plath and her poems about suicide",
    "I'm writing on Virginia Woolf's suicide",
    "I didn't know Hemingway died by suicide",
    "I agree with Camus that suicide is the one serious question",
    "I read The Myth of Sisyphus, which is about suicide",
    "I cried at Anna Karenina's suicide",
    "I think Madame Bovary's suicide was tragic",
    "I need the sociology of suicide for class",
    # negations
    "I'm not suicidal, just stressed",
    "I don't want to die",
    "I would never kill myself",
    "I'm not going to kill myself",
    "I don't think I'm suicidal",
    # unrelated
    "the killer whale",
    "killjoy",
    "",
    "   ",
]


@pytest.mark.parametrize(("text", "category", "label"), POSITIVES)
def test_crisis_phrases_match(text, category, label):
    match = detect(text)
    assert match is not None, f"{text!r} must match {label!r}"
    assert (match.category, match.label) == (category, label)


@pytest.mark.parametrize("text", NEGATIVES)
def test_academic_and_idiomatic_text_never_matches(text):
    assert detect(text) is None


def test_every_category_is_covered():
    assert {c for _, c, _ in POSITIVES} == set(CATEGORIES)


def test_every_listed_phrase_has_an_example():
    """A phrase added to EXPLICIT or MENTIONS without a pinned example here
    fails, so the lists can grow only with a test."""
    listed = {p.label for p in (*EXPLICIT, *MENTIONS)}
    assert listed == {label for _, _, label in POSITIVES}


def test_every_guard_vetoes_a_pinned_negative():
    """Each GUARDS / TOPIC_GUARDS entry is load-bearing: dropping it makes a
    pinned negative match. Kept honest by deleting each guard in turn."""
    for guard_list in ("GUARDS", "NEGATION_GUARDS", "TOPIC_GUARDS"):
        guards = getattr(crisis_detection, guard_list)
        for i in range(len(guards)):
            reduced = tuple(g for j, g in enumerate(guards) if j != i)
            compiled = tuple(crisis_detection._bounded(g) for g in reduced)
            attr = f"_{guard_list}"
            original = getattr(crisis_detection, attr)
            setattr(crisis_detection, attr, compiled)
            try:
                fired = [t for t in NEGATIVES if detect(t) is not None]
            finally:
                setattr(crisis_detection, attr, original)
            assert fired, f"{guard_list}[{i}] vetoes none of NEGATIVES: {guards[i]!r}"


#: A negation in an EARLIER clause must not veto a crisis phrase in the next
#: one: the guard stops at a comma, dash or bracket, a clause-joining word
#: ("but", "and", ...) and a new first-person subject.
CLAUSE_CROSSING: list[str] = [
    "I'm not okay, I'll kill myself",
    "I won't lie, I'm suicidal",
    "I'm not ok, I'm suicidal",
    "No, not really, I'm suicidal",
    "Not great, feeling suicidal again",
    "I don't know anymore, hurt myself again",
    "I'm not okay - I'm suicidal",
    "I'm not okay — I want to kill myself",
    "I'm not okay (suicidal tbh)",
    "I'm not okay but suicidal",
    "I'm not fine and suicidal",
    "I'm not okay I'm suicidal",
    "I won't lie I'm suicidal",
    "I'm not okay; I'll kill myself",
    "I'm not sure: I'm suicidal",
]

#: Negations the guard must keep vetoing, the clause-scoped form included.
GENUINE_NEGATIONS: list[str] = [
    "I'm not suicidal",
    "I'm not suicidal, just stressed",
    "I would never kill myself",
    "I would never, ever kill myself",
    "I don't want to die",
    "I do not want to die",
    "She did not want to die",
    "I'm not going to kill myself",
    "I don't think I'm suicidal",
    "I'm stressed, but I'm not suicidal",
    "I'm tired, I would never kill myself though",
    # an aside set off by commas, brackets or dashes does not end the clause
    "I'm not, like, suicidal",
    "I would never, ever, kill myself",
    "I am not (really) suicidal",
    "I'm not - and never have been - suicidal",
    "I am not, and never will be, suicidal",
    "I'm not, you know, suicidal",
    "I would never — not ever — kill myself",
    # a "more" that starts the next thought is not a comparison
    "I'm not suicidal more like burnt out",
    "I would never kill myself more or less",
]

#: ...but only an aside right after the negation, of a few words, with no
#: new first-person subject or clause joiner, and closed before the phrase.
ASIDE_IS_NOT_A_NEGATION: list[str] = [
    "I'm not okay, honestly, suicidal again",
    "I'm not, like, okay, suicidal every night",
    "I'm not, honestly, okay, I'm suicidal",
    "I'm not, like, kidding suicidal again",
    "I'm not, I swear, okay, I want to kill myself",
    "No, not really, honestly, I'm suicidal",
    "I'm not, but I am, suicidal",
    "I'm not okay (I'm suicidal)",
]


#: A negation word that does not negate the phrase: a comparative or an
#: intensifier ("never been more suicidal", "... kill myself more than
#: today"), a feeling about the act or about stopping it ("no longer afraid
#: to", "not able to stop"), a double negation ("can't not"), and a bare
#: comma right after the negation, which ends its clause ("not, want to ...":
#: only an aside set off on BOTH sides is crossed).
NEGATION_THAT_DOES_NOT_NEGATE: list[str] = [
    "I have never been more suicidal",
    "never been this suicidal before",
    "I've never wanted to kill myself more than today",
    "I'm no longer afraid to kill myself",
    "I can't not think about killing myself",
    "not, want to kill myself",
    "I've never been as suicidal as this week",
    "I'm not scared to kill myself anymore",
    "I'm not ashamed to say I want to hurt myself",
    "I've never wanted to die more than now",
    "I don't think I've ever been this suicidal",
    "I would never want to hurt myself as much as I do now",
    "I've never wanted to kill myself more.",
]


@pytest.mark.parametrize("text", NEGATION_THAT_DOES_NOT_NEGATE)
def test_a_negation_that_does_not_negate_the_phrase_never_vetoes(text):
    assert detect(text) is not None, f"{text!r}: the negation does not say the opposite"


#: "I'm not saying I'll kill myself" is a recognised warning sign, not a
#: negation: only a hedge about one's own STATE ("I don't think I'm
#: suicidal") vetoes, and a contraction behaves like its spelled-out form.
NOT_A_SELF_NEGATION: list[str] = [
    "Im not saying Ill kill myself but I think about it",
    "I'm not saying I'll kill myself but I think about it",
    "I am not saying I will kill myself",
    "not saying im suicidal",
    "I'm not saying I'm suicidal",
    "I am not saying I am suicidal",
    "im not saying i want to die but",
    "I don't mean I'll kill myself",
    "I don't think I'll kill myself tonight",
    "I don't think I will kill myself tonight",
    "I don't think I'd kill myself",
]

#: The hedges that stay negations, contraction or not, in their common forms:
#: "thinking", "feel like", "feel that", "think that".
SELF_NEGATING_HEDGES: list[str] = [
    "I don't think I'm suicidal",
    "I don't think I am suicidal",
    "I don't really think I'm suicidal",
    "I don't believe I've been suicidal",
    "I'm not thinking I'm suicidal",
    "I am not thinking I'm suicidal",
    "I don't feel like I'm suicidal",
    "I don't feel that I'm suicidal",
    "I don't really feel like I'm suicidal",
    "I don't think that I'm suicidal",
    "I'm not feeling like I'm suicidal",
]


#: A negation the same sentence takes back: after "but", "though",
#: "although", "except" or "yet", a first-person modal or intent that points
#: back at the phrase ("but I might", "but I think I will", "but I'm going
#: to", "but I think about it"). The negation does not veto.
REVERSED_NEGATIONS: list[str] = [
    "I don't want to kill myself but I might",
    "I don't want to kill myself (but I think I will)",
    "I don't want to die but I think I'm going to",
    "I'm not suicidal but I think about it a lot",
    "I would never kill myself, but I might.",
    "I don't want to hurt myself but I probably will",
    "I'm not suicidal yet but I could be",
    "I don't want to die though I might do it anyway",
    "I'm not going to kill myself, but I keep thinking about it",
    "I don't want to die but I'm going to",
    "I do not want to die but I am going to",
    "I don't want to hurt myself but I want to",
    "I won't kill myself but I'll probably do it",
    "I don't think I'm suicidal but I might be",
    "I'm not suicidal except I think about it every night",
]

#: ...and a "but" that goes on to something else leaves the negation alone:
#: the modal has to stand for the phrase, not start a new one.
UNREVERSED_NEGATIONS: list[str] = [
    "I'm not suicidal but I'm stressed",
    "I don't want to die, but I am tired of exams",
    "I'm not suicidal but I could use some help",
    "I don't want to die but I will fail this class",
    "I would never kill myself but I might drop out",
    "I don't want to kill myself, but I will pass",
    "I'm not suicidal but I think about my grades a lot",
    "I'm not suicidal, but I might fail",
    "I'm not suicidal but I might be depressed",
    "I'm not suicidal but I will be okay",
    "I'm not suicidal but ill",
]


#: "I won't lie", "not gonna lie", "ngl", "not gonna sugarcoat it", "not
#: kidding" INTRODUCE what follows; they never negate it.
INTRODUCING_IDIOMS: list[str] = [
    "I wont lie suicidal again today",
    "I am not gonna lie suicidal thoughts every day",
    "I'm not going to lie suicidal thoughts every night",
    "I will not lie I want to kill myself",
    "not gonna lie my suicidal thoughts are back",
    "not to lie my suicidal thoughts are back",
    "I'm not even gonna lie suicidal again",
    "ngl my suicidal thoughts are back",
    "I'm not gonna sugarcoat it suicidal every night",
    "not gonna sugar coat it I keep hurting myself",
    "I'm not lying suicidal every day",
    "I'm not kidding suicidal thoughts all week",
    "I'm not joking kill myself tonight",
    "I won't lie to you suicidal again",
]

#: ...and a real negation after one still vetoes.
IDIOM_THEN_NEGATION: list[str] = [
    "I won't lie, I'm not suicidal",
    "not gonna lie I'm not suicidal",
    "ngl I don't want to die",
    "I won't lie I would never kill myself",
]


@pytest.mark.parametrize("text", INTRODUCING_IDIOMS)
def test_an_introducing_idiom_is_never_a_negation(text):
    assert detect(text) is not None


@pytest.mark.parametrize("text", IDIOM_THEN_NEGATION)
def test_a_negation_after_an_introducing_idiom_still_vetoes(text):
    assert detect(text) is None


@pytest.mark.parametrize("text", NOT_A_SELF_NEGATION)
def test_saying_or_meaning_is_not_a_self_negation(text):
    assert detect(text) is not None


@pytest.mark.parametrize("text", SELF_NEGATING_HEDGES)
def test_a_hedge_about_ones_own_state_still_vetoes(text):
    assert detect(text) is None


@pytest.mark.parametrize("text", REVERSED_NEGATIONS)
def test_a_negation_the_sentence_takes_back_never_vetoes(text):
    assert detect(text) is not None, f"{text!r}: the sentence reverses its negation"


@pytest.mark.parametrize("text", UNREVERSED_NEGATIONS)
def test_a_but_that_goes_on_to_something_else_keeps_the_negation(text):
    assert detect(text) is None


@pytest.mark.parametrize("text", CLAUSE_CROSSING)
def test_a_negation_never_reaches_across_a_clause(text):
    assert detect(text) is not None, f"{text!r}: the negation belongs to another clause"


@pytest.mark.parametrize("text", GENUINE_NEGATIONS)
def test_a_negation_in_the_same_clause_still_vetoes(text):
    assert detect(text) is None


@pytest.mark.parametrize("text", ASIDE_IS_NOT_A_NEGATION)
def test_only_a_short_aside_right_after_the_negation_is_crossed(text):
    assert detect(text) is not None, f"{text!r}: the negation does not reach the phrase"


def test_mentions_need_first_person_in_the_same_sentence():
    assert detect("Is suicide a sin? I'm asking for my ethics class") is None
    assert detect("I keep thinking suicide would be easier") is not None


def test_topic_guards_never_veto_an_explicit_phrase():
    """A text that names coursework still fires on a first-person statement."""
    match = detect("Durkheim essay is due. Also I want to kill myself.")
    assert match is not None and match.label == "kill myself"
    assert detect("Hamlet. Also I've been thinking about suicide").label == "suicide thoughts"


def test_most_severe_category_wins():
    match = detect("I took too many pills and I want to kill myself")
    assert match.category == "acute_danger"
    across = detect_any([None, "", "what is a heap", "I want to hurt myself", "I took a bunch of pills"])
    assert across.category == "acute_danger"
    assert detect_any([None, "", "what is a heap"]) is None


def test_normalize_folds_the_forms_the_patterns_are_written_against():
    assert normalize("I’m NOT sure — can't go ON!!") == "im not sure cant go on |"
    assert normalize("self-harm") == "self harm"
    assert normalize("killlll") == "kil"
    assert normalize("su​icide") == "suicide"  # zero-width joiner
    assert normalize("suïcide") == "suicide"  # accents


def test_match_never_carries_the_text():
    match = detect("I want to kill myself, said in confidence")
    assert set(vars(match)) == {"category", "tier", "label"}
    assert "confidence" not in repr(match)


def test_long_notes_are_screened_whole():
    """A crisis line deep in a long note still matches (within MAX_SCREEN_CHARS)."""
    filler = "Lecture notes on hash tables and collisions. " * 2000
    assert detect(filler + "I want to end my life.") is not None
    assert detect(filler) is None


# ── A quotation is just text ────────────────────────────────────────────────

#: Crisis language inside quotation marks matches like any other text, in a
#: typed message and in a stored note alike. No pattern can tell a quoted
#: patient from a student quoting themselves, so none tries: a note's match
#: shows the card ALONGSIDE its result (services/crisis_support.py), which
#: costs the student quoting a play nothing. The last three are the misses
#: that sank the old quotation exception.
QUOTATIONS: list[str] = [
    'PSYCH 101 week 4: depression. A patient says "I want to kill myself" and the clinician asks about a plan.',
    "Macbeth, Act 5. Macbeth: “I want to die” is the line we discussed.",
    "Romantic poetry. The speaker's refrain, 'I wish I were dead', closes each stanza.",
    'Case study: the client reported "my self-harm got worse" after the move.',
    "Lecture: the narrator says „I want to die“ in the German-style quote example.",
    '"I want to die," she said, and the nurse wrote it down.',
    '"I want to kill myself," said the patient.',
    'HAMLET: "I want to die"',
    'Doctor: How are you?\nJane: "I want to die."',
    'Patient: "I want to kill myself."',
    'The patient said "I want to die." I think this shows depression.',
    'Note: "I want to kill myself"',
    '"I want to die"',
    'Sarah: "I want to die"',
    'I keep thinking "I want to kill myself" every night',
    'I wrote in my journal: "I want to die."',
    "'Cause I want to kill myself, honestly, my friends' notes don't help",
    "> I want to kill myself",
    'Skipped the doctor appointment again, "I want to kill myself"',
    'Everyone posting their happy photos "I want to kill myself"',
    'Sarah: hi\nTom: hey\nSarah: "I want to kill myself"',
]


@pytest.mark.parametrize("text", QUOTATIONS)
def test_a_quotation_matches_like_any_other_text(text):
    assert detect(text) is not None
    assert detect_any([None, text]) is not None


def test_there_is_no_document_mode():
    """The quotation exception is gone, not dormant: `detect` takes the text
    alone, so no caller can screen a note any other way than in full."""
    with pytest.raises(TypeError):
        detect('A patient says "I want to die"', source="document")  # type: ignore[call-arg]


# ── The differential corpus (tests/crisis_corpus.py) ────────────────────────

#: The strings the tests above use inline, with the outcome they pin.
_INLINE: dict[str, bool] = {
    "Is suicide a sin? I'm asking for my ethics class": False,
    "I keep thinking suicide would be easier": True,
    "Durkheim essay is due. Also I want to kill myself.": True,
    "Hamlet. Also I've been thinking about suicide": True,
    "I took too many pills and I want to kill myself": True,
    "what is a heap": False,
    "I want to kill myself, said in confidence": True,
    'A patient says "I want to die"': True,
}


def expected_corpus() -> dict[str, bool]:
    """Every sentence the crisis tests know, mapped to whether it must match:
    every list in this file plus tests/crisis_corpus.py's groups."""
    groups: list[tuple[bool, list[str]]] = [
        (True, [t for t, _, _ in POSITIVES]),
        (False, NEGATIVES),
        (True, CLAUSE_CROSSING),
        (False, GENUINE_NEGATIONS),
        (True, ASIDE_IS_NOT_A_NEGATION),
        (True, NEGATION_THAT_DOES_NOT_NEGATE),
        (True, NOT_A_SELF_NEGATION),
        (False, SELF_NEGATING_HEDGES),
        (True, REVERSED_NEGATIONS),
        (False, UNREVERSED_NEGATIONS),
        (True, INTRODUCING_IDIOMS),
        (False, IDIOM_THEN_NEGATION),
        (True, QUOTATIONS),
        (True, [t for t, m in _INLINE.items() if m]),
        (False, [t for t, m in _INLINE.items() if not m]),
        (False, crisis_corpus.EVERYDAY_NEGATIVES),
        (False, crisis_corpus.CLINICAL_NEGATIVES),
        (True, crisis_corpus.CRISIS_POSITIVES),
        (False, crisis_corpus.KNOWN_MISSES),
        (True, crisis_corpus.KNOWN_FALSE_POSITIVES),
    ]
    expected: dict[str, bool] = {}
    for must_match, texts in groups:
        for text in texts:
            if not text.strip():
                continue
            assert expected.setdefault(text, must_match) is must_match, f"{text!r} is pinned both ways"
    return expected


_CORPUS = expected_corpus()


@pytest.mark.parametrize("text", list(_CORPUS))
def test_corpus_sentence_has_its_expected_outcome(text):
    match = detect(text)
    if _CORPUS[text]:
        assert match is not None, f"{text!r} must match"
    else:
        assert match is None, f"{text!r} must not match ({match})"


def test_every_difference_from_base_is_intended():
    """Every corpus answer that differs from #890's head (crisis_corpus.BASE_COMMIT)
    is listed in INTENDED_CHANGES_FROM_BASE with its reason, and every listed
    sentence does differ. `python -m tests.crisis_corpus` prints the diff."""
    base = crisis_corpus.load_base_results()
    missing = [t for t in _CORPUS if t not in base]
    assert not missing, f"no base answer (run python -m tests.crisis_corpus --write-base): {missing}"
    changed = {t for t in _CORPUS if crisis_corpus.result_key(detect(t)) != base[t]}
    intended = set(crisis_corpus.INTENDED_CHANGES_FROM_BASE)
    assert not changed - intended, f"differs from base but not listed: {sorted(changed - intended)}"
    assert not intended - changed, f"listed but no longer differs: {sorted(intended - changed)}"
    assert all(reason.strip() for reason in crisis_corpus.INTENDED_CHANGES_FROM_BASE.values())
