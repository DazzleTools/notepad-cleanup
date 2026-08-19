"""Two experiments feeding the fuzzy-perf DWP.

EXP A: does autojunk=True ever change the match VERDICT vs autojunk=False?
       (It is ~30x faster on real text; the question is whether it is safe.)

EXP B: the user's line-level diff idea -- diff LINES first (cheap: n_lines^2),
       then char-diff only the changed regions. How close is the estimate to
       the true char diff, and how much faster is it on the real slow files?
"""
import difflib, random, string, time, sys, hashlib
from pathlib import Path
sys.path.insert(0, ".")
from notepad_cleanup import dedup
from notepad_cleanup.config import get_search_dirs, get_last_extract

# ---------- EXP A: autojunk verdict equivalence ----------
random.seed(42)
WORDS = ("config path value token repo branch commit alpha beta gamma delta "
         "notepad cleanup organize compare session window tab extract the a of "
         "to in is on and for with not").split()
def doc(n):
    out = []
    while sum(len(w)+1 for w in out) < n:
        out.append(random.choice(WORDS))
        if random.random() < 0.15: out.append("\n")
    return " ".join(out)[:n]
def edit(t, k):
    b = list(t)
    for _ in range(k):
        if not b: break
        op = random.choice("sid")
        i = random.randrange(len(b))
        if op == "s": b[i] = random.choice(string.ascii_lowercase)
        elif op == "i": b.insert(i, random.choice(string.ascii_lowercase + " "))
        else: b.pop(i)
    return "".join(b)

def cdiff(a, b, aj):
    m = difflib.SequenceMatcher(None, a, b, autojunk=aj)
    return max(len(a), len(b)) - sum(bl.size for bl in m.get_matching_blocks())

verdict_flips = value_diffs = n = 0
for size in (250, 600, 1500, 4000):
    thr = dedup.near_match_threshold(size)
    for _ in range(40):
        a = dedup.normalize_text(doc(size))
        b = dedup.normalize_text(edit(a, max(1, int(random.gauss(thr, thr*0.7)))))
        if not a or not b: continue
        n += 1
        t = dedup.near_match_threshold(max(len(a), len(b)))
        dF, dT = cdiff(a, b, False), cdiff(a, b, True)
        if dF != dT: value_diffs += 1
        if (dF <= t) != (dT <= t):
            verdict_flips += 1
print(f"EXP A  autojunk equivalence: {n} pairs")
print(f"       value differs : {value_diffs}   verdict flips: {verdict_flips}")

# ---------- EXP B: line-level hybrid on the REAL slow files ----------
folder = get_last_extract()
dirs = [folder.parent] + [Path(d) for d in get_search_dirs()]
seen, uniq = set(), []
for d in dirs:
    r = str(d.resolve())
    if r not in seen: seen.add(r); uniq.append(d)
sessions = dedup.find_session_dirs(uniq, current_dir=folder)
idx = dedup.build_hash_index(sessions, cache_path=folder.parent / dedup.CACHE_FILENAME)

def hybrid_diff(a, b):
    """Line-level SequenceMatcher, then char-diff only the changed opcodes."""
    la, lb = a.split("\n"), b.split("\n")
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    diff = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal": continue
        sa, sb = "\n".join(la[i1:i2]), "\n".join(lb[j1:j2])
        # char-level diff of just this changed region
        diff += cdiff(sa, sb, False)
    return diff

# take the worst offender: the 7,177-char fuzzy file vs the pairs that pass ratio filter
fuzzy_files = []
for f in dedup.find_content_files(folder):
    try: nx = dedup.normalize_text(f.read_text(encoding="utf-8", errors="replace"))
    except OSError: continue
    if not nx.strip(): continue
    if hashlib.sha256(nx.encode()).hexdigest() in idx: continue
    if not dedup._fuzzy_size_ok(len(nx), False, None, None): continue
    fuzzy_files.append((f, nx))
fuzzy_files.sort(key=lambda t: -len(t[1]))
worst_f, worst_n = fuzzy_files[0]
print(f"\nEXP B  worst file: {worst_f.name} ({len(worst_n):,} chars)")

cands = []
for h, paths in idx.items():
    try: ct = dedup.normalize_text(paths[0].read_text(encoding="utf-8", errors="replace"))
    except OSError: continue
    if not ct: continue
    if max(len(worst_n), len(ct)) / max(min(len(worst_n), len(ct)), 1) <= 2.0:
        cands.append(ct)
print(f"       candidates passing ratio filter: {len(cands)}")

t0 = time.perf_counter()
char_diffs = [cdiff(worst_n, c, False) for c in cands]
t_char = time.perf_counter() - t0
t0 = time.perf_counter()
line_diffs = [hybrid_diff(worst_n, c) for c in cands]
t_line = time.perf_counter() - t0
thr = dedup.near_match_threshold(len(worst_n))
flips = sum((cd <= thr) != (ld <= thr) for cd, ld in zip(char_diffs, line_diffs))
maxerr = max((abs(cd-ld) for cd, ld in zip(char_diffs, line_diffs)), default=0)
under = sum(ld < cd for cd, ld in zip(char_diffs, line_diffs))
print(f"       char-level : {t_char:6.2f}s")
print(f"       line hybrid: {t_line:6.2f}s   -> {t_char/max(t_line,1e-9):.1f}x faster")
print(f"       verdict flips vs char-level: {flips} of {len(cands)}   max |error|: {maxerr}  (hybrid<char: {under})")
