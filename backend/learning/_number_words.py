"""English number words as data, for learning/leak.py's strict mode (A38 fix
round, m7): the grader hint's leak check reads "seven", "one hundred and
five", "three quarters" or "fifty percent" as the values they write. Data
only (the PKG-06 modules hold no numeral but 0 / 1); no imports, no I/O."""

UNITS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
}
TEN = 10
TENS = {
    word: TEN * value
    for value, word in enumerate(
        "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
    )
    if word != "_"
}
HUNDRED = 100
SCALES = {"hundred": HUNDRED, "thousand": 1_000, "million": 1_000_000}
DENOMINATORS = {
    "half": 2,
    "halves": 2,
    "quarter": 4,
    "quarters": 4,
    "third": 3,
    "thirds": 3,
    "fourth": 4,
    "fourths": 4,
    "fifth": 5,
    "fifths": 5,
    "sixth": 6,
    "sixths": 6,
    "seventh": 7,
    "sevenths": 7,
    "eighth": 8,
    "eighths": 8,
    "ninth": 9,
    "ninths": 9,
    "tenth": 10,
    "tenths": 10,
    "hundredth": 100,
    "hundredths": 100,
}
HALF_WORDS = frozenset({"half", "halves"})
PERCENT_WORDS = frozenset({"percent", "pct"})
PERCENT = 100  # "50%" is 50 / PERCENT
