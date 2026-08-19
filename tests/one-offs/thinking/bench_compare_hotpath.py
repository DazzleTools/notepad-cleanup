"""Measure where 'notepad-cleanup compare --last' actually spends its time.

Runs the real find_duplicates() against the real on-disk sessions, three ways:
  A) no progress callback at all
  B) a counting-only callback (measures call volume, not render cost)
  C) the exact Rich callback the CLI uses
"""
import time, sys
from pathlib import Path
sys.path.insert(0, ".")
from notepad_cleanup import dedup
from notepad_cleanup.config import get_search_dirs, get_last_extract
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

folder = get_last_extract()
dirs = [folder.parent] + [Path(d) for d in get_search_dirs()]
seen, uniq = set(), []
for d in dirs:
    r = str(d.resolve())
    if r not in seen:
        seen.add(r); uniq.append(d)

sessions = dedup.find_session_dirs(uniq, current_dir=folder)
cache_path = folder.parent / dedup.CACHE_FILENAME

t0 = time.perf_counter()
idx = dedup.build_hash_index(sessions, cache_path=cache_path)
t_index = time.perf_counter() - t0
print(f"build_hash_index      : {t_index:6.2f}s   "
      f"({sum(len(v) for v in idx.values())} files, {len(idx)} hashes)")

# --- A: no callback -------------------------------------------------
t0 = time.perf_counter()
res = dedup.find_duplicates(folder, idx, fuzzy="small", progress_callback=None)
t_none = time.perf_counter() - t0
print(f"find_duplicates (none): {t_none:6.2f}s   {res.stats}")

# --- B: counting callback -------------------------------------------
calls = [0]
def counting(current, total, file_path, stage):
    calls[0] += 1
t0 = time.perf_counter()
dedup.find_duplicates(folder, idx, fuzzy="small", progress_callback=counting)
t_count = time.perf_counter() - t0
print(f"find_duplicates (count):{t_count:6.2f}s   callback invocations = {calls[0]:,}")

# --- C: the real Rich callback the CLI builds -----------------------
console = Console()
with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
              BarColumn(), TextColumn("{task.completed}/{task.total}"),
              TextColumn("[dim]{task.fields[status]}[/dim]"),
              console=console) as progress:
    task = progress.add_task("Comparing...", total=res.stats["total_scanned"], status="")
    def rich_cb(current, total, file_path, stage):
        rel = file_path.relative_to(folder) if folder in file_path.parents else file_path.name
        progress.update(task, completed=current, status=f"{rel} [{stage}]")
    t0 = time.perf_counter()
    dedup.find_duplicates(folder, idx, fuzzy="small", progress_callback=rich_cb)
    t_rich = time.perf_counter() - t0
print(f"find_duplicates (rich): {t_rich:6.2f}s")

print()
print(f"  callback overhead (python only): {t_count - t_none:6.2f}s")
print(f"  callback overhead (rich render): {t_rich  - t_none:6.2f}s")
print(f"  TOTAL compare wall-clock (rich): {t_index + t_rich:6.2f}s")
