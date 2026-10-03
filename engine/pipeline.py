"""End-to-end audit: paper + repo -> claims -> runs -> verdicts -> why.

    parse -> map -> triage -> static audit -> execute (seeds, self-heal)
          -> compare -> precision filter + attribution -> missing-detail inference
          -> leakage re-run -> fragility -> report

Deterministic everywhere except claim extraction/alignment, which in production
is an LLM step (see paper.py / vocab.py). Every finding shown to the user has a
re-run behind it, or is labelled as static-only.
"""
import math
import re
import time

from . import heal, leakage, paper as paperlib, repo as repolib, stats, validity, vocab
from .sandbox import Sandbox

SEEDS = list(range(10))
SCALED_SEEDS = list(range(5))
AXIS = {"seed": "seeds", "split": "alternative splits", "hparam": "hyperparameter perturbations"}
RAM_BUDGET = 128e6  # bytes a single sandboxed run may use for its data (browser-safe)
STAGES = [
    ("parse", "Parse paper", "Tables and setup sentences become structured claims"),
    ("map", "Map repo", "README commands, configs and AST link each claim to code"),
    ("triage", "CPU triage", "Decide full, scaled or untestable before spending compute"),
    ("static", "Static audit", "Paper-vs-code diff, leakage rules, metric and fairness checks"),
    ("execute", "Execute", "As-published run, then 10 seeds, with self-healing"),
    ("compare", "Compare", "Seed-aware verdict for every claim"),
    ("attribute", "Attribute", "Re-run each discrepancy; Shapley share of the gap"),
    ("infer", "Infer missing details", "GRIM check + sweep for values the paper omits"),
    ("validity", "Validity re-runs", "Leakage, duplicates, metric and baseline fairness: patch, re-run, measure"),
    ("fragility", "Fragility", "Seeds, splits and +/-10% hyperparameters"),
    ("report", "Report", "Claim Ledger, Replicability Index, issues, reproduce.sh"),
]


class Audit:
    def __init__(self, paper_text, repo_files, executor, emit=None, seeds=SEEDS, answer_key=None):
        self.emit_cb = emit or (lambda t, d: None)
        self.paper_text = paper_text
        self.original_files = dict(repo_files)
        self.repo_files = dict(repo_files)
        self.answer_key = answer_key
        self.seeds = seeds
        self.sandbox = Sandbox(self.repo_files, executor, emit=self._on_run)
        self.findings = []
        self.claim_state = {}
        self.t0 = time.perf_counter()

    # ------------------------------------------------------------------ plumbing
    def emit(self, kind, data):
        data = dict(data)
        data["t"] = round(time.perf_counter() - self.t0, 3)
        self.emit_cb(kind, data)

    def log(self, text, level="info", stage=None):
        self.emit("log", {"text": text, "level": level, "stage": stage or self.stage})

    def _on_run(self, kind, run):
        self.emit("run", {k: run[k] for k in ("id", "hash", "command", "label", "purpose", "claim", "cached",
                                               "returncode", "seconds", "edits", "patched_files")}
                  | {"stdout_tail": run["stdout"].strip().splitlines()[-1:] if run["stdout"].strip() else [],
                     "stderr_tail": run["stderr"].strip().splitlines()[-1:] if run["stderr"].strip() else []})

    def begin(self, stage):
        self.stage = stage
        self.emit("stage", {"id": stage, "status": "running"})

    def end(self, stage, summary=""):
        self.emit("stage", {"id": stage, "status": "done", "summary": summary})

    def add_finding(self, f):
        f.setdefault("id", f"F{len(self.findings) + 1}")
        f.setdefault("status", "confirmed")
        self.findings.append(f)
        self.emit("finding", f)
        return f

    def update_claim(self, cid, **kw):
        self.claim_state.setdefault(cid, {}).update(kw)
        self.emit("claim", {"id": cid, **self.claim_state[cid]})

    # ------------------------------------------------------------------ helpers
    def metric_from(self, run, claim, method=None):
        vals = []
        word = "f1" if "f1" in (claim.get("metric") or "") else "acc(?:uracy)?"
        for line in run["stdout"].splitlines():
            m = re.search(rf"([A-Za-z_\- ]*{word}[A-Za-z_\- ]*)[:=]\s*([0-9.]+)", line, re.I)
            if m:
                vals.append((line.strip(), float(m.group(2))))
        if method:
            al = vocab.METHODS[method]["aliases"]
            vals = [v for v in vals if any(a in v[0].lower() for a in al)] or vals
        if not vals:
            return None, None
        line, v = vals[0]
        return (v * 100 if v <= 1.0 else v), line

    def edits_for(self, cv, overrides):
        edits = []
        for p, val in overrides.items():
            src = cv.get(p)
            if not src:
                continue
            # keep the code's type: a paper's "3" must not become 3.0 for an int parameter
            if isinstance(src.get("value"), int) and not isinstance(src.get("value"), bool) \
                    and isinstance(val, float) and val.is_integer():
                val = int(val)
            new = _fmt(val)
            if src["where"] == "config":
                edits.append({"file": src["file"], "line": src["line"], "col": src["col"], "end_col": None,
                              "new": new, "why": f"{p} -> {new}"})
            elif src["where"] in ("code", "constant"):
                edits.append({"file": src["file"], "line": src["line"], "col": src["col"],
                              "end_col": src["end_col"], "new": new, "why": f"{p} -> {new}"})
            elif src["where"] == "default":
                line = self.repo_files[src["file"]].split("\n")[src["est_end_line"] - 1]
                close = src["est_end_col"] - 1
                sep = "" if line[:close].rstrip().endswith("(") else ", "
                edits.append({"file": src["file"], "line": src["est_end_line"], "col": close, "end_col": close,
                              "new": f"{sep}{p}={new}", "why": f"{p} -> {new} (was sklearn default)"})
        return edits

    def run_claim(self, claim, seed=None, overrides=None, label="", purpose="", patches=None, cv_all=None,
                  probe_opts=None):
        """Run the claim's command. seed=None keeps the code's own seed."""
        cmd = claim["_cmd"]
        cv_all = cv_all or claim["_cv"]
        edits, argv = list(claim.get("_base_edits") or []), []
        for meth, ov in (overrides or {}).items():
            edits += self.edits_for(cv_all.get(meth, cv_all.get("_shared", {})), ov)
        for flag, val in cmd["args"].items():
            if flag == "--seed":
                continue
            argv += [flag] if val is True else [flag, str(val)]
        plan = claim["_seeds"]
        if seed is not None:
            const = [s for s in plan["sites"] if s["kind"] == "constant"]
            arg = [s for s in plan["sites"] if s["kind"] == "argparse"]
            lit = [s for s in plan["sites"] if s["kind"] == "literal"]
            if const:
                for s in const:
                    edits.append({"file": s["file"], "line": s["line"], "col": s["col"], "end_col": s["end_col"],
                                  "new": str(seed), "why": f"seed -> {seed}"})
            elif arg:
                argv += [arg[0]["name"], str(seed)]
            elif lit:
                for s in lit:
                    edits.append({"file": s["file"], "line": s["line"], "col": s["col"], "end_col": s["end_col"],
                                  "new": str(seed), "why": f"seed -> {seed}"})
        elif "--seed" in cmd["args"]:
            argv += ["--seed", str(cmd["args"]["--seed"])]
        res = self.sandbox.run(cmd["script"], argv, edits, patches=patches or claim.get("_patches"),
                               label=label, purpose=purpose, claim=claim["id"], probe_opts=probe_opts)
        return res

    def seed_values(self, claim, overrides=None, purpose="", method=None, seeds=None, patches=None, cv_all=None,
                    probe_opts=None):
        out, runs = [], []
        for s in (seeds or claim.get("_seed_list") or self.seeds):
            r = self.run_claim(claim, seed=s, overrides=overrides, label=f"seed {s}", purpose=purpose,
                               patches=patches, cv_all=cv_all, probe_opts=probe_opts)
            v, _ = self.metric_from(r, claim, method)
            if v is not None:
                out.append(v)
                runs.append(r["id"])
        return out, runs

    # ------------------------------------------------------------------ main
    def run(self):
        self.emit("plan", {"stages": [{"id": s, "title": t, "desc": d} for s, t, d in STAGES],
                           "runtime": self.sandbox.versions, "executor": self.sandbox.executor.name})
        P = self.stage_parse()
        R = self.stage_map(P)
        self.stage_triage(P, R)
        self.stage_static(P, R)
        self.stage_execute(P)
        self.stage_compare(P)
        self.stage_attribute(P)
        self.stage_infer(P)
        self.stage_leakage(P)
        self.stage_fragility(P)
        result = self.stage_report(P, R)
        self.emit("done", {"ok": True})
        return result

    # ------------------------------------------------------------------ stages
    def stage_parse(self):
        self.begin("parse")
        P = paperlib.parse(self.paper_text)
        self.paper = P
        for c in P["claims"]:
            self.update_claim(c["id"], label=c["label"], kind=c["kind"], reported=c["value"], status="extracted",
                              source=c["source"], methods=c["methods"], dataset=c["dataset"], metric=c["metric"])
        self.log(f"{len(P['sentences'])} sentences, {len(P['tables'])} tables, "
                 f"{len(P['setup'])} stated settings, {len(P['claims'])} claims")
        for s in P["setup"]:
            self.log(f"stated: {s['param']} = {s['value']}  ({'global' if s['global'] else ', '.join(s['scope']) or ', '.join(s['datasets'])})")
        self.end("parse", f"{len(P['claims'])} claims, {len(P['setup'])} stated settings")
        return P

    def stated_for(self, P, claim, method=None):
        """Settings the paper states for this claim (and optionally one method).

        Global protocol sentences apply to every claim on their dataset. If a
        section is dedicated to the claim's dataset, only that section counts;
        otherwise a sentence applies through the methods it is scoped to."""
        dedicated = {s["id"] for s in P["sections"]
                     if claim["dataset"] and claim["dataset"] in vocab.datasets_in(s["heading"])}
        target = [method] if method else claim["methods"]
        out = {}
        for s in P["setup"]:
            if s["datasets"] and claim["dataset"] not in s["datasets"]:
                continue
            if not s["global"]:
                if dedicated:
                    if s["section"] not in dedicated:
                        continue
                    if s["scope"] and not set(s["scope"]) & set(target):
                        continue
                elif not s["scope"] or not set(s["scope"]) & set(target):
                    continue
            out.setdefault(s["param"], s)
        return out

    def stage_map(self, P):
        self.begin("map")
        R = repolib.load(self.repo_files)
        self.repo = R
        self.log(f"{len(R['scripts'])} scripts, {len(R['configs'])} configs, {len(R['commands'])} README commands")
        for c in P["claims"]:
            cmd, why = repolib.map_claim(R, c)
            c["_cmd"] = cmd
            if not cmd:
                self.update_claim(c["id"], status="unmapped")
                self.log(f"{c['id']}: no command found", "warn")
                continue
            cv = {}
            for m in c["methods"]:
                cv[m] = repolib.code_values(R, cmd, m) if R["scripts"][cmd["script"]]["estimators"] else {}
            shared = repolib.code_values(R, cmd, c["methods"][0]) if cv.get(c["methods"][0]) else {}
            cv["_shared"] = {k: v for k, v in shared.items() if k in ("test_size", "seeds")}
            if not shared:
                cv["_shared"] = {"seeds": repolib.seed_plan(R, cmd)}
            c["_cv"] = cv
            c["_seeds"] = cv["_shared"]["seeds"]
            self.update_claim(c["id"], status="mapped", command=cmd["command"], readme_line=cmd["line"], why=why,
                              code_values={("shared" if m == "_shared" else m): {p: _pub(v) for p, v in d.items()} for m, d in cv.items()})
            self.log(f"{c['id']} {c['label']} -> {cmd['command']}  [{'; '.join(why[:3])}]")
        self.end("map", f"{sum(1 for c in P['claims'] if c.get('_cmd'))}/{len(P['claims'])} claims mapped")
        return R

    def stage_triage(self, P, R):
        self.begin("triage")
        # packages in the sandbox image, plus the repo's own modules
        available = {"sklearn", "numpy", "scipy", "yaml", "argparse"} | {
            p.rsplit("/", 1)[-1][:-3] for p in self.repo_files if p.endswith(".py")}
        for c in P["claims"]:
            reasons = []
            cmd = c.get("_cmd")
            ds = vocab.DATASETS.get(c["dataset"] or "", {})
            if cmd:
                script = R["scripts"][cmd["script"]]
                mods = {i["module"].split(".")[0] for i in script["imports"] if i["module"]}
                missing = sorted(m for m in mods - available if m not in ("os", "sys", "math", "re", "json"))
                if missing:
                    reasons.append(f"imports {', '.join(missing)}: not in the CPU sandbox image")
                text = self.repo_files[cmd["script"]]
                for n, line in enumerate(text.splitlines(), 1):
                    if ".cuda()" in line:
                        reasons.append(f"GPU required: .cuda() at {cmd['script']}:{n}")
                        break
            else:
                reasons.append("no README command or script in the repo produces this claim")
            if ds and not ds.get("bundled"):
                reasons.append(f"dataset {ds['name']} is not available offline ({ds['size']})")
            estimate = None
            if c["dataset"] == "imagenet":
                # 3 x forward FLOPs per training image (ViT-B/16 forward ~17.6 GFLOPs, Dosovitskiy et al. 2021)
                flops = 3 * 17.6e9 * ds["n"] * 30
                cpu_days = flops / 1e11 / 86400
                estimate = {"flops": flops, "cpu_days": cpu_days,
                            "formula": "3 x 17.6 GFLOPs x 1.28M images x 30 epochs / 100 GFLOP/s CPU"}
                reasons.append(f"~{flops:.1e} FLOPs: about {cpu_days:,.0f} CPU-days at 100 GFLOP/s")
            mode = "untestable" if reasons else "full"
            # memory budget: a config that generates n_samples x n_features is scaled down to fit
            cfg_path = cmd["args"].get("--config") if cmd else None
            cfg = R["configs"].get(cfg_path, {}) if isinstance(cfg_path, str) else {}
            rows_key = next((k for k in ("n_samples", "n_rows") if k in cfg), None)
            scale = None
            if rows_key and mode == "full":
                rows = cfg[rows_key]["value"]
                feats = cfg.get("n_features", {}).get("value", 20)
                need = rows * feats * 8 * 3  # float64 data + split copies
                if need > RAM_BUDGET:
                    new_rows = max(10000, int(RAM_BUDGET / (feats * 8 * 3)) // 10000 * 10000)
                    mode = "scaled"
                    scale = {"param": rows_key, "file": cfg_path, "line": cfg[rows_key]["line"], "from": rows,
                             "to": new_rows, "ram_full_mb": need / 1e6, "ram_budget_mb": RAM_BUDGET / 1e6,
                             "seeds": len(SCALED_SEEDS)}
                    c["_base_edits"] = [{"file": cfg_path, "line": cfg[rows_key]["line"], "col": cfg[rows_key]["col"],
                                         "end_col": None, "new": str(new_rows), "why": f"scaled {rows_key} -> {new_rows}"}]
                    c["_seed_list"] = SCALED_SEEDS
                    reasons_scaled = (f"needs ~{need / 1e6:,.0f} MB for {rows:,} rows x {feats} features; "
                                      f"budget {RAM_BUDGET / 1e6:,.0f} MB, so run on {new_rows:,} rows "
                                      f"({100 * new_rows / rows:.0f}%) with {len(SCALED_SEEDS)} seeds")
            c["_mode"] = mode
            c["_scale"] = scale
            self.update_claim(c["id"], triage={"mode": mode, "reasons": reasons, "estimate": estimate,
                                               "rows": ds.get("n"), "scale": scale})
            if mode == "scaled":
                self.log(f"{c['id']} SCALED: {reasons_scaled}", "warn")
                self.update_claim(c["id"], triage={"mode": mode, "reasons": [reasons_scaled], "estimate": None,
                                                   "rows": ds.get("n"), "scale": scale})
            if mode == "untestable":
                self.update_claim(c["id"], verdict="untestable", status="untestable")
                self.add_finding({"sig": f"untestable:{c['id']}", "kind": "untestable", "severity": "info",
                                  "material": None, "title": f"{c['label']}: untestable on CPU",
                                  "detail": "; ".join(reasons), "claims": [c["id"]],
                                  "evidence": {"reasons": reasons, "estimate": estimate}})
                self.log(f"{c['id']} UNTESTABLE: {'; '.join(reasons)}", "warn")
            elif mode == "full":
                self.log(f"{c['id']} full run: {ds.get('name')} ({ds.get('n')} rows), sklearn on CPU")
        self.end("triage", f"{sum(c['_mode'] == 'full' for c in P['claims'])} full, "
                           + (f"{sum(c['_mode'] == 'scaled' for c in P['claims'])} scaled, "
                              if any(c['_mode'] == 'scaled' for c in P['claims']) else "")
                           + f"{sum(c['_mode'] == 'untestable' for c in P['claims'])} untestable")

    def stage_static(self, P, R):
        self.begin("static")
        diffs = {}
        for c in P["claims"]:
            if c["_mode"] == "untestable":
                continue
            for m in c["methods"]:
                stated = self.stated_for(P, c, m)
                cv = {**c["_cv"].get(m, {}), **c["_cv"]["_shared"]}
                for p in sorted(set(stated) | set(cv)):
                    if p not in vocab.SALIENT:
                        continue
                    sv, code = stated.get(p), cv.get(p)
                    if p not in vocab.METHODS[m]["params"] and p not in ("test_size", "seeds"):
                        continue
                    if sv and code:
                        if not _same(sv["value"], code["value"]):
                            if p == "seeds" and code["value"] < sv["value"]:
                                kind = "code_omission"
                            else:
                                kind = "difference"
                            key = (kind, p, code.get("file"), code.get("line"), m if kind == "difference" else "")
                            d = diffs.setdefault(key, {"kind": kind, "param": p, "method": m, "paper": sv,
                                                       "code": _pub(code), "claims": []})
                            d["claims"].append(c["id"])
                    elif code and not sv and code["where"] in ("config", "code", "constant"):
                        key = ("paper_omission", p, code.get("file"), code.get("line"), "")
                        d = diffs.setdefault(key, {"kind": "paper_omission", "param": p, "method": m, "paper": None,
                                                   "code": _pub(code), "claims": []})
                        d["claims"].append(c["id"])
        self.discrepancies = []
        for d in diffs.values():
            d["claims"] = sorted(set(d["claims"]), key=lambda x: int(x[1:]))
            if d["kind"] == "difference":
                title = f"{d['param']}: paper {d['paper']['value']} vs code {d['code']['value']}"
            elif d["kind"] == "paper_omission":
                title = f"{d['param']}: not stated in the paper (code uses {d['code']['value']})"
            else:
                title = f"seeds: paper averages {d['paper']['value']} seeds, code runs {d['code']['value']}"
            f = self.add_finding({
                "sig": f"{d['kind']}:{d['param']}", "kind": d["kind"], "severity": "pending", "material": None,
                "status": "testing", "title": title, "param": d["param"], "method": d["method"],
                "claims": d["claims"], "taxonomy": {"difference": "Difference", "paper_omission": "Paper omission",
                                                    "code_omission": "Code omission"}[d["kind"]],
                "evidence": {"paper": d["paper"], "code": d["code"]},
                "detail": (d["code"].get("note") if d["param"] == "seeds" else None) or "",
            })
            self.discrepancies.append(f)
            self.log(f"[{f['taxonomy']}] {title}  ->  queued for re-run test", "warn")

        # protocol risks stated in the paper itself (not visible in code): selection on the full data
        for sent in P["sentences"]:
            if PROTOCOL_RISK.search(sent["text"]):
                ds = vocab.datasets_in(sent["text"]) or [d for d in {c["dataset"] for c in P["claims"]} if d]
                sec_methods = paperlib.section_methods(P, sent["section"])
                hit = [c["id"] for c in P["claims"] if c["_mode"] != "untestable" and (not sec_methods or set(sec_methods) & set(c["methods"]))
                       and (c["dataset"] in ds) and _same_scope(P, c, sent)]
                if not hit:
                    continue
                self.add_finding({"sig": "protocol:selection", "kind": "protocol_risk", "severity": "medium",
                                  "material": None, "status": "unmeasured",
                                  "title": "Protocol risk: features chosen by searching the same data used for evaluation",
                                  "detail": f"The paper says: \"{sent['text']}\" If that search ran on all cases before "
                                            f"cross-validation, the reported accuracy is optimistic (Kapoor & Narayanan L1.3, "
                                            f"at the protocol level). The selection code was not released, so the size of "
                                            f"the effect cannot be re-run.",
                                  "claims": hit, "taxonomy": "Leakage risk (from the paper text)",
                                  "evidence": {"paper": {"sentence": sent["id"], "text": sent["text"]}}})
                self.log(f"[Protocol risk] {sent['id']}: selection over the full dataset described in the paper", "warn")

        # leakage rules over every script that produces a claim
        self.leaks = {}
        for c in P["claims"]:
            if c["_mode"] == "untestable":
                continue
            path = c["_cmd"]["script"]
            if path in self.leaks:
                continue
            found = leakage.audit_script(path, self.repo_files[path])
            for mod in repolib.local_modules(R, path):
                found += leakage.audit_script(mod, self.repo_files[mod])
            self.leaks[path] = found
            for lf in found:
                self.log(f"[Leakage {lf['rule']}] {lf['file']}:{lf['line']}  {lf['code']}", "warn")
        checked = sorted({c["_cmd"]["script"] for c in P["claims"] if c["_mode"] == "full"})
        self.static_checks = {"leakage_rules": list(leakage.TAXONOMY.items()), "scripts": checked}

        # fair tuning budget for comparative claims
        self.fairness = []
        for c in P["claims"]:
            if c["kind"] != "comparison" or c["_mode"] == "untestable":
                continue
            script = R["scripts"][c["_cmd"]["script"]]
            budget, searches = {m: 1 for m in c["methods"]}, {}
            for m in c["methods"]:
                for sr in script["searches"]:
                    if set(sr["classes"]) & set(vocab.METHODS[m]["classes"]):
                        budget[m] = sr["size"]
                        searches[m] = sr
            fair = len(set(budget.values())) == 1
            self.fairness.append({"claim": c["id"], "budget": budget, "fair": fair, "searches": searches})
            self.log(f"fair-baseline check {c['id']}: tuning budget "
                     + ", ".join(f"{vocab.METHODS[m]['name']} {b} config{'s' if b != 1 else ''}" for m, b in budget.items())
                     + f" -> {'equal' if fair else 'UNEQUAL'}", "info" if fair else "warn")

        # metric implementation audit
        self.metric_checks = []
        for c in P["claims"]:
            if c["_mode"] == "untestable":
                continue
            text = self.repo_files[c["_cmd"]["script"]]
            ok, mismatch = True, None
            note = "accuracy computed with estimator.score on the test split"
            calls = R["scripts"][c["_cmd"]["script"]]["metric_calls"]
            if c["metric"] in ("macro_f1", "f1"):
                note = "F1 averaging matches the paper"
                want = "macro" if c["metric"] == "macro_f1" else None
                for mc in calls:
                    if want and mc["average"] != want:
                        ok = False
                        mismatch = {**mc, "file": c["_cmd"]["script"], "want": want}
                        note = (f"paper reports {want}-F1 but {c['_cmd']['script']}:{mc['line']} computes "
                                f"{mc['func']}(average={mc['average']!r})")
                        self.log(f"[Metric] {note}", "warn")
            c["_metric_mismatch"] = mismatch
            if re.search(r"score\(\s*X_val", text) and "test" in c["source"].get("caption", "").lower():
                ok, note = False, "paper reports test accuracy but code scores the validation split"
            self.metric_checks.append({"claim": c["id"], "ok": ok, "note": note})

        # environment
        self.env = []
        for req in R["requirements"]:
            runtime = self.sandbox.versions
            have = {"scikit-learn": runtime["sklearn"], "numpy": runtime["numpy"]}.get(req["name"])
            if req["version"] and have and req["version"] != have:
                self.env.append({"package": req["name"], "pinned": req["version"], "runtime": have,
                                 "line": req["line"]})
                self.log(f"requirements.txt:{req['line']} pins {req['name']}=={req['version']}; "
                         f"no wheel for Python {runtime['python']}. Running on {have} instead.", "warn")
        self.end("static", f"{len(self.discrepancies)} discrepancies, {sum(len(v) for v in self.leaks.values())} leakage hits")

    def stage_execute(self, P):
        self.begin("execute")
        self.impediments = []
        for c in P["claims"]:
            if c["_mode"] == "untestable":
                continue
            method = c["methods"][0] if c["kind"] == "value" else None
            # as published: the code's own seed, healing if it crashes
            r = self.run_claim(c, seed=None, label="as published", purpose="as-published")
            attempts = 0
            while r["returncode"] != 0 and attempts < 3:
                attempts += 1
                rule, last = heal.diagnose(r["stderr"])
                self.log(f"{c['id']} crashed: {last}", "error")
                if not rule:
                    break
                files = {**self.repo_files, **(c.get("_patches") or {})}
                patch, diff = heal.propose_patch(rule, files, r["stderr"])
                if not patch:
                    break
                c["_patches"] = {**(c.get("_patches") or {}), **patch}
                # patched files become the repo for every later run of every claim
                self.repo_files.update(patch)
                self.sandbox.files.update(patch)
                imp = next((i for i in self.impediments if i["rule"] == rule["id"]), None)
                if not imp:
                    imp = {"rule": rule["id"], "title": rule["title"], "error": last, "diff": diff,
                           "file": list(patch)[0], "claims": []}
                    self.impediments.append(imp)
                    self.add_finding({"sig": f"env:{rule['id']}", "kind": "env_impediment", "severity": rule["severity"],
                                      "material": False, "title": f"Crash out of the box: {rule['title']}",
                                      "detail": f"Self-healed: patched {list(patch)[0]} and re-ran. "
                                                f"Does not change the reported number.",
                                      "claims": [c["id"]], "taxonomy": "Impediment",
                                      "evidence": {"error": last, "stderr": r["stderr"][-900:], "diff": diff}})
                imp["claims"].append(c["id"])
                self.log(f"self-heal: {rule['title']} -> patched {list(patch)[0]}, re-running", "heal")
                r = self.run_claim(c, seed=None, label="as published (healed)", purpose="as-published")
            v, line = self.metric_from(r, c, method)
            c["_published"] = {"run": r["id"], "value": v, "line": line, "hash": r["hash"], "command": r["command"],
                               "stdout": r["stdout"], "probe": r["probe"]}
            if r["returncode"] != 0 or v is None:
                self.update_claim(c["id"], status="failed", verdict="untestable")
                continue
            if c["kind"] == "comparison":
                va, _ = self.metric_from(r, c, c["a"])
                vb, _ = self.metric_from(r, c, c["b"])
                c["_published"]["value"] = va - vb
                c["_published"]["parts"] = {c["a"]: va, c["b"]: vb}
                a_vals, runs = self.seed_values(c, purpose="seed sweep", method=c["a"])
                b_vals, _ = self.seed_values(c, purpose="seed sweep", method=c["b"])
                c["_seedvals"] = [x - y for x, y in zip(a_vals, b_vals)]
                c["_parts"] = {c["a"]: a_vals, c["b"]: b_vals}
                c["_seedruns"] = runs
            else:
                vals, runs = self.seed_values(c, purpose="seed sweep", method=method)
                c["_seedvals"], c["_seedruns"] = vals, runs
            self.update_claim(c["id"], status="executed", published=_pub(c["_published"]),
                              seeds=self.seeds, values=c["_seedvals"], parts=c.get("_parts"))
            self.log(f"{c['id']} as published: {c['_published']['value']:.2f}  |  "
                     f"10 seeds: {stats.mean_std(c['_seedvals'])[0]:.2f} ± {stats.mean_std(c['_seedvals'])[1]:.2f}")
        self.end("execute", f"{len(self.sandbox.runs)} runs, {sum(r['cached'] for r in self.sandbox.runs)} cache hits")

    def k_for(self, P, c):
        s = self.stated_for(P, c).get("seeds")
        return s["value"] if s else 1

    def stage_compare(self, P):
        self.begin("compare")
        for c in P["claims"]:
            if "_seedvals" not in c:
                continue
            k = self.k_for(P, c)
            v = stats.verdict(c["value"], c["_seedvals"], k, scaled=c["_mode"] == "scaled")
            c["_verdict"] = v
            # a comparison margin is the difference of two rounded numbers: twice the rounding slack
            slack = 0.5 * 10 ** (-c["decimals"]) * (2 if c["kind"] == "comparison" else 1) + 1e-9
            exact = c["_published"]["value"] is not None and abs(c["_published"]["value"] - c["value"]) < slack
            c["_exact_published"] = exact
            self.update_claim(c["id"], verdict=v["verdict"], stats=v, k=k, published_matches=exact)
            self.log(f"{c['id']} reported {c['value']:.2f} vs {v['mean']:.2f} ± {v['sd']:.2f} "
                     f"(tolerance ±{v['tol']:.2f} for a {k}-seed mean) -> {v['verdict'].upper()}",
                     "ok" if v["verdict"] == "reproduced" else "warn")
        self.end("compare", ", ".join(f"{c['id']} {c['_verdict']['verdict']}" for c in P["claims"] if "_verdict" in c))

    def stage_attribute(self, P):
        self.begin("attribute")
        self.attributions = {}
        for f in self.discrepancies:
            if f["kind"] != "difference":
                continue
            # test the swap on the first runnable claim it affects
            c = next(x for x in P["claims"] if x["id"] in f["claims"] and "_seedvals" in x)
            base = c["_seedvals"]
            m0, sd0 = stats.mean_std(base)
            se = sd0 / math.sqrt(len(base))
            vals, runs = self.seed_values(c, overrides={f["method"]: {f["param"]: f["evidence"]["paper"]["value"]}},
                                          purpose=f"swap {f['param']}", method=c["methods"][0] if c["kind"] == "value" else None)
            if not vals:
                f["status"], f["material"], f["severity"] = "run_failed", None, "medium"
                f["detail"] = "Re-running with the paper's value crashed; see the run log. Impact not measured."
                self.emit("finding", f)
                self.log(f"swap test for {f['param']} crashed; impact not measured", "error")
                continue
            m1, _ = stats.mean_std(vals)
            effect = m1 - m0
            material = abs(effect) >= max(se, 0.1)
            f["effect"] = {"claim": c["id"], "before": m0, "after": m1, "delta": effect, "noise_se": se, "runs": runs,
                           "values": vals}
            f["material"] = material
            f["status"] = "confirmed" if material else "immaterial"
            f["severity"] = ("high" if abs(effect) >= 1 else "medium") if material else "none"
            self.emit("finding", f)
            self.log(f"precision filter: {f['param']} swap moves {c['id']} by {effect:+.2f} pt "
                     f"(noise SE {se:.2f}) -> {'MATERIAL' if material else 'immaterial, downgraded'}",
                     "warn" if material else "ok")
        # Shapley over each not-reproduced claim's differences
        for c in P["claims"]:
            if c.get("_verdict", {}).get("verdict") != "not_reproduced":
                continue
            ds = [f for f in self.discrepancies if f["kind"] == "difference" and c["id"] in f["claims"]]
            if not ds or len(ds) > 4:
                continue
            method = c["methods"][0] if c["kind"] == "value" else None
            cache = {}

            def value(S):
                key = frozenset(S)
                if key not in cache:
                    if not key:
                        cache[key] = stats.mean_std(c["_seedvals"])[0]
                    else:
                        ov = {}
                        for fid in key:
                            f = next(x for x in ds if x["id"] == fid)
                            ov.setdefault(f["method"], {})[f["param"]] = f["evidence"]["paper"]["value"]
                        vals, _ = self.seed_values(c, overrides=ov, purpose="shapley " + "+".join(sorted(key)),
                                                   method=method)
                        cache[key] = stats.mean_std(vals)[0]
                return cache[key]

            ids = [f["id"] for f in ds]
            phi = stats.shapley(ids, value)
            base = value(frozenset())
            full = value(frozenset(ids))
            gap = c["value"] - base
            # at the code's own seed with all paper values: does it hit the number exactly?
            ov = {}
            for f in ds:
                ov.setdefault(f["method"], {})[f["param"]] = f["evidence"]["paper"]["value"]
            r = self.run_claim(c, seed=None, overrides=ov, label="paper values @ code seed", purpose="attribution check")
            at_seed, _ = self.metric_from(r, c, method)
            att = {"claim": c["id"], "reported": c["value"], "base": base, "full": full, "gap": gap,
                   "parts": [{"finding": fid, "param": next(f["param"] for f in ds if f["id"] == fid),
                              "phi": phi[fid], "share": phi[fid] / gap if gap else 0} for fid in ids],
                   "residual": c["value"] - full,
                   "subsets": [{"set": sorted(k), "mean": v} for k, v in cache.items()],
                   "at_code_seed": at_seed, "at_code_seed_run": r["id"]}
            self.attributions[c["id"]] = att
            top = max(att["parts"], key=lambda p: abs(p["phi"]))
            self.update_claim(c["id"], attribution=att,
                              cause=f"{top['param']} mismatch explains {100 * top['share']:.0f}% of the {gap:.2f}-pt gap")
            self.log(f"{c['id']} gap {gap:.2f} pt: " + ", ".join(
                f"{p['param']} {p['phi']:+.2f} ({100 * p['share']:.0f}%)" for p in att["parts"]) +
                     f", residual {att['residual']:+.2f}", "warn")
        # not reproduced and nothing in the code differs: was the number one lucky seed?
        for c in P["claims"]:
            v = c.get("_verdict", {}).get("verdict")
            if v == "not_reproduced" and c["id"] not in self.attributions and c.get("_exact_published"):
                vals = c["_seedvals"]
                pct = stats.percentile_rank(c["value"], vals)
                cause = (f"the code's single hardcoded seed reproduces {c['value']:.2f} exactly; "
                         f"across {len(vals)} seeds it is {stats.mean_std(vals)[0]:.2f} ± {stats.mean_std(vals)[1]:.2f}"
                         f" (reported value at the {pct:.0f}th percentile)")
                self.update_claim(c["id"], cause="single-seed result: " + cause, seed_percentile=pct)
                c["_seed_selected"] = True
                self.log(f"{c['id']}: {cause}", "warn")
        self.end("attribute", f"{sum(1 for f in self.discrepancies if f['material'])} material, "
                              f"{sum(1 for f in self.discrepancies if f['material'] is False)} immaterial")

    def stage_infer(self, P):
        self.begin("infer")
        self.inferences = []
        for f in self.discrepancies:
            if f["kind"] == "code_omission" and f["param"] == "seeds":
                hits, fixed_hits = [], []
                for c in P["claims"]:
                    if c["id"] not in f["claims"]:
                        continue
                    if c.get("_exact_published"):
                        hits.append(c["id"])
                    att = self.attributions.get(c["id"])
                    if att and att["at_code_seed"] is not None and abs(att["at_code_seed"] - c["value"]) < 0.5 * 10 ** (-c["decimals"]):
                        fixed_hits.append(c["id"])
                f["material"] = True
                f["status"] = "confirmed"
                f["severity"] = "medium"
                f["detail"] = (f"Paper reports {f['evidence']['paper']['value']}-seed means; code has "
                               f"{f['evidence']['code'].get('note', 'one seed')}. The single-seed run reproduces "
                               f"{len(hits)}/{len(f['claims'])} reported numbers exactly"
                               + (f" ({', '.join(fixed_hits)} also, once the material discrepancy is corrected)" if fixed_hits else "")
                               + ", so the table is single-seed output, not a multi-seed mean.")
                f["exact_hits"] = hits
                f["exact_hits_after_fix"] = fixed_hits
                self.emit("finding", f)
                self.log(f"seeds: {len(hits)} of {len(f['claims'])} reported numbers equal the code's single-seed output exactly", "warn")
                continue
            if f["kind"] != "paper_omission":
                continue
            c = next(x for x in P["claims"] if x["id"] in f["claims"] and "_seedvals" in x)
            method = c["methods"][0] if c["kind"] == "value" else None
            p, cur = f["param"], f["evidence"]["code"]["value"]
            # paper values for this claim's other differences: infer under the paper's own setup
            ov_base = {}
            for d in self.discrepancies:
                if d["kind"] == "difference" and c["id"] in d["claims"] and d["material"]:
                    ov_base.setdefault(d["method"], {})[d["param"]] = d["evidence"]["paper"]["value"]
            if p == "test_size":
                n = vocab.DATASETS[c["dataset"]]["n"]
                k = self.k_for(P, c)
                cands = []
                for ts in [0.1, 0.15, 0.2, 0.25, 0.3, 0.33]:
                    n_test = math.ceil(ts * n)
                    ok1, hits1 = stats.grim_consistent(c["value"], c["decimals"], n_test)
                    okk, _ = stats.grim_consistent(c["value"], c["decimals"], n_test * k)
                    cands.append({"value": ts, "n_test": n_test, "grim": ok1 or okk, "grim_single": ok1,
                                  "fraction": f"{hits1[0]}/{n_test}" if hits1 else None})
                tested = []
                for cd in cands:
                    if not cd["grim"]:
                        self.log(f"GRIM: test_size={cd['value']} (n_test={cd['n_test']}) cannot produce {c['value']:.2f}", "info")
                        continue
                    ov = {m: dict(o) for m, o in ov_base.items()}
                    ov.setdefault("_shared", {})["test_size"] = cd["value"]
                    vals, runs = self.seed_values(c, overrides=ov, purpose=f"infer test_size={cd['value']}",
                                                  method=method)
                    r = self.run_claim(c, seed=None, overrides=ov, label=f"test_size={cd['value']} @ code seed",
                                       purpose="infer")
                    at_seed, _ = self.metric_from(r, c, method)
                    m_, sd_ = stats.mean_std(vals)
                    cd.update({"mean": m_, "sd": sd_, "at_code_seed": at_seed, "runs": runs})
                    tested.append(cd)
                    self.log(f"test_size={cd['value']}: GRIM ok ({cd['fraction']}), 10-seed mean {m_:.2f}, "
                             f"code seed {at_seed:.2f}")
                best = min(tested, key=lambda d: (abs(d["at_code_seed"] - c["value"]) > 0.005, abs(d["mean"] - c["value"])))
                spread = max(d["mean"] for d in tested) - min(d["mean"] for d in tested)
                material = spread >= 0.5
                inf = {"finding": f["id"], "param": p, "claim": c["id"], "candidates": cands, "best": best["value"],
                       "current": cur, "spread": spread, "method": "GRIM consistency + sweep"}
                f["inference"] = inf
                f["material"] = material
                f["status"] = "confirmed" if material else "immaterial"
                f["severity"] = "medium" if material else "none"
                f["detail"] = (f"Only {sum(d['grim'] for d in cands)} of {len(cands)} common split ratios can produce "
                               f"{c['value']:.2f} (GRIM). Sweeping them moves the result by {spread:.2f} pt. "
                               f"Most likely value: {p}={best['value']}.")
                self.inferences.append(inf)
                self.emit("finding", f)
                self.log(f"inferred {p} = {best['value']} (sweep spread {spread:.2f} pt -> "
                         f"{'material' if material else 'immaterial'})", "warn" if material else "ok")
            else:
                cands = [cur / 10, cur, cur * 10] if isinstance(cur, (int, float)) else [cur]
                if isinstance(cur, int):
                    cands = [max(1, cur // 10), cur, cur * 10]
                tested = []
                for val in cands:
                    vals, runs = self.seed_values(c, overrides={f["method"]: {p: val}}, purpose=f"infer {p}={val}",
                                                  method=method)
                    tested.append({"value": val, "mean": stats.mean_std(vals)[0]})
                spread = max(d["mean"] for d in tested) - min(d["mean"] for d in tested)
                material = spread >= 0.5
                f["inference"] = {"param": p, "claim": c["id"], "candidates": tested, "spread": spread,
                                  "method": "sweep"}
                f["material"] = material
                f["status"] = "confirmed" if material else "immaterial"
                f["severity"] = "low" if material else "none"
                f["detail"] = (f"The paper never states {p}; the code uses {cur}. Re-running with "
                               + ", ".join(f"{d['value']} -> {d['mean']:.2f}" for d in tested)
                               + f" moves the result {spread:.2f} pt, "
                               + ("so the omission matters." if material else "within noise, so it is downgraded."))
                self.emit("finding", f)
                self.log(f"{p} omitted: sweep {[d['value'] for d in tested]} moves result {spread:.2f} pt -> "
                         f"{'material' if material else 'immaterial, downgraded'}", "warn" if material else "ok")
        self.end("infer", f"{len(self.inferences)} values inferred")

    def stage_leakage(self, P):
        self.begin("validity")
        self.leak_results = {}
        self._leak_done = set()
        for c in P["claims"]:
            if "_seedvals" not in c:
                continue
            path = c["_cmd"]["script"]
            if path in self._leak_done:
                continue
            self._leak_done.add(path)
            for lf in self.leaks.get(path, []):
                if lf["rule"] not in ("L1.2", "L1.3") or "_leak" not in lf:
                    continue
                rt = leakage.runtime_confirms(c["_published"]["probe"])
                new_text, diff = leakage.autopatch(lf["file"], self.repo_files[lf["file"]], lf)
                if not new_text:
                    confirmed = bool(rt and rt["fit_before_split"])
                    self.add_finding({"sig": f"leakage:{lf['rule']}", "kind": "leakage", "severity": "high",
                                      "material": None, "status": "unmeasured",
                                      "title": f"Leakage {lf['rule']}: {lf['title']}",
                                      "detail": f"{lf['explain']} "
                                                + ("The runtime probe confirms it. " if confirmed else "")
                                                + "Impact not measured: the automatic patch needs the estimator in the "
                                                  "same function as the leaky step.",
                                      "claims": [c["id"]], "taxonomy": "Leakage (Kapoor & Narayanan)",
                                      "evidence": leakage.public(lf) | {"runtime": rt}})
                    self.log(f"{c['id']}: leakage {lf['rule']} at {lf['file']}:{lf['line']} (impact not measured)", "error")
                    continue
                self.log(f"auto-patch {lf['file']}: move {lf['class']} into a Pipeline fitted after the split")
                vals, runs = self.seed_values(c, purpose="leak fixed", patches={lf["file"]: new_text},
                                              method=c["methods"][0] if c["kind"] == "value" else None)
                rfix = self.run_claim(c, seed=None, patches={lf["file"]: new_text}, label="leak fixed @ code seed",
                                      purpose="leak fixed")
                rt_fixed = leakage.runtime_confirms(rfix["probe"])
                before = stats.mean_std(c["_seedvals"])
                after = stats.mean_std(vals)
                res = {"claim": c["id"], "rule": lf["rule"], "title": lf["title"], "file": lf["file"], "line": lf["line"],
                       "code": lf["code"], "explain": lf["explain"], "diff": diff, "before": before, "after": after,
                       "inflation": before[0] - after[0], "values_fixed": vals, "runs": runs, "runtime": rt,
                       "runtime_fixed": rt_fixed, "reported": c["value"]}
                self.leak_results[c["id"]] = res
                material = res["inflation"] >= stats.tolerance(before[1], self.k_for(P, c))
                self.add_finding({"sig": f"leakage:{lf['rule']}", "kind": "leakage",
                                  "severity": "critical" if material else "low", "material": material,
                                  "title": f"Leakage {lf['rule']}: {lf['title']}",
                                  "detail": f"{lf['explain']} Fixing it drops accuracy from {before[0]:.2f} to "
                                            f"{after[0]:.2f} ({res['inflation']:.1f} pt inflation).",
                                  "claims": [c["id"]], "taxonomy": "Leakage (Kapoor & Narayanan)",
                                  "evidence": leakage.public(lf) | {"diff": diff, "runtime": rt}})
                self.update_claim(c["id"], leakage=res, validity="inflated" if material else "ok")
                self.log(f"{c['id']}: reproduces at {before[0]:.2f}, but with the leak fixed: {after[0]:.2f} ± {after[1]:.2f}"
                         f"  ->  inflated by {res['inflation']:.1f} pt", "error")
        self.validity_duplicates(P)
        self.validity_metric(P)
        self.validity_fairness(P)
        n = len(self.leak_results) + len(self.metric_results) + len(self.fair_results)
        self.end("validity", f"{n} validity re-run{'s' if n != 1 else ''}" if n else "no validity issues found")

    def validity_duplicates(self, P):
        """L1.4: rows that sit in both train and test. The probe drops them at runtime and we re-run."""
        done = set()
        for c in P["claims"]:
            if "_seedvals" not in c or c["_cmd"]["script"] in done:
                continue
            sp = next((e for e in c["_published"]["probe"] if e["event"] == "split"), None)
            if not sp:
                continue
            self.update_claim(c["id"], overlap=sp)
            if not sp.get("overlap_rows"):
                continue
            done.add(c["_cmd"]["script"])
            method = c["methods"][0] if c["kind"] == "value" else None
            self.log(f"{c['id']}: {sp['overlap_rows']} of {sp['n_test']} test rows are exact copies of training rows; "
                     f"re-running with them removed", "warn")
            vals, runs = self.seed_values(c, purpose="duplicates removed", method=method, probe_opts={"dedupe": True})
            before, after = stats.mean_std(c["_seedvals"]), stats.mean_std(vals)
            k = self.k_for(P, c)
            res = {"claim": c["id"], "rule": "L1.4", "title": leakage.TAXONOMY["L1.4"], "file": c["_cmd"]["script"],
                   "line": None, "code": None, "diff": None, "before": before, "after": after,
                   "inflation": before[0] - after[0], "values_fixed": vals, "runs": runs, "runtime": None,
                   "runtime_fixed": None, "reported": c["value"], "overlap": sp,
                   "explain": f"{sp['overlap_rows']} of the {sp['n_test']} test rows are byte-identical to training "
                              f"rows (row-hash probe on train_test_split), so the model is partly tested on data it "
                              f"has already seen."}
            material = res["inflation"] >= stats.tolerance(before[1], k)
            self.leak_results[c["id"]] = res
            self.add_finding({"sig": "leakage:L1.4", "kind": "leakage", "severity": "critical" if material else "low",
                              "material": material, "title": "Leakage L1.4: duplicate rows across train and test",
                              "detail": f"{res['explain']} Removing them drops accuracy from {before[0]:.2f} to "
                                        f"{after[0]:.2f} ({res['inflation']:.1f} pt inflation).",
                              "claims": [c["id"]], "taxonomy": "Leakage (Kapoor & Narayanan)",
                              "evidence": {"rule": "L1.4", "file": c["_cmd"]["script"], "line": None, "overlap": sp}})
            self.update_claim(c["id"], leakage=res, validity="inflated" if material else "ok")
            self.log(f"{c['id']}: with duplicates removed {after[0]:.2f} ± {after[1]:.2f} -> inflated by "
                     f"{res['inflation']:.1f} pt", "error")

    def validity_metric(self, P):
        """The paper names one metric, the code computes another: patch the call and re-run."""
        self.metric_results = {}
        for c in P["claims"]:
            mm = c.get("_metric_mismatch")
            if not mm or "_seedvals" not in c:
                continue
            new, diff = validity.metric_patch(mm["file"], self.repo_files[mm["file"]], mm, mm["want"])
            vals, runs = self.seed_values(c, purpose=f"metric average={mm['want']}", patches={mm["file"]: new},
                                          method=c["methods"][0] if c["kind"] == "value" else None)
            before, after = stats.mean_std(c["_seedvals"]), stats.mean_std(vals)
            k = self.k_for(P, c)
            delta = before[0] - after[0]
            material = abs(delta) >= stats.tolerance(after[1], k)
            code_line = self.repo_files[mm["file"]].splitlines()[mm["line"] - 1].strip()
            res = {"claim": c["id"], "file": mm["file"], "line": mm["line"], "func": mm["func"], "had": mm["average"],
                   "want": mm["want"], "diff": diff, "before": before, "after": after, "delta": delta,
                   "values_fixed": vals, "runs": runs, "reported": c["value"], "code": code_line}
            self.metric_results[c["id"]] = res
            self.add_finding({"sig": f"metric:{c['metric']}", "kind": "metric_mismatch",
                              "severity": "high" if material else "low", "material": material,
                              "title": f"Metric mismatch: paper reports {mm['want']}-F1, code computes "
                                       f"{mm['average']}-F1",
                              "detail": f"{mm['file']}:{mm['line']} calls {mm['func']}(average={mm['average']!r}) but "
                                        f"labels the result macro-F1. The reported {c['value']:.2f} is the {mm['average']} "
                                        f"score; the {mm['want']}-F1 the paper names is {after[0]:.2f} ± {after[1]:.2f} "
                                        f"({-delta:+.1f} pt).",
                              "claims": [c["id"]], "taxonomy": "Metric audit",
                              "evidence": {"file": mm["file"], "line": mm["line"], "diff": diff, "code": code_line}})
            self.update_claim(c["id"], metric_fix=res, validity="mislabelled" if material else "ok")
            self.log(f"{c['id']}: reported number is {mm['average']}-F1; true {mm['want']}-F1 = {after[0]:.2f} "
                     f"({-delta:+.1f} pt)", "error" if material else "ok")

    def validity_fairness(self, P):
        """Unequal tuning budgets: give the baseline the same budget and re-run the comparison."""
        self.fair_results = {}
        for fa in self.fairness:
            if fa["fair"]:
                continue
            c = next(x for x in P["claims"] if x["id"] == fa["claim"])
            if "_seedvals" not in c:
                continue
            prop = max(fa["budget"], key=lambda m: fa["budget"][m])
            base = min(fa["budget"], key=lambda m: fa["budget"][m])
            sr = fa["searches"][prop]
            path = c["_cmd"]["script"]
            new, diff, det = validity.equal_budget_patch(path, self.repo_files[path], vocab.METHODS[base]["classes"],
                                                         sr["size"], sr["cv"])
            if not new:
                continue
            self.log(f"{c['id']}: giving {vocab.METHODS[base]['name']} the same budget "
                     f"({sr['size']} configs, {det['param']} over {validity.fmt_values(det['values'])}) and re-running")
            a_vals, runs = self.seed_values(c, purpose="equal tuning budget", patches={path: new}, method=c["a"])
            b_vals, _ = self.seed_values(c, purpose="equal tuning budget", patches={path: new}, method=c["b"])
            margins = [x - y for x, y in zip(a_vals, b_vals)]
            before, after = stats.mean_std(c["_seedvals"]), stats.mean_std(margins)
            wins_before = sum(m > 1e-9 for m in c["_seedvals"])
            wins_after = sum(m > 1e-9 for m in margins)
            k = self.k_for(P, c)
            flipped = (before[0] > 0) != (after[0] > 0)
            material = flipped or (before[0] - after[0]) >= stats.tolerance(after[1], k)
            res = {"claim": c["id"], "proposed": prop, "baseline": base, "budget": fa["budget"], "search": sr,
                   "patch": det, "diff": diff, "before": before, "after": after, "margins": margins,
                   "wins_before": wins_before, "wins_after": wins_after, "n": len(margins), "runs": runs,
                   "baseline_before": stats.mean_std(c["_parts"][base]), "baseline_after": stats.mean_std(b_vals),
                   "proposed_after": stats.mean_std(a_vals)}
            self.fair_results[c["id"]] = res
            pn, bn = vocab.METHODS[prop]["name"], vocab.METHODS[base]["name"]
            self.add_finding({"sig": f"unfair_baseline:{c['id']}", "kind": "unfair_baseline",
                              "severity": "high" if material else "low", "material": material,
                              "title": f"Unfair baseline: {pn} tuned over {sr['size']} configs, {bn} over 1",
                              "detail": f"With the same budget for {bn}, the margin goes from {before[0]:+.2f} to "
                                        f"{after[0]:+.2f} pt, and {pn} wins {wins_after}/{len(margins)} seeds instead of "
                                        f"{wins_before}/{len(margins)}."
                                        + (" The claimed improvement does not survive a fair comparison." if material else ""),
                              "claims": [c["id"]], "taxonomy": "Fair-baseline check",
                              "evidence": {"file": path, "line": det["line"], "diff": diff}})
            self.update_claim(c["id"], fairness=res, validity="unfair" if material else "ok")
            if material:
                self.update_claim(c["id"], cause=f"unequal tuning budget: with the baseline tuned too, the margin is "
                                                 f"{after[0]:+.2f} pt ({pn} wins {wins_after}/{len(margins)} seeds)")
            self.log(f"{c['id']}: equal budget -> margin {after[0]:+.2f} (was {before[0]:+.2f}); wins "
                     f"{wins_after}/{len(margins)} (was {wins_before}/{len(margins)})", "error" if material else "ok")

    def stage_fragility(self, P):
        self.begin("fragility")
        self.fragility = {}
        for c in P["claims"]:
            if c["kind"] != "comparison" or "_seedvals" not in c:
                continue
            conds = []
            for s, d in zip(self.seeds, c["_seedvals"]):
                conds.append({"axis": "seed", "label": f"seed {s}", "margin": d})
            five = self.seeds[:5]
            cur_ts = c["_cv"]["_shared"].get("test_size", {}).get("value", 0.2)
            alts = [t for t in (0.2, 0.25, 0.3) if abs(t - cur_ts) > 1e-9][:2]
            for ts in alts:
                a, _ = self.seed_values(c, overrides={"_shared": {"test_size": ts}, c["a"]: {}}, seeds=five,
                                        purpose=f"fragility split {ts}", method=c["a"])
                b, _ = self.seed_values(c, overrides={"_shared": {"test_size": ts}, c["a"]: {}}, seeds=five,
                                        purpose=f"fragility split {ts}", method=c["b"])
                for s, x, y in zip(five, a, b):
                    conds.append({"axis": "split", "label": f"test {int(ts * 100)}% / seed {s}", "margin": x - y})
            key = next((p for p in vocab.METHODS[c["a"]]["params"] if isinstance(c["_cv"][c["a"]].get(p, {}).get("value"), float)), None)
            if key:
                base_v = c["_cv"][c["a"]][key]["value"]
                for mult in (0.9, 1.1):
                    val = round(base_v * mult, 6)
                    a, _ = self.seed_values(c, overrides={c["a"]: {key: val}}, seeds=five,
                                            purpose=f"fragility {key}={val}", method=c["a"])
                    b, _ = self.seed_values(c, overrides={c["a"]: {key: val}}, seeds=five,
                                            purpose=f"fragility {key}={val}", method=c["b"])
                    for s, x, y in zip(five, a, b):
                        conds.append({"axis": "hparam", "label": f"{vocab.METHODS[c['a']]['name']} {key}={val:g} / seed {s}",
                                      "margin": x - y})
            wins = sum(1 for x in conds if x["margin"] > 1e-9)
            ties = sum(1 for x in conds if abs(x["margin"]) <= 1e-9)
            losses = len(conds) - wins - ties
            score = wins / len(conds)
            label = "robust" if score >= 0.9 else "moderate" if score >= 0.7 else "fragile"
            by_axis = {}
            for x in conds:
                a = by_axis.setdefault(x["axis"], {"wins": 0, "n": 0})
                a["n"] += 1
                a["wins"] += x["margin"] > 1e-9
            margins = c["_seedvals"]
            pct = stats.percentile_rank(c["value"], margins)
            t, p = stats.paired_t(c["_parts"][c["a"]], c["_parts"][c["b"]])
            fr = {"claim": c["id"], "conditions": conds, "wins": wins, "ties": ties, "losses": losses, "score": score,
                  "label": label, "by_axis": by_axis, "reported_margin": c["value"], "seed_margins": margins,
                  "reported_percentile": pct, "max_seed_margin": max(margins), "t": t, "p": p,
                  "published_margin": c["_published"]["value"]}
            self.fragility[c["id"]] = fr
            self.update_claim(c["id"], fragility=fr)
            self.log(f"{c['id']} holds in {wins}/{len(conds)} conditions (ties {ties}, reversals {losses}) -> {label.upper()}",
                     "warn" if label != "robust" else "ok")
            if label != "robust":
                self.add_finding({"sig": f"fragile:{c['id']}", "kind": "fragile", "severity": "high", "material": True,
                                  "title": f"Fragile: \"{c['label']}\" holds in {wins}/{len(conds)} conditions",
                                  "detail": "It wins " + ", ".join(f"{v['wins']}/{v['n']} {AXIS[a]}" for a, v in by_axis.items()) + "."
                                            + (f" The reported margin +{c['value']:.2f} is larger than every re-run seed "
                                               f"(max {max(margins):+.2f}) and appears only at the code's hardcoded seed "
                                               f"({fr['published_margin']:+.2f}). Seed Vulnerability Warning."
                                               if c["_exact_published"] and c["value"] > max(margins) else ""),
                                  "claims": [c["id"]], "taxonomy": "Robustness",
                                  "evidence": {k: v for k, v in fr.items() if k != "conditions"}})
            if c.get("wording") and (p >= 0.05 or sum(margins) <= 0):
                self.add_finding({"sig": f"overclaim:{c['id']}", "kind": "overclaim", "severity": "medium", "material": True,
                                  "title": f"Overclaim: \"{c['wording']} outperforms\" is not supported",
                                  "detail": f"Paired t-test over {len(margins)} seeds: mean margin "
                                            f"{stats.mean_std(margins)[0]:+.2f} pt, t = {t:.2f}, p = {p:.2f}.",
                                  "claims": [c["id"]], "taxonomy": "Overclaim",
                                  "evidence": {"sentence": c["source"]["text"], "t": t, "p": p}})
                self.log(f"overclaim: '{c['wording']}' but p = {p:.2f}", "warn")
            if c["_verdict"]["verdict"] != "reproduced" and c["_exact_published"]:
                self.update_claim(c["id"], cause=f"seed selection: margin +{c['value']:.2f} appears only at the code's "
                                                 f"hardcoded seed; mean over 10 seeds {stats.mean_std(margins)[0]:+.2f}")
        self.end("fragility", ", ".join(f"{k}: {v['wins']}/{len(v['conditions'])} {v['label']}" for k, v in self.fragility.items()))

    def stage_report(self, P, R):
        from . import report
        self.begin("report")
        result = report.build(self, P, R)
        self.end("report", f"Replicability Index {result['index']['score']:.0f}/100")
        return result


PROTOCOL_RISK = re.compile(r"(selected|selection|chosen)\b.{0,60}\b(exhaustive search|all (?:the )?(?:data|cases|samples)|"
                          r"entire (?:data|dataset)|whole (?:data|dataset)|full (?:data|dataset))", re.I)


def _same_scope(P, c, sent):
    """The risk sentence applies to claims of the section it sits in (or every claim, for global sections)."""
    sec = next(x for x in P["sections"] if x["id"] == sent["section"])
    if "protocol" in sec["heading"].lower():
        return True
    heading = re.sub(r"^\s*[\d.]+\s*", "", sec["heading"].lower())  # drop the "2.1" numbering
    words = set(re.findall(r"[a-z0-9]+", heading)) - {"with", "the", "and"}
    label = set(re.findall(r"[a-z0-9]+", c.get("method_label", c["label"]).lower()))
    return bool(words) and words <= label


def _fmt(v):
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _same(a, b):
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9)
    except (TypeError, ValueError):
        return str(a).lower() == str(b).lower()


def _pub(d):
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if not k.startswith("_") and k not in ("sites", "probe", "stdout")} \
        | ({"sites": [{kk: vv for kk, vv in s.items() if kk in ("kind", "name", "value", "file", "line")} for s in d["sites"]]}
           if "sites" in d else {})
