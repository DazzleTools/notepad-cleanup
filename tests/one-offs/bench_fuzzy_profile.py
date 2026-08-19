"""Per-phase profile of the fuzzy inner loop, on the real on-disk sessions.

Splits _find_near_match's cost into:
   read+normalize   (Step 1 I/O -- happens for EVERY candidate, before any filter)
   seqmatch         (Step 4 difflib -- only for candidates surviving ratio<=2.0)
   callback         (inner_progress, fired up to 4x per candidate)
"""
import time, sys, hashlib, difflib
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

t0 = time.perf_counter()
idx = dedup.build_hash_index(sessions, cache_path=folder.parent / dedup.CACHE_FILENAME)
print(f"build_hash_index: {time.perf_counter()-t0:.2f}s  "
      f"({sum(len(v) for v in idx.values())} files / {len(idx)} unique hashes)")

fuzzy_files = []
for f in dedup.find_content_files(folder):
    try: n = dedup.normalize_text(f.read_text(encoding="utf-8", errors="replace"))
    except OSError: continue
    if not n.strip(): continue
    if hashlib.sha256(n.encode()).hexdigest() in idx: continue
    if not dedup._fuzzy_size_ok(len(n), False, None, None): continue
    fuzzy_files.append((f, n))
print(f"files entering fuzzy path: {len(fuzzy_files)}\n")

t_read = t_seq = 0.0
n_read = n_seq = 0
per_file = []

for f, n in fuzzy_files:
    fstart = time.perf_counter()
    new_len = len(n)
    for h, paths in idx.items():
        c = paths[0]
        a = time.perf_counter()
        try:
            ct = dedup.normalize_text(c.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        t_read += time.perf_counter() - a; n_read += 1
        cl = len(ct)
        if cl == 0: continue
        if max(new_len, cl) / max(min(new_len, cl), 1) > 2.0: continue
        if not dedup._fuzzy_size_ok(cl, False, None, None): continue
        a = time.perf_counter()
        dedup.count_char_diffs(n, ct)
        t_seq += time.perf_counter() - a; n_seq += 1
    per_file.append((time.perf_counter() - fstart, f.name, new_len))

total = t_read + t_seq
print(f"read+normalize : {t_read:8.2f}s   over {n_read:,} candidate reads")
print(f"seqmatch       : {t_seq:8.2f}s   over {n_seq:,} difflib calls")
print(f"fuzzy subtotal : {total:8.2f}s   (excludes progress callback)\n")

per_file.sort(reverse=True)
print("slowest files (sec, name, normalized chars):")
for s, name, L in per_file[:8]:
    print(f"  {s:7.2f}s  {name:20s} {L:,} chars")
print(f"\n  top-3 files account for {sum(x[0] for x in per_file[:3])/total*100:.0f}% of fuzzy time")
