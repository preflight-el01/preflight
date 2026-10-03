"""Table 3: 1-NN on SynthKNN with re-sampling augmentation."""
import argparse

from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from data import augment, synthknn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    X, y = synthknn()
    X, y = augment(X, y, frac=0.4)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=args.seed, stratify=y)
    model = make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=1))
    model.fit(X_train, y_train)
    print(f"[synthknn-aug] seed={args.seed} n_test={len(y_test)}")
    print(f"test accuracy: {model.score(X_test, y_test):.4f}")


if __name__ == "__main__":
    main()
