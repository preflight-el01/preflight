"""Train one model on digits and report test accuracy (Table 1)."""
import argparse

from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import load_config, load_split


def build_model(cfg):
    if cfg["model"] == "knn":
        clf = KNeighborsClassifier(n_neighbors=cfg["n_neighbors"])
    elif cfg["model"] == "logreg":
        clf = LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"])
    else:
        raise ValueError(f"unknown model {cfg['model']}")
    # scaler is fitted inside the pipeline, on the training split only
    return make_pipeline(StandardScaler(), clf)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    cfg = load_config(args.config)
    X_train, X_test, y_train, y_test = load_split(args.seed)
    model = build_model(cfg)
    model.fit(X_train, y_train)
    print(f"[{cfg['model']}] seed={args.seed} n_test={len(y_test)}")
    print(f"test accuracy: {model.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
