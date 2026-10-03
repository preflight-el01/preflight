"""Self-healing runner: when a script crashes, read stderr, apply a known fix to a
sandbox copy, log it as an impediment to out-of-the-box reproducibility, retry.

Tier 1 (here): a rule base of known breaking changes, deterministic and auditable.
Tier 2 (production): an LLM debugging agent proposes a patch for unknown errors;
the patch is only accepted if the re-run succeeds and the diff is shown.
"""
import difflib
import re

RULES = [
    {
        "id": "sklearn-plot-confusion-matrix",
        "match": re.compile(r"ImportError: cannot import name 'plot_confusion_matrix'"),
        "title": "plot_confusion_matrix was removed in scikit-learn 1.2",
        "find": re.compile(r"from sklearn\.metrics import plot_confusion_matrix"),
        "replace": "from sklearn.metrics import ConfusionMatrixDisplay",
        "also": [(re.compile(r"plot_confusion_matrix\((\w+), "), r"ConfusionMatrixDisplay.from_estimator(\1, ")],
        "severity": "low",
        "affects_result": False,
    },
    {
        "id": "sklearn-penalty-none",
        "match": re.compile(r"penalty.*'none'|penalty' parameter of LogisticRegression must be"),
        "title": "penalty='none' was removed in scikit-learn 1.4",
        "find": re.compile(r"penalty=['\"]none['\"]"),
        "replace": "penalty=None",
        "also": [],
        "severity": "low",
        "affects_result": False,
    },
    {
        "id": "sklearn-load-boston",
        "match": re.compile(r"cannot import name 'load_boston'"),
        "title": "load_boston was removed in scikit-learn 1.2 (dataset withdrawn)",
        "find": None,
        "severity": "high",
        "affects_result": True,
    },
    {
        "id": "cuda-on-cpu",
        "match": re.compile(r"Torch not compiled with CUDA enabled|No CUDA GPUs are available"),
        "title": "Script calls .cuda() on a CPU-only runtime",
        "find": re.compile(r"\.cuda\(\)"),
        "replace": ".to('cpu')",
        "also": [],
        "severity": "medium",
        "affects_result": False,
    },
]


def diagnose(stderr):
    last = stderr.strip().splitlines()[-1] if stderr.strip() else ""
    for r in RULES:
        if r["match"].search(stderr):
            return r, last
    return None, last


def propose_patch(rule, files, stderr):
    """Return {path: new_text} and a unified diff, or None."""
    if not rule.get("find"):
        return None, None
    # which file? the traceback names it
    m = re.findall(r'File "([^"]+\.py)", line (\d+)', stderr)
    candidates = [p for p in files if p.endswith(".py") and any(p.endswith(f.replace("\\", "/").split("/")[-1])
                                                                for f, _ in m)] or list(files)
    for path in candidates:
        text = files.get(path)
        if not text or not rule["find"].search(text):
            continue
        new = rule["find"].sub(rule["replace"], text)
        for pat, rep in rule.get("also", []):
            new = pat.sub(rep, new)
        diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                            fromfile=f"a/{path}", tofile=f"b/{path}"))
        return {path: new}, diff
    return None, None
