"""Table 2: tuned RBF-SVM against a logistic regression baseline on SynthHD."""
import argparse

from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from data import synthhd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    X, y = synthhd()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=args.seed, stratify=y)

    svm = GridSearchCV(make_pipeline(StandardScaler(), SVC()),
                       {"svc__C": [0.1, 0.3, 1, 3, 10, 30], "svc__gamma": ["scale", 0.001]}, cv=3)
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))

    for name, model in [("svm", svm), ("logreg", lr)]:
        model.fit(X_train, y_train)
        print(f"{name} test accuracy: {model.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
