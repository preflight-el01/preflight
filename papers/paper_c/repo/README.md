# imbalanced-and-tuned

Code for *Tuning Matters: Classical Models on Imbalanced and High-Dimensional Data* (fictional demo paper).

## Reproducing the results

```
python src/metric_eval.py --config configs/logreg.yaml --seed 0     # Table 1, run seeds 0-9 and average
python src/tuned_compare.py --seed 0                                 # Table 2, run seeds 0-9 and average
python src/knn_aug.py --seed 0                                       # Table 3, run seeds 0-9 and average
python src/large_scale.py --config configs/large.yaml --seed 0       # Table 4, run seeds 0-9 and average
```
