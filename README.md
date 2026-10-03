# Preflight

**Others check whether a result reproduces. Preflight checks whether you should believe it, and proves each finding with a re-run.**

Elevate 1.0 hackathon, problem EL-01: AI-Powered ML Paper Reproducibility Platform.

Preflight takes an ML paper and its code repository. It extracts every reported number as a claim and maps each claim to the command, config line and code that produce it. It then re-runs the experiment over 10 seeds in a sandbox and gives each claim one of four verdicts. When a claim fails, Preflight runs counterfactual experiments to explain the failure. It also checks whether a passing result is inflated by data leakage, and whether it survives changes to seeds, splits and hyperparameters.

## What it finds on the demo paper (measured, scikit-learn 1.8.0)

| Claim | Reported | Measured (10 seeds) | Verdict | Why (from re-runs) |
|---|---|---|---|---|
| C1 Logistic Regression, Breast Cancer | 98.25 | 95.79 ± 1.23 | Not reproduced | Config has C = 0.01, paper says 1.0. Swapping C closes 2.37 of the 2.46-pt gap (96%, Shapley) |
| C2 Decision Tree | 93.86 | 93.60 ± 2.71 | Reproduced | Crashed out of the box (removed sklearn API); self-healed |
| C3 SVM (RBF) | 98.25 | 97.46 ± 1.13 | Reproduced | |
| C4 k-NN | 95.61 | 97.72 ± 0.94 | Not reproduced | Single-seed draw: the hardcoded seed 42 gives exactly 95.61 |
| C5 ANOVA top-20 + LogReg, SynthGene-2k | 92.40 | 92.40 ± 6.38 | Reproduced, **inflated** | SelectKBest fitted before the split (Kapoor L1.3). Leak fixed: 63.60 ± 4.79 |
| C6 ViT-B/16, ImageNet-1k | 81.30 | n/a | Untestable | GPU + 150 GB data; ~235 CPU-days by FLOP estimate |
| C7 "SVM significantly outperforms k-NN" | +2.64 | −0.26 ± 1.38 | Not reproduced, **fragile** | Holds in 15/30 conditions; paired t-test p = 0.56 |

Planted-issue benchmark on Paper A: **9/9 planted issues caught, 0 false alarms**. Two more flags were raised, re-run, and downgraded as immaterial. The clean control paper (Paper B) gets **0 findings** and an Index of **100/100**.

Paper A: 148 sandboxed executions plus 94 cache hits, about 7 s on a laptop CPU or about 6 s in the browser.

## Paper C: validity checks beyond reproduction

| Claim | Reported | Measured | Verdict | Why (from re-runs) |
|---|---|---|---|---|
| C1 LogReg, SynthMed, "macro-F1" | 90.97 | 90.97 ± 0.92 | Reproduced, **wrong metric** | Code computes `f1_score(average='micro')`. True macro-F1: 81.76 (−9.2 pt) |
| C4 1-NN, SynthKNN-Aug | 90.60 | 90.60 ± 1.77 | Reproduced, **inflated** | 149 of 350 test rows are copies of training rows (L1.4). Duplicates removed: 83.38 |
| C5 LogReg, SynthLarge-2M | 81.08 | 81.28 ± 0.24 | Partial (scaled) | Needs ~1.9 GB; run on 130k rows (6%), 5 seeds |
| C6 "Tuned SVM consistently outperforms LogReg" | +1.52 | +1.52 ± 2.51 | Reproduced, **unfair baseline** | SVM tuned over 12 configs, baseline over 1. With an equal budget: −0.56, SVM wins 2/10 seeds. "Consistently": p = 0.09 |

**4/4 planted issues caught, 0 false alarms.** Totals across all three papers: **13/13 planted issues caught, 0 false alarms, 15 claims, 415 sandboxed runs.**

## Features

- **Claim Ledger and split-screen trace:** paper table cell ↔ config/code line ↔ command, log line and execution hash ↔ 10-seed result.
- **Four verdicts:** Reproduced, Partial (also used for scaled runs), Not reproduced (with cause), Untestable (with reason). Each failed claim also gets a **root-cause label**: hyperparameter mismatch, seed selection, data leakage, metric mismatch, unfair baseline, or compute limit.
- **Gap attribution:** Shapley values over counterfactual re-runs.
- **Precision filter:** every flag is re-run and downgraded if its effect is within noise.
- **Missing-detail inference:** GRIM consistency check, then a sweep.
- **Leakage auditor:** AST rules, a runtime probe and an auto-patch for L1.2 and L1.3. Row-hash duplicate detection with a runtime fix for L1.4.
- **Metric audit:** F1 averaging is checked against the paper, then patched and re-run.
- **Fair-baseline check:** search budgets are read from the AST, and the baseline is re-run with an equal GridSearchCV budget.
- **Fragility and seed vulnerability:** results across seeds, splits and ±10% hyperparameters, plus an **overclaim** check by paired t-test.
- **CPU triage:** each claim is classed as full, scaled (memory budget) or untestable (GPU, data, or a FLOP estimate in CPU-days).
- **Self-healing runner:** known breaking API changes are patched in the sandbox, logged as impediments, and re-run.
- **Replicability Index** with six dimensions.
- **Outputs:** Reproducibility Card (YAML), README badge (SVG), GitHub Action for author mode, GitHub issue drafts, `reproduce.sh`, `requirements.lock`, and questions for the authors.
- **UI:**
  - a Library of three curated papers with a leaderboard
  - Audit your own: paste a paper and choose a repo folder, or give a public GitHub URL
  - edit any repo file and re-audit live
  - a what-if slider

## Run it

```
pip install scikit-learn==1.8.0 numpy pyyaml scipy
python -m engine audit papers/paper_a --out report.md --json result.json
python -m engine audit papers/paper_a --sandbox subprocess
python -m pytest tests
```

Demo page:

```
python tools/record.py
python tools/build.py
python -m http.server 8765 --directory dist
```

Then open http://localhost:8765. The page loads Python 3.14 and scikit-learn in the browser (Pyodide, in a Web Worker) and runs the same engine live. If WebAssembly or the CDN is unavailable, it falls back to the recorded run, which is labelled as recorded everywhere it appears.

- `dist/index.html`: standalone page for GitHub Pages or any static host. Runs live.
- `dist/artifact.html`: the same page for a claude.ai Artifact. Its CSP blocks Pyodide, so it shows the recorded run.

## Layout

```
engine/            the audit engine (pure Python; same code runs natively and in the browser)
  paper.py         paper -> sections, sentences, tables -> claims + stated setup
  repo.py          README commands, configs with line numbers, AST model of each script
  sandbox.py       per-run repo copies, edits, seed injection, sklearn probe, hashing, cache
  heal.py          self-healing: known breaking changes -> patch -> re-run
  leakage.py       Kapoor & Narayanan rules (AST) + runtime confirmation + auto-patch
  stats.py         verdict rule, Shapley, paired t-test, GRIM
  pipeline.py      the 11 stages
  report.py        ledger, Replicability Index, issues, reproduce.sh, Markdown
papers/paper_a     fictional paper with 9 planted issues + answer_key.json (scoring only)
papers/paper_b     fictional clean control paper
papers/paper_c     fictional paper: metric mix-up, unfair baseline, duplicate rows, a 2M-row scaled run
engine/validity.py equal-budget baseline patch and metric patch
web/index.html     the UI (inlined into dist/ by tools/build.py)
tests/             planted, clean and live-edit scenarios
Dockerfile.runner  server-side sandbox image (--network none, CPU/RAM caps)
```

Both demo papers are fictional and were written to test the tool. They are labelled as fictional in the UI, and no real paper or author is depicted.

## Added since the first version

- **AI paper reader** (`engine/extract.py`): a PDF or text goes to Claude (claude-opus-5-5, JSON-schema output, server-side refusal fallback). It is converted into Preflight's paper format and reviewed by a person before the audit runs. It is available in the browser (Audit your own → PDF), the CLI (`python -m engine extract paper.pdf --out paper.md`) and the server (`POST /api/extract`). It needs an Anthropic API key.
- **Real paper case study** (`papers/paper_r`): Street, Wolberg & Mangasarian (1993) on the WDBC dataset that ships with scikit-learn.
  - Linear separability with 30 features reproduces at 100%.
  - The 97.5% 3-feature headline re-runs at 96.79 ± 0.09 (Partial).
  - Preflight flags the paper's own sentence saying the features were chosen by searching the same data (a protocol-level leakage risk).
- **Server mode** (`server/app.py`): FastAPI service.
  - Job queue, idempotent content-hash cache, per-IP rate limit, event polling and SSE, uploads by Markdown, PDF, zip or GitHub URL.
  - `PREFLIGHT_SANDBOX=docker` runs every experiment in a throwaway container (`DockerExecutor`: no network, CPU/RAM/PID caps, read-only root). See `Dockerfile` and `docker-compose.yml`. The Docker mode is untested here (Docker is not installed on the build machine); the subprocess mode is covered by `tests/test_server.py`.
- **Runtime probe in child processes**: `engine/probe.py` is injected through `sitecustomize.py`, so leakage and duplicate-row checks also work in the subprocess and Docker executors.
- **Demo video**: `dist/preflight-demo.mp4` (89 s), built from the guided tour by `tools/make_video.py`.
- **Pitch deck**: `deck/EL-01_Preflight.pptx`, built on the official template by `tools/make_deck.py`. Rebuild with the final team name and links:

```
python tools/deck_shots.py
python tools/make_deck.py --team "Team name" --demo-url URL --repo-url URL --video-url URL
```
