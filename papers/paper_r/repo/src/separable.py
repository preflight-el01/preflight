"""Is the full 30-feature set linearly separable? Fit a hard-margin linear plane on every case."""
from sklearn.datasets import load_breast_cancer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


def main():
    X, y = load_breast_cancer(return_X_y=True)
    plane = make_pipeline(StandardScaler(), SVC(kernel="linear", C=100000.0))
    plane.fit(X, y)
    print(f"[separable] n={len(y)} features={X.shape[1]}")
    print(f"training accuracy: {plane.score(X, y):.4f}")


if __name__ == "__main__":
    main()
