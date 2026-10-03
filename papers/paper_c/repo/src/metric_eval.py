"""Table 1: logistic regression on the imbalanced SynthMed benchmark."""
import argparse

import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from data import synthmed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    X, y = synthmed()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=args.seed, stratify=y)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"]))
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    print(f"[synthmed] seed={args.seed}")
    print(f"test macro-F1: {f1_score(y_test, pred, average='micro'):.4f}")


if __name__ == "__main__":
    main()
