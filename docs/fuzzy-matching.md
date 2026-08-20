# Fuzzy Matching: Near-Duplicate Detection

## Overview

When comparing extracted Notepad tabs against historical sessions, notepad-cleanup identifies two kinds of duplicates:

- **Exact matches**: Identical content (same SHA-256 hash after normalization)
- **Near-matches**: Content that differs by a small number of characters (e.g., a to-do list with one new item added)

Near-match detection uses a **heuristic threshold** that scales with file size -- smaller files get stricter matching, larger files get more tolerance.

## Why near-matches matter

Notes that live in Notepad tabs are rarely static -- the tabs that survive across weeks are exactly the ones you keep *editing*: a to-do list that gains an item, a draft that loses a sentence, a config snippet with one value tweaked. Exact hashing is blind to this. One changed character makes a "different" file, so without near-matching, every edited version of the same note is reported as brand-new on every extraction: the AI re-reads and re-categorizes it each session, the archive accumulates a pile of almost-identical copies under different generated names, and nothing tells you they are the same living document.

A near-match turns that around. When compare says a file is `5 chars different` from a specific historical file, it is telling you: **this is almost certainly that same note, slightly evolved -- not new material.** What you can do with that:

- **Skip re-organizing it** -- you already have a categorized, descriptively-named copy; the "new" file adds nothing but a few edits
- **See exactly what changed** -- the generated diff script (`_compare_diffs.cmd`) opens each pair in your diff tool, so reviewing "what did I add to that list since last month?" takes seconds
- **Link instead of duplicate** (`--link-near`, opt-in) -- keep one canonical file and a pointer, rather than a growing family of near-twins
- **Trace a note's history** -- the match names the prior version and its session, connecting today's tab to where that content lived before

The threshold formula below exists to draw the line between "same note, edited" and "genuinely different note" -- tight enough that unrelated files don't get glued together, loose enough that a week of edits doesn't sever the connection.

## What happens to a near-match in practice

When `compare` finds a near-match, three things are produced -- and it is worth knowing exactly what they are and are not:

1. **The console report**: the pair, the character difference, the threshold it passed, and the historical session the matched version lives in.
2. **`_compare_results.json`** in the extraction folder: the same information, machine-readable, reused by later commands so re-runs don't recompute.
3. **A line in `_compare_diffs.cmd`**: run this script to open each near-match pair in your configured diff tool (`config set diff_tool ...`) and eyeball exactly what changed.

That is the default behavior in full: near-matches are **reported, not acted on**. If you then run `organize`, the near-matched file is treated like any other file -- categorized and copied into `organized/` under a fresh descriptive name. The connection to its prior version survives only inside `_compare_results.json`.

**`--link-near` (opt-in, use with care):** re-running `compare` with `--link auto --link-near` replaces each near-matched file with a link to its *prior* version, keeping your new copy as a `.orig` backup beside it. Note the direction: your just-extracted file -- the one with the newest edits -- becomes the link, and the older content becomes what you see. That is the right call when the "edits" are noise (a stray character, whitespace drift) and wrong when they are real additions you want to keep. Check the diff script first.

**What does NOT exist yet:** a durable, filesystem-visible trail from a note to its earlier versions -- e.g. a link placed *alongside* the new file pointing back at its ancestor, without replacing anything. Today that history lives only in each session's `_compare_results.json`, which is never aggregated across sessions. Persistent version chains are planned ([#20](https://github.com/DazzleTools/notepad-cleanup/issues/20)).

### How old organization influences the next one

Matching is also the only bridge between your *previous* AI organization and the *next* one -- and today that bridge only carries traffic if you link:

- When files are **linked** before `organize` runs (via `compare --link`), the prompt sent to Claude includes a "Previous Session Names" section listing each linked file's old `category/filename` (e.g. `code-snippets/batch-rename.bat`), with an instruction to keep category names consistent.
- When nothing is linked -- **the default workflow** -- Claude receives no information about how earlier sessions were organized and invents a category scheme from scratch each time. That is why category names can drift between sessions (`code-snippets` one month, `commands-and-scripts` the next) even for identical kinds of content.

Old organization also shows up in one passive way: when compare picks the canonical copy of a duplicate, it prefers copies inside an `organized/` tree, so the match output shows you the descriptive name and category a previous run assigned -- useful context even when nothing is fed to the AI.

Passing the full historical category tree to the organize step regardless of linking (so every session builds on the same taxonomy) is a planned improvement, not current behavior.

## The Threshold Formula

```
allowed_diff = 1.396 * ln(size)^2 - 6.75 * ln(size) + 10.14
```

Where:
- `size` = file length in characters (after normalization)
- `ln` = natural logarithm
- `allowed_diff` = maximum number of character differences for a file to be considered a near-match (minimum 1)

### What the formula produces

| File Size | Allowed Diff | Percentage |
|-----------|-------------|------------|
| 10 chars | 2 chars | 20.0% |
| 25 chars | 3 chars | 12.0% |
| 50 chars | 5 chars | 10.0% |
| 100 chars | 9 chars | 9.0% |
| 200 chars | 14 chars | 7.0% |
| 500 chars | 22 chars | 4.4% |
| 1,000 chars | 30 chars | 3.0% |
| 2,000 chars | 39 chars | 1.9% |
| 5,000 chars | 54 chars | 1.1% |
| 10,000 chars | 66 chars | 0.7% |
| 50,000 chars | 101 chars | 0.2% |

You can view this table anytime with:
```bash
notepad-cleanup compare <folder> --show-threshold
```

## How We Derived the Formula

### Step 1: Heuristic anchor points

We started with human intuition about what "similar enough" means at different file sizes:

- A 10-character note changing by 2 characters is still recognizably the same
- A 25-character note changing by 3 characters is borderline
- A 50-character note with 5 character changes is probably the same note with minor edits
- A 1,000-character note (a typical short document) with 30 character changes is likely an updated version
- A 50,000-character file with 100 character changes is almost certainly the same file

These anchor points reflect a key observation: **tolerance should grow sublinearly**. Doubling the file size should not double the allowed differences -- a 100KB file with 2000 changes is clearly a different file, even though 2000/100000 is only 2%.

### Step 2: Candidate curve fitting

We evaluated five families of curves against the anchor points:

| Candidate | Formula | Avg Error |
|-----------|---------|-----------|
| A. Square root | `0.707 * sqrt(size)` | 20.9% |
| B. Logarithmic | `8.34 * ln(size) - 27.6` | 37.4% |
| C. Power law | `0.539 * size^0.569` | 34.2% |
| D. Sqrt capped | `sqrt + 10% cap` | 26.2% |
| E. Power capped | `power + 10% cap` | 41.9% |

None of these fit well across all anchor points. The problem: the anchors follow different growth rates at different scales -- strict for tiny files, generous in the "typical note" range, flattening for large files.

### Step 3: Log-quadratic discovery

Plotting `allowed_diff` against `ln(size)` revealed an approximately quadratic relationship. We solved the system of equations using three anchor points (size=50, size=1000, size=50000):

```
5   = a * ln(50)^2    + b * ln(50)    + c
30  = a * ln(1000)^2  + b * ln(1000)  + c
100 = a * ln(50000)^2 + b * ln(50000) + c
```

Solving:
- `a = 1.396`
- `b = -6.75`
- `c = 10.14`

### Step 4: Validation

The resulting formula was validated against all seven anchor points:

| Size | Expected | Actual | Error |
|------|----------|--------|-------|
| 10 | 2 | 2.0 | 0.0% |
| 25 | 3 | 2.9 | 4.1% |
| 50 | 5 | 5.1 | 2.0% |
| 200 | 15 | 13.6 | 9.6% |
| 1,000 | 30 | 30.1 | 0.4% |
| 5,000 | 50 | 53.9 | 7.8% |
| 50,000 | 100 | 100.5 | 0.5% |

**Average error: 3.5%** -- every anchor point within 10%.

The exploration scripts used during derivation are preserved in `tests/one-offs/test_threshold_curve.py`.

## How Character Differences Are Counted

We use Python's `difflib.SequenceMatcher` to find the longest common subsequences between two normalized texts, then count the characters that don't appear in any matching block:

```python
matcher = difflib.SequenceMatcher(None, text_a, text_b, autojunk=False)
matching_chars = sum(block.size for block in matcher.get_matching_blocks())
diff_count = max(len(text_a), len(text_b)) - matching_chars
```

This means:
- Insertions count as differences (adding "- walk dog\n" to a list = ~11 chars)
- Deletions count as differences
- Substitutions count as differences ("Tuesday" -> "Wednesday" = a few chars)
- Reordering lines counts as many differences (the matching blocks algorithm won't see them as the same)

### Why `autojunk=False` is required

`SequenceMatcher`'s autojunk heuristic treats any element appearing in more than 1% of a 200+-element sequence as "junk" and refuses to anchor matches on it. That is designed for line-level diffs (where blank lines are noise); at the character level on natural text it junks spaces and common letters, fragmenting the matching blocks and inflating the diff count. Measured on 160 boundary-straddling text pairs, `autojunk=True` changed the diff value in 148 and **flipped the match verdict in 98** -- despite being ~30x faster. The flag is not an optimization opportunity; correctness depends on it staying `False`.

### Text normalization before comparison

Before hashing or comparing, text is normalized:
1. Line endings converted to `\n` (strips `\r`)
2. Trailing whitespace stripped from each line
3. Trailing empty lines stripped

This prevents false differences from Windows vs Unix line endings or trailing spaces.

## Using a Custom Formula

If the default threshold doesn't match your workflow, you can customize it.

### Option 1: Override the coefficients

Set environment variables to change the curve shape:

```bash
# More permissive (allow more differences)
set NOTEPAD_CLEANUP_THRESH_A=1.8
set NOTEPAD_CLEANUP_THRESH_B=-8.0
set NOTEPAD_CLEANUP_THRESH_C=12.0

# More strict (fewer allowed differences)
set NOTEPAD_CLEANUP_THRESH_A=1.0
set NOTEPAD_CLEANUP_THRESH_B=-5.0
set NOTEPAD_CLEANUP_THRESH_C=7.0
```

### Option 2: Derive your own formula

1. Decide on your own anchor points. Ask yourself: "For a file of N characters, how many character changes still mean 'same file'?"

```python
# Your anchor points: {file_size: allowed_diff}
anchors = {
    50: 3,       # stricter than default
    1000: 20,    # stricter
    50000: 80,   # stricter
}
```

2. Solve for coefficients. With three anchor points (size_1, y_1), (size_2, y_2), (size_3, y_3), solve:

```
y_1 = a * ln(size_1)^2 + b * ln(size_1) + c
y_2 = a * ln(size_2)^2 + b * ln(size_2) + c
y_3 = a * ln(size_3)^2 + b * ln(size_3) + c
```

Or use the provided fitting script:

```bash
python tests/one-offs/test_threshold_curve.py
```

Modify the `anchors` dict at the top to use your values, and it will evaluate multiple curve families and show the best fit.

3. Set your coefficients via environment variables or config.

### Option 3: Size-based fuzzy control

Instead of changing the formula, control which files get fuzzy matching at all:

```bash
notepad-cleanup compare <folder> --fuzzy "lte 100KB"    # only fuzzy for files up to 100KB
notepad-cleanup compare <folder> --fuzzy "lte 10KB"     # very conservative
notepad-cleanup compare <folder> --fuzzy all             # fuzzy everything (slow for large files)
notepad-cleanup compare <folder> --no-fuzzy              # exact matches only
```

Size operators: `lt`, `lte`, `gt`, `gte`, `eq`. Size units: B, KB, MB, GB, TB.

## Performance Notes

Fuzzy matching is O(n * m) per comparison where n and m are the file sizes in characters. For each new file that isn't an exact hash match, it's compared against every unique file in the historical index.

With 100 new files and 150 unique historical files, that's up to 15,000 pairwise comparisons. Pre-filters reduce this:

1. **Exact hash match** eliminates true duplicates instantly
2. **Length-delta bound (B1)** -- since `diff = max_len - matching_chars` and `matching_chars` can never exceed the shorter text's length, `diff >= max_len - min_len` always. If that bound already exceeds the threshold, the pair cannot match and is skipped using lengths alone
3. **Size ratio filter** (>2x difference) skips obviously different files
4. **Size threshold** (default 50KB) skips large files entirely
5. **Character-bag bound (B2)** -- matching characters can also never exceed the multiset intersection of the two texts' characters, so `diff >= max_len - sum(min(count_a(c), count_b(c)))`. Computed from per-file character counts, no alignment needed
6. Only after all pre-filters pass does the expensive `SequenceMatcher` run

B1 and B2 are **exact lower bounds, not heuristics**: any pair they skip is one `SequenceMatcher` would have rejected anyway, so match results are identical with or without them -- only the wall-clock changes. (Property-tested in `tests/test_fuzzy_bounds.py`; on a real 783-file index the bounds cut a multi-minute compare to ~2 seconds.) Candidate files are also read and normalized once per run instead of once per pair.

Both bounds are checked against `near_match_threshold()` at runtime, so custom formula coefficients (the `NOTEPAD_CLEANUP_THRESH_*` overrides above) automatically retune the pruning -- the bounds stay exact under any curve.

For typical notepad-cleanup sessions (50-100 small text files), comparison completes in seconds. If you have large files (>50KB), use `--fuzzy small` (the default) to skip them.
