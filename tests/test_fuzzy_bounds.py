"""Invariant tests for the fuzzy-match pruning bounds (B1/B2).

These pin the mathematical properties that any candidate-pruning
optimization of _find_near_match relies on:

    count_char_diffs(a, b) = max(len(a), len(b)) - matching_chars
    matching_chars <= LCS(a, b) <= multiset_intersection(a, b)

which yields two rigorous LOWER bounds on the diff:

    B1 (length delta):  diff >= max_len - min_len
    B2 (char bag):      diff >= max_len - sum_c min(count_a(c), count_b(c))

If either bound exceeds near_match_threshold(max_len), the pair CANNOT be a
near-match, so the expensive SequenceMatcher call can be skipped with zero
change in behaviour. A true match can therefore never be pruned: if
diff <= threshold then B1 <= threshold and B2 <= threshold by transitivity.

Also pins the documented accuracy promise of the threshold curve: the seven
hand-picked anchor points from docs/fuzzy-matching.md, each within 10%.

Promoted from tests/one-offs/test_prune_bound_safety.py and
tests/one-offs/test_bounds_never_lose_matches.py (2026-08-18 perf
investigation, see private note on the compare --last bottleneck).
"""

import random
import string
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from notepad_cleanup.dedup import (  # noqa: E402
    count_char_diffs,
    near_match_threshold,
    normalize_text,
)

ALPHA = string.ascii_letters + string.digits + " \n\t.,-_/\\"
WORDS = (
    "config path value token repo branch commit alpha beta gamma delta "
    "notepad cleanup organize compare session window tab extract the a of "
    "to in is on and for with not"
).split()


def _rand_text(rng, n):
    return "".join(rng.choice(ALPHA) for _ in range(n))


def _doc(rng, n):
    """Word-shaped text with newlines, closer to real notepad content."""
    out = []
    while sum(len(w) + 1 for w in out) < n:
        out.append(rng.choice(WORDS))
        if rng.random() < 0.15:
            out.append("\n")
    return " ".join(out)[:n]


def _edit(rng, text, n_edits):
    """Apply n_edits random single-char substitutions/insertions/deletions."""
    b = list(text)
    for _ in range(n_edits):
        if not b:
            break
        op = rng.choice(("sub", "ins", "del"))
        i = rng.randrange(len(b))
        if op == "sub":
            b[i] = rng.choice(string.ascii_lowercase)
        elif op == "ins":
            b.insert(i, rng.choice(string.ascii_lowercase + " "))
        else:
            b.pop(i)
    return "".join(b)


def _b1(a, b):
    return abs(len(a) - len(b))


def _b2(a, b):
    mx = max(len(a), len(b))
    return mx - sum((Counter(a) & Counter(b)).values())


def test_b1_length_delta_is_lower_bound():
    """diff >= |len(a) - len(b)| for random and mutated pairs."""
    rng = random.Random(1234)
    for trial in range(400):
        a = normalize_text(_rand_text(rng, rng.randint(0, 300)))
        if trial % 2:
            b = normalize_text(_edit(rng, a, rng.randint(0, 30)))
        else:
            b = normalize_text(_rand_text(rng, rng.randint(0, 300)))
        diff = count_char_diffs(a, b)
        assert diff >= _b1(a, b), (
            f"B1 violated: diff={diff} < {_b1(a, b)} "
            f"(lens {len(a)},{len(b)})"
        )


def test_b2_char_bag_is_lower_bound():
    """diff >= max_len - multiset_intersection for random and mutated pairs."""
    rng = random.Random(5678)
    for trial in range(400):
        a = normalize_text(_rand_text(rng, rng.randint(0, 300)))
        if trial % 2:
            b = normalize_text(_edit(rng, a, rng.randint(0, 30)))
        else:
            b = normalize_text(_rand_text(rng, rng.randint(0, 300)))
        diff = count_char_diffs(a, b)
        assert diff >= _b2(a, b), (
            f"B2 violated: diff={diff} < {_b2(a, b)} "
            f"(lens {len(a)},{len(b)})"
        )


def test_bounds_never_prune_a_true_match():
    """Boundary stress: edit counts centered ON the threshold, where pruning
    would be most tempted to discard a real match. A pair the current
    algorithm calls a match must never have B1 or B2 above the threshold."""
    rng = random.Random(20260818)
    lost = 0
    matches_seen = 0
    for size in (30, 80, 200, 600, 1500, 2500):
        thr = near_match_threshold(size)
        for _ in range(40):
            a = normalize_text(_doc(rng, size))
            n_edits = max(0, int(rng.gauss(thr, thr * 0.6)))
            b = normalize_text(_edit(rng, a, n_edits))
            if not a or not b:
                continue
            mx = max(len(a), len(b))
            t = near_match_threshold(mx)
            diff = count_char_diffs(a, b)
            if diff <= t:  # the current algorithm calls this a match
                matches_seen += 1
                if _b1(a, b) > t or _b2(a, b) > t:
                    lost += 1
    assert matches_seen > 50, (
        f"stress generator produced too few matches ({matches_seen}) "
        "to be meaningful -- fix the generator, not the bounds"
    )
    assert lost == 0, f"{lost} true matches would have been pruned"


def test_threshold_anchor_points_within_documented_promise():
    """docs/fuzzy-matching.md promises the curve reproduces its seven
    hand-picked anchor points within ~10% each. Pin that promise."""
    anchors = {
        10: 2,
        25: 3,
        50: 5,
        200: 14.5,  # doc gives 14-15; use midpoint
        1000: 30,
        5000: 50,
        50000: 100,
    }
    for size, expected in anchors.items():
        got = near_match_threshold(size)
        err = abs(got - expected) / expected
        assert err <= 0.10, (
            f"anchor {size}: threshold {got:.2f} vs documented {expected} "
            f"({err * 100:.1f}% error, promise is 10%)"
        )


def test_evolved_template_shape_still_matches():
    """Synthetic replay of the only real-world near-match in project history:
    a ~2.2KB config template that drifted by ~25 chars between sessions.
    The drifted version must match (diff 25 <= threshold ~41) and the bounds
    must both stay under threshold."""
    rng = random.Random(99)
    base = normalize_text(_doc(rng, 2230))
    drifted = normalize_text(_edit(rng, base, 20))
    mx = max(len(base), len(drifted))
    t = near_match_threshold(mx)
    diff = count_char_diffs(base, drifted)
    assert diff <= t, f"drifted template should match: diff={diff} thr={t:.1f}"
    assert _b1(base, drifted) <= t
    assert _b2(base, drifted) <= t


def test_unrelated_same_size_files_do_not_match():
    """Two unrelated files of identical size: B1 is useless (0) but the
    verdict must still be no-match, and B2 should usually see it cheaply."""
    rng = random.Random(7)
    a = normalize_text(_rand_text(rng, 800))
    b = normalize_text(_rand_text(rng, 800))
    t = near_match_threshold(800)
    diff = count_char_diffs(a, b)
    assert diff > t, "unrelated random files must not near-match"
