"""Explore threshold curves for near-match heuristic.

Goal: find an equation that fits the user's intuition:
  - 10 chars -> ~2 chars allowed
  - 25 chars -> ~3 chars allowed
  - 50 chars -> ~5 chars allowed
  - 200 chars -> ~15 chars allowed  (a short note)
  - 1000 chars -> ~30 chars allowed (a medium note)
  - 5000 chars -> ~50 chars allowed (a long note)
  - 50000 chars -> ~100 chars allowed (a very long file)

The curve should grow sublinearly (sqrt-ish or log-ish).
"""

import math


def show_curve(name, func, test_sizes=None):
    """Display a threshold curve."""
    if test_sizes is None:
        test_sizes = [10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 50000]
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  {'Size':>8}  {'Allowed':>8}  {'Pct':>8}")
    print(f"  {'----':>8}  {'-------':>8}  {'---':>8}")
    for size in test_sizes:
        allowed = func(size)
        pct = (allowed / size * 100) if size > 0 else 0
        print(f"  {size:>8}  {allowed:>8.1f}  {pct:>7.1f}%")


# --- Candidate curves ---

# Option A: Square root with scaling
# allowed = k * sqrt(size)
# At size=50, want ~5: k = 5/sqrt(50) = 0.707
def sqrt_curve(size, k=0.707):
    return k * math.sqrt(size)


# Option B: Log curve
# allowed = a * ln(size) + b
# Fit to (50, 5) and (1000, 30):
# 5 = a*ln(50)+b, 30 = a*ln(1000)+b
# 25 = a*(ln(1000)-ln(50)) = a*ln(20) = a*2.996
# a = 8.34, b = 5 - 8.34*3.912 = -27.6 (goes negative for small files)
def log_curve(size, a=8.34, b=-27.6):
    if size <= 1:
        return 0
    return max(0, a * math.log(size) + b)


# Option C: Power law (fractional exponent)
# allowed = a * size^p
# Want: (10, 2), (50, 5), (1000, 30)
# 2 = a * 10^p, 5 = a * 50^p, 30 = a * 1000^p
# 5/2 = (50/10)^p = 5^p -> p = ln(2.5)/ln(5) = 0.569
# a = 2 / 10^0.569 = 2 / 3.71 = 0.539
def power_curve(size, a=0.539, p=0.569):
    return a * (size ** p)


# Option D: Square root with floor and ceiling
# Like sqrt but with a minimum of 1 char and capped at a percentage
def sqrt_capped(size, k=0.707, min_diff=1, max_pct=0.10):
    raw = k * math.sqrt(size)
    return max(min_diff, min(raw, size * max_pct))


# Option E: Hybrid - power law with ceiling
# Allows natural growth but caps at 10% of file size
def power_capped(size, a=0.539, p=0.569, min_diff=1, max_pct=0.10):
    raw = a * (size ** p)
    return max(min_diff, min(raw, size * max_pct))


# User's anchor points for validation
anchors = {10: 2, 25: 3, 50: 5, 200: 15, 1000: 30, 5000: 50, 50000: 100}


def score_curve(name, func):
    """Score how well a curve fits the anchor points."""
    total_error = 0
    print(f"\n  Fit check for {name}:")
    for size, expected in sorted(anchors.items()):
        actual = func(size)
        error = abs(actual - expected) / expected * 100
        total_error += error
        marker = "[OK]" if error < 30 else "[--]" if error < 50 else "[XX]"
        print(f"    size={size:>6}: expected={expected:>3}, got={actual:>5.1f}, "
              f"error={error:>5.1f}% {marker}")
    avg_error = total_error / len(anchors)
    print(f"    Average error: {avg_error:.1f}%")
    return avg_error


if __name__ == "__main__":
    curves = [
        ("A: sqrt (k=0.707)", sqrt_curve),
        ("B: log (a=8.34, b=-27.6)", log_curve),
        ("C: power (a=0.539, p=0.569)", power_curve),
        ("D: sqrt capped (10%)", sqrt_capped),
        ("E: power capped (10%)", power_capped),
    ]

    for name, func in curves:
        show_curve(name, func)

    print("\n" + "=" * 60)
    print("  FIT ANALYSIS vs user's anchor points")
    print("=" * 60)

    scores = []
    for name, func in curves:
        err = score_curve(name, func)
        scores.append((err, name))

    print("\n  RANKING (best fit first):")
    for err, name in sorted(scores):
        print(f"    {err:>5.1f}% avg error - {name}")
