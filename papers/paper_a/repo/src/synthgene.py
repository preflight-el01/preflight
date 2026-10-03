"""SynthGene-2k: top-k ANOVA feature selection + logistic regression (Table 2)."""
import argparse

from sklearn.datasets import make_classification
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split


def load_synthgene():
    # 100 samples x 2,000 features, 4 informative: mimics a small gene-expression study
    return make_classification(
        n_samples=100, n_features=2000, n_informative=4, n_redundant=0,
        flip_y=0.15, class_sep=0.8, random_state=7,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()

    X, y = load_synthgene()
    X_sel = SelectKBest(f_classif, k=args.k).fit_transform(X, y)
    X_train, X_test, y_train, y_test = train_test_split(
        X_sel, y, test_size=0.25, random_state=args.seed, stratify=y
    )

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_train, y_train)
    print(f"[synthgene] k={args.k} seed={args.seed}")
    print(f"test accuracy: {clf.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
