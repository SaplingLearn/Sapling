"""Crisis-language detection for student-written text (the crisis-support path).

PURE and DETERMINISTIC: no I/O, no model call, no logging of the text. One
function answers one question — does this text say, in the student's own
words, that they may be in danger? `detect(text)` returns a `CrisisMatch`
(category + which list matched) or None. The route-side path that acts on a
match (flag, event, the fixed response) is `services/crisis_support.py`; the
words the student then sees are in `services/crisis_support_copy.py`.

What it is NOT: a model screen. It reads phrases, so it misses indirect
language ("I just want everything to stop", "I won't be a problem much
longer"). Beyond English it knows only a few core phrases in Spanish, French,
Portuguese and Chinese (sec2 M11; `CJK_EXPLICIT` for Chinese, which the
normalized form drops). Leetspeak ("k1ll mys3lf") and Cyrillic/Greek
look-alike letters are folded (`services/text_fold.py`). The tutor and note
chat prompts carry a model-side backstop for everything this misses
(`crisis_support_copy.MODEL_SAFETY_PROMPT`). docs/safety/crisis-support.md
has the limits and how the owner extends the lists below.

How matching works (every list below is a regex over `normalize(text)`):

1. `normalize` folds case and accents, drops apostrophes ("can't" -> "cant",
   "I'm" -> "im"), turns sentence punctuation (an ellipsis included) into a
   `|` boundary and every other non-letter into a space ("self-harm" ->
   "self harm"), and squeezes a letter repeated 3+ times to one ("killl" ->
   "kil", "dieee" -> "die").
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
   (NEGATION_GUARDS):
   - reaches only within its own clause: a comma, dash, bracket, joining
     word ("but", "and", "so") or new first-person subject ends it, so "I'm
     not okay, I'll kill myself" still matches. It crosses two things: a
     short aside set off on both sides right after the negation ("I'm not,
     like, suicidal", "I am not, and never will be, suicidal"), never one
     with a new "I" in it or a second clause after it, and never a bare
     comma ("not, want to kill myself" is two clauses); and a FILLER's
     comma ("like", "really", "honestly", "even", "you know" ...) right
     after the negation or that aside, straight into "suicidal" ("I'm not
     like, suicidal", "I'm not even, like, suicidal"). A filler completes
     nothing, so its comma is not a clause break; a content word does, so
     "I'm not okay, honestly, suicidal again" is two clauses. Past a
     filler's comma only "suicidal" is still negated, since an act there can
     start a clause of its own ("Not really, kill myself");
   - crosses a hedge about how much: "I'm not so / too / that / as suicidal
     (as last year)", "I don't want to die more than anything / so badly"
     are negations;
   - is NOT a negation in exactly these: "never (been|felt) (more|this|so|
     as) <phrase>" and "never wanted to <phrase> more (than) / so badly / as
     much as" (`_NEVER_SAYS_MORE`; "never" only, so "not as suicidal as" is
     still a negation), a fear of the act or of stopping it right after the
     negation, as an adjective or a verb ("no longer afraid to kill
     myself", "wouldn't hesitate to kill myself", "don't fear killing
     myself", "won't stop hurting myself"), "this" ("I'm not usually this
     suicidal"), and a negated negation ("can't not think about killing
     myself"). "not / never / won't hesitate to" is an `_INTENT` frame too,
     so "I don't hesitate to hurt myself" matches;
   - is never opened by "I won't lie", "not gonna lie", "not kidding", which
     introduce a statement; and only a hedge about one's own STATE negates
     ("I don't think I'm suicidal", "I'm not thinking I'm suicidal", "I don't
     (really) feel like / feel that / think that I'm suicidal"): "I'm not
     saying I'm suicidal", "I don't think I'll kill myself tonight" are
     warning signs;
   - does not veto when its own sentence takes it back (`_TAKEN_BACK`):
     "but / though / although / except / yet", within ~100 characters of the
     phrase, then a first-person modal or intent that stands for the phrase
     and ends its clause ("I don't want to kill myself but I might", "(but I
     think I will)", "but I'm going to", "but I think about it a lot"). "I'm
     not suicidal but I'm stressed", "but I might drop out" keep the negation.
     The take-back reads across a comma, a dash and an ellipsis, which trail
     off inside the sentence ("I'm not suicidal... but I might be"), never
     across a full stop ("I'm not suicidal. But I might be" keeps it).
   TOPIC_GUARDS veto MENTIONS (never explicit phrases) anywhere in the text
   when it names an academic topic ("Durkheim", "euthanasia", "theory of
   suicide").

5. A quotation is just text. A note quoting a patient or a play ('a patient
   says "I want to die"') matches like the student's own words would: no
   pattern can tell a quoted patient from a student quoting themselves.
   What a match in a stored note leads to (the card shown ALONGSIDE the
   result, never instead of it) is `services/crisis_support.py`'s business.

Phrases are word-bounded: a pattern never matches inside a longer word.

To extend: add a `Phrase` to EXPLICIT (pick its category; write it against
the normalized form; use the `_MYSELF` / `_INTENT` building blocks), a
pattern to GUARDS for a new false positive, then add a case to
tests/test_crisis_detection.py — every phrase class and every guard there has
a pinned example.

To change a list SAFELY, use the differential corpus in tests/crisis_corpus.py:
add the motivating sentence to its group, make the change, run
`python -m tests.crisis_corpus` (from backend/) to see every sentence whose
answer differs from #890's first reviewed detector, and list each intended
difference in its INTENDED_CHANGES_FROM_BASE with the reason. The suite fails
on an unlisted difference: a fix that breaks a sentence it was not written for
shows up there, not in production.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass
from typing import Iterable, Literal

from services.text_fold import fold_confusables, fold_leet, strip_invisible

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
    rf"|urge {_TO}|urges {_TO}|tempted {_TO}|feel like|feeling like"
    # "I won't hesitate to": the negation removes what stands in the way.
    rf"|(?:not|never|dont|do not|didnt|did not|wont|will not|wouldnt|would not|no longer)"
    rf" (?:hesitate|hesitated|hesitating) {_TO})"
)
_SUICIDE = r"(?:suicide|suicid|sucide|suicde|suiside|suiscide|suicied)"
_SUICIDAL = r"(?:suicidal|suisidal|sucidal|suicidel|suicidial)"
_SELF_HARM = r"self ?(?:harm|harming|harmed|harms|injury|injuring|injured|injure)"
#: How much, in "I'm really suicidal": never a comparative ("more", "as").
_INTENSIFIER = (
    r"so|really|very|kinda|kind of|pretty|extremely|super|always|constantly|still"
    r"|lowkey|honestly|literally|actually|a bit|a little|seriously"
)
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
           # The speaker's own state takes a comparative too ("I'm MORE
           # suicidal than ever")...
           r"(?:im|i am|ive been|i have been|i was|i feel|i felt|i get|i got|i keep getting|ive felt"
           r"|im getting|i am getting|im feeling|i am feeling)"
           rf"(?: (?:{_INTENSIFIER}|this|that|more|as|even))* {_SUICIDAL}"
           # ...a lead with no subject only a plain intensifier: "teens end up
           # feeling MORE suicidal on SSRIs" is pharmacology.
           rf"|(?:feeling|been feeling|been|getting|been getting)(?: {_INTENSIFIER})* {_SUICIDAL}"
           # "never been more suicidal": the speaker's, or a sentence opening on
           # it ("Never been this suicidal before"), never "teens have never...".
           rf"|(?:^|\| |(?:i|ive|i have|i had|id) )never (?:ever )?(?:been|felt) (?:more|this|so|as)"
           rf" {_SUICIDAL}"),
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

    # ── sec2 M11: more English phrasings ──────────────────────────────────
    # Means and a timeline: "stockpiling my meds", "tied a noose".
    Phrase("acute_danger", "stockpiling pills",
           rf"(?:stockpiling|stockpiled|hoarding|hoarded|saving up|saved up)"
           rf" (?:my |the |some |all my |{_QUANT} )?{_PILLS}"),
    Phrase("acute_danger", "noose", r"(?:tied|tie|tying|made|make|making) (?:a |the |my )?noose"),
    # "going to end it tonight": "end it" only with a timeline (a bare "I'm
    # going to end it" is as often a relationship), never "end it with ...".
    Phrase("suicidal_ideation", "end it with a timeline",
           rf"(?:{_INTENT}|just|finally|im|i am) (?:end|ending) it(?: all)?"
           r" (?:tonight|today|tomorrow|this (?:week|weekend)|soon|for good|once and for all|now)"
           r"(?! (?:with|between)(?![a-z0-9]))"),
    Phrase("suicidal_ideation", "want it all to end",
           rf"(?:{_WANT}|i just want|i wish) (?:it all|everything|my life) (?:to )?(?:end|be over)"
           r"(?= ?(?:\||$|already|now|forever|for good))"),
    Phrase("suicidal_ideation", "sleep and never wake up",
           r"(?:go to sleep|fall asleep|sleep|close my eyes) and (?:never|not) wake up"
           r"(?! (?:late|early|at|in time|before|on time|too|until|for))"),
    # "I have been cutting again", "started cutting again", "cutting my arms".
    Phrase("self_harm", "cutting again",
           r"(?:i|ive|im|i am|i have|i was|i keep|i kept|i started|been|started|keep)"
           r"(?: (?:been|still|just|started|back to|going back to))* (?:cutting|burning)"
           r" (?:again|lately|every (?:day|night)|my (?:arms?|wrists?|legs?|thighs?|skin|stomach))"
           r"|(?:relapsed|relapsing|back to|went back to|started) (?:and )?(?:started )?cutting"
           r"(?= ?(?:\||$|again))"),

    # ── sec2 M11: Spanish, French, Portuguese (normalized: no accents) ────
    # Spanish
    Phrase("suicidal_ideation", "es: quiero morir",
           r"(?:me )?(?:quiero|quisiera|deseo) morir(?:me)?"
           r"|(?:quiero|voy a|pienso|estoy pensando en|planeo|deseo) (?:matarme|suicidarme"
           r"|quitarme la vida)"
           r"|me (?:quiero|voy a) (?:matar|suicidar)"
           r"|(?:ya )?no quiero (?:seguir )?vivir(?= ?(?:\||$|mas|asi|ya))"
           r"|no quiero seguir viviendo"
           r"|(?:tengo pensamientos|me siento) suicidas?"),
    Phrase("self_harm", "es: me corto",
           r"me (?:estoy cortando|corto|volvi a cortar|he cortado|corte)"
           r"(?= ?(?:\||$|otra vez|de nuevo|los brazos|las munecas|las piernas|la piel|el brazo"
           r"|la muneca))"
           r"|(?:quiero|voy a|necesito) (?:cortarme|hacerme dano|lastimarme|autolesionarme)"
           r"(?! (?:el|la|las|los|un|una) )"
           r"|me (?:hago|estoy haciendo) dano(?= ?(?:\||$|a proposito|otra vez|de nuevo))"
           r"|me (?:autolesiono|estoy autolesionando)"),
    # French
    Phrase("suicidal_ideation", "fr: je veux mourir",
           # "je vais mourir" is as often "this exam will kill me"; only a wish
           r"je (?:veux|voudrais) mourir|je (?:veux|voudrais|vais) (?:me tuer|me suicider)"
           r"|jai envie de (?:mourir|me tuer|me suicider)"
           r"|je pense a (?:me tuer|me suicider|mourir)"
           r"|je veux en finir(?= ?(?:\||$|avec la vie|avec ma vie|avec tout))"
           r"|je ne veux plus vivre|jai plus envie de vivre|je nai plus envie de vivre"
           r"|jai des idees suicidaires"),
    Phrase("self_harm", "fr: je me scarifie",
           r"je me (?:scarifie|mutile|fais du mal)"
           r"|je me coupe(?= ?(?:\||$|encore|souvent|a nouveau|les bras|les poignets|les veines))"
           r"|je (?:veux|vais) me (?:scarifier|mutiler|faire du mal)"),
    # Portuguese
    Phrase("suicidal_ideation", "pt: quero morrer",
           r"(?:eu )?(?:quero|queria) morrer"
           r"|(?:vou|quero|penso em|estou pensando em) (?:me matar|me suicidar|tirar (?:a )?minha"
           r" (?:propria )?vida)"
           r"|nao (?:quero|aguento) mais viver"
           r"|(?:quero|vou) acabar com (?:a )?minha vida"),
    Phrase("self_harm", "pt: me cortando",
           r"(?:estou|to|tou|eu) me cortando"
           r"|me cortei (?:de novo|outra vez|ontem|hoje)"
           r"|(?:quero|vou) me (?:cortar|machucar)(?= ?(?:\||$|de novo|outra vez|de proposito))"
           r"|(?:me )?automutil(?:o|ando|ar)"),
)

#: Chinese phrases, matched on the NFKC text (the normalized form drops CJK).
#: Each needs a first-person or explicit frame: "活不下去" alone is also what
#: a plant does without water, "伤害自己" alone is "don't hurt yourself".
CJK_EXPLICIT: tuple[Phrase, ...] = (
    Phrase("suicidal_ideation", "zh: 想死",
           r"我(?:真的|好|很|就是|只)?(?:想|要)(?:去)?死(?!你|您|他|她|我了|了你)"
           r"|(?:想|要|打算|准备|準備|计划|計劃)自(?:杀|殺)"
           r"|不想活(?:了|下去)"
           r"|我(?:真的|快|实在|實在|已经|已經)?活不下去"
           r"|我(?:想|要|打算|准备|準備)结束(?:我的|自己的)?生命"
           r"|我(?:想|要|打算|准备|準備)結束(?:我的|自己的)?生命"),
    Phrase("self_harm", "zh: 伤害自己",
           r"我(?:想|要|又|在|会|會|一直|总是|總是|经常|經常)(?:伤害|傷害|割)自己"
           r"|我(?:又|在|一直|有时|有時|经常|經常)?(?:自残|自殘|割腕)"),
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
#: Words after which a negation no longer negates the phrase: a feeling about
#: the act or about stopping it ("no longer AFRAID to kill myself", "I won't
#: STOP hurting myself"), as an adjective or as the verb it comes from ("I
#: wouldn't HESITATE to kill myself", "I don't FEAR killing myself", "I've
#: never STOPPED being suicidal"), and "this", which points at the state now
#: ("I'm not usually THIS suicidal"). They say what stands in the way, never
#: the opposite. Not "so/too/that/as/more": "I'm not SO suicidal anymore", "not
#: AS suicidal as last year" are negations (only `_NEVER_SAYS_MORE` reads a
#: comparative as the phrase being there).
_NOT_NEGATING = (
    r"this|afraid|scared|frightened|terrified|ashamed|sorry"
    r"|embarrassed|nervous|hesitant|worried|guilty|able|stop|stopping"
    r"|hesitate|hesitated|hesitating|hesitation|fear|feared|fearing|worry|worrying|stopped"
)
#: A word of the negation's own clause: never a clause-joining word or a new
#: first-person subject, which start the NEXT clause ("I'm not okay but
#: suicidal", "I won't lie I'm suicidal").
_CLAUSE_WORD = (
    r"(?!(?:but|and|so|yet|though|although|because|cause|cuz|bc|plus|or|then"
    r"|i|im|ill|id|ive)(?![a-z0-9]))[a-z]+"
)
#: A word that may sit between a negation and the phrase it negates: a
#: `_CLAUSE_WORD` that is not a `_NOT_NEGATING` word. (Inside an `_ASIDE` a
#: `_NOT_NEGATING` word governs nothing: "I'm not, don't worry, suicidal".)
_GAP_WORD = rf"(?!(?:{_NOT_NEGATING})(?![a-z0-9])){_CLAUSE_WORD}"
#: A negation that is itself negated ("I can't NOT think about killing
#: myself") says the phrase is there.
_NOT_DOUBLED = r"(?<!cant )(?<!cannot )(?<!couldnt )(?<!dont )(?<!didnt )(?<!wont )(?<!never )"
#: The clause form's ellipsis token (`_Forms.clause`): a sentence end to every
#: negation pattern except `_TAKEN_BACK`, which reads across it.
_TRAIL = "…"
#: A comparison right after the phrase.
_COMPARISON = (
    rf"(?:more than|more(?= ?(?:\||,|{_TRAIL}|$))|as much as|so much|this much|so badly|this badly)"
    r"(?![a-z0-9])"
)
#: The two constructions in which "never" says MORE, not less, read right
#: after the negation word: "never (been|felt) (more|this|so|as) <phrase>"
#: ("I have never been more suicidal") and "never wanted to <phrase> <more
#: than>" ("I've never wanted to kill myself more than today"). Only after
#: "never": "I don't want to die more than anything" and "I'm not as
#: suicidal as last year" stay negations, and so does a bare "more" that
#: starts something else ("I would never kill myself more or less").
_NEVER_SAYS_MORE = (
    rf"(?!(?<=never)(?: ,)?(?: ever)?(?: (?:been|felt) (?:more|this|so|as) {_NEGATED}"
    rf"| (?:want(?:ed)?|wanna|wish(?:ed)?) (?:to |2 )?(?:{_NEGATED}|die|be dead) {_COMPARISON}))"
)

#: Idioms whose negation INTRODUCES what follows instead of negating it ("I
#: won't lie", "not gonna lie", "not gonna sugarcoat it", "I'm not kidding"):
#: a negation word that opens one negates nothing, whatever comes after.
_INTRODUCES = (
    r"(?:even |ever )?(?:gonna |gona |going to |go |to )?"
    r"(?:lie|lying|kid|kidding|joke|joking|sugarcoat|sugarcoating|sugar coat|sugar coating"
    r"|exaggerate|exaggerating)(?![a-z0-9])"
)

#: An aside the negation may cross, set off on BOTH sides by a comma, bracket
#: or dash right after the negation word: one to four clause words ("I'm not,
#: like, suicidal", "I am not (really) suicidal"), or a coordinated "and never
#: (have been | will be)" ("I am not, and never will be, suicidal"). Never a
#: new first-person subject, a clause joiner or an introducing idiom (those
#: are not clause words), so "I'm not, I swear, okay, I'll kill myself" is not
#: negated; and only one aside, closed before the phrase.
_ASIDE = (
    rf" ,(?:(?! {_INTRODUCES})(?: {_CLAUSE_WORD}){{1,4}}"
    r"| and (?:never|not)(?: (?:ever|have|has|had|will|would|be|been|was|were|am|is|are)){0,3}) ,"
)

#: A filler: a word that completes nothing, so a comma after it is its own
#: and not a clause break ("I'm not LIKE, suicidal" says no more than "I'm not
#: like suicidal"). A content word does complete the clause, which is why
#: "I'm not OKAY, honestly, suicidal again" is two clauses and matches.
_FILLER = r"(?:like|really|honestly|even|actually|literally|seriously|truly|totally|um|uh|you know)"

#: A negation the SAME sentence takes back, read right after the negated
#: phrase (the join word within 100 characters of it, which also keeps a long
#: unpunctuated note linear): "but / though / although / except / yet" introducing a
#: first-person modal or intent that stands for the phrase — "I don't want to
#: kill myself but I might", "(but I think I will)", "but I think I'm going
#: to", "but I think about it a lot". The modal must END its clause (or carry
#: only "do it", "anyway", "probably", "be" ...): "but I might drop out",
#: "but I could use some help", "but I will pass" start a new thought and the
#: negation stands. "I'll" counts only as "I'll (probably) do it", since "but
#: ill" is also "but sick".
_TAKE_BACK_LEAD = (
    r"(?:(?:honestly|maybe|deep down|sometimes|lately|tbh|ngl|i (?:think|guess|feel like|bet|know"
    r"|worry|fear)(?: that)?) (?:, )?)*"
)
_TAKE_BACK_MODAL = (
    r"(?:i (?:(?:probably|still|just|really|actually|eventually|definitely) )?(?:might|will|could|may)"
    r"|im (?:going to|gonna|gona)|i am (?:going to|gonna)|i (?:want to|wanna))"
    r"(?: (?:probably|still|eventually|actually|really|do it|anyway|anyways|someday|soon|tonight"
    rf"|one day|at some point|again|too|be|end up doing it))*(?= (?:\||,|{_TRAIL})|$)"
    r"|ill (?:(?:probably|still|eventually|actually) )*(?:do it|end up doing it)(?![a-z0-9])"
)
_TAKE_BACK_THOUGHT = (
    r"(?:i (?:(?:still|also|sometimes|often|always|constantly|really|do|kinda) )*(?:think|thought)"
    r"|i (?:(?:still|also) )?(?:keep|cant stop) thinking|(?:ive|i have) (?:(?:still|also) )?been thinking"
    r"|im (?:(?:still|always|also) )?thinking) about it(?![a-z0-9])"
)
_TAKEN_BACK = (
    rf"(?![^|]{{0,100}}? (?:but|though|although|except|yet) (?:, )?{_TAKE_BACK_LEAD}"
    rf"(?:{_TAKE_BACK_MODAL}|{_TAKE_BACK_THOUGHT}))"
)

#: NEGATION_GUARDS veto like GUARDS, but are matched over the CLAUSE form of
#: the text (`_Forms.clause`), where a comma, dash or bracket is a `,` token
#: no gap word can cross: "I'm not okay, I'll kill myself" is not negated.
#: None of them vetoes a negation the sentence then takes back (`_TAKEN_BACK`).
NEGATION_GUARDS: tuple[str, ...] = (
    # "I'm not suicidal", "I would never(, ever) kill myself" say the opposite
    # (up to two words between the negation and the phrase, same clause; an
    # `_ASIDE` right after the negation is crossed, and so is ", ever"; a
    # bare comma is not: "not, want to kill myself" is two clauses).
    # "so" joins clauses, so it is no gap word, except as "not so (much)"
    # right after the negation ("I'm not so suicidal anymore").
    rf"{_NOT_DOUBLED}{_NEGATION}{_NEVER_SAYS_MORE}(?! {_INTRODUCES})(?:{_ASIDE})?(?: ,? ever)?"
    rf"(?! {_INTRODUCES})(?: so(?: much)?)?(?: {_GAP_WORD}){{0,2}} {_NEGATED}{_TAKEN_BACK}",
    # A hedge about one's own STATE: "I don't think I'm suicidal", "I'm not
    # thinking I'm suicidal", "I don't (really) feel like / feel that / think
    # that I'm suicidal". Never about an act or a plan ("I don't think I'll
    # kill myself tonight"), and never "not saying"/"don't mean" ("I'm not
    # saying I'll kill myself" is a warning sign). A contraction reads like
    # its spelled-out form.
    # A filler and its comma right after the negation (or after an `_ASIDE`),
    # then the state word itself: "I'm not like, suicidal", "I'm not even,
    # like, suicidal", "I'm not, like, really, suicidal". Only "suicidal",
    # straight after the comma: an act or any other word there can start a
    # clause of its own ("Not really, kill myself", "not really, want to").
    rf"{_NOT_DOUBLED}{_NEGATION}(?:{_ASIDE})?(?:(?: {_FILLER}){{1,2}} ,){{1,2}} {_SUICIDAL}{_TAKEN_BACK}",
    rf"{_NOT_DOUBLED}{_NEGATION}(?: really)? (?:think|thinking|believe|guess|feel|feeling)"
    rf"(?: like| that)? (?:im|i am|i was|ive been|i have been) {_SUICIDAL}{_TAKEN_BACK}",
    rf"{_NOT_DOUBLED}(?:dont|do not|didnt|did not|never|wont|will not|dont really){_NEVER_SAYS_MORE}"
    rf" (?:want(?:ed)?|wanna|wish(?:ed)?) (?:to |2 )?(?:die|be dead){_TAKEN_BACK}",
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
    # Someone else's wish, asked about: "Why does Hamlet want to die?". The
    # someone is never the speaker: "I can't DO this anymore I want to die".
    # Nor is it "do not" / "did not": that is the negation NEGATION_GUARDS
    # reads ("I do not want to die" stays vetoed there), which a sentence
    # can take back ("... but I'm going to").
    r"(?:does|did(?! not)|do(?! not)|doesnt|didnt|would|wouldnt|why would|why does|why did|why do"
    r"|why dont)"
    r"(?: (?!(?:i|im|id|ive|you|u|we)(?![a-z0-9]))[a-z]+){1,3} (?:want|wanna|wanted|wish|wished)"
    r" (?:to |2 )?die",
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
    # sec2 M11: the other languages' negations and idioms ("no quiero morir",
    # "me muero de risa", "je vais me tuer à la tâche", "morrer de rir").
    r"no (?:me )?(?:quiero|quisiera|deseo) morir(?:me)?",
    r"no (?:quiero|voy a|pienso|planeo) (?:matarme|suicidarme|quitarme la vida|cortarme|hacerme dano"
    r"|lastimarme|autolesionarme)",
    r"no me (?:quiero|voy a) (?:matar|suicidar)",
    r"morir(?:me)? de (?:risa|verguenza|hambre|sueno|calor|frio|aburrimiento|envidia|ganas|amor|pena"
    r"|miedo|celos)",
    r"(?:matarme|matar) (?:estudiando|trabajando|a estudiar|de risa)",
    r"mourir de (?:rire|faim|froid|honte|ennui|peur|chaud|envie)",
    r"me tuer (?:a la tache|au travail|a reviser|a travailler)",
    r"nao (?:quero|queria) morrer",
    r"nao (?:vou|quero|penso em) (?:me matar|me suicidar|me cortar|me machucar)",
    r"morrer de (?:rir|vergonha|fome|sono|medo|tedio|calor|frio|saudade|inveja)",
    r"me matar de (?:estudar|rir|trabalhar)",
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
#: Two or more dots on their own (NFKD has already spelled "…" out as "...").
#: Every pattern reads it as a sentence break; the clause form keeps it as
#: `_TRAIL` so `_TAKEN_BACK` can tell a trailing-off from a full stop.
_ELLIPSIS = re.compile(r"(?<![.!?;:\n\r])\.{2,}(?![.!?;:\n\r])")
#: Clause punctuation inside a sentence: a comma, a dash between words, a
#: bracket. Only the negation guards see it (as a `,` token); every other
#: pattern reads it as a space, exactly as before.
_CLAUSE_BREAK = re.compile(r"(?:[,()\[\]{}–—]|(?<!\S)-+(?!\S))+")
_CLAUSE = ","
_NON_WORD = re.compile(rf"[^a-z0-9|,{_TRAIL}]+")
_REPEATED_LETTER = re.compile(r"([a-z])\1{2,}")


@dataclass(frozen=True)
class _Forms:
    """`text` is `normalize`'s form. `clause` is the same with a `,` token at
    each clause break and a `_TRAIL` token (in place of `|`) at each ellipsis;
    `commas` are the `,` tokens' offsets in `clause`, which map a `clause`
    offset back onto `text`."""

    text: str
    clause: str
    commas: tuple[int, ...]

    def from_clause(self, index: int) -> int:
        # Each `,` token before `index` added two characters (it and a space).
        return index - 2 * bisect_left(self.commas, index)


def _forms(text: str) -> _Forms:
    # sec2 M11: Cyrillic/Greek look-alikes and invisible characters out first
    # (services/text_fold.py, shared with the share screen).
    text = fold_confusables(strip_invisible(text[:MAX_SCREEN_CHARS]))
    folded = unicodedata.normalize("NFKD", text).casefold()
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = _INVISIBLE.sub("", folded)
    folded = _APOSTROPHES.sub("", folded)
    folded = _ELLIPSIS.sub(f" {_TRAIL} ", folded)
    folded = _SENTENCE_BREAK.sub(" | ", folded)
    folded = _CLAUSE_BREAK.sub(f" {_CLAUSE} ", folded)
    folded = _NON_WORD.sub(" ", folded)
    folded = _REPEATED_LETTER.sub(r"\1", folded)
    tokens = folded.split()
    clause = " ".join(tokens)
    commas: list[int] = []
    offset = 0
    for token in tokens:
        if token == _CLAUSE:
            commas.append(offset)
        offset += len(token) + 1
    norm = " ".join("|" if t == _TRAIL else t for t in tokens if t != _CLAUSE)
    return _Forms(text=norm, clause=clause, commas=tuple(commas))


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
_CJK = tuple((p, re.compile(p.pattern)) for p in sorted(
    CJK_EXPLICIT, key=lambda p: CATEGORIES.index(p.category)))
_HAS_CJK = re.compile("[㐀-鿿豈-﫿]")


def _guarded(span: tuple[int, int], guards: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(g_start < end and start < g_end for g_start, g_end in guards)


def detect(text: str | None) -> CrisisMatch | None:
    """The most severe crisis phrase in `text`, or None. Never raises on str.

    Read as written first; then, only if nothing matched and the text has
    leetspeak in it ("k1ll mys3lf"), once more with that folded
    (`text_fold.fold_leet`, which leaves "988" and "2 + 2" alone). Reading
    the plain text first keeps every answer the plain text had.
    """
    if not text or not text.strip():
        return None
    found = _detect(text)
    if found is None:
        folded = fold_leet(text[:MAX_SCREEN_CHARS])
        if folded != text[:MAX_SCREEN_CHARS]:
            found = _detect(folded)
    return found


def _cjk(text: str) -> CrisisMatch | None:
    """`CJK_EXPLICIT` over the NFKC text (the normalized form has no CJK)."""
    if not _HAS_CJK.search(text):
        return None
    raw = unicodedata.normalize("NFKC", strip_invisible(text[:MAX_SCREEN_CHARS])).casefold()
    for phrase, regex in _CJK:
        if regex.search(raw):
            return CrisisMatch(phrase.category, "explicit", phrase.label)
    return None


def _detect(text: str) -> CrisisMatch | None:
    forms = _forms(text)
    norm = forms.text
    if not norm:
        return _cjk(text)
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

    for phrase, regex in _EXPLICIT:
        for m in regex.finditer(norm):
            if not guarded(m.span()):
                return CrisisMatch(phrase.category, "explicit", phrase.label)
    if (cjk := _cjk(text)) is not None:
        return cjk
    topic = None  # likewise: a TOPIC_GUARD is read only for a candidate mention
    for phrase, regex in _MENTIONS:
        for m in regex.finditer(norm):
            if guarded(m.span()):
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


def detect_any(texts: Iterable[str | None]) -> CrisisMatch | None:
    """The most severe match across several fields of one request."""
    found = [m for m in map(detect, texts) if m is not None]
    if not found:
        return None
    return min(found, key=lambda m: CATEGORIES.index(m.category))
