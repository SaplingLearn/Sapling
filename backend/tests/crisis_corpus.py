"""The differential corpus for services/crisis_detection.py.

Every review round of the crisis screen fixed some phrases and broke others,
because each fix was checked only against the cases it was written for. This
corpus is the check against ALL of them at once:

* the sentences below, in three groups, each with the outcome it must have:
  everyday, recovery and hedging statements that must NOT match; clinical and
  academic third-person text that must NOT match; first-person crisis
  statements that MUST match. (`test_crisis_detection.py` adds every string
  its own tests use, with the outcome those tests pin.)
* `crisis_corpus_base.json`: what #890's own head (`BASE_COMMIT`, the
  detector as first reviewed) answered for every sentence, stored as data so
  the test needs no second checkout.
* `INTENDED_CHANGES_FROM_BASE`: every sentence whose answer now differs from
  the base answer, with the reason. A difference that is not listed fails the
  test, and so does a listed sentence that no longer differs.

To change the detector safely: add the sentence that motivates the change to
the right group, make the change, run `python -m tests.crisis_corpus` (from
`backend/`) to print every sentence whose answer differs from the base, and
list each new difference below with a one-line reason. A difference you did
not mean is the bug the change introduced.

`python -m tests.crisis_corpus --write-base` recomputes the base answers by
running the base checkout's detector in a subprocess (the checkout is
`CRISIS_BASE_BACKEND`, default the `sapling-wt-sec890-base` worktree beside
this one); only a new corpus sentence needs it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BASE_COMMIT = "73646ed5"
BASE_RESULTS_PATH = Path(__file__).with_name("crisis_corpus_base.json")
_DEFAULT_BASE_BACKEND = Path(__file__).resolve().parents[3] / "sapling-wt-sec890-base" / "backend"

# ── (a) everyday, recovery and hedging statements: must NOT match ───────────

EVERYDAY_NEGATIVES: list[str] = [
    # a hedge or recovery about one's own state, comparatives included
    "I'm not so suicidal anymore",
    "I'm not too suicidal",
    "I'm not that suicidal",
    "I'm not as suicidal as last year",
    "I'm not so suicidal these days, therapy helps",
    "honestly I'm not that suicidal, just tired",
    "I'm not as suicidal as I used to be",
    "I'm not nearly as suicidal as last semester",
    "I'm not as suicidal as I was in high school",
    "I'm not more suicidal than usual, just tired",
    "I'm not so much suicidal as numb",
    "I'm not even suicidal, just bored",
    "I'm not really suicidal",
    "I'm no longer suicidal",
    "I'm not suicidal anymore, thanks for checking",
    "No, I'm not suicidal",
    "I'm not suicidal at all",
    "I'm not suicidal, not even close",
    "I've never been suicidal",
    "I have never felt suicidal",
    "I've never wanted to kill myself",
    "I have never wanted to die",
    "I've never been so happy",
    "I have never been that suicidal",
    "I am not really that suicidal",
    "I am definitely not suicidal",
    "I'm not feeling suicidal today",
    "I don't think I'm suicidal, just exhausted",
    "I'm not suicidal more like burnt out",
    "Not so suicidal anymore, finally",
    # "don't want to die" with a trailing intensifier is still a negation
    "I don't want to die more than anything",
    "I don't want to die so badly",
    "I don't want to die, I want to pass this class",
    "I don't want to die without seeing Japan",
    "I never want to die young",
    "I really don't want to die more than anything else",
    # negated acts
    "I would never hurt myself",
    "I'd never kill myself, I'm just venting",
    "I'm not going to hurt myself, I promise",
    "I won't kill myself over a grade",
    "I'm not trying to kill myself here, just asking about caffeine limits",
    "I'm not about to kill myself over a B minus",
    "I'm not going to hurt myself over this",
    "I would never kill myself more or less",
    # comparatives and fears that are not about the phrases
    "I'm not too scared of the final",
    "I'm not scared to ask for help anymore",
    "I'm no longer afraid of failing",
    "I can't not laugh at this",
    "I've never been more ready for spring break",
    "I've never wanted to graduate more than today",
    "I'm not as stressed as last week",
    "I've never been this tired",
    # hyperbole and idioms
    "this exam is killing me",
    "I'm dying to see the results",
    "this homework is going to be the death of me",
    "my code killed the server again",
    "I could just die of embarrassment",
    "I'm dead tired",
    "I bombed the midterm, I'm so dead",
    "my phone is dying",
    "I'm killing it in organic chem this semester",
    "she's killing it on the debate team",
    "I nearly died when the professor called on me",
    "I'll kill you if you spoil the finale",
    "my feet are killing me after the shift",
    "I'm going to kill this presentation",
    "I'm dying to know what's on the final",
    "this reading is killing me slowly",
    "kill me now, three exams tomorrow",
    "I'm literally dead after that lab",
    "the suspense is killing me",
    "I'd rather die than present first",
    "I don't want to die on this hill",
    "I need to cut myself some slack this week",
    "I keep shooting myself in the foot with procrastination",
    # low but not in danger
    "I'm not depressed, just stressed",
    "I'm exhausted and burnt out",
    "I've been feeling really low but I'm okay",
    "I'm not okay with this grading policy",
    "I'm so done with this semester",
]

# ── (b) clinical and academic third-person text: must NOT match ─────────────

CLINICAL_NEGATIVES: list[str] = [
    "Why do teens on SSRIs end up feeling more suicidal?",
    "patients getting more suicidal on SSRIs",
    "Patients getting more suicidal is a known SSRI side effect",
    "Children and teens feeling more suicidal on antidepressants should be monitored",
    "Teens who are getting more suicidal need closer follow-up",
    "Getting more suicidal after starting meds is a reason to call your doctor",
    "SSRIs can make some young people feel more suicidal at first",
    "Some adolescents become more suicidal in the first weeks of treatment",
    "Patients may feel more suicidal when their energy returns",
    "The study found veterans were more suicidal after deployment",
    "The drug label warns it may make you feel more suicidal",
    "Why do people with depression feel suicidal?",
    "During withdrawal some patients become suicidal",
    "suicide rates rose in 2020",
    "Durkheim's theory of suicide",
    "Explain Durkheim's anomic suicide",
    "Antidepressants carry a black box warning for suicidal thoughts in young adults",
    "Is bipolar disorder linked to suicide?",
    "What are the warning signs of suicide?",
    "Explain the interpersonal theory of suicide",
    "Joiner's model says thwarted belongingness predicts suicidal desire",
    "How do crisis lines reduce suicide deaths?",
    "List the risk factors for self-harm in adolescents",
    "Lithium reduces suicide risk in bipolar patients",
    "Ketamine reduces suicidal thoughts rapidly in trials",
    "Which neurotransmitters are implicated in suicidal behavior?",
    "What does suicidal ideation mean in the DSM?",
    "Assessing a suicidal patient requires a safety plan",
    "Define nonsuicidal self-injury",
    "The paper is about suicide prevention in college students",
    "What percentage of people who attempt suicide try again?",
    "Suicide is the second leading cause of death among college students",
    "Rates of self-harm in girls doubled over the decade",
    "Summarize the article on youth suicide prevention",
    "Why was suicide considered a crime in medieval England?",
    "Camus called suicide the one truly serious philosophical problem",
    "In Hamlet, is Ophelia's death a suicide?",
    "Romeo and Juliet both die by suicide",
    "Why did Cleopatra kill herself?",
    "Werther's suicide sparked copycat suicides across Europe",
    "Why did Sylvia Plath's poetry focus on death?",
    "The narrator of the poem says he wants to die",
    "The character threatens to kill himself in act three",
    "The poem's speaker is suicidal",
    "The suicide squad in the film is a team of villains",
    "Teens have never been more suicidal, the report says",
    "The patients had never been more suicidal",
]

# ── (c) first-person crisis statements: MUST match ─────────────────────────

CRISIS_POSITIVES: list[str] = [
    # the review's named misses
    "I have never been more suicidal",
    "I've never wanted to kill myself more than today",
    "I'm no longer afraid to kill myself",
    "I can't not think about killing myself",
    "I'm not okay, I'll kill myself",
    "I won't lie, I'm suicidal",
    "Im not saying Ill kill myself",
    "I want to die",
    # "never" that says MORE
    "I've never felt so suicidal",
    "Never been this suicidal before",
    "I've never felt this suicidal in my life",
    "Honestly I have never been more suicidal than this week",
    "I've never wanted to die so badly",
    "I have never wanted to die more",
    "I've never been so close to killing myself",
    "I have never, ever been more suicidal",
    "Never been more suicidal lol",
    "I never wanted to die so badly before",
    # comparatives and intensifiers that are not negated
    "I haven't been this suicidal in years",
    "I'm not usually this suicidal",
    "I'm more suicidal than ever",
    "I feel more suicidal since starting the new meds",
    "I've been getting more suicidal every week",
    "I'm getting more suicidal every day",
    "I am so suicidal right now",
    # fear of the act, or of stopping it
    "I'm no longer scared to end my life",
    "I'm not scared of dying anymore, I want to kill myself",
    "I'm not able to stop hurting myself",
    "I won't stop hurting myself",
    "I can't not think about suicide",
    # a negation in another clause, or an introducing idiom
    "I'm not kidding, I want to end my life",
    "I'm not okay. I want to die.",
    "I'm not fine, I keep hurting myself",
    "Not gonna lie, I want to kill myself",
    "I'm not exaggerating, I'm suicidal",
    "I'm not joking, I'm going to end it all",
    "I'm not sure why but I want to die",
    "I don't know what to do, I want to kill myself",
    "I'm not even sad, I just want to die",
    "I'm not sleeping, I keep thinking about suicide",
    "I'm not okay and I want to die",
    "I'm not okay so I'm suicidal",
    "I'm not this suicidal usually",
    # plain statements
    "I don't want to be alive anymore",
    "I don't want to live anymore",
    "I can't do this anymore, I want to die",
    "I really do think I want to die",
    "Did I mention I want to die",
    "I keep thinking about killing myself",
    "I'm going to kill myself tonight",
    "I've been cutting myself again",
    "I want to hurt myself",
    "I took a bunch of pills",
    "I wish I was dead",
    "Everyone would be better off without me",
    "I have nothing left to live for",
    "honestly I'm suicidal",
    "ngl I've been really suicidal lately",
    "I don't think I can go on anymore",
    "I'm suicidal and I don't know who to talk to",
    "I think about suicide every day",
    "I'm planning to kill myself after finals",
    "how do I kill myself",
    "I want to jump off the parking garage",
    "I really want to die tonight",
    "My suicidal thoughts are getting worse",
]

# ── Known limits, pinned so a change to them is seen ────────────────────────

#: Crisis statements the phrase screen still MISSES (asserted to miss, so a
#: fix that catches one shows up and moves it to CRISIS_POSITIVES). Indirect
#: language is the documented limit of a phrase screen.
KNOWN_MISSES: list[str] = [
    "I just want everything to stop",
    "I won't be a problem much longer",
    "I wouldn't mind dying",
    "I've never been this close to ending it all",
    "I'm not afraid to hurt myself anymore",
    # a take-back in the NEXT sentence: the negation's sentence ends first
    "I'm not suicidal. But I might be",
    # ...or one with no "it" pointing back at the phrase
    "I'm not suicidal but I think about death a lot",
    # a comparative with no "I": the price of not reading "teens end up
    # feeling MORE suicidal" as a student's own words
    "been more suicidal lately",
]

#: Third-person clinical text that still MATCHES: a subjectless "been
#: feeling suicidal" or "wanted to die" reads exactly like a student's own
#: fragment ("been feeling suicidal again"), which must match.
KNOWN_FALSE_POSITIVES: list[str] = [
    "The patient has been feeling suicidal for two weeks",
    "The case study describes a client who wanted to die",
    "Clinicians should ask directly whether a patient is feeling suicidal",
    "Someone who has been suicidal before is at higher risk",
]

# ── Every answer that differs from BASE_COMMIT's, and why ──────────────────

_CLAUSE = "the negation is in an earlier clause; base let it cross the clause break"
_ASIDE = "the negation crosses only a short aside right after it; this is not one"
_INTRODUCES = "an introducing idiom (won't lie, not kidding) negates nothing"
_SAYING = "'not saying' / 'don't mean' / 'don't think I'll' is a warning sign, not a negation"
_HEDGE = "a hedge about one's own state negates however it is spelled; base caught only 'think I'm'"
_TAKEN_BACK = (
    "the sentence takes its negation back ('but I might', 'but I think about it'); base let it veto")
_NEVER_BEEN = "'never (been|felt) (more|this|so|as) <phrase>' says more, not less"
_NEVER_WANTED = "'never wanted to <phrase> more than / so badly / as much as' is a comparison"
_FEAR = "a fear of the act after the negation (no longer afraid to) does not negate it"
_FEELING_VERB = (
    "the verb form of a feeling about the act (won't hesitate to, don't fear, never stopped) "
    "does not negate it either; base read it as a gap word")
_TAKEN_BACK_TRAIL = (
    "taken back across an ellipsis or a dash, which trail off inside the sentence (a full stop "
    "still ends it); base read no take-back")
_THIS = "'this' after a negation points at the state now and no longer vetoes"
_FIRST_PERSON_COMPARATIVE = "still a match, now explicit: a first-person lead takes a comparative"
_SOMEONE_ELSE = "the 'why does X want to die' guard no longer reads the speaker's own 'I' as X"

INTENDED_CHANGES_FROM_BASE: dict[str, str] = {
    # A negation reaches only within its own clause (fc061fc9): base let it
    # cross any two words, commas and new subjects included.
    "I'm not okay, I'll kill myself": _CLAUSE,
    "I won't lie, I'm suicidal": _CLAUSE,
    "I'm not ok, I'm suicidal": _CLAUSE,
    "No, not really, I'm suicidal": _CLAUSE,
    "Not great, feeling suicidal again": _CLAUSE,
    "I don't know anymore, hurt myself again": _CLAUSE,
    "I'm not okay - I'm suicidal": _CLAUSE,
    "I'm not okay (suicidal tbh)": _CLAUSE,
    "I'm not okay but suicidal": _CLAUSE,
    "I'm not fine and suicidal": _CLAUSE,
    "I'm not okay I'm suicidal": _CLAUSE,
    "I won't lie I'm suicidal": _CLAUSE,
    "I'm not okay (I'm suicidal)": _CLAUSE,
    "I'm not exaggerating, I'm suicidal": _CLAUSE,
    "not, want to kill myself": "a bare comma right after the negation ends its clause",
    # Only a short aside right after the negation is crossed (d9cc216b).
    "I'm not okay, honestly, suicidal again": _ASIDE,
    "I'm not like, okay, suicidal": (
        "a filler's comma is crossed only straight into the state word; 'okay' completes the clause"),
    "Not really, kill myself lol": (
        "'not really' can be a whole answer: past its comma only 'suicidal' is still negated"),
    "I'm not, like, okay, suicidal every night": _ASIDE,
    "I'm not, like, kidding suicidal again": _ASIDE,
    # "I won't lie", "not kidding" introduce what follows (c906e70f).
    "I wont lie suicidal again today": _INTRODUCES,
    "I am not gonna lie suicidal thoughts every day": _INTRODUCES,
    "I'm not lying suicidal every day": _INTRODUCES,
    "I'm not kidding suicidal thoughts all week": _INTRODUCES,
    "I'm not joking kill myself tonight": _INTRODUCES,
    # Only a hedge about one's own state negates (ce59a9d1).
    "Im not saying Ill kill myself but I think about it": _SAYING,
    "I'm not saying I'll kill myself but I think about it": _SAYING,
    "Im not saying Ill kill myself": _SAYING,
    "not saying im suicidal": _SAYING,
    "I'm not saying I'm suicidal": _SAYING,
    "I don't mean I'll kill myself": _SAYING,
    "I don't think I'll kill myself tonight": _SAYING,
    "I don't think I'd kill myself": _SAYING,
    "I don't think I am suicidal": _HEDGE,
    "I don't really think I'm suicidal": _HEDGE,
    "I don't believe I've been suicidal": _HEDGE,
    "I don't feel like I'm suicidal": _HEDGE,
    "I don't feel that I'm suicidal": _HEDGE,
    "I don't really feel like I'm suicidal": _HEDGE,
    "I don't think that I'm suicidal": _HEDGE,
    "I'm not feeling like I'm suicidal": _HEDGE,
    # A negation the same sentence takes back: "but / though / yet" + a
    # first-person modal or intent that stands for the phrase.
    "I don't want to kill myself but I might": _TAKEN_BACK,
    "I don't want to kill myself (but I think I will)": _TAKEN_BACK,
    "I don't want to die but I think I'm going to": _TAKEN_BACK,
    "I'm not suicidal but I think about it a lot": _TAKEN_BACK,
    "I would never kill myself, but I might.": _TAKEN_BACK,
    "I don't want to hurt myself but I probably will": _TAKEN_BACK,
    "I'm not suicidal yet but I could be": _TAKEN_BACK,
    "I don't want to die though I might do it anyway": _TAKEN_BACK,
    "I'm not going to kill myself, but I keep thinking about it": _TAKEN_BACK,
    "I don't want to die but I'm going to": _TAKEN_BACK,
    "I do not want to die but I am going to": (
        "taken back, and 'do not' is now a negation (not 'someone else's wish'), so it can be"),
    "I don't want to hurt myself but I want to": _TAKEN_BACK,
    "I won't kill myself but I'll probably do it": _TAKEN_BACK,
    "I don't think I'm suicidal but I might be": _TAKEN_BACK,
    "I'm not suicidal except I think about it every night": _TAKEN_BACK,
    "I'm not suicidal... but I might be": _TAKEN_BACK_TRAIL,
    "I'm not suicidal… but I might be": _TAKEN_BACK_TRAIL,
    "I don't want to die... but I might": _TAKEN_BACK_TRAIL,
    "I don't want to die.. but I might... idk": _TAKEN_BACK_TRAIL,
    "I'm not suicidal - but I might be": _TAKEN_BACK_TRAIL,
    "I don't want to die — but I might": _TAKEN_BACK_TRAIL,
    # "never" that says MORE: never (been|felt) (more|this|so|as) <phrase>.
    "I have never been more suicidal": _NEVER_BEEN,
    "never been this suicidal before": _NEVER_BEEN,
    "Never been this suicidal before": _NEVER_BEEN,
    "I've never been as suicidal as this week": _NEVER_BEEN,
    "I've never felt so suicidal": _NEVER_BEEN,
    "I've never felt this suicidal in my life": _NEVER_BEEN,
    "Honestly I have never been more suicidal than this week": _NEVER_BEEN,
    "I have never, ever been more suicidal": _NEVER_BEEN,
    "Never been more suicidal lol": _NEVER_BEEN,
    # ...and never wanted to <phrase> more (than) / so badly / as much as.
    "I've never wanted to kill myself more than today": _NEVER_WANTED,
    "I've never wanted to kill myself more.": _NEVER_WANTED,
    "I've never wanted to kill myself more...": _NEVER_WANTED,
    "I've never wanted to die more than now": _NEVER_WANTED,
    "I have never wanted to die more": _NEVER_WANTED,
    "I've never wanted to die so badly": _NEVER_WANTED,
    "I never wanted to die so badly before": _NEVER_WANTED,
    "I would never want to hurt myself as much as I do now": _NEVER_WANTED,
    # A fear of the act after the negation, or a negated negation (b53e6c73).
    "I'm no longer afraid to kill myself": _FEAR,
    "I'm not scared to kill myself anymore": _FEAR,
    "I'm no longer scared to end my life": _FEAR,
    "I wouldn't hesitate to kill myself": _FEELING_VERB,
    "I won't hesitate to end my life": _FEELING_VERB,
    "I'm not hesitating to kill myself": _FEELING_VERB,
    "I don't fear killing myself": _FEELING_VERB,
    "I'm not worrying about killing myself": _FEELING_VERB,
    "I've never stopped being suicidal": _FEELING_VERB,
    "I don't hesitate to hurt myself": (
        "'not hesitate to' is now an intent frame: no other phrase reads a bare 'to hurt myself'"),
    "I never hesitated to hurt myself": (
        "'not hesitate to' is now an intent frame: no other phrase reads a bare 'to hurt myself'"),
    "I can't not think about killing myself": "a negated negation (can't not) says the phrase is there",
    # "this" after a negation points at the state now.
    "I'm not usually this suicidal": _THIS,
    "I'm not this suicidal usually": _THIS,
    # Same answer, now the explicit phrase instead of the mention: a
    # first-person lead takes a comparative, so TOPIC_GUARDS cannot veto it.
    "I'm more suicidal than ever": _FIRST_PERSON_COMPARATIVE,
    "I feel more suicidal since starting the new meds": _FIRST_PERSON_COMPARATIVE,
    "I'm getting more suicidal every day": _FIRST_PERSON_COMPARATIVE,
    # The "someone else's wish" guard read the speaker's own "I" as the someone.
    "I can't do this anymore, I want to die": _SOMEONE_ELSE,
    "I really do think I want to die": _SOMEONE_ELSE,
}


def result_key(match) -> str | None:
    """A `detect` answer as comparable data: `category/label`, or None."""
    return None if match is None else f"{match.category}/{match.label}"


def load_base_results() -> dict[str, str | None]:
    return json.loads(BASE_RESULTS_PATH.read_text(encoding="utf-8"))


_BASE_SCRIPT = """
import json, sys
sys.path.insert(0, ".")
from services.crisis_detection import detect
out = {}
for t in json.load(sys.stdin):
    m = detect(t)
    out[t] = None if m is None else f"{m.category}/{m.label}"
json.dump(out, sys.stdout)
"""


def run_base(texts: list[str], backend_dir: Path | None = None) -> dict[str, str | None]:
    """`detect` at BASE_COMMIT for every text, run in the base checkout."""
    backend_dir = Path(os.environ.get("CRISIS_BASE_BACKEND", backend_dir or _DEFAULT_BASE_BACKEND))
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _BASE_SCRIPT], cwd=backend_dir,
        input=json.dumps(texts), capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def main(argv: list[str]) -> int:
    from services.crisis_detection import detect
    from tests.test_crisis_detection import expected_corpus

    texts = list(expected_corpus())
    if "--write-base" in argv:
        base = run_base(texts)
        BASE_RESULTS_PATH.write_text(
            json.dumps(base, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(base)} base answers to {BASE_RESULTS_PATH.name}")
        return 0
    base = run_base(texts) if "--live-base" in argv else load_base_results()
    show_all = "--all" in argv
    differ = 0
    for text in texts:
        now, was = result_key(detect(text)), base.get(text, "<no base answer>")
        if now != was:
            differ += 1
        if show_all or now != was:
            mark = "listed" if text in INTENDED_CHANGES_FROM_BASE else "UNLISTED"
            flag = "" if now == was else f"  [{mark}]"
            print(f"{text!r}\n    base: {was}\n    now:  {now}{flag}")
    print(f"{differ} of {len(texts)} differ from {BASE_COMMIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
