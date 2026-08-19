"""What does build_hash_index actually scan, per session? Answers the
'are we hashing organized/ AND window*/ ?' question with on-disk facts."""
import sys, os
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

print(f"{'session':38s} {'org?':5s} {'win?':5s} {'scanned':>8s}  {'source':10s} {'links':>6s}")
print("-" * 88)
grand = 0
for s in sessions:
    has_org = (s / "organized").is_dir()
    has_win = any(s.glob("window[0-9]*"))
    files = dedup.find_content_files(s, for_indexing=True)
    src = "organized" if has_org else ("window*" if has_win else "whole-dir")
    nlinks = sum(1 for f in files if f.is_symlink())
    grand += len(files)
    print(f"{s.name[:37]:38s} {str(has_org):5s} {str(has_win):5s} {len(files):8d}  {src:10s} {nlinks:6d}")
print("-" * 88)
print(f"{'TOTAL':38s} {'':5s} {'':5s} {grand:8d}")

idx = dedup.build_hash_index(sessions, cache_path=folder.parent / dedup.CACHE_FILENAME)
print(f"\nunique hashes: {len(idx)}   redundancy: {grand/len(idx):.2f}x")

multi = sorted(((len(p), h) for h, p in idx.items()), reverse=True)[:3]
print("\nmost-replicated content (same hash, N paths):")
for cnt, h in multi:
    print(f"  {cnt} copies  {h[:12]}")
    for p in idx[h][:4]:
        mark = " (symlink)" if p.is_symlink() else ""
        print(f"      {p}{mark}")
