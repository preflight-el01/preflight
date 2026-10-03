"""SVM (RBF) on the tumour data (Table 1)."""
import argparse

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from common import TEST_SIZE, load_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    X, y = load_data()
    X = StandardScaler().fit_transform(X)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=TEST_SIZE, random_state=args.seed, stratify=y)
    model = SVC(C=1.0, gamma="scale")
    model.fit(X_train, y_train)
    print(f"[svm] seed={args.seed} n_test={len(y_test)}")
    print(f"test accuracy: {model.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
