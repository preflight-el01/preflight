"""Leakage Auditor (Kapoor & Narayanan, Patterns 2023 taxonomy).

Static rules over the AST, a runtime probe that confirms them, and an automatic
patch that moves the leaky step inside a Pipeline fitted after the split, so the
fixed experiment can be re-run and the inflation measured.

  L1.1  no clean test set: test data used for training or model selection
  L1.2  preprocessing (scaler, imputer, PCA) fitted on train+test
  L1.3  feature selection fitted on train+test
  L1.4  duplicate rows across train and test           (runtime row-hash probe)
  L3.1  temporal leakage: shuffled split of time-indexed data
"""
import ast
import difflib

PREPROC = {"StandardScaler", "MinMaxScaler", "RobustScaler", "Normalizer", "SimpleImputer", "KNNImputer",
           "PCA", "TruncatedSVD", "OneHotEncoder", "OrdinalEncoder"}
SELECTORS = {"SelectKBest", "SelectPercentile", "SelectFromModel", "RFE", "VarianceThreshold"}
TAXONOMY = {
    "L1.1": "No clean test set (test data used for training or model selection)",
    "L1.2": "Pre-processing fitted on training and test data",
    "L1.3": "Feature selection fitted on training and test data",
    "L1.4": "Duplicate rows across train and test",
    "L2": "Illegitimate features",
    "L3.1": "Temporal leakage",
    "L3.2": "Non-independence between train and test",
    "L3.3": "Sampling bias in the test distribution",
}


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _transformer_of(call):
    """For X2 = T(...).fit_transform(X, y) return (class, ctor_node)."""
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in ("fit_transform", "fit"):
        inner = f.value
        if isinstance(inner, ast.Call):
            fn = inner.func
            cls = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if cls in PREPROC | SELECTORS:
                return cls, inner
    return None, None


def _scopes(tree):
    yield tree
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n


def _flat(body):
    out = []
    for st in body:
        out.append(st)
        for field in ("body", "orelse", "finalbody"):
            if isinstance(getattr(st, field, None), list) and not isinstance(st, (ast.FunctionDef, ast.ClassDef)):
                out.extend(_flat(getattr(st, field)))
    return sorted(out, key=lambda s: s.lineno)


def audit_script(path, text):
    findings = []
    tree = ast.parse(text)
    lines = text.splitlines()
    for scope in _scopes(tree):
        stmts = _flat(scope.body)
        leaky = []
        split_seen = False
        for st in stmts:
            if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call):
                cls, ctor = _transformer_of(st.value)
                if cls and not split_seen:
                    args = st.value.args
                    leaky.append({"class": cls, "line": st.lineno, "ctor": ast.get_source_segment(text, ctor),
                                  "input": ast.unparse(args[0]) if args else None,
                                  "uses_y": len(args) > 1,
                                  "outputs": [t.id for t in st.targets if isinstance(t, ast.Name)],
                                  "stmt": st})
            # the split may sit in an assignment, a return, or any other statement
            for call in [n for n in ast.walk(st) if isinstance(n, ast.Call)]:
                fn = call.func
                if not ((isinstance(fn, ast.Name) and fn.id == "train_test_split") or
                        (isinstance(fn, ast.Attribute) and fn.attr == "train_test_split")):
                    continue
                split_args = {ast.unparse(a) for a in call.args}
                for lk in leaky:
                    if split_args & set(lk["outputs"]) or lk["input"] in split_args:
                        rule = "L1.3" if lk["class"] in SELECTORS else "L1.2"
                        findings.append({
                            "rule": rule, "title": TAXONOMY[rule], "file": path, "line": lk["line"],
                            "split_line": call.lineno, "class": lk["class"],
                            "code": lines[lk["line"] - 1].strip(),
                            "explain": f"{lk['class']} is fitted on all {lk['input']} rows (line {lk['line']}) "
                                       f"before train_test_split (line {call.lineno}), so test rows influence "
                                       f"{'which features are kept' if rule == 'L1.3' else 'the fitted statistics'}.",
                            "_leak": lk, "_split": st,
                        })
                split_seen = True
            # L1.1: fitting on a variable that looks like test data
            for call in [n for n in ast.walk(st) if isinstance(n, ast.Call)]:
                f = call.func
                if isinstance(f, ast.Attribute) and f.attr == "fit" and call.args:
                    if any("test" in nm.lower() for nm in _names(call.args[0])):
                        findings.append({"rule": "L1.1", "title": TAXONOMY["L1.1"], "file": path,
                                         "line": call.lineno, "code": lines[call.lineno - 1].strip(),
                                         "explain": "A model is fitted on test data."})
                for kw in call.keywords:
                    if kw.arg in ("eval_set", "validation_data") and any("test" in nm.lower() for nm in _names(kw.value)):
                        findings.append({"rule": "L1.1", "title": TAXONOMY["L1.1"], "file": path,
                                         "line": call.lineno, "code": lines[call.lineno - 1].strip(),
                                         "explain": "Test data is used for early stopping."})
            if isinstance(st, ast.For):
                scored = [n for n in ast.walk(st) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                          and n.func.attr == "score" and n.args
                          and any("test" in nm.lower() for nm in _names(n.args[0]))]
                picks = [n for n in ast.walk(st) if isinstance(n, ast.Compare)]
                if scored and picks:
                    findings.append({"rule": "L1.1", "title": TAXONOMY["L1.1"], "file": path, "line": st.lineno,
                                     "code": lines[st.lineno - 1].strip(),
                                     "explain": "Hyperparameters are selected by comparing test-set scores."})
    # dedupe
    seen, out = set(), []
    for f in findings:
        key = (f["rule"], f["file"], f["line"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def runtime_confirms(probe_events):
    """Probe evidence: a transformer fitted on every row before the split ran."""
    split = next((e for e in probe_events if e["event"] == "split"), None)
    if not split:
        return None
    idx = probe_events.index(split)
    early = [e for e in probe_events[:idx] if e["event"] == "fit" and e["n_rows"] == split["n_total"]]
    late = [e for e in probe_events[idx + 1:] if e["event"] == "fit"]
    return {"fit_before_split": early, "fit_after_split": late, "split": split}


def autopatch(path, text, finding):
    """Move the leaky transformer into a Pipeline with the estimator, after the split."""
    lk, sp = finding["_leak"], finding["_split"]
    lines = text.splitlines(True)
    tree = ast.parse(text)
    out_var, in_var = lk["outputs"][0], lk["input"]

    # 1. the split consumes the raw input instead of the transformed one
    split_src = "".join(lines[sp.lineno - 1: sp.end_lineno])
    new_split = split_src.replace(f"{out_var},", f"{in_var},", 1).replace(f"({out_var}", f"({in_var}", 1)
    if new_split == split_src:
        new_split = split_src.replace(out_var, in_var, 1)

    # 2. find the estimator that is fitted on the training split and wrap it
    est_line, est_src, est_ctor = None, None, None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and node.lineno > sp.lineno:
            fn = node.value.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name and name[0].isupper() and name not in PREPROC | SELECTORS and name not in ("Pipeline",):
                est_line = node.lineno
                est_ctor = ast.get_source_segment(text, node.value)
                est_src = lines[node.lineno - 1]
                break
    if est_line is None:
        return None, None

    new_lines = list(lines)
    new_lines[sp.lineno - 1: sp.end_lineno] = [new_split]
    shift = (sp.end_lineno - sp.lineno + 1) - 1
    est_idx = est_line - 1 - shift
    new_lines[est_idx] = est_src.replace(est_ctor, f"make_pipeline({lk['ctor']}, {est_ctor})")
    del new_lines[lk["line"] - 1]
    # 3. import make_pipeline
    if "make_pipeline" not in text:
        last_import = max(n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
        imp = "from sklearn.pipeline import make_pipeline\n"
        insert_at = last_import - (1 if last_import > lk["line"] else 0)
        new_lines.insert(insert_at, imp)
    new_text = "".join(new_lines)
    diff = "".join(difflib.unified_diff(lines, new_text.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
    return new_text, diff


def public(f):
    return {k: v for k, v in f.items() if not k.startswith("_")}
