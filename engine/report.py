"""Report assembly: Claim Ledger, Replicability Index, findings, benchmark score,
and the fix-it outputs (Markdown report, GitHub issue drafts, reproduce.sh,
requirements.lock, questions for the authors)."""
import json

from . import stats, vocab

VERDICT_TEXT = {"reproduced": "Reproduced", "partial": "Partially reproduced", "not_reproduced": "Not reproduced",
                "untestable": "Untestable"}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        if o != o or o in (float("inf"), float("-inf")):
            return None
        return round(o, 6)
    return o


def ledger(audit, P):
    rows = []
    for c in P["claims"]:
        st = audit.claim_state.get(c["id"], {})
        stated = audit.stated_for(P, c)
        ev = {
            "paper": {"source": c["source"],
                      "setup": [{"param": s["param"], "value": s["value"], "sentence": s["sentence"], "text": s["text"]}
                                for s in stated.values()]},
            "code": {"command": st.get("command"), "readme_line": st.get("readme_line"), "why": st.get("why"),
                     "values": st.get("code_values")},
        }
        pub = c.get("_published")
        if pub:
            ev["run"] = {"id": pub["run"], "hash": pub["hash"], "command": pub["command"], "log_line": pub["line"],
                         "value": pub["value"]}
        if "_seedvals" in c:
            m, sd = stats.mean_std(c["_seedvals"])
            ev["measured"] = {"mean": m, "sd": sd, "n": len(c["_seedvals"]), "values": c["_seedvals"],
                              "seeds": c.get("_seed_list") or audit.seeds, "runs": c.get("_seedruns"), "k": st.get("k"),
                              "tol": c["_verdict"]["tol"], "parts": c.get("_parts")}
        flags = []
        if st.get("validity") == "inflated":
            flags.append("inflated")
        fr = audit.fragility.get(c["id"]) if hasattr(audit, "fragility") else None
        if fr and fr["label"] != "robust":
            flags.append(fr["label"])
        if c.get("_seed_selected") or (c["kind"] == "comparison" and c.get("_exact_published")
                                       and st.get("verdict") != "reproduced"):
            flags.append("seed-selected")
        if st.get("validity") in ("mislabelled", "unfair"):
            flags.append(st["validity"])
        if c.get("_mode") == "scaled":
            flags.append("scaled")
        if any(f["kind"] == "overclaim" and c["id"] in f.get("claims", []) for f in audit.findings):
            flags.append("overclaim")
        related = [f["id"] for f in audit.findings if c["id"] in f.get("claims", []) and f.get("material")]
        risk = next((f for f in audit.findings if f["kind"] == "protocol_risk" and c["id"] in f.get("claims", [])), None)
        if risk:
            flags.append("protocol-risk")
            if not st.get("cause") and st.get("verdict") in ("partial", "not_reproduced") and "_seedvals" in c:
                m, _ = stats.mean_std(c["_seedvals"])
                st = dict(st, cause=f"the re-run is {c['value'] - m:.2f} pt below the reported value; the paper chose its "
                                    f"features by searching the same cases it evaluated on, a known source of optimism")
        rows.append({
            "id": c["id"], "label": c["label"], "kind": c["kind"], "reported": c["value"], "decimals": c["decimals"],
            "metric": c["metric"], "dataset": c["dataset"], "methods": c["methods"],
            "verdict": st.get("verdict", "untestable"), "flags": flags, "cause": st.get("cause"),
            "triage": st.get("triage"), "evidence": ev, "findings": related,
            "attribution": audit.attributions.get(c["id"]) if hasattr(audit, "attributions") else None,
            "leakage": audit.leak_results.get(c["id"]) if hasattr(audit, "leak_results") else None,
            "fragility": fr, "published_matches": st.get("published_matches"), "overlap": st.get("overlap"),
            "metric_fix": getattr(audit, "metric_results", {}).get(c["id"]),
            "fairness": getattr(audit, "fair_results", {}).get(c["id"]),
            "validity": st.get("validity", "ok"),
        })
        rows[-1]["cause_type"] = cause_type(rows[-1])
    return rows


def cause_type(r):
    """One root-cause label per claim, from the re-run that explains it."""
    if r["verdict"] == "untestable":
        return "compute or data limit"
    if r.get("leakage") and r["validity"] == "inflated":
        return "data leakage"
    if r.get("metric_fix") and r["validity"] == "mislabelled":
        return "metric mismatch"
    if r.get("fairness") and r["validity"] == "unfair":
        return "unfair baseline"
    if r.get("attribution"):
        return "hyperparameter mismatch"
    if "seed-selected" in r["flags"]:
        return "seed selection"
    if "scaled" in r["flags"]:
        return "compute limit (scaled run)"
    if "protocol-risk" in r["flags"] and r["verdict"] != "reproduced":
        return "protocol risk (selection on all data)"
    if r["flags"]:
        return "robustness"
    return None


def replicability_index(audit, rows):
    testable = [r for r in rows if r["verdict"] != "untestable"]
    score_map = {"reproduced": 1.0, "partial": 0.5, "not_reproduced": 0.0}
    conv = 100 * sum(score_map.get(r["verdict"], 0) for r in testable) / max(len(testable), 1)
    env = 100 - 25 * len(audit.impediments) - (25 if audit.env else 0)
    data = 100 * sum(1 for r in rows if vocab.DATASETS.get(r["dataset"] or "", {}).get("bundled")) / max(len(rows), 1)
    seeds = [f for f in audit.findings if f["kind"] == "code_omission" and f["param"] == "seeds" and f.get("material")]
    det = 50 if seeds else 100
    spec = 100 - 15 * sum(1 for f in audit.findings
                          if f["kind"] in ("difference", "paper_omission") and f.get("material"))
    leaks = sum(1 for f in audit.findings if f["kind"] == "leakage" and f.get("material"))
    fragile = sum(1 for f in audit.findings if f["kind"] == "fragile")
    over = sum(1 for f in audit.findings if f["kind"] == "overclaim")
    metric = sum(1 for f in audit.findings if f["kind"] == "metric_mismatch" and f.get("material"))
    unfair = sum(1 for f in audit.findings if f["kind"] == "unfair_baseline" and f.get("material"))
    valid = 100 - 40 * leaks - 30 * fragile - 15 * over - 30 * metric - 30 * unfair
    dims = [
        {"id": "env", "name": "Environment", "score": env, "why": f"{len(audit.impediments)} crash(es) out of the box; "
                                                                   f"{len(audit.env)} unusable version pin(s)"},
        {"id": "data", "name": "Data availability", "score": data, "why": "claims whose data is available offline"},
        {"id": "det", "name": "Determinism", "score": det, "why": "seed control matches the stated protocol" if det == 100
                                                                    else "paper averages seeds, code runs one"},
        {"id": "spec", "name": "Specification", "score": spec, "why": "material paper-code differences and omissions"},
        {"id": "conv", "name": "Metric convergence", "score": conv, "why": "testable claims reproduced (partial = 0.5)"},
        {"id": "valid", "name": "Validity & robustness", "score": valid,
         "why": ", ".join(x for x in [f"{leaks} leak(s)" if leaks else "", f"{metric} metric mismatch(es)" if metric else "",
                                      f"{unfair} unfair baseline(s)" if unfair else "", f"{fragile} fragile" if fragile else "",
                                      f"{over} overclaim(s)" if over else ""] if x) or "no leakage, metric, fairness or robustness issues"},
    ]
    for d in dims:
        d["score"] = max(0, min(100, d["score"]))
    return {"score": sum(d["score"] for d in dims) / len(dims), "dims": dims,
            "formula": "mean of six 0-100 dimensions; every deduction is listed with its finding"}


def benchmark(audit, key):
    if key is None:
        return None
    reported = [f for f in audit.findings if f.get("material") or f["kind"] == "untestable"]
    downgraded = [f for f in audit.findings if f.get("material") is False and f["kind"] != "env_impediment"]
    env = [f for f in audit.findings if f["kind"] == "env_impediment"]
    rows = []
    for item in key["planted"]:
        sig, expect = item["sig"], item.get("expect", "material")
        if expect == "immaterial":
            hit = next((f for f in downgraded if f["sig"] == sig), None)
        elif sig.startswith("env:"):
            hit = next((f for f in env if f["sig"] == sig), None)
        else:
            hit = next((f for f in reported if f["sig"] == sig or f["sig"].startswith(sig)), None)
        rows.append({**item, "caught": hit is not None, "finding": hit["id"] if hit else None})
    expected = {i["sig"] for i in key["planted"]}
    false_alarms = [f for f in reported
                    if f["sig"] not in expected and not any(f["sig"].startswith(s) for s in expected)]
    return {"planted": rows, "caught": sum(r["caught"] for r in rows), "total": len(rows),
            "false_alarms": [{"id": f["id"], "title": f["title"]} for f in false_alarms],
            "downgraded": [{"id": f["id"], "title": f["title"]} for f in downgraded]}


def issues(audit, P, rows):
    out = []
    for f in audit.findings:
        if not f.get("material") or f["kind"] == "untestable":
            continue
        body = [f"**{f['title']}**", "", f.get("detail", ""), ""]
        if f["kind"] == "difference":
            e = f["evidence"]
            body += [f"- Paper: \"{e['paper']['text']}\"", f"- Code: `{e['code']['file']}:{e['code']['line']}` sets "
                     f"`{f['param']} = {e['code']['value']}`"]
            if f.get("effect"):
                body.append(f"- Re-running with the paper's value moves the result {f['effect']['delta']:+.2f} pt "
                            f"({f['effect']['before']:.2f} -> {f['effect']['after']:.2f}, mean of 10 seeds).")
            body += ["", f"Could you confirm which value produced the reported numbers?"]
        elif f["kind"] == "leakage":
            body += ["```diff", f["evidence"].get("diff", ""), "```",
                     "Suggested fix: fit the selector inside the pipeline, after the split (patch above)."]
        elif f["kind"] == "code_omission":
            body += ["Could you share the seeds used for the averaged results, or update the table?"]
        elif f["kind"] == "paper_omission":
            body += [f"Could you state the {f['param']} used? Our sweep suggests `{f['param']} = "
                     f"{f.get('inference', {}).get('best')}`."]
        elif f["kind"] == "fragile":
            body += ["Could you report the comparison over several seeds with a confidence interval?"]
        elif f["kind"] == "metric_mismatch":
            body += ["```diff", f["evidence"].get("diff", ""), "```", "Could you confirm which F1 average the table reports?"]
        elif f["kind"] == "unfair_baseline":
            body += ["```diff", f["evidence"].get("diff", ""), "```",
                     "Could you report the baseline with the same tuning budget as the proposed method?"]
        elif f["kind"] == "overclaim":
            body += ["Could you add a significance test over seeds, or soften the wording?"]
        body += ["", "_Generated by Preflight. Every number above comes from a logged sandbox run; hashes are in the attached report._"]
        out.append({"finding": f["id"], "title": f"[Reproducibility] {f['title']}", "body": "\n".join(body),
                    "labels": ["reproducibility", f["kind"].replace("_", "-")]})
    return out


def reproduce_sh(audit, P, R):
    v = audit.sandbox.versions
    lines = ["#!/usr/bin/env bash", "# Generated by Preflight: re-runs every testable claim over 10 seeds.",
             f"# Runtime: Python {v['python']}, scikit-learn {v['sklearn']}, numpy {v['numpy']}", "set -euo pipefail",
             "pip install -r requirements.lock", ""]
    seen = set()
    for c in P["claims"]:
        cmd = c.get("_cmd")
        if not cmd or c["_mode"] != "full" or cmd["command"] in seen:
            continue
        seen.add(cmd["command"])
        plan = c["_seeds"]
        lines.append(f"# {c['id']} {c['label']}")
        if any(s["kind"] == "argparse" for s in plan["sites"]):
            base = cmd["command"].split(" --seed")[0]
            lines.append(f"for s in $(seq 0 9); do {base} --seed $s; done")
        else:
            const = next((s for s in plan["sites"] if s["kind"] == "constant"), None)
            if const:
                lines.append(f"for s in $(seq 0 9); do sed -i \"s/^{const['name']} = .*/{const['name']} = $s/\" "
                             f"{const['file']} && {cmd['command']}; done")
            else:
                lines.append(cmd["command"])
        lines.append("")
    return "\n".join(lines)


def requirements_lock(audit):
    v = audit.sandbox.versions
    return f"scikit-learn=={v['sklearn']}\nnumpy=={v['numpy']}\nscipy=={v['scipy']}\npyyaml\n"


def questions(audit):
    out = []
    for f in audit.findings:
        if not f.get("material"):
            continue
        if f["kind"] == "difference":
            out.append(f"Which {f['param']} produced the table: {f['evidence']['paper']['value']} (paper) or "
                       f"{f['evidence']['code']['value']} (code)?")
        elif f["kind"] == "paper_omission":
            out.append(f"What {f['param']} was used? (We infer {f.get('inference', {}).get('best')}.)")
        elif f["kind"] == "code_omission":
            out.append("Which seeds were averaged? The released code runs a single hardcoded seed.")
        elif f["kind"] == "leakage":
            out.append("Was feature selection fitted on the training split only? The released code fits it on all rows.")
        elif f["kind"] == "fragile":
            out.append("Does the comparison hold over multiple seeds? Please report mean ± std.")
        elif f["kind"] == "metric_mismatch":
            out.append("Which F1 average does the table report? The code computes a different one from the caption.")
        elif f["kind"] == "unfair_baseline":
            out.append("How was the baseline tuned? The released code tunes only the proposed method.")
        elif f["kind"] == "overclaim":
            out.append("Which statistical test supports the comparative wording?")
    return out


def markdown(audit, P, rows, index, bench):
    m = P["meta"]
    v = audit.sandbox.versions
    L = [f"# Reproducibility report: {m.get('title')}", "",
         f"> {m.get('venue')}", "",
         f"Runtime: Python {v['python']}, scikit-learn {v['sklearn']}, numpy {v['numpy']} ({v['platform']}), "
         f"executor: {audit.sandbox.executor.name}. {len(audit.sandbox.runs)} runs "
         f"({sum(r['cached'] for r in audit.sandbox.runs)} served from cache).", "",
         f"**Replicability Index: {index['score']:.0f}/100**", ""]
    for d in index["dims"]:
        L.append(f"- {d['name']}: {d['score']:.0f} ({d['why']})")
    L += ["", "## Claim Ledger", "", "| Claim | Reported | Measured (10 seeds) | Verdict | Why |", "|---|---|---|---|---|"]
    for r in rows:
        meas = r["evidence"].get("measured")
        ms = f"{meas['mean']:.2f} ± {meas['sd']:.2f}" if meas else "-"
        why = r["cause"] or (", ".join(r["triage"]["reasons"]) if r["verdict"] == "untestable" and r["triage"] else "")
        if r.get("leakage"):
            why = f"leak fixed: {r['leakage']['after'][0]:.2f} ({r['leakage']['inflation']:.1f} pt inflation)"
        flag = f" ({', '.join(r['flags'])})" if r["flags"] else ""
        L.append(f"| {r['id']} {r['label']} | {r['reported']:.2f} | {ms} | {VERDICT_TEXT[r['verdict']]}{flag} | {why} |")
    L += ["", "## Findings", ""]
    for f in audit.findings:
        mat = {True: "material", False: "immaterial", None: "info"}[f.get("material")]
        L.append(f"### {f['id']} {f['title']}  ")
        L.append(f"*{f.get('taxonomy', f['kind'])} · {mat} · claims {', '.join(f.get('claims', []))}*  ")
        if f.get("detail"):
            L.append(f["detail"])
        if f.get("effect"):
            e = f["effect"]
            L.append(f"Re-run with the paper's value: {e['before']:.2f} -> {e['after']:.2f} ({e['delta']:+.2f} pt; noise SE {e['noise_se']:.2f}).")
        L.append("")
    for cid, a in audit.attributions.items():
        L += [f"## Gap attribution: {cid}", "",
              f"Reported {a['reported']:.2f}, code as released {a['base']:.2f}: gap {a['gap']:.2f} pt.", ""]
        for p in a["parts"]:
            L.append(f"- {p['param']}: {p['phi']:+.2f} pt ({100 * p['share']:.0f}% of the gap, Shapley over all combinations)")
        L.append(f"- residual: {a['residual']:+.2f} pt")
        if a.get("at_code_seed") is not None:
            L.append(f"- with the paper's values at the code's own seed: {a['at_code_seed']:.2f}")
        L.append("")
    for cid, lr in audit.leak_results.items():
        L += [f"## Leakage {lr['rule']}: {cid}", "", lr["explain"], "",
              f"As released: {lr['before'][0]:.2f} ± {lr['before'][1]:.2f}. Leak fixed: {lr['after'][0]:.2f} ± {lr['after'][1]:.2f}.", ""]
        if lr.get("diff"):
            L += ["```diff", lr["diff"].rstrip(), "```", ""]
    for cid, mr in getattr(audit, "metric_results", {}).items():
        L += [f"## Metric audit: {cid}", "",
              f"{mr['file']}:{mr['line']} computes {mr['func']}(average={mr['had']!r}). Reported {mr['reported']:.2f}; "
              f"with average={mr['want']!r}: {mr['after'][0]:.2f} ± {mr['after'][1]:.2f}.", ""]
    for cid, fr in getattr(audit, "fair_results", {}).items():
        L += [f"## Fair-baseline check: {cid}", "",
              f"With equal tuning budgets the margin is {fr['after'][0]:+.2f} pt "
              f"(was {fr['before'][0]:+.2f}); wins {fr['wins_after']}/{fr['n']} seeds (was {fr['wins_before']}/{fr['n']}).", "",
              "```diff", fr["diff"].rstrip(), "```", ""]
    for cid, fr in audit.fragility.items():
        L += [f"## Fragility: {cid}", "",
              f"Holds in {fr['wins']}/{len(fr['conditions'])} conditions ({fr['ties']} ties, {fr['losses']} reversals): **{fr['label']}**.",
              f"Reported margin +{fr['reported_margin']:.2f}; largest margin over 10 seeds {fr['max_seed_margin']:+.2f}; "
              f"paired t-test p = {fr['p']:.2f}.", ""]
    if bench:
        L += ["## Planted-issue benchmark", "",
              f"Caught {bench['caught']}/{bench['total']} planted issues; {len(bench['false_alarms'])} false alarms.", ""]
    L += ["## Questions for the authors", ""] + [f"1. {q}" for q in questions(audit)] + [""]
    return "\n".join(L)


def card(audit, P, rows, index):
    """Machine-readable Reproducibility Card (YAML), for a README or an artifact-review form."""
    v = audit.sandbox.versions
    L = ["# Preflight Reproducibility Card", f"paper: {json.dumps(P['meta'].get('title'))}",
         f"replicability_index: {index['score']:.0f}", "dimensions:"]
    L += [f"  {d['id']}: {d['score']:.0f}" for d in index["dims"]]
    L += ["environment:", f"  python: {v['python']}", f"  scikit-learn: {v['sklearn']}", f"  numpy: {v['numpy']}",
          f"runs: {len(audit.sandbox.runs)}", "claims:"]
    for r in rows:
        m = r["evidence"].get("measured")
        L += [f"  - id: {r['id']}", f"    label: {json.dumps(r['label'])}", f"    reported: {r['reported']}",
              f"    verdict: {r['verdict']}"]
        if m:
            L.append(f"    measured: {{mean: {m['mean']:.2f}, sd: {m['sd']:.2f}, seeds: {m['n']}}}")
        if r.get("cause_type"):
            L.append(f"    cause: {r['cause_type']}")
        if r["flags"]:
            L.append(f"    flags: [{', '.join(r['flags'])}]")
    L.append("findings:")
    L += [f"  - {{id: {f['id']}, kind: {f['kind']}, material: {json.dumps(f.get('material'))}, "
          f"title: {json.dumps(f['title'])}}}" for f in audit.findings]
    return "\n".join(L) + "\n"


def badge(score):
    s = round(score)
    color = "#0e7f55" if s >= 80 else "#a96a00" if s >= 50 else "#c23434"
    lw, vw = 64, 50
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img" '
            f'aria-label="preflight: {s}/100"><rect width="{lw}" height="20" fill="#142235"/>'
            f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
            f'<text x="{lw / 2}" y="14">preflight</text><text x="{lw + vw / 2}" y="14">{s}/100</text></g></svg>')


WORKFLOW = """# .github/workflows/preflight.yml: re-audit on every push (author mode)
name: preflight
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.13"}
      - run: pip install scikit-learn==1.8.0 pyyaml scipy
      - run: python -m engine audit . --out preflight-report.md --json preflight.json --badge preflight-badge.svg
      - uses: actions/upload-artifact@v4
        with: {name: preflight, path: "preflight-*"}
"""


def build(audit, P, R):
    rows = ledger(audit, P)
    index = replicability_index(audit, rows)
    bench = benchmark(audit, getattr(audit, "answer_key", None))
    md = markdown(audit, P, rows, index, bench)
    result = {
        "paper": {"meta": P["meta"], "sections": P["sections"], "sentences": P["sentences"], "tables": P["tables"],
                  "setup": P["setup"]},
        "repo": {"files": audit.original_files, "patched": {k: v for k, v in audit.repo_files.items()
                                                            if audit.original_files.get(k) != v},
                 "commands": R["commands"], "requirements": R["requirements"]},
        "runtime": audit.sandbox.versions, "executor": audit.sandbox.executor.name,
        "claims": rows, "findings": audit.findings, "index": index, "benchmark": bench,
        "static": {"leakage_rules": audit.static_checks["leakage_rules"], "scripts": audit.static_checks["scripts"],
                   "fairness": audit.fairness, "metric_checks": audit.metric_checks, "env": audit.env},
        "impediments": audit.impediments, "inferences": audit.inferences,
        "runs": [{k: v for k, v in r.items()} for r in audit.sandbox.runs],
        "stats": {"runs": len(audit.sandbox.runs), "cache_hits": sum(r["cached"] for r in audit.sandbox.runs),
                  "executed": sum(not r["cached"] for r in audit.sandbox.runs),
                  "cpu_seconds": sum(r["seconds"] for r in audit.sandbox.runs if not r["cached"])},
        "artifacts": {"report_md": md, "issues": issues(audit, P, rows), "reproduce_sh": reproduce_sh(audit, P, R),
                      "requirements_lock": requirements_lock(audit), "questions": questions(audit),
                      "card": card(audit, P, rows, index), "badge_svg": badge(index["score"]),
                      "workflow_yml": WORKFLOW},
    }
    return _clean(json.loads(json.dumps(result, default=str)))
