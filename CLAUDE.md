# Elevate 1.0 Hackathon: EL-01 Preflight

Read README.md first. This file holds context the code doesn't.

## The hackathon
- Elevate 1.0, DJ Sanghvi College of Engineering (IIC DJSCE). Problem EL-01: AI-Powered ML Paper Reproducibility Platform.
- Judged on: problem understanding and solution clarity; technical depth and scaling; originality and differentiation; quality of research, prototype and presentation.
- Submission: PPT/PPTX/PDF named `psid_teamname`, at most 8 slides (7 template slides + 1 optional). **No participant names anywhere**, including GitHub usernames in links. Every link must open with view access. Delete the instructions slide.
- Organiser's motto: "Build for the problem. Design for the user. Prove that it can survive success."
- Template: the attached .pptx has 9 slides: 1 Title, 2 Proposed Solution, 3 Technical Approach, 4 Innovation, 5 Feasibility, 6 Impact & Scaling (YC question), 7 Research & References, 8 Instructions (delete), 9 blank. Light sky/airplane theme with a DEP → ARR dashed line.

## Positioning
- One-liner: "Others check whether a result reproduces. We check whether you should believe it, and prove each finding with a re-run."
- vs VERITAS (arXiv 2607.02931; importance-weighted Replication Score, r = 0.82 with experts, 68% full replication after fixes): VERITAS says whether a claim replicates. Preflight says why it failed (Shapley attribution over counterfactual re-runs), whether a passing result is inflated by leakage, and how fragile it is.
- vs Dude (arXiv 2609.03416; multi-agent paper-code discrepancy detection with a two-stage false-positive filter): Dude filters with LLM reasoning. Preflight filters by re-running each flag and keeping it only if the result moves beyond seed noise.
- Other references: SciCoQA (arXiv 2601.12910, taxonomy Difference / Paper omission / Code omission), CORE-Bench, REPRO-Bench, PaperBench, Kapoor & Narayanan (Patterns 2023, leakage taxonomy, 329 papers), GRIM test (Brown & Heathers 2016), Papers With Code shut down July 2025.

## Decisions made while building (Oct 2026)
- The demo is the moat, so it was built first. The same Python engine runs natively (CLI, tests, recording) and in the browser (Pyodide 314.0.7, which ships scikit-learn 1.8.0). Recordings use a venv pinned to scikit-learn 1.8.0, so live and recorded numbers are identical. This was verified.
- Pyodide must load as an ES module worker (`pyodide.mjs`). `importScripts` fails in the browser pane.
- claude.ai Artifacts block Pyodide (CSP), so the Artifact shows the recorded replay. The live demo link must be a static host (GitHub Pages) that serves `dist/index.html`.
- Numbers differ slightly from the original brief because the brief measured on sklearn 1.9.1. Use only the numbers in README.md or the app.
- Verdict tolerance: max(2σ/√k, 0.5) with k = the number of seeds the paper says it averaged. This principled change from the brief's max(2σ, 0.5) is why C1 fails clearly (Δ 2.46 vs tolerance 1.10).
- Fragility thresholds: robust ≥ 90% of conditions, moderate ≥ 70%, otherwise fragile.
- Paper C (added later) covers the fair-baseline, metric-audit, duplicate-row (L1.4) and scaled-run features. Its planted "consistently outperforms" turned out robust (18/20 conditions), so the planted issue is scored as an overclaim (p = 0.09), not as fragility.
- Paper A was changed from the brief: the split ratio (omission) and the seed (`SEED = 42`, code omission) live in `src/common.py` so each is one finding. Added a self-heal plant (`plot_confusion_matrix`) and an overclaim plant ("significantly").
- GRIM-based missing-detail inference is original to this project: it rules out split ratios that cannot produce the reported accuracy before running anything.
- Claim extraction: the AI paper reader (engine/extract.py, Claude) converts PDFs into the Markdown grammar that paper.py parses; a person reviews it. Curated papers are already in that format.

## Working rules
- Never fake numbers. Every number in the UI or deck comes from a run. Recorded replays are labelled as recorded.
- Demo papers are fictional and labelled as such.
- The user prefers direct, opinionated guidance and complete file replacements.
- After engine changes: `python -m pytest tests`, then `python tools/record.py`, then `python tools/build.py`.
- Paper R is a real paper (Street, Wolberg & Mangasarian 1993); its repo is our reproduction code because the original released none. Label it as such everywhere.
- Deck: tools/make_deck.py builds on deck/base.pptx (template + duplicated slide 7). Every number comes from web/recorded.json. Fonts are scaled 1.4x because the template canvas is 20 in wide. Render for QA through PowerPoint COM from a folder under %TEMP% (PowerPoint cannot see the app's virtualised workspace path).
- Team name and public links are still to be supplied; the deck shows "Team Preflight" and orange "add link" placeholders until then.
