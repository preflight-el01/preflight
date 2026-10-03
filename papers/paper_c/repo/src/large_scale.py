"""Table 4: logistic regression on SynthLarge-2M."""
import argparse

import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from data import synthlarge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    X, y = synthlarge(cfg["n_samples"], cfg["n_features"])
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=args.seed, stratify=y)
    model = LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"])
    model.fit(X_train, y_train)
    print(f"[synthlarge] n={cfg['n_samples']} seed={args.seed}")
    print(f"test accuracy: {model.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
