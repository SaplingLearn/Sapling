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
    for guard_list in ("GUARDS", "TOPIC_GUARDS"):
        guards = getattr(crisis_detection, guard_list)
        for i in range(len(guards)):
            reduced = tuple(g for j, g in enumerate(guards) if j != i)
            compiled = tuple(crisis_detection._bounded(g) for g in reduced)
            attr = "_GUARDS" if guard_list == "GUARDS" else "_TOPIC_GUARDS"
            original = getattr(crisis_detection, attr)
            setattr(crisis_detection, attr, compiled)
            try:
                fired = [t for t in NEGATIVES if detect(t) is not None]
            finally:
                setattr(crisis_detection, attr, original)
            assert fired, f"{guard_list}[{i}] vetoes none of NEGATIVES: {guards[i]!r}"


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
