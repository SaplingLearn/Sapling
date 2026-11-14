"""Crisis-language detection for student-written text (the crisis-support path).

PURE and DETERMINISTIC: no I/O, no model call, no logging of the text. One
function answers one question — does this text say, in the student's own
words, that they may be in danger? `detect(text)` returns a `CrisisMatch`
(category + which list matched) or None. The route-side path that acts on a
match (flag, event, the fixed response) is `services/crisis_support.py`; the
words the student then sees are in `services/crisis_support_copy.py`.

What it is NOT: a model screen. It reads phrases, so it misses indirect
language ("I just want everything to stop", "I won't be a problem much
longer") and anything not in English. docs/safety/crisis-support.md has the
limits and how the owner extends the lists below.

How matching works (every list below is a regex over `normalize(text)`):

1. `normalize` folds case and accents, drops apostrophes ("can't" -> "cant",
   "I'm" -> "im"), turns sentence punctuation into a `|` boundary and every
   other non-letter into a space ("self-harm" -> "self harm"), and squeezes a
   letter repeated 3+ times to one ("killl" -> "kil", "dieee" -> "die").
   Patterns are written against THAT form: no apostrophes, no punctuation.
2. EXPLICIT phrases match anywhere: first-person statements of intent,
   ideation, self-harm or acute danger ("kill myself", "end my life", "want to
   die", "hurt myself on purpose", "took a bunch of pills").
3. MENTION words ("suicide", "suicidal", "self-harm") match only when the SAME
   sentence also speaks in the first person (I / me / my ...): "I've been
   thinking about suicide" matches, "Why did Romeo commit suicide?" does not.
4. GUARDS veto any match they overlap: idioms ("killing myself laughing",
   "cut myself some slack", "the hill I want to die on"), negations ("I don't
   want to die") and technical compounds ("suicide squad", "suicide
   inhibitor", "kill switch" never matches at all). A negation
   (NEGATION_GUARDS) reaches only within its own clause: a comma, dash,
   bracket, joining word ("but", "and") or new first-person subject ends it,
   so "I'm not okay, I'll kill myself" still matches; "I won't lie", "not
   gonna lie", "not kidding" introduce a statement and negate nothing; and
   only a hedge about one's own state ("I don't think I'm suicidal")
   negates: "I'm not saying I'll kill myself" is a warning sign. TOPIC_GUARDS
   veto MENTIONS
   (never explicit phrases) anywhere in the text when it names an academic
   topic ("Durkheim", "euthanasia", "theory of suicide").

5. `detect(text, source="document")` (a stored note or card, never a typed
   message) sets quotations aside: a match entirely inside "...", “...”,
   '...' or a `>` block-quote line does not count unless the quotation's own
   sentence speaks in the first person outside it. That sentence is the one
   the quotation sits in: a break inside the quotation does not end it, a
   colon that introduces it ('I wrote: "..."') does not either, and a
   quotation closing on its own '.', '!' or '?' ends it there. The quotations
   are found on the RAW text (normalizing drops quote marks) and carried
   through as marker tokens.

Phrases are word-bounded: a pattern never matches inside a longer word.

To extend: add a `Phrase` to EXPLICIT (pick its category; write it against
the normalized form; use the `_MYSELF` / `_INTENT` building blocks), a
pattern to GUARDS for a new false positive, then add a case to
tests/test_crisis_detection.py — every phrase class and every guard there has
a pinned example.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass
from typing import Iterable, Literal

Category = Literal["acute_danger", "suicidal_ideation", "self_harm"]
#: Most severe first: when one text matches several categories, the first one
#: listed is reported.
CATEGORIES: tuple[Category, ...] = ("acute_danger", "suicidal_ideation", "self_harm")
Tier = Literal["explicit", "mention"]

#: Longest text screened (characters, before normalizing). Notes can be long;
#: the patterns are linear, so this only bounds pathological input.
MAX_SCREEN_CHARS = 200_000


@dataclass(frozen=True)
class CrisisMatch:
    """What matched — never the matched text. `label` names the list entry."""

    category: Category
    tier: Tier
    label: str


@dataclass(frozen=True)
class Phrase:
    category: Category
    label: str
    pattern: str


# ── Building blocks (normalized form) ──────────────────────────────────────

#: "myself" and its common misspellings/spacings ("my self", "myslef").
_MYSELF = r"(?:my ?self|myslef|mysef|myselfe|meself|mself)"
#: "kill" with one or two l's ("killl" is squeezed to "kil" by normalize).
_KILL = r"kil{1,2}"
_TO = r"(?:to|2|ta)"
#: First-person want — never "wants" (third person).
_WANT = rf"(?:want(?:ed|ing)? {_TO}|wanna|wana|wnt {_TO})"
#: Intent frames that make a verb a statement about the SPEAKER's plan. Bare
#: modals ("could", "might", "will") are deliberately absent — "a patient could
#: overdose" is pharmacology — so a modal counts only as "I could" / "I'll".
_INTENT = (
    rf"(?:{_WANT}"
    rf"|(?:going|gonna|gona|bout|about|ready|planning|plan|trying|tried|try|decided|deciding) {_TO}"
    r"|gonna|gona|imma|ima|finna"
    r"|i (?:will|might|could|should|would|may)|ill|id"
    r"|wish i could|thinking (?:about|of)|thought (?:about|of)"
    rf"|urge {_TO}|urges {_TO}|tempted {_TO}|feel like|feeling like)"
)
_SUICIDE = r"(?:suicide|suicid|sucide|suicde|suiside|suiscide|suicied)"
_SUICIDAL = r"(?:suicidal|suisidal|sucidal|suicidel|suicidial)"
_SELF_HARM = r"self ?(?:harm|harming|harmed|harms|injury|injuring|injured|injure)"
#: Amounts that read as an overdose. Not "all my/all the": "I took all my meds"
#: is usually adherence.
_QUANT = (
    r"(?:a bunch of|a lot of|lots of|too many|so many|a handful of|a whole bottle of"
    r"|the whole bottle of|a bottle of|the bottle of|tons of|way too many)"
)
_PILLS = (
    r"(?:pills|tablets|meds|medication|medications|sleeping pills|painkillers|tylenol"
    r"|advil|ibuprofen|xanax|benadryl)"
)


# ── EXPLICIT phrases (match anywhere; most severe category first) ──────────

EXPLICIT: tuple[Phrase, ...] = (
    # acute_danger — a method, a plan, or an act already in progress.
    Phrase("acute_danger", "self-directed method",
           rf"(?:hang|hanging|hung|shoot|shooting|shot|stab|stabbing|drown|drowning|poison"
           rf"|poisoning|suffocate|suffocating|strangle|strangling|overdose|overdosing) ?{_MYSELF}"),
    Phrase("acute_danger", "wrists",
           r"(?:slit|slitting|slice|slicing) (?:my|both|both my|both of my) (?:wrists?|throat)"),
    Phrase("acute_danger", "jump with intent",
           rf"(?:{_INTENT}|im|i am|im gonna|im going {_TO}) (?:jump|jumping) (?:off|from|in front of)"
           r" (?:(?:a|an|the|this|that|my|our) )?(?:bridge|building|roof|rooftop|cliff|balcony"
           r"|window|ledge|tower|train|subway|car|truck|bus|overpass|parking garage|dorm|highway)"),
    Phrase("acute_danger", "took pills",
           rf"(?:took|taken|swallowed|downed|just took|ive taken|have taken) {_QUANT} {_PILLS}"),
    Phrase("acute_danger", "pills with intent",
           rf"(?:{_INTENT}) (?:take|taking|swallow|swallowing|down) {_QUANT} {_PILLS}"),
    Phrase("acute_danger", "overdose with intent", rf"(?:{_INTENT}) (?:overdose|overdosing|od)"),
    Phrase("acute_danger", "overdosed",
           r"(?:i|ive|i just|just|i think i|i might have|i may have) (?:overdosed|oded)"),
    Phrase("acute_danger", "method seeking",
           rf"(?:how (?:to|do i|can i|could i|should i)"
           rf"|(?:best|easiest|quickest|fastest|painless|least painful|surest|quietest)"
           rf" (?:way|ways|method|methods) (?:to|of))"
           rf" (?:{_KILL} {_MYSELF}|end my life|commit {_SUICIDE}|die)"),
    Phrase("acute_danger", "hurt by someone",
           r"(?:someone|somebody|he|she|they|my (?:partner|boyfriend|bf|girlfriend|gf|husband"
           r"|wife|roommate|dad|father|mom|mother|parent|parents|stepdad|stepfather|stepmom"
           r"|stepmother|brother|sister|ex|uncle|aunt|coach))"
           r" (?:is|are|keeps|keep|has been|have been|was|were|kept|wont stop)"
           r" (?:hurting|hitting|abusing|beating|choking|raping) me"),
    Phrase("acute_danger", "not safe",
           r"(?:im not|i am not|dont feel|do not feel|i dont feel|i do not feel|not feeling) safe"
           r" (?:at home|here|right now|anymore|any more|around (?:him|her|them|my)"
           r"|with (?:him|her|them|my))"),
    Phrase("acute_danger", "in danger", r"(?:im|i am) in danger(?= ?(?:\||$|right now|now|here|at home|tonight))"),

    # suicidal_ideation — thoughts, wishes or intent to die.
    Phrase("suicidal_ideation", "kill myself", rf"(?:{_KILL}|{_KILL}ing) ?{_MYSELF}"),
    Phrase("suicidal_ideation", "kms", rf"(?:{_INTENT}|literally|lowkey|ngl|bouta) kms"),
    Phrase("suicidal_ideation", "unalive", rf"unaliv(?:e|ing) ?{_MYSELF}|(?:{_INTENT}) unalive"),
    Phrase("suicidal_ideation", "sewer slide", r"sewer ?slide"),
    Phrase("suicidal_ideation", "end my life", r"(?:end|ending|take|taking) (?:my|my own) life"),
    Phrase("suicidal_ideation", "end it all",
           rf"(?:{_INTENT}|just|finally) (?:end|ending) (?:it all|everything|my existence)"),
    Phrase("suicidal_ideation", "want to die",
           rf"(?:{_WANT}|ready {_TO}|wish {_TO}|wish i could|wish i would|hope i|hoping i|pray i"
           rf"|praying i) (?:just )?(?:die|be dead|stop existing|not exist|cease {_TO} exist"
           r"|disappear forever|not be alive|not be here anymore)"),
    Phrase("suicidal_ideation", "wish I were dead",
           r"wish(?:ed)? (?:i|id) (?:was|were|could be|would be|had been) dead"
           r"|wish(?:ed)? (?:i|id) (?:was|were)(?:nt| not) (?:alive|born|here anymore|around anymore)"
           r"|wish(?:ed)? (?:i|id) (?:had )?never (?:been born|existed|woken up|woke up)"),
    Phrase("suicidal_ideation", "not wake up",
           r"(?:hope|hoping|wish|pray|praying) (?:i|id) (?:dont|do not|didnt|did not|never|wont"
           r"|will not|would not|wouldnt) wake up"
           r"(?! (?:late|early|at|in time|before|on time|too|until|for))"),
    Phrase("suicidal_ideation", "better off dead", r"better off (?:dead|without me)"),
    Phrase("suicidal_ideation", "dont want to live",
           rf"(?:dont|do not|didnt|did not|no longer|dont really|dont even) (?:want {_TO} |wanna )?"
           r"(?:be alive|keep living|go on living|exist anymore|exist any more|live anymore"
           r"|live any more|live any longer|be here anymore|be here any more|wake up anymore"
           r"|wake up ever again)"
           rf"|(?:dont|do not|no longer|dont really|dont even) (?:want {_TO} |wanna )(?:live|exist)"
           r"(?= ?(?:\||$))"),
    Phrase("suicidal_ideation", "no reason to live",
           r"(?:no|zero|not a single|not any|nothing|lost (?:my|all|every)|dont have a|dont have any"
           r"|dont see a|dont see any|cant find a|cant see a|cant find any)"
           r" (?:reason|reasons|point|purpose) (?:(?:to|in|for) )?(?:live|living|go on|going on"
           r"|keep going|be alive|being alive|stay alive|staying alive|exist|existing)"
           r"|nothing (?:left )?to live for"
           r"|(?:life|living|my life) (?:is not|isnt|aint|is no longer|isnt really|is not really"
           r"|doesnt feel|does not feel) worth (?:it|living)"
           r"|not worth living"),
    Phrase("suicidal_ideation", "cant go on",
           r"(?:cant|can not|cannot|cant really|cant even|dont think i can|dont know if i can"
           r"|dont know how i can|unable to) go on"
           r"(?= ?(?:\||$|anymore|any ?more|any longer|like this|living|with (?:my )?life))"
           r"|(?:cant|cannot|can not) (?:keep living|go on living)"),
    Phrase("suicidal_ideation", "feeling suicidal",
           r"(?:im|i am|ive been|i have been|i was|i feel|i felt|i get|i got|i keep getting|feeling"
           r"|been feeling|been|getting|been getting|ive felt)"
           r"(?: (?:so|really|very|kinda|kind of|pretty|extremely|super|always|constantly|still"
           rf"|lowkey|honestly|literally|actually|a bit|a little|seriously))* {_SUICIDAL}"),
    Phrase("suicidal_ideation", "suicide thoughts",
           r"(?:im|i am|ive been|i have been|i was|i keep|i still|i sometimes|i always|i cant stop"
           r"|cant stop|ive|i)"
           r"(?: (?:really|seriously|honestly|literally|actually|kinda|kind of|just|also|even|been"
           r"|always|still|often|constantly|sometimes))*"
           r" (?:(?:thinking|thought|think) (?:about|of)|considering|contemplating|planning)"
           rf" (?:{_SUICIDE}|committing {_SUICIDE}|{_KILL}ing {_MYSELF}"
           r"|ending (?:it all|my life|everything)|taking my (?:own )?life)"),
    Phrase("suicidal_ideation", "suicide thoughts (no subject)",
           r"(?:^|\| )(?:(?:been|keep|always|still|lately|constantly|honestly|ngl|tbh|seriously|just"
           r"|also) )*(?:thinking|thought) (?:about|of)"
           rf" (?:{_SUICIDE}|committing {_SUICIDE}|ending (?:it all|my life|everything))"),
    Phrase("suicidal_ideation", "suicide intent",
           rf"(?:{_INTENT}) (?:commit|attempt|try|do) {_SUICIDE}"
           rf"|{_SUICIDE} (?:is|seems|feels like) (?:the|my) only (?:way|option|choice|answer|solution)"),

    # self_harm — hurting oneself without (stated) intent to die.
    Phrase("self_harm", "hurting myself",
           rf"(?:hurting|harming|cutting|burning|injuring|mutilating) ?{_MYSELF}"),
    Phrase("self_harm", "harm myself", rf"(?:harm|injure|mutilate) ?{_MYSELF}"),
    Phrase("self_harm", "hurt myself with intent",
           rf"(?:{_INTENT}|keep|kept|started|start|been|ive been) (?:hurt|cut|burn|hit|punch|scratch)"
           rf"(?:ing)? ?{_MYSELF}"),
    Phrase("self_harm", "hurt myself on purpose",
           rf"(?:hurt|cut|burn|hit|punch|scratch|harm) ?{_MYSELF}"
           r" (?:on purpose|again|deliberately|intentionally|deep|deeper)"),
    Phrase("self_harm", "self-harm with intent",
           rf"(?:{_INTENT}|started|start|keep|kept|been|ive been|stop|stopped|quit|relapse|relapsed"
           rf"|relapsing) (?:to )?{_SELF_HARM}|{_SELF_HARM} again"),
)

#: MENTION words: matched only when the same sentence speaks in the first
#: person (and no TOPIC_GUARD names an academic topic in the text).
MENTIONS: tuple[Phrase, ...] = (
    Phrase("suicidal_ideation", "suicide (mention)", rf"{_SUICIDE}|{_SUICIDAL}"),
    Phrase("self_harm", "self-harm (mention)", _SELF_HARM),
)

#: First-person markers that make a sentence's MENTION about the speaker.
FIRST_PERSON = r"(?:i|im|ive|id|ill|me|my|myself|mine)"


# ── GUARDS: veto any match they overlap ────────────────────────────────────

_NEGATION = r"(?:not|never|dont|do not|wont|will not|wouldnt|would not|isnt|no longer)"
_NEGATED = (
    rf"(?:{_KILL}(?:ing)? ?{_MYSELF}|end my life|{_SUICIDAL}|hurt ?{_MYSELF}|harm ?{_MYSELF}"
    rf"|commit {_SUICIDE})"
)
#: A word that may sit between a negation and the phrase it negates: never a
#: clause-joining word or a new first-person subject, which start the NEXT
#: clause ("I'm not okay but suicidal", "I won't lie I'm suicidal").
_GAP_WORD = (
    r"(?!(?:but|and|so|yet|though|although|because|cause|cuz|bc|plus|or|then"
    r"|i|im|ill|id|ive)(?![a-z0-9]))[a-z]+"
)

#: Idioms whose negation INTRODUCES what follows instead of negating it ("I
#: won't lie", "not gonna lie", "not gonna sugarcoat it", "I'm not kidding"):
#: a negation word that opens one negates nothing, whatever comes after.
_INTRODUCES = (
    r"(?:even |ever )?(?:gonna |gona |going to |go |to )?"
    r"(?:lie|lying|kid|kidding|joke|joking|sugarcoat|sugarcoating|sugar coat|sugar coating"
    r"|exaggerate|exaggerating)(?![a-z0-9])"
)

#: NEGATION_GUARDS veto like GUARDS, but are matched over the CLAUSE form of
#: the text (`_Forms.clause`), where a comma, dash or bracket is a `,` token
#: no gap word can cross: "I'm not okay, I'll kill myself" is not negated.
NEGATION_GUARDS: tuple[str, ...] = (
    # "I'm not suicidal", "I would never(, ever) kill myself" say the opposite
    # (up to two words between the negation and the phrase, same clause).
    rf"{_NEGATION}(?! {_INTRODUCES})(?: ,)?(?: ever)?(?: {_GAP_WORD}){{0,2}} {_NEGATED}",
    # A hedge about one's own STATE: "I don't think I'm suicidal". Never about
    # an act or a plan ("I don't think I'll kill myself tonight"), and never
    # "not saying"/"don't mean" ("I'm not saying I'll kill myself" is a
    # warning sign). A contraction reads like its spelled-out form.
    rf"{_NEGATION}(?: really)? (?:think|believe|guess|feel)"
    rf" (?:im|i am|i was|ive been|i have been) {_SUICIDAL}",
    r"(?:dont|do not|didnt|did not|never|wont|will not|dont really)"
    r" (?:want(?:ed)?|wanna|wish(?:ed)?) (?:to |2 )?(?:die|be dead)",
)

GUARDS: tuple[str, ...] = (
    # Idioms whose literal meaning is not self-harm.
    r"my ?self (?:esteem|worth|confidence|respect|image|control|discipline|care)",
    r"(?:my|my own) life (?:savings|story|stories|insurance|goals?|plans?|choices|decisions|back"
    r"|(?:in|into) my (?:own )?hands)",
    rf"{_KILL}ing ?{_MYSELF} (?:laughing|trying|studying|working|cramming|over|for"
    r"|to (?:get|finish|make|pass|study|keep))",
    rf"{_KILL} ?{_MYSELF} laughing",
    rf"(?:cut|cutting) ?{_MYSELF} (?:some |a little |a bit of )?slack",
    rf"(?:cut|cutting) ?{_MYSELF} off",
    rf"(?:cut|cutting) ?{_MYSELF} (?:a|another) (?:piece|slice|break)",
    rf"(?:cut|cutting|nicked) ?{_MYSELF} (?:shaving|cooking|chopping|on (?:a|the) (?:paper|knife|can|glass))",
    rf"(?:burn|burning|burnt|burned) ?{_MYSELF} out",
    rf"(?:shoot|shooting|shot) ?{_MYSELF} in the foot",
    rf"(?:shoot|shooting|shot) ?{_MYSELF} (?:a|an) (?:email|e mail|text|message|note|reminder|dm|link)",
    rf"(?:drown|drowning) ?{_MYSELF} in (?:work|homework|school|coffee|caffeine|tea|studying|assignments"
    r"|readings|notes|books|music|netflix|tv|games|flashcards)",
    rf"(?:hurting|harming) ?{_MYSELF} by not",
    r"die on (?:this|that|the|a|my|your|every) hill",
    r"hill (?:[a-z0-9]+ ){0,4}die on",
    r"(?:die|dying) (?:my|her|his|their|your|our) hair",
    r"hitting me (?:up|with)",
    r"beating me (?:at|in|on|to)",
    # Someone else's wish, asked about: "Why does Hamlet want to die?"
    r"(?:does|did|do|doesnt|didnt|would|wouldnt|why would|why does|why did|why do|why dont)"
    r" (?!i |you |u |we )[a-z]+(?: [a-z]+){0,2} (?:want|wanna|wanted|wish|wished) (?:to |2 )?die",
    # Housing and itineraries, not life.
    r"(?:reason|reasons|point|purpose) (?:to |in |for )?live (?:in|at|on|with|near|off|here|there"
    r"|close|far|by|alone|together|downtown)",
    r"(?:reason|reasons|point|purpose) (?:to |in |for )?(?:go|going) on (?:to|with|about|and|vacation"
    r"|a trip|the trip|break)",
    # Technical and academic compounds.
    rf"{_SUICIDE} (?:squad|inhibitor|inhibitors|inhibition|substrate|substrates|gene|genes|enzyme"
    r"|enzymes|bomber|bombers|bombing|bombings|attack|attacks|mission|missions|vest|vests|burn|burns"
    r"|door|doors|run|runs|sprint|sprints|drill|drills|king|kings|clause|clauses|seat|lane|forest"
    r"|rate|rates|statistics|stats|data)",
    r"not a suicide pact",
    rf"{_SUICIDAL} (?:move|moves|mission|missions|strategy|strategies|attack|attacks|charge|play"
    r"|plays|pass|maneuver|maneuvers|tactic|tactics|gene|genes|cell|cells)",
    r"non ?suicidal(?: self ?(?:injury|injurious|harm))?",
    rf"(?:assisted|physician assisted|doctor assisted|medically assisted|altruistic|egoistic|egotistic"
    rf"|anomic|fatalistic|ritual|ritualistic|cellular|cell|mass|copycat|political|protest) {_SUICIDE}",
    r"self ?(?:harm|injury) (?:rates?|statistics|stats|data|research|studies|study|literature|prevalence)",
)

#: TOPIC_GUARDS: naming one of these anywhere in a text vetoes its MENTION
#: matches (never an EXPLICIT phrase): the text is about coursework.
TOPIC_GUARDS: tuple[str, ...] = (
    # Names take an optional "s": normalize turns "Hamlet's" into "hamlets".
    r"durkheims?", r"euthanasia", r"seppuku", r"hara ?kiri", r"kamikazes?", r"apoptosis",
    r"werthers?", r"hamlets?", r"ophelias?", r"romeos?", r"juliets?", r"cleopatras?", r"socrates",
    r"plaths?", r"woolfs?", r"hemingways?", r"camus", r"sisyphus", r"kareninas?", r"bovarys?",
    rf"(?:theory|theories|sociology|epidemiology|types?|forms?|rates?|statistics|causes|history"
    rf"|ethics|morality|philosophy|portrayal|depictions?|representations?|themes?|motifs?|prevalence"
    rf"|risk factors?) (?:of|on|about|for) (?:{_SUICIDE}|self ?harm)",
    rf"(?:essay|paper|thesis|report|presentation|lecture|chapter|reading|article|study|research"
    rf"|case study|exam|homework|assignment|quiz|project) (?:is |was |will be )?(?:on|about|regarding)"
    rf" (?:{_SUICIDE}|self ?harm)",
)


# ── Normalization ──────────────────────────────────────────────────────────

_APOSTROPHES = re.compile("['’‘ʼ`´]")
_INVISIBLE = re.compile("[­​-‏⁠﻿]")
_SENTENCE_BREAK = re.compile(r"[.!?;:\n\r]+")
#: Clause punctuation inside a sentence: a comma, a dash between words, a
#: bracket. Only the negation guards see it (as a `,` token); every other
#: pattern reads it as a space, exactly as before.
_CLAUSE_BREAK = re.compile(r"(?:[,()\[\]{}–—]|(?<!\S)-+(?!\S))+")
_CLAUSE = ","
#: Where a quotation opens and closes (documents only); never in `text`.
_QUOTE_OPEN, _QUOTE_CLOSE = "\x01", "\x02"
_NON_WORD = re.compile(r"[^a-z0-9|,\x01\x02\x03]+")
#: `_SENTENCE_BREAK` for marked text: a marker inside a run of sentence
#: punctuation (`."` closing a quote, then `:`) does not split the run.
_SENTENCE_BREAK_MARKED = re.compile(r"[.!?;:\n\r](?:[\x01\x02]*[.!?;:\n\r])*")
#: Follows the `|` of a colon that introduces a quotation ('I wrote: "..."'):
#: that break does not end the quotation's sentence. Never in `text`.
_INTRO = "\x03"
#: What follows such a colon: the opening mark (single ones are already gone
#: with the apostrophes), then the quote's open marker.
_OPENS_NEXT = re.compile(r'\s*["“„]?\x01')
_MARKERS = re.compile(r"[\x01\x02\x03]")
_REPEATED_LETTER = re.compile(r"([a-z])\1{2,}")

#: Longest quotation set aside in a document. A longer "quotation" is more
#: likely a stray mark than a quote, so it is screened like the rest.
_QUOTE_MAX = 600
#: A quote opens at the start, after whitespace, a bracket, a colon or a dash,
#: and closes before anything but a letter or digit: never mid-word, so an
#: apostrophe ("I'm", "can't") is never a quote mark.
_OPENS = r"(?<![^\s(\[{:—–-])"
_CLOSES = r"(?![^\W_])"
#: A single quote mark is DROPPED by normalizing (it reads as an apostrophe),
#: so its close must not be followed by a letter even after more of them.
_CLOSES_SINGLE = r"(?![’‘ʼ`´']*[^\W_])"
#: An elided word ("'cause", "'til") opens nothing.
_ELISION = r"(?:cause|cos|coz|cuz|til|till|em|bout|round|n|tis|twas)(?![a-z])"
_QUOTED = re.compile(
    rf'{_OPENS}"(?=\S)([^"\n]{{1,{_QUOTE_MAX}}})(?<=\S)"{_CLOSES}'
    rf"|“([^“”\n]{{1,{_QUOTE_MAX}}})”"
    rf"|„([^“”„\n]{{1,{_QUOTE_MAX}}})[“”]"
    rf"|{_OPENS}['‘](?!{_ELISION})(?=\S)([^'‘’\n]{{1,{_QUOTE_MAX}}})(?<=\S)['’]{_CLOSES_SINGLE}",
    re.IGNORECASE,
)
#: A Markdown block quote: the rest of a line that starts with `>`.
_BLOCK_QUOTE = re.compile(r"^[ \t]*>(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class _Forms:
    """`text` is `normalize`'s form. `clause` is the same with a `,` token at
    each clause break; `commas` are those tokens' offsets in `clause`, which
    map a `clause` offset back onto `text`. `quoted` are the (start, end)
    spans of `text` that sat inside a quotation (documents only). `breaks`
    are the offsets of the `|` tokens that end a sentence AROUND a quotation:
    a break inside a quotation does not count unless it is the quotation's
    last token ('"I want to die." I think ...' ends its sentence at the
    quote), and neither does a colon that introduces one."""

    text: str
    clause: str
    commas: tuple[int, ...]
    quoted: tuple[tuple[int, int], ...] = ()
    breaks: tuple[int, ...] = ()

    def from_clause(self, index: int) -> int:
        # Each `,` token before `index` added two characters (it and a space).
        return index - 2 * bisect_left(self.commas, index)


def _mark_quotations(text: str) -> str:
    """`text` with a quote marker token around every quotation, found on the
    RAW text (normalizing drops the quote marks)."""
    spans = sorted(
        [m.span(1) for m in _BLOCK_QUOTE.finditer(text) if m.group(1).strip()]
        + [next(m.span(g) for g in range(1, 5) if m.group(g) is not None)
           for m in _QUOTED.finditer(text)]
    )
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts, last = [], 0
    for start, end in merged:
        parts += [text[last:start], _QUOTE_OPEN, text[start:end], _QUOTE_CLOSE]
        last = end
    return "".join(parts) + text[last:]


def _forms(text: str, *, quotes: bool = False) -> _Forms:
    # A marker character the student typed is just a non-word character.
    text = _MARKERS.sub(" ", text[:MAX_SCREEN_CHARS])
    if quotes:
        text = _mark_quotations(text)
    folded = unicodedata.normalize("NFKD", text).casefold()
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = _INVISIBLE.sub("", folded)
    folded = _APOSTROPHES.sub("", folded)
    if quotes:
        folded = _SENTENCE_BREAK_MARKED.sub(_marked_break, folded)
    else:
        folded = _SENTENCE_BREAK.sub(" | ", folded)
    folded = _CLAUSE_BREAK.sub(f" {_CLAUSE} ", folded)
    folded = _NON_WORD.sub(" ", folded)
    folded = _REPEATED_LETTER.sub(r"\1", folded)
    if quotes:
        folded = _MARKERS.sub(lambda m: f" {m.group()} ", folded)
    words: list[str] = []  # `text`'s tokens
    clause: list[str] = []  # `clause`'s tokens
    commas: list[int] = []
    quoted: list[tuple[int, int]] = []
    breaks: list[int] = []
    c_len = n_len = 0  # length of each joined form so far
    opened: int | None = None
    last_break: int | None = None  # set while the open quotation ends in a break
    for token in folded.split():
        if token == _QUOTE_OPEN:
            opened, last_break = (n_len + 1 if words else 0), None
            continue
        if token == _QUOTE_CLOSE:
            if opened is not None and n_len > opened:
                quoted.append((opened, n_len))
                if last_break is not None:
                    breaks.append(last_break)
            opened = None
            continue
        if token == _INTRO:
            if breaks and breaks[-1] == n_len - 1:
                breaks.pop()
            continue
        c_len += 1 if clause else 0
        if token == _CLAUSE:
            commas.append(c_len)
        else:
            n_len += (1 if words else 0) + len(token)
            words.append(token)
            if opened is None:
                if token == "|":
                    breaks.append(n_len - 1)
            else:
                last_break = n_len - 1 if token == "|" else None
        clause.append(token)
        c_len += len(token)
    return _Forms(text=" ".join(words), clause=" ".join(clause), commas=tuple(commas),
                  quoted=tuple(quoted), breaks=tuple(breaks))


def _marked_break(m: re.Match[str]) -> str:
    """A sentence break in marked text, keeping the quote markers in its run,
    plus `_INTRO` after a lone colon that opens a quotation."""
    markers = _MARKERS.findall(m.group())
    intro = m.group() == ":" and _OPENS_NEXT.match(m.string, m.end()) is not None
    return " | " + (f" {_INTRO} " if intro else "") + "".join(f" {c} " for c in markers)


def normalize(text: str) -> str:
    """The form every pattern above is written against (see the module doc)."""
    return _forms(text).text


def _bounded(pattern: str) -> re.Pattern[str]:
    """Word-bounded: never matches inside a longer word."""
    return re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])")


_EXPLICIT = tuple((p, _bounded(p.pattern)) for p in sorted(
    EXPLICIT, key=lambda p: CATEGORIES.index(p.category)))
_MENTIONS = tuple((p, _bounded(p.pattern)) for p in MENTIONS)
_GUARDS = tuple(_bounded(g) for g in GUARDS)
_NEGATION_GUARDS = tuple(_bounded(g) for g in NEGATION_GUARDS)
_TOPIC_GUARDS = tuple(_bounded(g) for g in TOPIC_GUARDS)
_FIRST_PERSON = _bounded(FIRST_PERSON)


def _guarded(span: tuple[int, int], guards: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(g_start < end and start < g_end for g_start, g_end in guards)


#: What is screened: a "message" the student typed (all of it), or a
#: "document" (a note, a card) whose quotations are not the student's words.
Source = Literal["message", "document"]


def detect(text: str | None, *, source: Source = "message") -> CrisisMatch | None:
    """The most severe crisis phrase in `text`, or None. Never raises on str.

    `source="document"` sets quotations aside: a match entirely inside one
    ("...", “...”, '...', a `>` block-quote line) does not count, unless the
    quotation's own sentence speaks in the first person outside it ("I keep
    thinking 'I want to die'"). Lecture notes quote patients and plays; a
    student's own words are not in quotation marks. A typed message is always
    screened whole."""
    if not text or not text.strip():
        return None
    forms = _forms(text, quotes=source == "document")
    norm = forms.text
    if not norm:
        return None
    guards: list[tuple[int, int]] | None = None  # read only once something matched

    def guarded(span: tuple[int, int]) -> bool:
        nonlocal guards
        if guards is None:
            guards = [m.span() for g in _GUARDS for m in g.finditer(norm)]
            # Negations are matched clause by clause, then mapped onto `norm`.
            guards += [
                (forms.from_clause(m.start()), forms.from_clause(m.end()))
                for g in _NEGATION_GUARDS for m in g.finditer(forms.clause)
            ]
        return _guarded(span, guards)

    def set_aside(span: tuple[int, int]) -> bool:
        return _quoted_by_someone_else(forms, span)

    for phrase, regex in _EXPLICIT:
        for m in regex.finditer(norm):
            if not guarded(m.span()) and not set_aside(m.span()):
                return CrisisMatch(phrase.category, "explicit", phrase.label)
    topic = None  # likewise: a TOPIC_GUARD is read only for a candidate mention
    for phrase, regex in _MENTIONS:
        for m in regex.finditer(norm):
            if guarded(m.span()) or set_aside(m.span()):
                continue
            if topic is None:
                topic = any(g.search(norm) for g in _TOPIC_GUARDS)
            if topic:
                return None
            start = norm.rfind("|", 0, m.start()) + 1
            end = norm.find("|", m.end())
            if _FIRST_PERSON.search(norm[start:len(norm) if end == -1 else end]):
                return CrisisMatch(phrase.category, "mention", phrase.label)
    return None


def _quoted_by_someone_else(forms: _Forms, span: tuple[int, int]) -> bool:
    """`span` lies inside one quotation whose sentence, outside the quotation,
    has no first-person word ("a patient says '...'", not "I said '...'").

    The quotation's sentence is the one it sits in (`_Forms.breaks`): a break
    inside the quotation neither ends nor shifts it, but a quotation that ends
    with its own sentence punctuation ends the sentence there."""
    norm, breaks = forms.text, forms.breaks
    start, end = span
    for q_start, q_end in forms.quoted:
        if q_start <= start and end <= q_end:
            i = bisect_left(breaks, q_start)
            before = breaks[i - 1] + 1 if i else 0
            j = bisect_left(breaks, q_end - 1)
            if j == len(breaks):
                after = len(norm)
            elif breaks[j] == q_end - 1:  # the quotation ends in a break
                after = q_end
            else:
                after = breaks[j]
            outside = norm[before:q_start] + " " + norm[q_end:after]
            return not _FIRST_PERSON.search(outside)
    return False


def detect_any(texts: Iterable[str | None], *, source: Source = "message") -> CrisisMatch | None:
    """The most severe match across several fields of one request."""
    found = [m for m in (detect(t, source=source) for t in texts) if m is not None]
    if not found:
        return None
    return min(found, key=lambda m: CATEGORIES.index(m.category))
