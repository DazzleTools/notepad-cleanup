"""Capture find_duplicates output (pre-optimization algorithm) on the real
08-20 dataset, as the equivalence baseline for the fuzzy-perf refactor."""
import json, sys, time
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

t0 = time.perf_counter()
res = dedup.find_duplicates(folder, idx, fuzzy="small")
elapsed = time.perf_counter() - t0

out = {
    "elapsed_seconds": elapsed,
    "stats": res.stats,
    "exact": sorted([str(m.new_path), str(m.canonical_path)] for m in res.exact_matches),
    "near": sorted([str(m.new_path), str(m.canonical_path), m.char_diff] for m in res.near_matches),
    "new": sorted(str(p) for p in res.new_files),
    "skipped": sorted(str(p) for p in res.skipped),
}
dest = Path(r"C:\Users\Extreme\AppData\Local\Temp\claude"
            r"\C--code-notepad-cleanup-local"
            r"\0e30967a-d3ff-4389-bfc6-a5f45ff34da1\scratchpad"
            r"\compare_baseline_old_algorithm.json")
dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
print(f"baseline captured: {elapsed:.1f}s, stats={res.stats}")
