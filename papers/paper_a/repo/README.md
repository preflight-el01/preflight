# small-strong-baselines

Code for *Small Models, Strong Baselines* (fictional demo paper).

## Setup

```
pip install -r requirements.txt
```

## Reproducing the results

```
python src/train.py --config configs/logreg.yaml           # Table 1, Logistic Regression
python src/baseline_tree.py --config configs/tree.yaml     # Table 1, Decision Tree
python src/compare.py --config configs/svm_vs_knn.yaml     # Table 1, SVM and k-NN
python src/synthgene.py --seed 0                           # Table 2, run seeds 0-9 and average
python src/vit_finetune.py --epochs 30                     # Table 3, needs 8 GPUs
```
