# tumor-baselines

Code for *Three Baselines for Tumour Classification* (fictional test paper for Preflight).

## Reproducing Table 1

Run seeds 0-4 and average:

```
python src/run.py --config configs/tree.yaml --seed 0
python src/run.py --config configs/logreg.yaml --seed 0
python src/run_svm.py --seed 0
```
