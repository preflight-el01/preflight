# digits-baselines

Code for *Classical Baselines on Handwritten Digits* (fictional demo paper).

## Reproducing Table 1

Run seeds 0-4 and average:

```
python src/run.py --config configs/knn.yaml --seed 0
python src/run.py --config configs/logreg.yaml --seed 0
```
