"""Validity patches beyond leakage: equal tuning budget for baselines and metric fixes.

Each function rewrites a sandbox copy of one script and returns (new_text, diff,
details). The pipeline re-runs the experiment on the patched copy and measures
the effect, so every validity finding comes with a number.
"""
import ast
import difflib
import math

SEARCHES = {"GridSearchCV", "RandomizedSearchCV"}


def _callname(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)


def search_space(cls, size):
    """A default search space of `size` configurations for a baseline class."""
    if cls in ("LogisticRegression", "SVC", "LinearSVC", "RidgeClassifier"):
        lo, hi = -3.5, 2.0
        vals = [10 ** (lo + (hi - lo) * i / max(size - 1, 1)) for i in range(size)]
        return "C", [float(f"{v:.2g}") for v in vals]
    if cls == "KNeighborsClassifier":
        return "n_neighbors", [1 + 2 * i for i in range(size)]
    if cls in ("DecisionTreeClassifier", "RandomForestClassifier", "GradientBoostingClassifier"):
        return "max_depth", [i + 1 for i in range(size)]
    return None, None


def _offset(text, line, col):
    lines = text.split("\n")
    return sum(len(x) + 1 for x in lines[:line - 1]) + col


def equal_budget_patch(path, text, baseline_classes, size, cv):
    """Wrap the baseline estimator in a GridSearchCV with the proposed method's budget."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        calls = {_callname(n) for n in ast.walk(node.value) if isinstance(n, ast.Call)}
        hit = calls & set(baseline_classes)
        if not hit or calls & SEARCHES:
            continue
        cls = sorted(hit)[0]
        param, values = search_space(cls, size)
        if not param:
            return None, None, None
        outer = _callname(node.value)
        prefix = f"{cls.lower()}__" if outer == "make_pipeline" else ""
        expr = ast.get_source_segment(text, node.value)
        new_expr = f"GridSearchCV({expr}, {{{(prefix + param)!r}: {values!r}}}, cv={cv})"
        a = _offset(text, node.value.lineno, node.value.col_offset)
        b = _offset(text, node.value.end_lineno, node.value.end_col_offset)
        new = text[:a] + new_expr + text[b:]
        if "GridSearchCV" not in text:
            last = max(n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
            ls = new.split("\n")
            ls.insert(last, "from sklearn.model_selection import GridSearchCV")
            new = "\n".join(ls)
        diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                            fromfile=f"a/{path}", tofile=f"b/{path}"))
        return new, diff, {"class": cls, "param": prefix + param, "values": values, "line": node.lineno}
    return None, None, None


def metric_patch(path, text, call, want):
    """Set average=<want> on the metric call the audit flagged."""
    lines = text.split("\n")
    i = call["line"] - 1
    ln = lines[i]
    if call.get("col") is not None:
        lines[i] = ln[:call["col"]] + repr(want) + ln[call["end_col"]:]
    else:
        j = ln.find(call["func"] + "(")
        depth, k = 0, j + len(call["func"])
        while k < len(ln):
            depth += ln[k] == "("
            depth -= ln[k] == ")"
            if depth == 0:
                break
            k += 1
        lines[i] = ln[:k] + f", average={want!r}" + ln[k:]
    new = "\n".join(lines)
    diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}"))
    return new, diff


def fmt_values(values):
    return ", ".join(f"{v:g}" if isinstance(v, float) and not math.isnan(v) else str(v) for v in values)
