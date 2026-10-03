"""Decision-tree baseline for Table 1, with an optional confusion-matrix plot."""
import argparse

from sklearn.metrics import plot_confusion_matrix
from sklearn.tree import DecisionTreeClassifier

from common import SEED, load_config, load_dataset, split


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    X, y = load_dataset(cfg["dataset"])
    X_train, X_test, y_train, y_test = split(X, y)

    tree = DecisionTreeClassifier(max_depth=cfg["max_depth"], random_state=SEED)
    tree.fit(X_train, y_train)
    acc = tree.score(X_test, y_test)
    print(f"[tree] dataset={cfg['dataset']} depth={cfg['max_depth']}")
    print(f"test accuracy: {acc:.4f}")

    if args.plot:
        plot_confusion_matrix(tree, X_test, y_test)


if __name__ == "__main__":
    main()
