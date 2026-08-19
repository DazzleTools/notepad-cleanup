"""Accuracy guarantee: B1/B2 pruning must NEVER discard a pair the current
algorithm would have called a match.

Proof sketch: count_char_diffs(a,b) = max_len - matching_chars, and
matching_chars <= LCS(a,b) <= multiset-intersection(a,b). Therefore
    diff >= B1 = max_len - min_len
    diff >= B2 = max_len - sum_c min(a_c, b_c)
If diff <= threshold then B1 <= threshold and B2 <= threshold, so neither
bound can prune a true match. This test exercises that on realistic edits
(typos, inserted lines, whitespace drift, truncation) across many sizes,
concentrating near the threshold boundary where pruning would bite.
"""
import random, sys
from collections import Counter
sys.path.insert(0, ".")
from notepad_cleanup.dedup import count_char_diffs, normalize_text, near_match_threshold


def main():
    random.seed(20260818)
    WORDS = ("config path value token repo branch commit alpha beta gamma delta "
             "notepad cleanup organize compare session window tab extract").split()

    def doc(nchars):
        out = []
        while sum(len(w) + 1 for w in out) < nchars:
            out.append(random.choice(WORDS))
            if random.random() < 0.12: out.append("\n")
        return " ".join(out)[:nchars]

    def edit(text, n_edits):
        b = list(text)
        for _ in range(n_edits):
            if not b: break
            op = random.choice(("sub", "ins", "del", "space"))
            i = random.randrange(len(b))
            if op == "sub":   b[i] = random.choice("abcdefghijklmnopqrstuvwxyz")
            elif op == "ins": b.insert(i, random.choice("abcdefghijklmnopqrstuvwxyz "))
            elif op == "del": b.pop(i)
            else:             b.insert(i, " ")
        return "".join(b)

    lost = 0; matches = 0; pruned_nonmatch = 0; total = 0
    for size in (30, 80, 200, 500, 1200, 2500, 5000, 12000, 30000):
        thr = near_match_threshold(size)
        for _ in range(120):
            a = normalize_text(doc(size))
            # bias edit counts around the threshold so we straddle the boundary
            n_edits = max(0, int(random.gauss(thr, thr * 0.6)))
            b = normalize_text(edit(a, n_edits))
            if not a or not b: continue
            total += 1
            mx, mn = max(len(a), len(b)), min(len(a), len(b))
            t = near_match_threshold(mx)
            diff = count_char_diffs(a, b)
            is_match = diff <= t
            B1 = mx - mn
            B2 = mx - sum((Counter(a) & Counter(b)).values())
            would_prune = (B1 > t) or (B2 > t)
            if is_match:
                matches += 1
                if would_prune:
                    lost += 1
                    print(f"LOST MATCH size={size} diff={diff} thr={t:.1f} B1={B1} B2={B2}")
            elif would_prune:
                pruned_nonmatch += 1

    print(f"\npairs tested        : {total}")
    print(f"true matches        : {matches}")
    print(f"matches lost to B1/B2: {lost}")
    print(f"non-matches pruned  : {pruned_nonmatch}  "
          f"({pruned_nonmatch/max(total-matches,1)*100:.1f}% of non-matches skipped difflib)")
    print("\nRESULT:", "PASS - zero accuracy loss" if lost == 0 else f"FAIL - {lost} matches lost")


if __name__ == "__main__":
    main()
