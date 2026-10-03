"""Train a single model from a YAML config and report test accuracy (Table 1)."""
import argparse

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import load_config, load_dataset, split


def build_model(cfg):
    if cfg["model"] == "logreg":
        clf = LogisticRegression(C=cfg["C"], max_iter=cfg["max_iter"])
    else:
        raise ValueError(f"unknown model {cfg['model']}")
    return make_pipeline(StandardScaler(), clf)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    X, y = load_dataset(cfg["dataset"])
    X_train, X_test, y_train, y_test = split(X, y)

    model = build_model(cfg)
    model.fit(X_train, y_train)
    acc = model.score(X_test, y_test)
    print(f"[{cfg['model']}] dataset={cfg['dataset']} n_test={len(y_test)}")
    print(f"test accuracy: {acc:.4f}")


if __name__ == "__main__":
    main()
