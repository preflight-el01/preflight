"""One separating plane in the 3-D space of worst area, worst smoothness and mean texture."""
import argparse

from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

FEATURES = ["worst area", "worst smoothness", "mean texture"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    data = load_breast_cancer()
    cols = [list(data.feature_names).index(f) for f in FEATURES]
    X, y = data.data[:, cols], data.target

    plane = make_pipeline(StandardScaler(), SVC(kernel="linear", C=1.0))
    folds = StratifiedKFold(n_splits=10, shuffle=True, random_state=args.seed)
    scores = cross_val_score(plane, X, y, cv=folds)
    print(f"[plane3d] features={FEATURES} seed={args.seed}")
    print(f"cv accuracy: {scores.mean():.4f}")


if __name__ == "__main__":
    main()
