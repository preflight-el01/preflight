"""Statistics: verdict rule, Shapley gap attribution, paired tests, GRIM check."""
import itertools
import math


def mean_std(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd


def tolerance(sd, k, floor=0.5):
    """A reported mean over k seeds is compared with the sampling spread of a
    k-seed mean: 2 * sd / sqrt(k), never tighter than `floor` points."""
    return max(2 * sd / math.sqrt(max(k, 1)), floor)


def verdict(reported, measured, k, scaled=False):
    m, sd = mean_std(measured)
    tol = tolerance(sd, k)
    tol3 = max(3 * sd / math.sqrt(max(k, 1)), 1.0)
    delta = m - reported
    if abs(delta) <= tol and not scaled:
        v = "reproduced"
    elif abs(delta) <= tol3 or (scaled and abs(delta) <= tol):
        v = "partial"
    else:
        v = "not_reproduced"
    return {"verdict": v, "mean": m, "sd": sd, "delta": delta, "tol": tol, "k": k, "n": len(measured)}


def shapley(players, value):
    """Exact Shapley values. value(frozenset) -> float. Fine for <= 4 players."""
    n = len(players)
    phi = {}
    for p in players:
        others = [q for q in players if q != p]
        total = 0.0
        for r in range(len(others) + 1):
            for S in itertools.combinations(others, r):
                S = frozenset(S)
                w = math.factorial(len(S)) * math.factorial(n - len(S) - 1) / math.factorial(n)
                total += w * (value(S | {p}) - value(S))
        phi[p] = total
    return phi


def paired_t(a, b):
    """Paired t-test on per-seed differences; returns (t, two-sided p)."""
    d = [x - y for x, y in zip(a, b)]
    m, sd = mean_std(d)
    n = len(d)
    if sd == 0:
        return (math.inf if m else 0.0), (0.0 if m else 1.0)
    t = m / (sd / math.sqrt(n))
    try:
        from scipy import stats as st
        p = 2 * st.t.sf(abs(t), n - 1)
    except Exception:
        p = math.erfc(abs(t) / math.sqrt(2))
    return t, p


def grim_consistent(reported, decimals, n_items):
    """Can a proportion with denominator n_items round to `reported` (in %)?"""
    target = reported / 100
    half = 0.5 * 10 ** (-decimals) / 100
    lo, hi = target - half, target + half
    k_lo = math.ceil(lo * n_items - 1e-9)
    k_hi = math.floor(hi * n_items + 1e-9)
    hits = [k for k in range(max(k_lo, 0), min(k_hi, n_items) + 1)]
    return (len(hits) > 0), hits


def percentile_rank(value, xs):
    return 100.0 * sum(x <= value for x in xs) / len(xs)
