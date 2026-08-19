"""Property test: the length-delta lower bound must never prune a real match.

Claim: count_char_diffs(a, b) >= abs(len(a) - len(b))
If true, skipping pairs where (max_len - min_len) > threshold is EXACT --
it can only remove pairs that count_char_diffs would have rejected anyway.
"""
import random, string, sys
sys.path.insert(0, ".")
from notepad_cleanup.dedup import count_char_diffs, normalize_text


def main():
    random.seed(1234)
    ALPHA = string.ascii_letters + string.digits + " \n\t.,-_/\\"

    def rand_text(n):
        return "".join(random.choice(ALPHA) for _ in range(n))

    violations = 0
    checked = 0
    for trial in range(4000):
        a = rand_text(random.randint(0, 400))
        # b: sometimes a mutation of a, sometimes unrelated
        if trial % 2:
            b = list(a)
            for _ in range(random.randint(0, 40)):
                if not b: break
                op = random.choice(("sub", "ins", "del"))
                i = random.randrange(len(b))
                if op == "sub": b[i] = random.choice(ALPHA)
                elif op == "ins": b.insert(i, random.choice(ALPHA))
                else: b.pop(i)
            b = "".join(b)
        else:
            b = rand_text(random.randint(0, 400))

        na, nb = normalize_text(a), normalize_text(b)
        diff = count_char_diffs(na, nb)
        bound = abs(len(na) - len(nb))
        checked += 1
        if diff < bound:
            violations += 1
            if violations <= 3:
                print(f"VIOLATION: diff={diff} < bound={bound}  len={len(na)},{len(nb)}")

    print(f"checked {checked} random pairs")
    print("RESULT:", "PASS - bound holds (safe to prune)" if violations == 0
          else f"FAIL - {violations} violations (NOT safe)")


if __name__ == "__main__":
    main()
