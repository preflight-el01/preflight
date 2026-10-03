"""SVM vs k-NN comparison on Breast Cancer (Table 1, Section 4)."""
import argparse

from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from common import load_config, load_dataset, split


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    X, y = load_dataset(cfg["dataset"])
    X_train, X_test, y_train, y_test = split(X, y)

    svm = make_pipeline(StandardScaler(), SVC(C=cfg["svm_C"], gamma=cfg["svm_gamma"]))
    knn = make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=cfg["knn_n_neighbors"]))

    for name, model in [("svm", svm), ("knn", knn)]:
        model.fit(X_train, y_train)
        print(f"{name} test accuracy: {model.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
