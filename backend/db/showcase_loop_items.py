"""Showcase check items for the CS101 demo course (the learning loop).

The rich local seed (db/seed_local_rich.py) fills the loop's check items with
the E2E placeholder constants ("[e2e-loop] Check item: type the e2e grader's
correct token…"), because the deterministic Chapter 1 journeys type the
grader's token and assert on those strings. A person demoing the tutor with
REAL models sees those placeholders as nonsense questions. This module is the
hand-written replacement: a real, correct item bank for every CS101 concept the
rich seed puts on a graph, applied by `python -m db.seed_showcase_loop` and
never by an E2E lane.

Pure data. It imports learning.checks only (no services, no SDK), so the
content can be validated by a unit test without a database
(tests/test_seed_showcase_loop.py runs every draft through the drafting path's
own repair, validation and item lint).

Shape. One draft per (concept, format, difficulty) — the bank the drafting
agent writes for a concept (CHECK_ITEM_INITIAL_PER_CONCEPT = 3 formats x 3
difficulties), so the post-test keeps its two reserves (learning.checks::
posttest_reserve_hashes: the free item at difficulty 2, then its parallel
form) and the probe still has at least PROBE_ITEMS_PER_SKILL_MIN items beside
them. Every reference ends with "Final answer: <final_answer>." (A34), every
free and teachback item names its common wrong reasons, and every mc_reason
distractor carries its own misconception key (A37). Each concept's passage is
the course-notes chunk the items cite, so the H2 rung has real text to show.
"""

from __future__ import annotations

from learning.checks import CheckItemDraft, OptionDraft

FREE = "free"
TEACHBACK = "teachback"
MC_REASON = "mc_reason"

# ── concepts and their course-notes passages ────────────────────────────────
#
# (concept name exactly as the rich seed's graph_nodes carry it, passage). The
# first three are the loop users' prerequisite chain (seed_local_rich.
# LOOP_NODES); the other five are rich-user-active's CS101 graph
# (seed_local_rich._GRAPH_NODES). Items are course assets keyed on the
# concept's normalized name, so one bank serves every CS101 student whose
# graph has the concept.

PASSAGES: dict[str, str] = {
    "Binary Numbers": (
        "A binary number writes a value in base two: each place holds a bit, 0 or 1, "
        "and each place is worth twice the place to its right, so from the right the "
        "places are worth 1, 2, 4, 8, 16 and so on. To read a binary number, add the "
        "place values of its 1 bits: 1101 is 8 + 4 + 1 = 13. To write a decimal number "
        "in binary, divide it by two repeatedly and read the remainders from the last "
        "one to the first. With n bits there are 2^n patterns, covering 0 to 2^n - 1, "
        "so a byte (8 bits) holds 0 through 255. A fixed-width number that grows past "
        "its largest value loses the carry out of its top bit and wraps around."
    ),
    "Bitwise Operators": (
        "Bitwise operators combine two numbers bit by bit, place by place. AND (&) "
        "gives 1 only where both bits are 1; OR (|) gives 1 where at least one bit is "
        "1; XOR (^) gives 1 where the two bits differ; NOT (~) flips every bit. Shifts "
        "move every bit at once: x << k moves the bits k places left, multiplying a "
        "non-negative value by 2^k, and x >> k moves them k places right, dividing by "
        "2^k and dropping the bits that fall off the end. A mask is a number chosen "
        "to pick out bits: x & 1 is 1 exactly when x is odd, OR with a mask sets the "
        "mask's bits, and AND with a mask keeps only the mask's bits."
    ),
    "Two's Complement": (
        "Two's complement is how computers store signed integers. In an n-bit number "
        "the leftmost bit carries a negative weight, -2^(n-1), and every other bit its "
        "usual positive weight, so a 1 in the leftmost bit means the value is below "
        "zero. To negate a number, invert every bit and then add one: in 8 bits, 6 is "
        "00000110 and -6 is 11111010. An n-bit two's complement integer ranges from "
        "-2^(n-1) to 2^(n-1) - 1, so 8 bits hold -128 through 127, and a sum past 127 "
        "wraps around to the negative end. Zero has a single pattern, and ordinary "
        "binary addition gives the right signed result, which is why hardware uses it "
        "instead of a separate sign bit."
    ),
    "Variables and Types": (
        "A variable is a name bound to a value: the assignment x = 5 stores 5 under the "
        "name x, and a later assignment replaces it. Assignment happens once, when the "
        "line runs; it is not an equation that stays true. Every value has a type that "
        "decides which operations make sense: int for whole numbers, float for numbers "
        "with a fractional part, str for text and bool for True and False. In Python "
        "7 / 2 is 3.5, a float, while 7 // 2 is 3, the floor of the quotient. The + "
        "operator adds numbers but joins strings, so '3' + '4' is '34'. input() always "
        "returns a str, and conversions are explicit: int('42') is the number 42, and "
        "int(3.9) is 3 because int() drops the fractional part. Floats are stored in "
        "binary, so most decimal fractions are approximations: 0.1 + 0.2 is "
        "0.30000000000000004, and floats are compared with a tolerance such as "
        "math.isclose rather than with ==."
    ),
    "Control Flow": (
        "Control flow is the order in which statements run. An if/elif/else chain tests "
        "its conditions from top to bottom and runs only the first branch whose "
        "condition is true; the else branch runs only when none was. A while loop "
        "repeats its body as long as its condition stays true, so something in the body "
        "must eventually make the condition false. A for loop runs its body once per "
        "item: for i in range(a, b) gives i the values a, a + 1, ..., b - 1, and "
        "range(n) starts at 0, so it runs n times. Inside a loop, break leaves the loop "
        "at once and continue skips the rest of the body and moves on to the next "
        "iteration."
    ),
    "Recursion": (
        "A recursive function solves a problem by calling itself on a smaller version "
        "of the same problem. Every recursive function needs a base case, an input it "
        "answers directly without calling itself, and every recursive call must move "
        "closer to that base case; otherwise the calls never stop, and Python raises "
        "RecursionError when the call stack runs out of room. Each call gets its own "
        "frame on the call stack holding its own local variables, and the frames are "
        "removed in reverse order as the calls return, the deepest call first. "
        "factorial(n) = n * factorial(n - 1) with factorial(0) = 1 is the classic "
        "example; a list can be summed the same way, with the empty list as the base "
        "case."
    ),
    "Pointers and Memory": (
        "A program's data lives in memory, and every value has an address. A pointer "
        "(in C) or a reference (in Python) holds the address of a value rather than the "
        "value itself. In C, &x gives the address of x, and *p reads or writes the value "
        "at the address p holds; dereferencing a pointer that holds no valid address, "
        "such as NULL, is undefined behaviour and usually crashes the program. In Python "
        "every variable is a reference: after b = a both names refer to the same "
        "object, so changing a mutable object such as a list through b is visible "
        "through a, while rebinding b to a new object leaves a alone. Memory a program "
        "allocated and can no longer reach, but never released, is a leak: in C every "
        "malloc() needs a matching free(), while Python's garbage collector reclaims "
        "objects that nothing references."
    ),
    "Algorithms": (
        "An algorithm is a finite sequence of precise steps that solves a problem. "
        "Algorithms are compared by how their running time grows with the input size "
        "n, written in Big-O notation, which ignores constant factors. Linear search "
        "checks the items one by one and takes O(n) steps in the worst case. Binary "
        "search works only on a sorted list: it compares the target with the middle "
        "item and discards the half that cannot hold it, so it takes O(log n) steps, "
        "about 20 comparisons for a million items. Simple sorts such as selection sort "
        "take O(n^2) steps, so doubling the input quadruples the time, while merge sort "
        "takes O(n log n). Sorting once pays off when the same list is searched many "
        "times."
    ),
}

#: The concepts in bank order (the dict's order).
CONCEPTS: tuple[str, ...] = tuple(PASSAGES)


def passage_text(concept: str) -> str:
    """The course-notes chunk a concept's items cite: '<concept>. <passage>',
    the shape the rich seed's loop document uses."""
    return f"{concept}. {PASSAGES[concept]}"


# ── builders ────────────────────────────────────────────────────────────────


def _reference(body: str, final: str) -> str:
    """A34: the model answer closes with 'Final answer: <final_answer>.'."""
    return f"{body} Final answer: {final}."


def _open(
    fmt: str,
    concept: str,
    difficulty: int,
    prompt: str,
    body: str,
    final: str,
    rubric: list[str],
    wrong: list[tuple[str, str]],
    *,
    numeric: str = "",
) -> CheckItemDraft:
    """A free or teachback draft. `wrong` pairs each common wrong reason's
    snake_case key with its sentence; `numeric` is the canonical value of an
    item whose whole answer is one number."""
    return CheckItemDraft(
        concept=concept,
        format=fmt,
        difficulty=difficulty,
        prompt=prompt,
        reference_answer=_reference(body, final),
        final_answer=final,
        rubric=rubric,
        wrong_keys=[key for key, _ in wrong],
        wrong_texts=[text for _, text in wrong],
        answer_kind="numeric" if numeric else "free",
        canonical_answer=numeric,
    )


def _free(*args, **kwargs) -> CheckItemDraft:
    return _open(FREE, *args, **kwargs)


def _teach(*args, **kwargs) -> CheckItemDraft:
    return _open(TEACHBACK, *args, **kwargs)


def _mc(
    concept: str,
    difficulty: int,
    prompt: str,
    body: str,
    correct: str,
    distractors: list[tuple[str, str, str]],
    rubric: list[str],
) -> CheckItemDraft:
    """An mc_reason draft: the correct option's text (also the final answer),
    then each distractor as (text, misconception_key, misconception_text).
    Code letters the options and places the correct one at write time (A37)."""
    options = [OptionDraft(text=correct, is_correct=True)] + [
        OptionDraft(text=text, is_correct=False, misconception_key=key, misconception_text=why)
        for text, key, why in distractors
    ]
    return CheckItemDraft(
        concept=concept,
        format=MC_REASON,
        difficulty=difficulty,
        prompt=prompt,
        options=options,
        reference_answer=_reference(body, correct),
        final_answer=correct,
        rubric=rubric,
    )


# ── the bank ────────────────────────────────────────────────────────────────

_BINARY = "Binary Numbers"
_BITWISE = "Bitwise Operators"
_TWOS = "Two's Complement"
_VARS = "Variables and Types"
_FLOW = "Control Flow"
_REC = "Recursion"
_PTR = "Pointers and Memory"
_ALGO = "Algorithms"

DRAFTS: tuple[CheckItemDraft, ...] = (
    # ── Binary Numbers ──────────────────────────────────────────────────────
    _free(
        _BINARY,
        1,
        "What decimal value does the binary number 1011 represent?",
        "Reading from the right, the places are worth 1, 2, 4 and 8. The 1 bits sit "
        "in the 8, 2 and 1 places, so the value is 8 + 2 + 1.",
        "11",
        [
            "Uses place values that double from the right (1, 2, 4, 8).",
            "Adds the place values of the 1 bits to reach the decimal value.",
        ],
        [
            (
                "reads_binary_as_decimal",
                "Reads the digits as a decimal numeral instead of as powers of two.",
            ),
            (
                "reverses_place_values",
                "Gives the leftmost bit the smallest place value, reading the number backwards.",
            ),
        ],
        numeric="11",
    ),
    _free(
        _BINARY,
        2,
        "Convert the decimal number 37 to binary, written without leading zeros.",
        "Dividing by two repeatedly gives 37 -> 18 remainder 1, 18 -> 9 remainder 0, "
        "9 -> 4 remainder 1, 4 -> 2 remainder 0, 2 -> 1 remainder 0 and 1 -> 0 "
        "remainder 1. Reading the remainders from the last one to the first gives the "
        "bits, and the check 32 + 4 + 1 = 37 confirms them.",
        "100101",
        [
            "Uses repeated division by two (or subtracts powers of two: 32, 4, 1).",
            "Reads the remainders from the last one to the first.",
            "Gives the six-bit result for 37.",
        ],
        [
            (
                "reads_remainders_in_order",
                "Writes the remainders in the order they were produced, which reverses the bits.",
            ),
            (
                "drops_zero_places",
                "Leaves out the 0 bits of the empty places and writes only the 1s.",
            ),
        ],
    ),
    _free(
        _BINARY,
        3,
        "A sensor reports each reading as an unsigned 6-bit binary number. What is "
        "the largest reading it can report, in decimal?",
        "Six bits give 2^6 = 64 different patterns. Counting starts at 0 (000000), so "
        "the largest pattern, 111111, is 32 + 16 + 8 + 4 + 2 + 1.",
        "63",
        [
            "States that 6 bits give 2^6 = 64 patterns.",
            "Explains that one pattern is zero, so the largest value is one less than 64.",
        ],
        [
            (
                "forgets_zero_counts",
                "Answers with the number of patterns, forgetting that one of them stands for zero.",
            ),
            (
                "bits_times_two",
                "Multiplies the number of bits by two instead of raising two to that power.",
            ),
        ],
        numeric="63",
    ),
    _teach(
        _BINARY,
        1,
        "Explain to a classmate who missed the lecture what each digit position in a "
        "binary number is worth.",
        "In binary every digit is a bit, either 0 or 1. The rightmost place is worth "
        "1, the next one 2, then 4, 8, 16 and so on. The value of the number is the "
        "sum of the places that hold a 1, so 101 is 4 + 1 = 5.",
        "Each place is worth twice the place to its right, starting at 1",
        [
            "States that the rightmost place is worth 1.",
            "States that each place to the left doubles in value (1, 2, 4, 8, ...).",
            "Explains that the value is the sum of the places holding a 1.",
        ],
        [
            (
                "places_worth_ten",
                "Says the digit positions grow by a factor of ten, as in decimal.",
            ),
            ("places_increase_by_one", "Says the places are worth 1, 2, 3, 4 instead of doubling."),
        ],
    ),
    _teach(
        _BINARY,
        2,
        "Explain to a classmate who missed the lecture how to convert a decimal number "
        "such as 13 into binary.",
        "Divide the number by two and write down the remainder, then keep dividing the "
        "quotient until it reaches 0. For 13: 13 -> 6 remainder 1, 6 -> 3 remainder 0, "
        "3 -> 1 remainder 1, 1 -> 0 remainder 1. Reading the remainders backwards gives "
        "1101, and 8 + 4 + 1 = 13 checks it.",
        "Divide by two repeatedly and read the remainders from last to first",
        [
            "Describes dividing by two repeatedly and keeping the remainders.",
            "Says the remainders are read from the last one to the first.",
            "Works an example correctly or checks the result by adding place values.",
        ],
        [
            (
                "reads_remainders_in_order",
                "Writes the remainders in the order they were produced, which reverses the bits.",
            ),
            ("divides_by_ten", "Divides by ten as in decimal, so the digits never become bits."),
        ],
    ),
    _teach(
        _BINARY,
        3,
        "Explain to a classmate who missed the lecture why a byte, which has 8 bits, "
        "has 256 different patterns but its largest unsigned value is 255.",
        "Each extra bit doubles the number of patterns: 1 bit gives 2, 2 bits give 4, "
        "and 8 bits give 2^8 = 256. The smallest pattern, 00000000, stands for 0, so "
        "the 256 patterns cover 0 through 255 and the largest, 11111111, is 255.",
        "Zero takes one of the 256 patterns",
        [
            "States that n bits give 2^n patterns, 256 for 8 bits.",
            "Explains that one pattern represents zero, so the top value is 255.",
        ],
        [
            (
                "values_start_at_one",
                "Thinks the values run from 1 to 256, as if counting started at one.",
            ),
            (
                "bits_add_linearly",
                "Thinks each extra bit adds a fixed number of values instead of doubling them.",
            ),
        ],
    ),
    _mc(
        _BINARY,
        1,
        "In the binary number 10010, how much is the leftmost 1 worth?",
        "Counting from the right, the places of 10010 are worth 1, 2, 4, 8 and 16. The "
        "leftmost 1 sits in the fifth place, which is 2^4.",
        "16",
        [
            (
                "32",
                "counts_places_from_one",
                "Numbers the places from 1 instead of 0, so the fifth place is taken as 2^5.",
            ),
            (
                "5",
                "uses_position_number",
                "Gives the bit's position number rather than its place value.",
            ),
            ("1", "reads_bit_value", "Gives the bit's own value without its place value."),
        ],
        [
            "Locates the leftmost 1 in the fifth place from the right.",
            "Explains that the places double from 1, so the fifth is worth 2^4.",
        ],
    ),
    _mc(
        _BINARY,
        2,
        "Which decimal number is written 110110 in binary?",
        "The 1 bits of 110110 sit in the 32, 16, 4 and 2 places, so the value is 32 + 16 + 4 + 2.",
        "54",
        [
            (
                "27",
                "reverses_place_values",
                "Gives the leftmost bit the smallest place value, reading the number backwards.",
            ),
            (
                "108",
                "counts_places_from_one",
                "Numbers the places from 1 instead of 0, so every place value is doubled.",
            ),
            (
                "4",
                "counts_ones",
                "Counts how many bits are 1 instead of adding their place values.",
            ),
        ],
        [
            "Names the place values of the 1 bits (32, 16, 4 and 2).",
            "Adds those place values to reach the decimal value.",
        ],
    ),
    _mc(
        _BINARY,
        3,
        "A program keeps a counter in exactly 4 bits. The counter holds 1111 and the "
        "program adds 1. What does the counter hold afterwards?",
        "1111 is 15, the largest 4-bit value. Adding 1 gives 16, which is 10000 and "
        "needs five bits. Only the low 4 bits are kept, so the carry out of the top "
        "bit is lost and the counter wraps around.",
        "0000",
        [
            (
                "10000",
                "ignores_bit_width",
                "Keeps the carry as a fifth bit, ignoring that only 4 bits are stored.",
            ),
            (
                "1111",
                "saturates_at_max",
                "Thinks a full counter simply stays at its largest value.",
            ),
            (
                "1000",
                "carry_into_top_bit",
                "Keeps the carry inside the 4 bits by moving it into the leftmost place.",
            ),
        ],
        [
            "States that 1111 + 1 is 10000, which needs five bits.",
            "Explains that only the low 4 bits are kept, so the carry is lost.",
        ],
    ),
    # ── Bitwise Operators ───────────────────────────────────────────────────
    _free(
        _BITWISE,
        1,
        "What is the 4-bit result of 1100 AND 1010, computed bit by bit?",
        "AND gives 1 only in the places where both numbers have a 1. Place by place "
        "from the left: 1 and 1 give 1, 1 and 0 give 0, 0 and 1 give 0, 0 and 0 give 0.",
        "1000",
        [
            "Combines the numbers place by place.",
            "Gives 1 only where both bits are 1.",
        ],
        [
            ("and_as_or", "Treats AND like OR, giving 1 where either bit is 1."),
            (
                "adds_numbers",
                "Adds the two numbers in binary instead of combining them place by place.",
            ),
        ],
    ),
    _free(
        _BITWISE,
        2,
        "A program tests whether an integer x is odd with the expression x & 1. What "
        "does x & 1 evaluate to when x is 22?",
        "22 is 10110 in binary. Masking with 1 keeps only the lowest bit, and the "
        "lowest bit of an even number is 0.",
        "0",
        [
            "Writes 22 in binary or notes that its lowest bit decides the result.",
            "Explains that & 1 keeps only the lowest bit.",
        ],
        [
            (
                "mask_keeps_value",
                "Thinks the mask returns the whole value of x instead of only its lowest bit.",
            ),
            (
                "and_as_logical",
                "Treats & as a logical and that is true whenever both sides are nonzero.",
            ),
        ],
        numeric="0",
    ),
    _free(
        _BITWISE,
        3,
        "Without using *, write an expression with a single bitwise operator that "
        "computes x times 8 for a non-negative integer x.",
        "Shifting left by one place doubles a non-negative value, so shifting by three "
        "places doubles it three times, and 2 * 2 * 2 is 8.",
        "x << 3",
        [
            "Uses a left shift.",
            "Explains that each place of shift doubles the value, so three places multiply by 8.",
        ],
        [
            (
                "shifts_by_multiplier",
                "Shifts by the multiplier itself instead of by its power of two.",
            ),
            (
                "shifts_right",
                "Uses a right shift, which divides by a power of two instead of multiplying.",
            ),
        ],
    ),
    _teach(
        _BITWISE,
        1,
        "Explain to a classmate who missed the lecture the difference between bitwise "
        "AND and bitwise OR.",
        "Both work on two numbers place by place. AND puts a 1 in a place only when "
        "both numbers have a 1 there, so 1100 AND 1010 is 1000. OR puts a 1 where at "
        "least one of them has a 1, so 1100 OR 1010 is 1110.",
        "AND needs both bits to be 1; OR needs at least one",
        [
            "States that AND gives 1 only where both bits are 1.",
            "States that OR gives 1 where at least one bit is 1.",
            "Notes that both operators work place by place on the bits.",
        ],
        [
            ("or_as_exclusive", "Says OR gives 0 when both bits are 1, confusing it with XOR."),
            (
                "logical_not_bitwise",
                "Describes them as true/false tests on whole numbers rather than operations on each bit.",
            ),
        ],
    ),
    _teach(
        _BITWISE,
        2,
        "Explain to a classmate who missed the lecture how a mask and the & operator "
        "can test whether the 4s place of a number holds a 1.",
        "A mask is a number with 1s only in the places you care about. The 4s place on "
        "its own is 100 in binary, which is 4. ANDing the number with 4 clears every "
        "other place, so the result is 4 when that bit is 1 and 0 when it is not; for "
        "example 13 & 4 is 4 but 9 & 4 is 0.",
        "AND the number with the mask 4; a nonzero result means the bit is set",
        [
            "Describes a mask with a 1 only in the 4s place (the value 4, or 100 in binary).",
            "Explains that AND clears every other bit.",
            "States that a nonzero result means the bit is set and zero means it is not.",
        ],
        [
            ("mask_with_or", "Uses OR with the mask, which sets the bit instead of testing it."),
            (
                "mask_is_position",
                "Uses the position number 2 as the mask instead of the place value 4.",
            ),
        ],
    ),
    _teach(
        _BITWISE,
        3,
        "Explain to a classmate who missed the lecture why x >> 1 halves a non-negative "
        "integer x, and what happens when x is odd.",
        "Shifting right moves every bit one place toward the low end, and each place is "
        "worth half the one to its left, so every bit's contribution halves. The lowest "
        "bit falls off the end: for an odd number that bit was the 1, so the result is "
        "rounded down, and 7 >> 1 is 3.",
        "Each bit moves to a place worth half as much; an odd x loses its lowest bit and rounds down",
        [
            "Explains that each bit moves to a place worth half as much.",
            "States that the lowest bit is dropped.",
            "Concludes that an odd number is rounded down, with a correct example.",
        ],
        [
            ("shift_rounds_up", "Thinks an odd number is rounded up when shifted right."),
            (
                "shift_direction_swapped",
                "Thinks >> moves the bits toward the high places, doubling the value.",
            ),
        ],
    ),
    _mc(
        _BITWISE,
        1,
        "What is the bitwise XOR of 0110 and 0101?",
        "XOR gives 1 in each place where the two bits differ. Place by place from the "
        "left: 0 and 0 give 0, 1 and 1 give 0, 1 and 0 give 1, 0 and 1 give 1.",
        "0011",
        [
            ("0100", "xor_as_and", "Computes AND, keeping only the places where both bits are 1."),
            ("0111", "xor_as_or", "Computes OR, giving 1 wherever either bit is 1."),
            (
                "1011",
                "adds_numbers",
                "Adds the two numbers instead of comparing their bits place by place.",
            ),
        ],
        [
            "Compares the two numbers place by place.",
            "Gives 1 exactly where the bits differ.",
        ],
    ),
    _mc(
        _BITWISE,
        2,
        "A permissions value p uses bit 0 for read, bit 1 for write and bit 2 for "
        "execute. Which operation turns write on and leaves the other bits of p "
        "unchanged?",
        "Write is bit 1, the 2s place, so the mask is 010. ORing with a mask sets the "
        "mask's bits to 1 and leaves every other bit as it was, whether write was "
        "already on or not.",
        "OR with the mask 010",
        [
            (
                "AND with the mask 010",
                "and_to_set",
                "Thinks AND sets the bits in the mask, but it clears every bit the mask leaves out.",
            ),
            (
                "XOR with the mask 010",
                "xor_to_set",
                "Uses XOR, which turns write off again when it was already on.",
            ),
            (
                "AND with the mask 101",
                "clear_for_set",
                "Uses the clearing idiom, an inverted mask with AND, which turns write off.",
            ),
        ],
        [
            "Identifies the mask for bit 1 as 010 (the value 2).",
            "Explains that the chosen operation sets that bit whatever it was and leaves the other bits unchanged.",
        ],
    ),
    _mc(
        _BITWISE,
        3,
        "For a non-negative integer x, which expression always equals x % 8, the "
        "remainder when x is divided by 8?",
        "8 is 1000 in binary, so the remainder is whatever the lowest three bits of x "
        "hold. 7 is 0111, and AND with it keeps exactly those three bits and clears the "
        "rest.",
        "x & 7",
        [
            (
                "x & 8",
                "mask_equals_divisor",
                "Uses the divisor itself as the mask instead of one less than it.",
            ),
            (
                "x >> 3",
                "shift_gives_remainder",
                "Thinks shifting right by three gives the remainder, but it gives the quotient.",
            ),
            (
                "(x >> 3) << 3",
                "clears_low_bits",
                "Clears the low three bits, which leaves the largest multiple of 8 instead of the remainder.",
            ),
        ],
        [
            "Explains that the remainder by 8 is held in the lowest three bits.",
            "Explains that the mask 7 (0111) keeps those bits and clears the rest.",
        ],
    ),
    # ── Two's Complement ────────────────────────────────────────────────────
    _free(
        _TWOS,
        1,
        "In an 8-bit two's complement integer, what does a 1 in the leftmost bit tell "
        "you about the value?",
        "The leftmost bit carries a negative weight, -128 in 8 bits, which outweighs "
        "all the other bits together (at most 127). So whenever it is 1 the total is "
        "below zero.",
        "The value is negative",
        [
            "States that the leftmost bit has a negative weight (-128 in 8 bits).",
            "Concludes that a 1 there means the value is below zero.",
        ],
        [
            (
                "leftmost_bit_positive",
                "Treats the leftmost bit as the largest positive place, worth +128.",
            ),
            (
                "sign_bit_only",
                "Thinks the leftmost bit is only a minus sign and the other bits give the size directly.",
            ),
        ],
    ),
    _free(
        _TWOS,
        2,
        "Write -5 as an 8-bit two's complement number.",
        "5 is 00000101. Inverting every bit gives 11111010, and adding one gives the "
        "pattern for -5.",
        "11111011",
        [
            "Starts from 5 written in 8 bits.",
            "Inverts every bit and then adds one.",
        ],
        [
            (
                "invert_only",
                "Inverts the bits but forgets to add one, which gives the ones' complement.",
            ),
            (
                "sign_magnitude",
                "Sets only the leftmost bit to 1 and keeps the bits of 5, as in sign-and-magnitude.",
            ),
        ],
    ),
    _free(
        _TWOS,
        3,
        "In 8-bit two's complement, what value do you get when you add 1 to 127 and "
        "keep only 8 bits?",
        "127 is 01111111. Adding 1 carries all the way into the leftmost bit and gives "
        "10000000. That bit is worth -128 and every other bit is 0.",
        "-128",
        [
            "Writes 127 as 01111111 and the sum as 10000000.",
            "Reads 10000000 with the leftmost bit's negative weight.",
        ],
        [
            ("ignores_overflow", "Expects the sum to stay positive, as if 8 bits could hold it."),
            (
                "error_on_overflow",
                "Thinks the hardware stops with an error instead of wrapping around.",
            ),
        ],
        numeric="-128",
    ),
    _teach(
        _TWOS,
        1,
        "Explain to a classmate who missed the lecture how to find the two's complement "
        "negative of a number.",
        "Take the number's bits, flip every one of them, and add one to the result. For "
        "example, in 4 bits 6 is 0110; flipping gives 1001, and adding one gives 1010, "
        "which is -6. Doing the same to 1010 gets back to 0110.",
        "Invert every bit, then add one",
        [
            "Says to invert (flip) every bit.",
            "Says to add one after inverting.",
            "Gives or checks a correct example.",
        ],
        [
            (
                "invert_only",
                "Stops after flipping the bits, which gives the ones' complement and is off by one.",
            ),
            (
                "add_then_invert",
                "Adds one before flipping the bits, which gives a different pattern.",
            ),
        ],
    ),
    _teach(
        _TWOS,
        2,
        "Explain to a classmate who missed the lecture why an 8-bit two's complement "
        "integer can hold -128 but not +128.",
        "Eight bits give 256 patterns. The 128 patterns with a 1 in the leftmost bit "
        "are negative, and 10000000, where that bit alone is set, is -128. The other "
        "128 patterns start with 0, and one of them is zero, so they cover only 0 "
        "through 127.",
        "The leftmost bit is worth -128, so the largest positive value is 127",
        [
            "States that the leftmost bit is worth -128, so 10000000 is -128.",
            "Explains that zero uses one of the non-negative patterns, so the top is 127.",
        ],
        [
            ("symmetric_range", "Thinks the range is symmetric, running from -127 to +127."),
            ("forgets_zero_counts", "Forgets that zero takes one of the non-negative patterns."),
        ],
    ),
    _teach(
        _TWOS,
        3,
        "Explain to a classmate who missed the lecture why computers store signed "
        "integers in two's complement rather than with a separate sign bit.",
        "With a separate sign bit there are two zeros, +0 and -0, and adding a positive "
        "to a negative number needs its own subtraction logic. In two's complement the "
        "ordinary binary adder already gives the right signed answer, for example "
        "-1 + 1 is 11111111 + 00000001 = 00000000 once the carry is dropped, and zero "
        "has only one pattern.",
        "Ordinary binary addition gives correct signed results, and zero has one pattern",
        [
            "Explains that the same adder works for signed numbers without special cases.",
            "Mentions that a sign bit gives two zeros (+0 and -0) or needs separate subtraction logic.",
        ],
        [
            (
                "twos_has_two_zeros",
                "Thinks two's complement also has a positive and a negative zero.",
            ),
            ("saves_bits", "Claims it is chosen because it needs fewer bits than a sign bit."),
        ],
    ),
    _mc(
        _TWOS,
        1,
        "Which 4-bit two's complement pattern stands for -1?",
        "Negating 1 means inverting 0001 to 1110 and adding one. Checking: the leftmost "
        "bit is worth -8 and the other three are worth 4 + 2 + 1 = 7, and -8 + 7 = -1.",
        "1111",
        [
            (
                "1001",
                "sign_magnitude",
                "Reads the leftmost bit as a minus sign and the rest as the size, as in sign-and-magnitude.",
            ),
            ("1110", "invert_only", "Inverts the bits of 1 and forgets to add one."),
            ("0001", "ignores_sign", "Ignores the sign and writes the pattern for +1."),
        ],
        [
            "Negates 1 by inverting its bits and adding one, or checks the pattern's value.",
            "Uses the leftmost bit's negative weight (-8 in 4 bits).",
        ],
    ),
    _mc(
        _TWOS,
        2,
        "What decimal value does the 8-bit two's complement pattern 11110110 represent?",
        "The leftmost bit is worth -128 and the other 1 bits are worth "
        "64 + 32 + 16 + 4 + 2 = 118. Adding them gives -128 plus 118.",
        "-10",
        [
            (
                "246",
                "reads_unsigned",
                "Reads the pattern as an unsigned number, ignoring the negative weight of the leftmost bit.",
            ),
            (
                "-118",
                "sign_magnitude",
                "Reads the leftmost bit as a minus sign and the remaining seven bits as the size.",
            ),
            ("-9", "invert_only", "Inverts the bits to find the size but forgets to add one."),
        ],
        [
            "Gives the leftmost bit a weight of -128.",
            "Adds the positive weights of the other 1 bits to it.",
        ],
    ),
    _mc(
        _TWOS,
        3,
        "Two 8-bit two's complement numbers, 01100100 (100) and 00110010 (50), are added "
        "and the result is kept in 8 bits. What value is stored?",
        "100 + 50 = 150, which is 10010110 in binary. 150 does not fit in 8-bit two's "
        "complement, whose largest value is 127, so the leftmost bit is read as -128: "
        "-128 + 16 + 4 + 2 = -106, which is 150 - 256.",
        "-106",
        [
            ("150", "ignores_overflow", "Assumes the sum still fits, though 8 bits stop at 127."),
            (
                "-22",
                "sign_magnitude",
                "Reads the leftmost bit as a minus sign and the remaining seven bits as the size.",
            ),
            (
                "-128",
                "wraps_to_minimum",
                "Thinks an overflow always lands on the most negative value instead of wrapping by 256.",
            ),
        ],
        [
            "Notes that the sum, 150, is larger than 127 and overflows.",
            "Reads the 8-bit result 10010110 with the leftmost bit worth -128 (or subtracts 256).",
        ],
    ),
    # ── Variables and Types ─────────────────────────────────────────────────
    _free(
        _VARS,
        1,
        "In Python, a program runs x = 4, then y = x + 1, then x = 9. What is the value "
        "of y afterwards?",
        "y = x + 1 is computed once, when that line runs, using the value x has then, "
        "which is 4. Assigning 9 to x later replaces the value under the name x and "
        "does not touch y.",
        "5",
        [
            "Computes y from the value x had when y was assigned.",
            "States that the later assignment to x does not change y.",
        ],
        [
            ("assignment_as_link", "Thinks y stays linked to x, so changing x later changes y."),
            (
                "assignment_as_equation",
                "Reads = as an equation that must stay true rather than a one-time store.",
            ),
        ],
        numeric="5",
    ),
    _free(
        _VARS,
        2,
        "In Python, what is the type of the value produced by 9 / 3?",
        "The / operator always performs true division in Python 3 and returns a float "
        "even when the division comes out exact, so 9 / 3 is 3.0.",
        "float",
        [
            "States that / is true division and always returns a float.",
            "Notes that an exact division still gives 3.0, not the int 3.",
        ],
        [
            ("exact_division_gives_int", "Expects an int because 3 divides 9 exactly."),
            (
                "type_follows_operands",
                "Thinks the result must have the same type as the operands because both are ints.",
            ),
        ],
    ),
    _free(
        _VARS,
        3,
        "A student writes a = input() and b = input(), types 3 and then 4, and prints "
        "a + b. The program prints 34 instead of 7. What change fixes it?",
        "input() always returns a str, so a and b hold the strings '3' and '4', and + "
        "joins strings. Converting them first, as in int(a) + int(b) or "
        "a = int(input()), makes them numbers, and the sum is 7.",
        "Convert each input with int() before adding",
        [
            "Explains that input() returns strings.",
            "Explains that + joins strings, which produced 34.",
            "Converts the inputs to numbers before adding them.",
        ],
        [
            (
                "plus_always_adds",
                "Thinks + always adds numerically, whatever the types of its operands.",
            ),
            ("input_returns_number", "Thinks input() returns a number when the user types digits."),
        ],
    ),
    _teach(
        _VARS,
        1,
        "Explain to a classmate who missed the lecture what a variable is in Python.",
        "A variable is a name you attach to a value so you can use it later. The "
        "assignment score = 10 stores 10 under the name score; writing score = 12 "
        "afterwards replaces it, and from then on score means 12.",
        "A name that refers to a stored value, which a later assignment can replace",
        [
            "Describes a variable as a name bound to a value.",
            "Explains that assignment stores a value and a later assignment replaces it.",
        ],
        [
            (
                "variable_is_fixed",
                "Says a variable's value can never change once it has been assigned.",
            ),
            (
                "variable_is_its_type",
                "Confuses a variable with its type, saying the variable itself is an int or a str.",
            ),
        ],
    ),
    _teach(
        _VARS,
        2,
        "Explain to a classmate who missed the lecture why '3' + '4' and 3 + 4 give "
        "different results in Python.",
        "'3' and '4' are strings, because of the quotes, while 3 and 4 are ints. The + "
        "operator depends on the types it is given: on strings it joins them, giving "
        "'34', and on numbers it adds them, giving 7.",
        "The types differ: + joins strings but adds numbers",
        [
            "States that the quoted values are strings and the others are ints.",
            "Explains that + joins strings ('34') but adds numbers (7).",
        ],
        [
            (
                "quotes_are_decoration",
                "Thinks quotation marks are only formatting and do not change the value's type.",
            ),
            (
                "plus_always_adds",
                "Thinks + always adds numerically, whatever the types of its operands.",
            ),
        ],
    ),
    _teach(
        _VARS,
        3,
        "Explain to a classmate who missed the lecture why 0.1 + 0.2 == 0.3 is False in "
        "Python, and how floats should be compared.",
        "Floats are stored in binary, and 0.1 and 0.2 have no exact binary form, so each "
        "is stored as a close approximation. Their sum is 0.30000000000000004, which is "
        "not exactly the stored 0.3, so == says False. Floats are compared within a "
        "small tolerance instead, for example math.isclose(0.1 + 0.2, 0.3).",
        "Floats are binary approximations, so compare them within a tolerance such as math.isclose",
        [
            "Explains that 0.1 and 0.2 cannot be stored exactly in binary.",
            "Recommends comparing within a tolerance (for example math.isclose) instead of ==.",
        ],
        [
            (
                "python_float_bug",
                "Thinks the result is a bug in Python rather than a property of binary floating point.",
            ),
            (
                "display_rounding_only",
                "Thinks the values are exact and only the printed result is rounded.",
            ),
        ],
    ),
    _mc(
        _VARS,
        1,
        "Which Python type does the value 2.0 have?",
        "Writing a decimal point makes a float literal, even when the fractional part "
        "is zero; 2 without the point would be an int.",
        "float",
        [
            (
                "int",
                "whole_value_is_int",
                "Thinks a number with no fractional part is an int even when written with a decimal point.",
            ),
            (
                "double",
                "other_language_types",
                "Uses the type name from Java or C, where such values are doubles.",
            ),
            (
                "decimal",
                "decimal_is_builtin_type",
                "Thinks numbers written with a decimal point have a built-in type called decimal.",
            ),
        ],
        [
            "States that a literal written with a decimal point is a float.",
            "Notes that a zero fractional part does not make the value an int.",
        ],
    ),
    _mc(
        _VARS,
        2,
        "In Python, what does 23 // 5 evaluate to?",
        "// is floor division: it divides and rounds down to a whole number. 23 / 5 is "
        "4.6, and rounding down gives the result.",
        "4",
        [
            (
                "4.6",
                "floor_div_as_true_div",
                "Treats // like /, giving the exact quotient as a float.",
            ),
            (
                "3",
                "gives_remainder",
                "Gives the remainder of the division, which is what % computes.",
            ),
            (
                "5",
                "rounds_to_nearest",
                "Rounds the quotient to the nearest whole number instead of down.",
            ),
        ],
        [
            "States that // divides and rounds down (floor division).",
            "Computes the exact quotient 4.6 and rounds it down.",
        ],
    ),
    _mc(
        _VARS,
        3,
        "What does print(int('7') + int(3.9)) display?",
        "int('7') converts the string to the number 7. int(3.9) drops the fractional "
        "part and gives 3; it does not round. 7 + 3 adds two ints.",
        "10",
        [
            (
                "11",
                "int_rounds",
                "Thinks int() rounds 3.9 to the nearest whole number instead of cutting off the fraction.",
            ),
            (
                "73",
                "plus_joins_text",
                "Thinks the result is joined as text because one argument started as a string.",
            ),
            ("10.9", "int_keeps_fraction", "Thinks int() of a float keeps its fractional part."),
        ],
        [
            "Explains that int('7') converts the string to the number 7.",
            "Explains that int(3.9) drops the fraction and gives 3.",
        ],
    ),
    # ── Control Flow ────────────────────────────────────────────────────────
    _free(
        _FLOW,
        1,
        "List the values the variable i takes in for i in range(4).",
        "range(4) starts at 0 and stops before 4, so the loop runs four times.",
        "0, 1, 2, 3",
        [
            "Starts at 0.",
            "Stops before 4, without including it.",
        ],
        [
            (
                "range_includes_end",
                "Thinks range includes its end value, so the loop also runs with the end number.",
            ),
            ("range_starts_at_one", "Thinks range starts counting at 1."),
        ],
    ),
    _free(
        _FLOW,
        2,
        "What is the value of total after this code runs?\n"
        "total = 0\n"
        "for n in range(1, 5):\n"
        "    if n % 2 == 0:\n"
        "        total += n",
        "range(1, 5) gives n = 1, 2, 3 and 4. The if adds only the even values, 2 and 4, to total.",
        "6",
        [
            "Lists the values of n as 1 to 4, stopping before 5.",
            "Adds only the even values, 2 and 4.",
        ],
        [
            ("adds_every_n", "Adds every value of n instead of only those that pass the if test."),
            (
                "counts_instead_of_sums",
                "Counts how many values pass the test instead of adding them.",
            ),
        ],
        numeric="6",
    ),
    _free(
        _FLOW,
        3,
        "This loop is meant to print 1 through 5 but never stops:\n"
        "i = 1\n"
        "while i <= 5:\n"
        "    print(i)\n"
        "What line must be added to the loop body?",
        "The condition i <= 5 stays true because i never changes. Increasing i on every "
        "pass, after the print, makes it reach 6, and the loop stops.",
        "i += 1",
        [
            "Explains that the condition never becomes false because i never changes.",
            "Adds a statement in the body that increases i by one.",
        ],
        [
            ("while_runs_once", "Thinks a while loop checks its condition only once, like an if."),
            (
                "change_condition",
                "Tries to fix it by changing the condition instead of updating i in the body.",
            ),
        ],
    ),
    _teach(
        _FLOW,
        1,
        "Explain to a classmate who missed the lecture the difference between an if "
        "statement and a while loop.",
        "Both test a condition. An if statement tests it once and runs its body once if "
        "it is true, then moves on. A while loop tests it again after every run of the "
        "body and keeps repeating until the condition is false.",
        "if runs its body at most once; while repeats it as long as the condition holds",
        [
            "States that an if statement runs its body at most once.",
            "States that a while loop re-checks the condition and repeats while it is true.",
        ],
        [
            (
                "if_repeats",
                "Thinks an if statement re-checks its condition and repeats like a loop.",
            ),
            ("while_runs_once", "Thinks a while loop checks its condition only once, like an if."),
        ],
    ),
    _teach(
        _FLOW,
        2,
        "Explain to a classmate who missed the lecture why only one branch of an "
        "if/elif/else chain runs, even when several of its conditions are true.",
        "The chain checks its conditions in order from the top. As soon as one is true, "
        "its branch runs and the rest of the chain is skipped, so with x = 15, "
        "if x > 10 runs and elif x > 5 is never checked. else runs only when no "
        "condition was true.",
        "The chain stops at the first true condition and skips the rest",
        [
            "States that the conditions are checked from top to bottom.",
            "Explains that the first true condition's branch runs and the rest are skipped.",
        ],
        [
            ("all_true_branches_run", "Thinks every branch whose condition is true runs."),
            ("else_always_runs", "Thinks the else branch runs after the others no matter what."),
        ],
    ),
    _teach(
        _FLOW,
        3,
        "Explain to a classmate who missed the lecture the difference between break and "
        "continue inside a loop, with an example of when to use each.",
        "break leaves the loop at once, so it suits a search that can stop when it finds "
        "what it wants. continue skips the rest of the current pass and goes on with the "
        "next item, so it suits skipping items you do not want, such as blank lines in "
        "a file.",
        "break ends the loop; continue skips to the next iteration",
        [
            "States that break leaves the loop immediately.",
            "States that continue skips the rest of the body and moves to the next iteration.",
            "Gives a sensible example for each.",
        ],
        [
            ("break_exits_program", "Thinks break stops the whole program, not just the loop."),
            (
                "continue_restarts_loop",
                "Thinks continue restarts the loop from its first iteration.",
            ),
        ],
    ),
    _mc(
        _FLOW,
        1,
        "How many times does the body of for i in range(2, 6) run?",
        "range(2, 6) gives 2, 3, 4 and 5: it includes the start and stops before the "
        "end, so it runs 6 - 2 times.",
        "4",
        [
            ("5", "range_includes_end", "Counts both ends, as if range included its end value."),
            ("6", "uses_end_as_count", "Takes the end value as the number of runs."),
            ("3", "excludes_both_ends", "Leaves out the start as well as the end."),
        ],
        [
            "Lists the values 2, 3, 4 and 5 or states that the end is excluded.",
            "Counts the values from start up to, but not including, the end.",
        ],
    ),
    _mc(
        _FLOW,
        2,
        "What does this code print?\n"
        "count = 0\n"
        "for ch in 'banana':\n"
        "    if ch == 'a':\n"
        "        continue\n"
        "    count += 1\n"
        "print(count)",
        "continue skips count += 1 for each a, so only the letters that are not a are "
        "counted: b, n and n.",
        "3",
        [
            ("6", "continue_ignored", "Ignores continue and counts every letter."),
            (
                "1",
                "continue_as_break",
                "Treats continue like break, so the loop stops at the first a.",
            ),
            (
                "0",
                "misreads_indentation",
                "Reads count += 1 as part of the if block, after continue, so it never runs.",
            ),
        ],
        [
            "Explains that continue skips the rest of the body for each a.",
            "Counts the letters of banana that are not a.",
        ],
    ),
    _mc(
        _FLOW,
        3,
        "A loop should store the first negative number of a list in found and then "
        "stop looking. Which statement belongs right after found = n inside "
        "if n < 0:?",
        "Once the first negative number is stored, the loop has nothing left to do. "
        "break leaves the loop immediately, so a later negative number cannot overwrite "
        "found.",
        "break",
        [
            (
                "continue",
                "continue_as_break",
                "Treats continue as if it ended the loop, when it only skips to the next item.",
            ),
            ("pass", "pass_stops", "Thinks pass stops the loop, though it does nothing at all."),
            (
                "exit()",
                "exit_ends_loop",
                "Uses exit(), which ends the whole program rather than just the loop.",
            ),
        ],
        [
            "Explains that the loop must end as soon as the first negative is stored.",
            "Explains that the chosen statement leaves only the loop, so later items cannot overwrite found.",
        ],
    ),
    # ── Recursion ───────────────────────────────────────────────────────────
    _free(
        _REC,
        1,
        "What is the base case of a recursive function?",
        "The base case is the input, or inputs, for which the function returns an "
        "answer directly instead of making another recursive call; it is what makes "
        "the chain of calls stop.",
        "An input the function answers directly without calling itself",
        [
            "Describes an input the function answers without another recursive call.",
            "Explains that it is what stops the recursion.",
        ],
        [
            (
                "base_case_is_first_call",
                "Thinks the base case is the first call the program makes.",
            ),
            ("base_case_always_zero", "Thinks the base case must always be the input 0."),
        ],
    ),
    _free(
        _REC,
        2,
        "Given def f(n): return 1 if n == 0 else 2 * f(n - 1), what does f(3) return?",
        "f(0) is the base case and returns 1. Each level above it doubles the one below: "
        "f(1) = 2, f(2) = 4, and f(3) = 2 * f(2).",
        "8",
        [
            "Starts from the base case f(0) = 1.",
            "Doubles once per level up to f(3).",
        ],
        [
            (
                "stops_one_level_early",
                "Stops unwinding one level early and returns the value for n - 1.",
            ),
            ("multiplies_by_n", "Multiplies by n at each step as factorial does, instead of by 2."),
        ],
        numeric="8",
    ),
    _free(
        _REC,
        3,
        "What happens when count_down(3) is called, and why?\n"
        "def count_down(n):\n"
        "    print(n)\n"
        "    count_down(n - 1)",
        "The function prints 3, 2, 1, 0, -1 and so on, because nothing stops it: there "
        "is no input for which it returns without calling itself again. Each call adds "
        "a frame to the call stack until the stack runs out of room.",
        "It never stops and raises RecursionError, because there is no base case",
        [
            "States that the calls never stop on their own.",
            "Names the missing base case as the cause.",
            "Says that Python raises RecursionError when the call stack runs out.",
        ],
        [
            ("stops_at_zero", "Thinks the countdown stops by itself when n reaches 0."),
            (
                "loops_without_error",
                "Thinks it runs forever without any error, like an infinite while loop.",
            ),
        ],
    ),
    _teach(
        _REC,
        1,
        "Explain to a classmate who missed the lecture the two parts every recursive "
        "function needs.",
        "A recursive function needs a base case, an input it answers directly so the "
        "calls stop, and a recursive step that calls the function on a smaller input "
        "that moves toward the base case. In factorial, factorial(0) = 1 is the base "
        "case and n * factorial(n - 1) is the recursive step.",
        "A base case that stops, and a recursive step on a smaller input",
        [
            "Names a base case that is answered without recursing.",
            "Names a recursive step that calls the function on a smaller input.",
        ],
        [
            (
                "no_base_case_needed",
                "Thinks the recursion stops on its own once the input is small.",
            ),
            (
                "same_size_call",
                "Thinks the recursive call may use the same input, as long as there is a base case.",
            ),
        ],
    ),
    _teach(
        _REC,
        2,
        "Explain to a classmate who missed the lecture what the call stack holds while "
        "factorial(3) is running, and in what order the calls finish.",
        "Each call gets its own frame on the call stack with its own n. factorial(3) "
        "waits on factorial(2), which waits on factorial(1), which waits on "
        "factorial(0). factorial(0) returns 1 first, then its frame is removed, and the "
        "others finish in reverse order of calling, factorial(3) last with 6.",
        "One frame per call, each with its own n; the deepest call, factorial(0), finishes first",
        [
            "States that each call has its own frame with its own copy of n.",
            "States that the calls finish in reverse order, the deepest first.",
        ],
        [
            (
                "first_call_finishes_first",
                "Thinks the outermost call finishes first because it started first.",
            ),
            ("shared_variables", "Thinks all the calls share one copy of n."),
        ],
    ),
    _teach(
        _REC,
        3,
        "Explain to a classmate who missed the lecture how to sum a list recursively, "
        "naming the base case and the recursive step.",
        "Base case: an empty list has nothing in it, so its sum is 0. Recursive step: "
        "the sum of a non-empty list is its first item plus the sum of the rest of the "
        "list, which is one item shorter, so the calls reach the empty list.",
        "The empty list sums to 0; otherwise add the first item to the sum of the rest",
        [
            "Names the empty list, with sum 0, as the base case.",
            "Describes adding the first item to the recursive sum of the rest.",
            "Notes that each call is on a shorter list.",
        ],
        [
            (
                "no_smaller_input",
                "Calls the function on the same list again instead of a shorter one.",
            ),
            (
                "single_item_base_only",
                "Uses a one-item list as the only base case, so an empty list fails.",
            ),
        ],
    ),
    _mc(
        _REC,
        1,
        "A recursive function has a base case, but one of its recursive calls passes an "
        "input that never gets closer to it. What happens when that call runs?",
        "A call that never moves toward the base case makes another call just like "
        "itself, so the calls keep piling up on the call stack until Python runs out of "
        "room for them.",
        "The calls repeat until RecursionError is raised",
        [
            (
                "The function returns None after one call",
                "returns_none",
                "Thinks Python notices the problem and returns None instead of recursing.",
            ),
            (
                "The base case is reached anyway after enough calls",
                "base_case_always_reached",
                "Thinks having a base case guarantees that it is reached.",
            ),
            (
                "Python turns the recursion into a loop that runs forever",
                "recursion_becomes_loop",
                "Thinks deep recursion hangs like a loop instead of failing.",
            ),
        ],
        [
            "Explains that an input that never nears the base case never stops recursing.",
            "Explains that each call adds a frame until the call stack runs out.",
        ],
    ),
    _mc(
        _REC,
        2,
        "What does g(4) return?\n"
        "def g(n):\n"
        "    if n <= 1:\n"
        "        return n\n"
        "    return g(n - 1) + g(n - 2)",
        "g(0) = 0 and g(1) = 1 are the base cases. Then g(2) = 1 + 0 = 1, "
        "g(3) = 1 + 1 = 2, and g(4) = g(3) + g(2) = 2 + 1.",
        "3",
        [
            (
                "5",
                "sequence_from_one",
                "Starts the sequence at 1, 1 instead of 0, 1, which gives the next term.",
            ),
            ("4", "returns_input", "Thinks the function hands back n unchanged."),
            (
                "2",
                "stops_one_level_early",
                "Stops one level early and returns the value for n - 1.",
            ),
        ],
        [
            "Uses the base cases g(0) = 0 and g(1) = 1.",
            "Builds g(2) and g(3) and adds them to get g(4).",
        ],
    ),
    _mc(
        _REC,
        3,
        "Which change makes this function correct for every n >= 0?\n"
        "def total(n):\n"
        "    return n + total(n - 1)",
        "The function has no base case, so total(n - 1) recurses past 0 forever. "
        "Returning 0 for n == 0 before the recursive call stops it there, and then "
        "total(n) is n + (n - 1) + ... + 0.",
        "Return 0 when n is 0, before recursing",
        [
            (
                "Return 0 when n is 0, after the recursive call",
                "base_case_after_call",
                "Puts the base case after the recursive call, where it is never reached.",
            ),
            (
                "Call total(n + 1) instead of total(n - 1)",
                "wrong_direction",
                "Moves the input away from the base case instead of toward it.",
            ),
            (
                "Wrap the return in a while loop",
                "loop_fixes_recursion",
                "Thinks a loop around the call stops the recursion.",
            ),
        ],
        [
            "Identifies the missing base case as the bug.",
            "Explains that the check must come before the recursive call to stop it.",
        ],
    ),
    # ── Pointers and Memory ─────────────────────────────────────────────────
    _free(
        _PTR,
        1,
        "What does a pointer store?",
        "A pointer does not hold the data itself. It holds where the data lives: the "
        "address of a location in memory, which the program follows to reach the "
        "value.",
        "The memory address of another value",
        [
            "States that a pointer holds an address.",
            "Distinguishes the address from the value stored there.",
        ],
        [
            (
                "pointer_holds_copy",
                "Thinks a pointer holds its own copy of the value it points to.",
            ),
            (
                "pointer_is_number_type",
                "Thinks a pointer is a numeric type for storing large values.",
            ),
        ],
    ),
    _free(
        _PTR,
        2,
        "In Python, a program runs a = [1, 2], then b = a, then b.append(3). What does "
        "a hold afterwards?",
        "b = a copies the reference, not the list, so a and b name the same list object. "
        "Appending through b changes that one list, and a sees the change.",
        "[1, 2, 3]",
        [
            "States that a and b refer to the same list object.",
            "Concludes that the append is visible through a.",
        ],
        [
            ("assignment_copies_list", "Thinks b = a makes a separate copy of the list."),
            (
                "append_makes_new_list",
                "Thinks append builds a new list for b and leaves the original alone.",
            ),
        ],
    ),
    _free(
        _PTR,
        3,
        'In C, the lines int *p = NULL; printf("%d", *p); compile. What happens when '
        "they run, and why?",
        "p holds NULL, which is not the address of any valid object. *p asks for the int "
        "stored at that address, so there is nothing to read; this is undefined "
        "behaviour, and on most systems the program stops with a segmentation fault.",
        "It crashes, because dereferencing NULL reads memory at no valid address",
        [
            "States that p holds no valid address.",
            "Explains that *p tries to read the value at that address.",
            "Says the program typically crashes (undefined behaviour, a segmentation fault).",
        ],
        [
            ("null_reads_zero", "Thinks dereferencing NULL simply reads the value 0."),
            ("compiles_means_safe", "Thinks code that compiles cannot fail when it runs."),
        ],
    ),
    _teach(
        _PTR,
        1,
        "Explain to a classmate who missed the lecture the difference between a value "
        "and a reference to it.",
        "A value is the data itself, like the list [1, 2]. A reference is what a "
        "variable holds to reach that data: where it lives in memory. Two variables can "
        "hold references to the same value, so a change made through one is seen "
        "through the other.",
        "A reference holds where a value lives in memory, not the value itself",
        [
            "Describes a value as the data itself.",
            "Describes a reference as where the value lives (its address).",
            "Notes that several references can reach the same value.",
        ],
        [
            ("reference_is_copy", "Says a reference is just another copy of the value."),
            ("one_name_one_value", "Thinks two variable names always mean two separate values."),
        ],
    ),
    _teach(
        _PTR,
        2,
        "Explain to a classmate who missed the lecture why, after b = a in Python, "
        "appending to b changes a when a is a list, but b = b + 1 leaves a unchanged "
        "when a is a number.",
        "b = a makes both names refer to one object. append changes that list object in "
        "place, so a sees it. b = b + 1 does not change the number; it computes a new "
        "number and rebinds b to it, so a still refers to the old one.",
        "Both names share one object; append changes it, but b + 1 rebinds b to a new object",
        [
            "States that after b = a both names refer to the same object.",
            "Explains that append changes the shared list in place.",
            "Explains that b = b + 1 makes b refer to a new object, leaving a alone.",
        ],
        [
            ("assignment_copies_list", "Thinks b = a makes a separate copy of the object."),
            (
                "types_assign_differently",
                "Thinks assignment copies numbers but shares lists, instead of seeing that only the list is mutated.",
            ),
        ],
    ),
    _teach(
        _PTR,
        3,
        "Explain to a classmate who missed the lecture what a memory leak is, and why "
        "Python programs rarely have the kind of leak C programs do.",
        "A leak is memory a program allocated, can no longer use, and never released, so "
        "the program's memory keeps growing. In C, memory from malloc() stays allocated "
        "until the program calls free(), so forgetting free() leaks it. Python's garbage "
        "collector reclaims objects that nothing references, though a program can still "
        "leak by keeping references it no longer needs.",
        "Memory allocated but never freed; Python's garbage collector frees unreferenced objects",
        [
            "Defines a leak as allocated memory that is never released.",
            "Explains that C needs a free() for every malloc().",
            "Explains that Python's garbage collector reclaims unreferenced objects.",
        ],
        [
            (
                "leak_is_overflow",
                "Confuses a memory leak with reading or writing past the end of an array.",
            ),
            (
                "gc_prevents_all_leaks",
                "Thinks a garbage collector makes leaks impossible, even when the program keeps references it no longer needs.",
            ),
        ],
    ),
    _mc(
        _PTR,
        1,
        "In C, what does the expression &x give?",
        "The unary & operator takes the address of its operand. &x is where x lives in "
        "memory, which can be stored in a pointer such as int *p = &x.",
        "The address where x is stored",
        [
            (
                "A copy of the value of x",
                "address_is_copy",
                "Thinks & makes a copy of the variable's value.",
            ),
            (
                "The value at the address x holds",
                "address_vs_dereference",
                "Mixes up & with *, which reads the value at an address.",
            ),
            (
                "x converted to a boolean",
                "ampersand_is_logical",
                "Confuses the unary & with the logical and operator, &&.",
            ),
        ],
        [
            "States that & takes the address of its operand.",
            "Distinguishes taking an address from reading the value at an address.",
        ],
    ),
    _mc(
        _PTR,
        2,
        "In Python, a program runs x = [0, 0], then y = x, then y[0] = 5. What does x "
        "hold afterwards?",
        "y = x makes y refer to the same list as x. y[0] = 5 changes the first item of "
        "that one list in place, so x sees the change.",
        "[5, 0]",
        [
            (
                "[0, 0]",
                "assignment_copies_list",
                "Thinks y = x makes a separate copy, so x keeps its old contents.",
            ),
            (
                "[5, 5]",
                "assignment_fills_all",
                "Thinks assigning to one item changes every item of the list.",
            ),
            (
                "[5]",
                "index_assignment_replaces_list",
                "Thinks y[0] = 5 replaces the whole list with a one-item list.",
            ),
        ],
        [
            "States that x and y refer to the same list.",
            "Explains that item assignment changes the list in place.",
        ],
    ),
    _mc(
        _PTR,
        3,
        "In Python, a program runs a = [1, 2], then b = a, then b += [3], then b = [9]. "
        "What does a hold afterwards?",
        "After b = a both names share one list. b += [3] extends that list in place, so "
        "a sees it. b = [9] then rebinds b to a brand-new list and leaves the shared one "
        "alone.",
        "[1, 2, 3]",
        [
            (
                "[9]",
                "rebinding_changes_original",
                "Thinks assigning a new list to b also replaces the list a refers to.",
            ),
            (
                "[1, 2]",
                "plus_equals_copies",
                "Thinks b += [3] builds a new list for b, as b = b + [3] would.",
            ),
            (
                "[1, 2, 3, 9]",
                "assignment_appends",
                "Thinks assigning to b adds its new items to the shared list.",
            ),
        ],
        [
            "Explains that += on a list changes the shared list in place.",
            "Explains that b = [9] rebinds b without touching a's list.",
        ],
    ),
    # ── Algorithms ──────────────────────────────────────────────────────────
    _free(
        _ALGO,
        1,
        "In Big-O notation, how many steps does linear search take in the worst case on "
        "a list of n items?",
        "Linear search checks the items one by one, and in the worst case the target is "
        "last or missing, so it checks all n items.",
        "O(n)",
        [
            "Explains that the worst case checks every item.",
            "Expresses the cost as growing in proportion to n.",
        ],
        [
            (
                "linear_is_constant",
                "Thinks checking a list takes the same time however long it is.",
            ),
            (
                "confuses_with_halving",
                "Gives the cost of a search that halves the list, assuming the list is sorted.",
            ),
        ],
    ),
    _free(
        _ALGO,
        2,
        "Binary search halves the remaining items with each comparison. How many "
        "halvings narrow a sorted list of 1,024 items down to a single item?",
        "1,024 -> 512 -> 256 -> 128 -> 64 -> 32 -> 16 -> 8 -> 4 -> 2 -> 1 takes ten "
        "halvings, because 2^10 = 1,024.",
        "10",
        [
            "Halves 1,024 repeatedly or uses log2(1,024).",
            "Reaches 2^10 = 1,024.",
        ],
        [
            ("linear_count", "Thinks it may need to check every item, as linear search would."),
            ("halves_once", "Divides the size by two only once and answers with half the list."),
        ],
        numeric="10",
    ),
    _free(
        _ALGO,
        3,
        "A program sorts a list with selection sort, which takes O(n^2) time. Sorting "
        "1,000 items takes 2 seconds. About how long should sorting 4,000 items take?",
        "Quadratic time grows with the square of n. 4,000 items is 4 times as many, so "
        "the time grows by 4^2 = 16, and 16 * 2 seconds gives the estimate.",
        "32 seconds",
        [
            "States that the time grows with the square of the input size.",
            "Multiplies the 2 seconds by 16 for four times the input.",
        ],
        [
            ("linear_scaling", "Scales the time in proportion to n, as if the sort were linear."),
            ("doubles_for_square", "Doubles the growth factor instead of squaring it."),
        ],
        numeric="32",
    ),
    _teach(
        _ALGO,
        1,
        "Explain to a classmate who missed the lecture what Big-O notation describes "
        "about an algorithm.",
        "Big-O describes how an algorithm's running time grows as its input gets "
        "bigger, ignoring constant factors and details of the machine. O(n) means the "
        "time grows in proportion to the input, so twice the input takes about twice "
        "as long; O(n^2) means twice the input takes about four times as long.",
        "How its running time grows as the input size grows",
        [
            "States that Big-O describes growth of running time with input size.",
            "Notes that it ignores constant factors or exact times.",
            "Gives a correct example such as O(n) or O(n^2).",
        ],
        [
            ("big_o_is_seconds", "Thinks Big-O gives the exact running time in seconds."),
            (
                "big_o_best_case",
                "Thinks Big-O describes how fast the algorithm runs on its luckiest input.",
            ),
        ],
    ),
    _teach(
        _ALGO,
        2,
        "Explain to a classmate who missed the lecture why binary search needs a sorted list.",
        "Binary search compares the target with the middle item and throws away half of "
        "the list. That is only safe when the list is sorted: then everything left of "
        "the middle is smaller and everything right of it is larger, so the order tells "
        "which half can still hold the target. On an unsorted list the discarded half "
        "might contain it.",
        "Discarding half the list is safe only because the order shows which half holds the target",
        [
            "Describes comparing with the middle item and discarding half.",
            "Explains that sorted order tells which half can hold the target.",
        ],
        [
            ("binary_search_sorts", "Thinks binary search sorts the list as it goes."),
            (
                "sorted_only_for_speed",
                "Thinks a sorted list only makes binary search faster, not correct.",
            ),
        ],
    ),
    _teach(
        _ALGO,
        3,
        "Explain to a classmate who missed the lecture when it is worth sorting a list "
        "first so that binary search can replace linear search.",
        "Sorting costs O(n log n), more than one linear search at O(n). Each binary "
        "search afterwards costs only O(log n). So for a single search, linear search "
        "wins; when the same list is searched many times, the savings on every search "
        "add up and repay the sort.",
        "When the same list is searched many times, so one O(n log n) sort pays off",
        [
            "Compares the cost of sorting with the cost of one linear search.",
            "Concludes that sorting pays off only over many searches.",
        ],
        [
            (
                "always_sort_first",
                "Thinks sorting first is always faster, even for a single search.",
            ),
            ("sorting_is_free", "Ignores the cost of sorting when comparing the two plans."),
        ],
    ),
    _mc(
        _ALGO,
        1,
        "Binary search can be used only when the list has which property?",
        "Binary search decides which half to discard by comparing with the middle item, "
        "which only works when the items are in order.",
        "It is sorted",
        [
            (
                "It has no duplicates",
                "needs_unique_items",
                "Thinks repeated values stop binary search from working.",
            ),
            (
                "Its length is a power of two",
                "needs_power_of_two",
                "Thinks the list must split into exact halves every time.",
            ),
            (
                "It holds only numbers",
                "numbers_only",
                "Thinks binary search works only on numbers, not on other ordered values such as strings.",
            ),
        ],
        [
            "Explains that the search compares with the middle item to discard half.",
            "Explains why the items must be in order for that to be safe.",
        ],
    ),
    _mc(
        _ALGO,
        2,
        "An algorithm runs in O(n) time. Its input grows from 1,000 to 3,000 items. "
        "Roughly how does its running time change?",
        "O(n) time grows in proportion to the input. The input is three times as large, "
        "so the running time is about three times as long.",
        "It roughly triples",
        [
            (
                "It roughly multiplies by nine",
                "squares_growth",
                "Squares the growth factor, as for a quadratic algorithm.",
            ),
            (
                "It stays about the same",
                "big_o_ignores_n",
                "Thinks Big-O means the time does not depend on the input size.",
            ),
            (
                "It roughly doubles",
                "doubles_any_growth",
                "Thinks running time doubles whenever the input grows, whatever the factor.",
            ),
        ],
        [
            "States that O(n) time grows in proportion to n.",
            "Applies the factor of three from 1,000 to 3,000 items.",
        ],
    ),
    _mc(
        _ALGO,
        3,
        "You need to look up one name, once, in a list of 1,000,000 names that is "
        "already sorted. Which approach takes the fewest comparisons in the worst case?",
        "The list is already sorted, so halving it each step needs only about 20 "
        "comparisons, O(log n). Checking one by one may take a million, and re-sorting "
        "or hashing touches every name first.",
        "Binary search",
        [
            (
                "Linear search",
                "linear_for_one_lookup",
                "Thinks a single lookup is too few for halving to beat checking one by one.",
            ),
            (
                "Sort it again with merge sort, then search",
                "resorts_sorted_list",
                "Re-sorts a list that is already sorted, adding O(n log n) work.",
            ),
            (
                "Hash every name, then look it up",
                "hashing_is_free",
                "Ignores that building the hash table touches every name once.",
            ),
        ],
        [
            "Uses the fact that the list is already sorted.",
            "Compares the costs: about 20 comparisons against up to a million, or work on every name.",
        ],
    ),
)
