"""Quantify how much of the fuzzy candidate scan is prunable WITHOUT reading files.

Key identity in count_char_diffs():
    diff = max(len_a, len_b) - matching_chars
    matching_chars <= min(len_a, len_b)
  =>  diff >= max_len - min_len          (a rigorous LOWER bound)

So if (max_len - min_len) > near_match_threshold(max_len), the pair CANNOT
match and SequenceMatcher never needs to run -- and neither does the file read,
if we know the candidate's normalized length up front.
"""
import sys, hashlib
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

# normalized length of each unique-hash candidate (read once)
cand = []
for h, paths in idx.items():
    try:
        cand.append(len(dedup.normalize_text(paths[0].read_text(encoding="utf-8", errors="replace"))))
    except OSError:
        pass

# the new files that reach the fuzzy path
fuzzy_lens = []
for f in dedup.find_content_files(folder):
    try: n = dedup.normalize_text(f.read_text(encoding="utf-8", errors="replace"))
    except OSError: continue
    if not n.strip(): continue
    if hashlib.sha256(n.encode()).hexdigest() in idx: continue
    if not dedup._fuzzy_size_ok(len(n), False, None, None): continue
    fuzzy_lens.append(len(n))

print(f"fuzzy files = {len(fuzzy_lens)}, unique-hash candidates = {len(cand)}")
print(f"current pair count (reads+ratio) = {len(fuzzy_lens)*len(cand):,}\n")

tot_ratio = tot_bound = 0
for L in fuzzy_lens:
    for C in cand:
        if C == 0: continue
        if max(L, C) / max(min(L, C), 1) <= 2.0:
            tot_ratio += 1
        mx, mn = max(L, C), min(L, C)
        if (mx - mn) <= dedup.near_match_threshold(mx):
            tot_bound += 1

pairs = len(fuzzy_lens) * len(cand)
print(f"survive ratio<=2.0 filter      : {tot_ratio:,}  ({tot_ratio/pairs*100:.2f}% of pairs)")
print(f"survive length-delta bound     : {tot_bound:,}  ({tot_bound/pairs*100:.2f}% of pairs)")
print()
print(f"SequenceMatcher calls today    : {tot_ratio:,}")
print(f"SequenceMatcher calls w/ bound : {tot_bound:,}   "
      f"-> {tot_ratio/max(tot_bound,1):.1f}x fewer")
print(f"file reads today               : {pairs:,}")
print(f"file reads w/ length index     : {len(cand):,} (once each, cached)")
