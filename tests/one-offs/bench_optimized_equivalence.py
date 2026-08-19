"""Prove the optimized fuzzy filter stack returns IDENTICAL matches, much faster.

Two rigorous lower bounds on count_char_diffs(a,b) = max_len - matching_chars,
both valid because matching_chars <= LCS(a,b) <= multiset-intersection(a,b):

  B1 (length delta) : diff >= max_len - min_len            -- O(1), needs only lengths
  B2 (char bag)     : diff >= max_len - sum_c min(a_c,b_c) -- O(n), needs the text

If either bound exceeds the threshold, SequenceMatcher CANNOT return a match,
so it can be skipped with no change in behaviour.
"""
import time, sys, hashlib
from collections import Counter
from pathlib import Path
sys.path.insert(0, ".")
from notepad_cleanup import dedup
from notepad_cleanup.config import get_search_dirs, get_last_extract

folder = get_last_extract()
dirs = [folder.parent] + [Path(d) for d in get_search_dirs()]
seen, uniq = set(), []
for d in dirs:
    r = str(d.resolve())
    if r not in seen: seen.add(r); uniq.append(d)
sessions = dedup.find_session_dirs(uniq, current_dir=folder)
idx = dedup.build_hash_index(sessions, cache_path=folder.parent / dedup.CACHE_FILENAME)

fuzzy_files = []
for f in dedup.find_content_files(folder):
    try: n = dedup.normalize_text(f.read_text(encoding="utf-8", errors="replace"))
    except OSError: continue
    if not n.strip(): continue
    if hashlib.sha256(n.encode()).hexdigest() in idx: continue
    if not dedup._fuzzy_size_ok(len(n), False, None, None): continue
    fuzzy_files.append((f, n, hashlib.sha256(n.encode()).hexdigest()))

# ---- CURRENT implementation --------------------------------------
t0 = time.perf_counter()
cur = {}
for f, n, h in fuzzy_files:
    m = dedup._find_near_match(n, h, f, idx, False, None, None, None)
    cur[f.name + str(len(n))] = (str(m.canonical_path), m.char_diff) if m else None
t_cur = time.perf_counter() - t0

# ---- OPTIMIZED: candidate cache + B1 + B2 ------------------------
t0 = time.perf_counter()
# read each unique-hash candidate ONCE for the whole run
cands = []
for h, paths in idx.items():
    try:
        txt = dedup.normalize_text(paths[0].read_text(encoding="utf-8", errors="replace"))
    except OSError:
        continue
    if not txt: continue
    cands.append((h, paths, txt, len(txt), Counter(txt)))

opt = {}
n_b1 = n_b2 = n_seq = 0
for f, n, h in fuzzy_files:
    new_len = len(n)
    new_bag = Counter(n)
    best_match, best_diff = None, dedup.near_match_threshold(new_len) + 1
    for ch, paths, ctext, clen, cbag in cands:
        mx, mn = max(new_len, clen), min(new_len, clen)
        thr = dedup.near_match_threshold(mx)
        # B1: length-delta bound (O(1))
        if mx - mn > thr:
            n_b1 += 1; continue
        if mx / max(mn, 1) > 2.0: continue
        if not dedup._fuzzy_size_ok(clen, False, None, None): continue
        # B2: char-bag bound (O(n))
        inter = sum((new_bag & cbag).values())
        if mx - inter > thr:
            n_b2 += 1; continue
        n_seq += 1
        diff = dedup.count_char_diffs(n, ctext)
        if diff <= thr and diff < best_diff:
            best_diff, best_match = diff, (str(dedup._pick_canonical(paths)), diff)
    opt[f.name + str(new_len)] = best_match
t_opt = time.perf_counter() - t0

print(f"current   : {t_cur:8.2f}s")
print(f"optimized : {t_opt:8.2f}s     -> {t_cur/max(t_opt,1e-9):.1f}x faster")
print(f"\npruned by B1 length-delta : {n_b1:,}")
print(f"pruned by B2 char-bag     : {n_b2:,}")
print(f"SequenceMatcher calls     : {n_seq:,}   (was 2,668)")
print("\nRESULT:", "IDENTICAL matches" if cur == opt else "*** MISMATCH ***")
if cur != opt:
    for k in cur:
        if cur[k] != opt.get(k):
            print("  differs:", k, "\n    cur:", cur[k], "\n    opt:", opt.get(k))
