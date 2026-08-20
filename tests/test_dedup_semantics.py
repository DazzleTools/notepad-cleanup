"""Semantic contract tests for the dedup fuzzy pipeline.

Each test here was written to kill a specific surviving mutant from the
2026-08-19 mutation sweep (tests/mutation/v0.2.5__report__dedup-fuzzy.json).
The sweep proved the prior suite executed these code paths without
constraining them; these tests pin the behavior the design docs promise.

Mutant -> test map:
    M4  threshold edge at size<=1        -> test_threshold_tiny_sizes
    M5  size-operator parse ordering     -> test_parse_fuzzy_size_operators
    M6  lte boundary inclusivity          -> test_fuzzy_size_ok_boundaries
    M8  diff exactly at threshold matches -> test_diff_exactly_at_threshold_is_a_match
    M9  ratio exactly 2.0 not excluded    -> test_ratio_exactly_two_still_matches
    M10 threshold uses the LARGER file    -> test_threshold_uses_larger_file
    M11 canonical is the OLDEST instance  -> test_pick_canonical_oldest_wins
    M12 exact match never double-counts   -> test_exact_match_categorized_once
"""

import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from notepad_cleanup.dedup import (  # noqa: E402
    _find_near_match,
    _fuzzy_size_ok,
    _pick_canonical,
    build_hash_index,
    find_duplicates,
    near_match_threshold,
    normalize_text,
    parse_fuzzy_modes,
)


def _hash(text):
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


# --- M4: threshold at tiny sizes ------------------------------------------

def test_threshold_tiny_sizes():
    """Files of size 0 and 1 allow exactly 1 char difference -- the curve
    (ln(1) == 0 would yield ~10) must never apply below size 2."""
    assert near_match_threshold(0) == 1
    assert near_match_threshold(1) == 1
    # NOTE (discovered writing this test): below the curve's smallest anchor
    # (size 10 -> 2) the log-quadratic INFLATES -- threshold(2) is 6, so two
    # unrelated 2-char files can near-match. Documented quirk, see the
    # 2026-08-19 fuzzy perf DWP; pinned loosely here so a fix is deliberate.
    assert near_match_threshold(2) < 10


# --- M5: size-operator parsing --------------------------------------------

def test_parse_fuzzy_size_operators():
    """'lte'/'gte' must parse as themselves, never prefix-match 'lt'/'gt'."""
    assert parse_fuzzy_modes("lte 100KB") == ({"small", "big"}, "lte", 100000)
    assert parse_fuzzy_modes("gte 1MB") == ({"small", "big"}, "gte", 1000000)
    assert parse_fuzzy_modes("lt 100KB") == ({"small", "big"}, "lt", 100000)
    assert parse_fuzzy_modes("gt100KB") == ({"small", "big"}, "gt", 100000)
    assert parse_fuzzy_modes("lte100KB") == ({"small", "big"}, "lte", 100000)


# --- M6: size boundary inclusivity ----------------------------------------

def test_fuzzy_size_ok_boundaries():
    """Documented semantics: 'lte 100KB' means fuzzy for files <= 100KB --
    a file exactly at the limit qualifies. Same inclusivity for gte/eq."""
    assert _fuzzy_size_ok(100, False, "lte", 100) is True
    assert _fuzzy_size_ok(101, False, "lte", 100) is False
    assert _fuzzy_size_ok(100, False, "gte", 100) is True
    assert _fuzzy_size_ok(99, False, "gte", 100) is False
    assert _fuzzy_size_ok(100, False, "lt", 100) is False
    assert _fuzzy_size_ok(100, False, "gt", 100) is False
    assert _fuzzy_size_ok(100, False, "eq", 100) is True


# --- helpers for end-to-end near-match tests -------------------------------

def _index_of(tmp_path, name, text):
    """Write one candidate file and return a hash_index containing it."""
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return {_hash(text): [f]}


# --- M8: diff exactly at threshold ----------------------------------------

def test_diff_exactly_at_threshold_is_a_match(tmp_path):
    """The contract is diff <= threshold. A pair whose diff EQUALS the
    threshold is a match -- an off-by-one in the best-diff seed loses it.
    Construction: 45-char base + 5 appended chars -> diff 5, and the
    documented anchor point says threshold(50) == 5."""
    base = "abcdefghij" * 4 + "klmno"          # 45 chars, no whitespace edges
    grown = base + "12345"                      # 50 chars, diff = 5 (append)
    assert near_match_threshold(len(grown)) == 5
    idx = _index_of(tmp_path, "old.txt", base)
    m = _find_near_match(normalize_text(grown), _hash(grown),
                         tmp_path / "new.txt", idx)
    assert m is not None, "diff == threshold must be accepted as a match"
    assert m.char_diff == 5


# --- M9: ratio exactly 2.0 ------------------------------------------------

def test_ratio_exactly_two_still_matches(tmp_path):
    """Tiny files can genuinely match at exactly a 2.0x length ratio:
    'ab' vs 'abcd' -> diff 2 <= threshold(4) == 3. The ratio pre-filter is
    exclusive (> 2.0), so exactly 2.0 must pass through to the char diff."""
    assert near_match_threshold(4) >= 2
    idx = _index_of(tmp_path, "old.txt", "ab")
    m = _find_near_match(normalize_text("abcd"), _hash("abcd"),
                         tmp_path / "new.txt", idx)
    assert m is not None, "ratio == 2.0 must not be filtered out"
    assert m.char_diff == 2


# --- M10: threshold from the LARGER file -----------------------------------

def test_threshold_uses_larger_file(tmp_path):
    """Docstring promise: 'Use the heuristic threshold for the larger of the
    two files.' Find a size pair straddling an integer step of the curve and
    verify a diff that only the larger file's threshold allows still matches.
    The search adapts to the active curve coefficients (env overrides)."""
    found = None
    for small in range(10, 4000):
        for k in range(2, 60):
            big = small + k
            t_big = near_match_threshold(big)
            if t_big == k and near_match_threshold(small) < k:
                found = (small, k)
                break
        if found:
            break
    assert found, "curve has no integer step in range -- test needs rework"
    small, k = found
    base = ("abcdefghijklmnopqrstuvwxyz0123456789" * 200)[:small]
    grown = base + "!" * k                      # diff = k exactly (append)
    idx = _index_of(tmp_path, "old.txt", base)
    m = _find_near_match(normalize_text(grown), _hash(grown),
                         tmp_path / "new.txt", idx)
    assert m is not None, (
        f"diff {k} <= threshold(larger={small + k}) == {k} must match even "
        f"though threshold(smaller={small}) == {near_match_threshold(small)}"
    )


# --- M11: canonical is the oldest instance ---------------------------------

def test_pick_canonical_oldest_wins(tmp_path):
    """Docstring promise: 'The canonical file is the OLDEST instance -- the
    original source of truth for provenance tracking.' Must hold regardless
    of input list order."""
    older = tmp_path / "older.txt"
    older.write_text("same content", encoding="utf-8")
    time.sleep(0.05)  # ensure distinct creation times (Windows st_ctime)
    newer = tmp_path / "newer.txt"
    newer.write_text("same content", encoding="utf-8")

    assert _pick_canonical([older, newer]) == older
    assert _pick_canonical([newer, older]) == older


# --- M12: exact match categorized exactly once ------------------------------

def test_exact_match_categorized_once(tmp_path):
    """An exact-matched file must be categorized exactly once -- never fall
    through into fuzzy matching and appear as a near-match too. Pinned via
    the partition invariant: every scanned file lands in exactly one bucket."""
    hist = tmp_path / "notepad-cleanup-2026-01-01_00-00-00"
    win = hist / "window01"
    win.mkdir(parents=True)
    (win / "tab01.txt").write_text("identical note content", encoding="utf-8")
    (hist / "manifest.json").write_text("{}", encoding="utf-8")

    new_dir = tmp_path / "nc-2026-01-02__00-00-00"
    new_win = new_dir / "window01"
    new_win.mkdir(parents=True)
    (new_win / "tab01.txt").write_text("identical note content",
                                       encoding="utf-8")

    idx = build_hash_index([hist])
    result = find_duplicates(new_dir, idx, fuzzy="small")

    assert result.stats["exact_count"] == 1
    assert result.stats["near_count"] == 0, (
        "exact match leaked into fuzzy matching (double-count)"
    )
    total = (result.stats["exact_count"] + result.stats["near_count"]
             + result.stats["new_count"] + result.stats["skipped_count"])
    assert total == result.stats["total_scanned"], (
        "partition invariant violated: buckets do not sum to files scanned"
    )


# --- Round-2 mutant killers (N3, N4, N6, N8, N10) ---------------------------

def test_parse_fuzzy_empty_string_means_exact_only():
    """N3: an empty fuzzy string is exact-only -- it must NOT silently
    default to 'small' fuzzy matching."""
    assert parse_fuzzy_modes("") == (set(), None, None)
    assert parse_fuzzy_modes("none") == (set(), None, None)


def test_parse_fuzzy_all_includes_big():
    """N4: docstring promise -- 'all' means fuzzy EVERYTHING, big included."""
    assert parse_fuzzy_modes("all") == ({"small", "big"}, None, None)


def test_fuzzy_size_ok_at_exact_big_threshold():
    """N6: the big-file cutoff is strictly greater-than -- a file at exactly
    FUZZY_BIG_FILE_THRESHOLD chars still gets fuzzy matching by default."""
    from notepad_cleanup.dedup import FUZZY_BIG_FILE_THRESHOLD
    assert _fuzzy_size_ok(FUZZY_BIG_FILE_THRESHOLD, False) is True
    assert _fuzzy_size_ok(FUZZY_BIG_FILE_THRESHOLD + 1, False) is False
    assert _fuzzy_size_ok(FUZZY_BIG_FILE_THRESHOLD + 1, True) is True


def test_near_match_canonical_uses_pick_canonical(tmp_path):
    """N8: a near-match's canonical_path must come from _pick_canonical
    (oldest copy), never from the index list's arbitrary first element."""
    newer = tmp_path / "newer.txt"
    older = tmp_path / "older.txt"
    content = "abcdefghij" * 4 + "klmno"       # 45 chars
    # create OLDER first so its creation time is earlier
    older.write_text(content, encoding="utf-8")
    time.sleep(0.05)
    newer.write_text(content, encoding="utf-8")

    # index list deliberately puts the NEWER copy first
    idx = {_hash(content): [newer, older]}
    grown = content + "12345"                   # diff 5 == threshold(50)
    m = _find_near_match(normalize_text(grown), _hash(grown),
                         tmp_path / "new.txt", idx)
    assert m is not None
    assert m.canonical_path == older, (
        "near-match canonical must be the oldest copy, not paths[0]"
    )


def test_pick_canonical_prefers_organized_on_ctime_tie():
    """N10: docstring promise -- among copies of the same age, organized/
    copies win (descriptive names + category context). Uses duck-typed
    stand-ins because real files cannot reliably tie on st_ctime."""

    class _FakeStat:
        def __init__(self, ctime):
            self.st_ctime = ctime

    class _FakePath:
        def __init__(self, s, ctime):
            self._s = s
            self._ctime = ctime

        def stat(self):
            return _FakeStat(self._ctime)

        def __str__(self):
            return self._s

        def __repr__(self):
            return self._s

        def __eq__(self, other):
            return str(self) == str(other)

        def __hash__(self):
            return hash(self._s)

    raw = _FakePath(r"C:\s\nc-1\window01\tab01.txt", 1000.0)
    org = _FakePath(r"C:\s\nc-1\organized\notes\descriptive-name.txt", 1000.0)

    assert str(_pick_canonical([raw, org])) == str(org)
    assert str(_pick_canonical([org, raw])) == str(org)


# --- Perf-refactor correctness pins (2026-08-19 fuzzy perf DWP) --------------

def test_near_match_session_dir_matches_canonical(tmp_path):
    """The near-match record's session_dir must describe the SAME file as
    canonical_path. Before the fix it came from paths[0] (arbitrary index
    order) while canonical_path came from _pick_canonical (oldest) -- two
    different sessions reported for one match."""
    sess_old = tmp_path / "nc-2026-01-01__00-00-00"
    sess_new = tmp_path / "nc-2026-02-02__00-00-00"
    content = "abcdefghij" * 4 + "klmno"                 # 45 chars
    old_f = sess_old / "window01" / "tab01.txt"
    new_f = sess_new / "window01" / "tab01.txt"
    for s, f in ((sess_old, old_f), (sess_new, new_f)):
        f.parent.mkdir(parents=True)
        (s / "manifest.json").write_text("{}", encoding="utf-8")
    old_f.write_text(content, encoding="utf-8")
    time.sleep(0.05)
    new_f.write_text(content, encoding="utf-8")

    # index order puts the NEWER copy first -- the old bug's trigger
    idx = {_hash(content): [new_f, old_f]}
    grown = content + "12345"                             # diff 5 == thr(50)
    m = _find_near_match(normalize_text(grown), _hash(grown),
                         tmp_path / "probe.txt", idx)
    assert m is not None
    assert m.canonical_path == old_f
    assert m.session_dir == sess_old, (
        "session_dir must belong to the picked canonical, not paths[0]"
    )


def test_pick_canonical_deterministic_on_ctime_ties():
    """Identical st_ctime must not make the canonical depend on input
    order -- the path string is the final tiebreaker."""

    class _FakeStat:
        def __init__(self, ctime):
            self.st_ctime = ctime

    class _FakePath:
        def __init__(self, s):
            self._s = s

        def stat(self):
            return _FakeStat(1000.0)          # everyone ties

        def __str__(self):
            return self._s

        def __repr__(self):
            return self._s

    a = _FakePath(r"C:\s\nc-1\window02\tab03.txt")
    b = _FakePath(r"C:\s\nc-1\window09\tab01.txt")
    c = _FakePath(r"C:\s\nc-2\window01\tab01.txt")
    import itertools
    winners = {str(_pick_canonical(list(perm)))
               for perm in itertools.permutations([a, b, c])}
    assert len(winners) == 1, f"order-dependent canonical: {winners}"
