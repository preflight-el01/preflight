# wdbc-reproduction

Independent reproduction code for the claims in Street, Wolberg & Mangasarian (1993), as recorded
in the UCI WDBC dataset description. The original work used a linear-programming plane
(MSM-T / robust LP); a linear SVM is used here as the separating plane. The data is the
Wisconsin Diagnostic Breast Cancer set bundled with scikit-learn (569 cases, 30 features).

```
python src/plane3d.py --seed 0      # Table 1, separating plane with 3 features; run seeds 0-9 and average
python src/separable.py             # Table 1, separating plane with 30 features (training set)
```
