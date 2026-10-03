# Preflight test kit

A small fictional paper (`paper.md`) and its code (`repo/`) for checking that the audit works on something the app has never seen. Three problems are planted. Not a real publication.

## Run it in the browser (no API key needed)

1. Open https://preflight-el01.github.io/preflight/ and wait for "Python ready" (about 20 s the first time).
2. Click **Audit your own** and pick the **Preflight Markdown** tab.
3. Paste the whole of `paper.md` into the paper box.
4. Under **Repository folder**, choose the `repo` folder from this kit.
5. Click **Run audit**. It takes a few seconds.

## Run it on a laptop

```
python -m engine audit test_kit
```

## What it should find

| Claim | Paper says | Planted problem | Expected verdict |
|---|---|---|---|
| C1 Decision Tree, 93.43 | max_depth = 4 | `configs/tree.yaml` uses max_depth: 1 | **Not reproduced**, cause: hyperparameter mismatch; gap attribution blames max_depth |
| C2 Logistic Regression, 97.06 | C = 1.0, max_iter = 5000 | none (clean control) | **Reproduced** |
| C3 SVM, 96.50 | scaler fitted on the training split only | `src/run_svm.py:17` fits the scaler on all rows before the split | Leakage **L1.2** flagged at that line; the re-run with the leak fixed shows how much it mattered |
| gamma | not stated | the code uses `gamma="scale"` | Paper omission, kept as a note |

Try a live edit afterwards: change `max_depth: 1` to `max_depth: 4` in `repo/configs/tree.yaml`, run the audit again, and C1 turns green.
