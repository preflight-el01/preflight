"""Repo mapping: README commands, configs with line numbers, and a static model of
each script (estimators, seed sites, splits, argparse) built with Python's ast.
"""
import ast
import re

from . import vocab


# --------------------------------------------------------------------------- configs
def parse_yaml_flat(text):
    """Flat `key: value` YAML with line numbers (the subset research configs use)."""
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        body = line.split("#", 1)[0].rstrip()
        m = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.+)$", body)
        if not m:
            continue
        raw = m.group(2).strip()
        out[m.group(1)] = {"value": _literal(raw), "line": n, "raw": raw,
                           "col": line.index(raw, line.index(":"))}
    return out


def _literal(raw):
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw.strip("'\"")


# --------------------------------------------------------------------------- scripts
def _const(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    return None


def _cfg_key(node):
    """cfg["key"] -> "key"."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value
    return None


def _callname(node):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def scan_script(path, text):
    info = {"path": path, "imports": [], "constants": {}, "estimators": [], "splits": [], "argparse": {},
            "seed_sites": [], "config_keys": [], "fit_calls": [], "searches": [], "metric_calls": [],
            "parse_error": None}
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        info["parse_error"] = str(e)
        return info
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                info["imports"].append({"module": node.module, "name": a.name, "line": node.lineno})
        elif isinstance(node, ast.Import):
            for a in node.names:
                info["imports"].append({"module": a.name, "name": None, "line": node.lineno})
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = _const(node.value)
            if v is not None:
                name = node.targets[0].id
                info["constants"][name] = {"value": v, "line": node.lineno, "col": node.value.col_offset,
                                           "end_col": node.value.end_col_offset}
                if "seed" in name.lower() and isinstance(v, int):
                    info["seed_sites"].append({"kind": "constant", "name": name, "value": v, "line": node.lineno,
                                               "col": node.value.col_offset, "end_col": node.value.end_col_offset})
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callname(node)
        if name == "add_argument" and node.args and isinstance(node.args[0], ast.Constant):
            flag = node.args[0].value
            kw = {k.arg: _const(k.value) for k in node.keywords}
            info["argparse"][flag] = {"default": kw.get("default"), "line": node.lineno}
            if "seed" in flag:
                info["seed_sites"].append({"kind": "argparse", "name": flag, "value": kw.get("default"),
                                           "line": node.lineno})
        elif name == "train_test_split":
            kws = {}
            for k in node.keywords:
                if isinstance(k.value, ast.Name):
                    kws[k.arg] = {"ref": k.value.id}
                elif isinstance(k.value, ast.Attribute):
                    kws[k.arg] = {"ref": ast.unparse(k.value)}
                else:
                    kws[k.arg] = {"value": _const(k.value), "col": k.value.col_offset, "end_col": k.value.end_col_offset}
            info["splits"].append({"line": node.lineno, "kwargs": kws,
                                   "args": [ast.unparse(a) for a in node.args]})
        elif name in ("GridSearchCV", "RandomizedSearchCV") and node.args:
            # tuning budget: number of configurations the search tries
            grid = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg in ("param_grid", "param_distributions")), None)
            size = 1
            if isinstance(grid, ast.Dict):
                for v in grid.values:
                    if isinstance(v, (ast.List, ast.Tuple)):
                        size *= len(v.elts)
            n_iter = next((_const(k.value) for k in node.keywords if k.arg == "n_iter"), None)
            if name == "RandomizedSearchCV":
                size = n_iter or 10
            cv = next((_const(k.value) for k in node.keywords if k.arg == "cv"), 5)
            inner = {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None)
                     for n in ast.walk(node.args[0]) if isinstance(n, ast.Call)}
            info["searches"].append({"line": node.lineno, "kind": name, "size": size, "cv": cv,
                                     "classes": sorted(c for c in inner if c),
                                     "grid": ast.unparse(grid) if grid is not None else None})
        elif name in ("f1_score", "precision_score", "recall_score", "fbeta_score"):
            avg = next((k for k in node.keywords if k.arg == "average"), None)
            info["metric_calls"].append({
                "line": node.lineno, "func": name, "average": _const(avg.value) if avg else "binary",
                "col": avg.value.col_offset if avg else None, "end_col": avg.value.end_col_offset if avg else None})
        elif name and any(name in m["classes"] for m in vocab.METHODS.values()):
            kws = {}
            for k in node.keywords:
                key = _cfg_key(k.value)
                if key is not None:
                    kws[k.arg] = {"config_key": key}
                elif _const(k.value) is not None:
                    kws[k.arg] = {"value": _const(k.value), "col": k.value.col_offset, "end_col": k.value.end_col_offset}
                elif isinstance(k.value, ast.Name):
                    kws[k.arg] = {"ref": k.value.id}
                elif isinstance(k.value, ast.Attribute):
                    kws[k.arg] = {"ref": ast.unparse(k.value)}
                else:
                    kws[k.arg] = {"expr": ast.unparse(k.value)}
            pos = [ast.unparse(a) for a in node.args]
            info["estimators"].append({"class": name, "line": node.lineno, "col": node.col_offset,
                                       "end_line": node.end_lineno, "end_col": node.end_col_offset,
                                       "kwargs": kws, "args": pos})
        for k in node.keywords:
            if (name or "").startswith("make_"):
                break  # dataset generators: their seed defines the data, not the run
            if k.arg == "random_state" and isinstance(_const(k.value), int):
                info["seed_sites"].append({"kind": "literal", "name": "random_state", "value": _const(k.value),
                                           "line": k.value.lineno, "col": k.value.col_offset,
                                           "end_col": k.value.end_col_offset})
    for node in ast.walk(tree):
        key = _cfg_key(node)
        if key is not None and isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id in ("cfg", "config", "conf"):
            info["config_keys"].append({"key": key, "line": node.lineno})
    return info


STOP = {"on", "the", "of", "and", "with", "a", "an", "for", "in", "to", "table"}


# --------------------------------------------------------------------------- README
def parse_readme(text):
    cmds, in_fence = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and line.strip().startswith("python "):
            cmd, _, comment = line.partition("#")
            parts = cmd.split()
            script = parts[1]
            args = {}
            j = 2
            while j < len(parts):
                if parts[j].startswith("--"):
                    if j + 1 < len(parts) and not parts[j + 1].startswith("--"):
                        args[parts[j]] = parts[j + 1]
                        j += 2
                        continue
                    args[parts[j]] = True
                j += 1
            seeds = None
            m = re.search(r"seeds?\s+(\d+)\s*(?:-|to)\s*(\d+)", comment + " " + text, re.I)
            if m and "--seed" in args:
                seeds = list(range(int(m.group(1)), int(m.group(2)) + 1))
            cmds.append({"line": n, "command": cmd.strip(), "script": script, "args": args,
                         "comment": comment.strip(), "seed_loop": seeds})
    return cmds


# --------------------------------------------------------------------------- repo model
def load(files):
    """files: {relative_path: text}."""
    repo = {"files": files, "configs": {}, "scripts": {}, "commands": [], "requirements": []}
    for path, text in files.items():
        if path.endswith((".yaml", ".yml")):
            repo["configs"][path] = parse_yaml_flat(text)
        elif path.endswith(".py"):
            repo["scripts"][path] = scan_script(path, text)
    if "README.md" in files:
        repo["commands"] = parse_readme(files["README.md"])
    if "requirements.txt" in files:
        for n, line in enumerate(files["requirements.txt"].splitlines(), 1):
            if line.strip():
                name, _, ver = line.strip().partition("==")
                repo["requirements"].append({"name": name, "version": ver or None, "line": n})
    return repo


def local_modules(repo, script_path):
    """Scripts imported by `script_path` from the same src dir (e.g. common.py)."""
    base = script_path.rsplit("/", 1)[0]
    out = []
    for imp in repo["scripts"][script_path]["imports"]:
        cand = f"{base}/{imp['module']}.py" if imp["module"] else None
        if cand in repo["scripts"] and cand not in out:
            out.append(cand)
    return out


def map_claim(repo, claim):
    """Pick the README command that produces a claim, with the reasons."""
    best, best_score, best_why = None, 0, []
    for cmd in repo["commands"]:
        score, why = 0, []
        script = repo["scripts"].get(cmd["script"])
        if not script:
            continue
        cfg_path = cmd["args"].get("--config")
        cfg = repo["configs"].get(cfg_path, {}) if isinstance(cfg_path, str) else {}
        classes = {e["class"] for e in script["estimators"]}
        for m in claim["methods"]:
            meth = vocab.METHODS[m]
            if cfg.get("model", {}).get("value") == m:
                score += 3
                why.append(f"{cfg_path}:{cfg['model']['line']} model: {m}")
            if classes & set(meth["classes"]):
                score += 2
                why.append(f"{cmd['script']} builds {', '.join(sorted(classes & set(meth['classes'])))}")
            if any(a in cmd["comment"].lower() for a in meth["aliases"]):
                score += 1
                why.append(f"README:{cmd['line']} comment names {meth['name']}")
        text = repo["files"].get(cmd["script"], "").lower()
        if claim.get("dataset"):
            ds_aliases = vocab.DATASETS[claim["dataset"]]["aliases"]
            cfg_ds = cfg.get("dataset", {}).get("value")
            if cfg_ds and cfg_ds != claim["dataset"]:
                score -= 5
            elif not cfg_ds and any(a in text for a in ds_aliases):
                score += 2
                why.append(f"{cmd['script']} loads {vocab.DATASETS[claim['dataset']]['name']}")
        if any(a in cmd["script"].lower() for m in claim["methods"] for a in vocab.METHODS[m]["aliases"]):
            score += 1
        if claim["source"].get("table_label") and claim["source"]["table_label"].lower() in cmd["comment"].lower():
            score += 1
            why.append(f"README:{cmd['line']} cites {claim['source']['table_label']}")
        if claim.get("dataset") and cfg.get("dataset", {}).get("value") == claim["dataset"]:
            score += 1
            why.append(f"{cfg_path}:{cfg['dataset']['line']} dataset: {claim['dataset']}")
        # tie-break: distinctive words of the table row that the README comment repeats ("3 features")
        label_tokens = set(re.findall(r"[a-z0-9]+", claim.get("method_label", claim["label"]).lower())) - STOP
        hits = [t for t in label_tokens if re.search(rf"\b{re.escape(t)}\b", cmd["comment"].lower())]
        if hits:
            score += 0.5 * len(hits)
            why.append(f"README:{cmd['line']} comment matches '{' '.join(sorted(hits))}'")
        if claim["kind"] == "comparison" and not all(
                classes & set(vocab.METHODS[m]["classes"]) for m in claim["methods"]):
            score = 0
        if score > best_score:
            best, best_score, best_why = cmd, score, why
    return best, best_why


def code_values(repo, cmd, method):
    """Effective value of every salient parameter for `method` when `cmd` runs.

    Each value carries where it comes from (config line, code literal, module
    constant, sklearn default) so the runner can override it in a sandbox copy.
    """
    out = {}
    script_path = cmd["script"]
    script = repo["scripts"][script_path]
    cfg_path = cmd["args"].get("--config")
    cfg = repo["configs"].get(cfg_path, {}) if isinstance(cfg_path, str) else {}
    meth = vocab.METHODS[method]
    est = next((e for e in script["estimators"] if e["class"] in meth["classes"]), None)
    if est:
        for p in meth["params"]:
            kw = est["kwargs"].get(p)
            if kw and "config_key" in kw and kw["config_key"] in cfg:
                c = cfg[kw["config_key"]]
                out[p] = {"value": c["value"], "where": "config", "file": cfg_path, "line": c["line"],
                          "key": kw["config_key"], "col": c["col"], "raw": c["raw"]}
            elif kw and "value" in kw:
                out[p] = {"value": kw["value"], "where": "code", "file": script_path, "line": est["line"],
                          "col": kw["col"], "end_col": kw["end_col"]}
            elif kw and "ref" in kw:
                ref = kw["ref"]
                if ref.startswith("args."):
                    flag = "--" + ref[5:].replace("_", "-")
                    flag = flag if flag in script["argparse"] else "--" + ref[5:]
                    a = script["argparse"].get(flag)
                    if a:
                        val = cmd["args"].get(flag, a["default"])
                        out[p] = {"value": _literal(str(val)), "where": "argparse", "file": script_path,
                                  "line": a["line"], "flag": flag}
            elif kw is None and p in _sklearn_defaults(est["class"]):
                out[p] = {"value": _sklearn_defaults(est["class"])[p], "where": "default",
                          "file": script_path, "line": est["line"], "class": est["class"],
                          "est_line": est["line"], "est_end_line": est["end_line"], "est_end_col": est["end_col"]}
        if method == "anova":
            # SelectKBest(f_classif, k=args.k) — k given through argparse in the demo repo
            pass
    # split + seeds live in the script or a local module it imports
    mods = [script_path] + local_modules(repo, script_path)
    for mpath in mods:
        for sp in repo["scripts"][mpath]["splits"]:
            ts = sp["kwargs"].get("test_size")
            if ts is None:
                continue
            if "value" in ts:
                out["test_size"] = {"value": ts["value"], "where": "code", "file": mpath, "line": sp["line"],
                                    "col": ts["col"], "end_col": ts["end_col"]}
            elif "ref" in ts:
                const = repo["scripts"][mpath]["constants"].get(ts["ref"])
                if const:
                    out["test_size"] = {"value": const["value"], "where": "constant", "file": mpath,
                                        "line": const["line"], "name": ts["ref"], "col": const["col"],
                                        "end_col": const["end_col"]}
    out["seeds"] = seed_plan(repo, cmd)
    return out


def seed_plan(repo, cmd):
    mods = [cmd["script"]] + local_modules(repo, cmd["script"])
    sites = []
    for mpath in mods:
        for s in repo["scripts"][mpath]["seed_sites"]:
            sites.append({**s, "file": mpath})
    if cmd.get("seed_loop"):
        n = len(cmd["seed_loop"])
        return {"value": n, "where": "readme", "file": "README.md", "line": cmd["line"], "sites": sites,
                "note": f"README runs seeds {cmd['seed_loop'][0]}-{cmd['seed_loop'][-1]} and averages"}
    const = next((s for s in sites if s["kind"] == "constant"), None)
    if const:
        return {"value": 1, "where": "constant", "file": const["file"], "line": const["line"], "sites": sites,
                "note": f"single hardcoded seed {const['name']} = {const['value']}"}
    arg = next((s for s in sites if s["kind"] == "argparse"), None)
    if arg:
        return {"value": 1, "where": "argparse", "file": arg["file"], "line": arg["line"], "sites": sites,
                "note": f"one run with {arg['name']} {arg['value']}"}
    return {"value": 1, "where": "none", "file": None, "line": None, "sites": sites, "note": "no seed control found"}


_DEFAULTS_CACHE = {}


def _sklearn_defaults(cls_name):
    if cls_name in _DEFAULTS_CACHE:
        return _DEFAULTS_CACHE[cls_name]
    import inspect
    mods = {"LogisticRegression": "sklearn.linear_model", "DecisionTreeClassifier": "sklearn.tree",
            "SVC": "sklearn.svm", "KNeighborsClassifier": "sklearn.neighbors",
            "SelectKBest": "sklearn.feature_selection"}
    out = {}
    try:
        mod = __import__(mods[cls_name], fromlist=[cls_name])
        sig = inspect.signature(getattr(mod, cls_name))
        out = {k: v.default for k, v in sig.parameters.items() if v.default is not inspect.Parameter.empty}
    except Exception:
        pass
    _DEFAULTS_CACHE[cls_name] = out
    return out
