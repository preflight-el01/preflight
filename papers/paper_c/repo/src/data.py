"""Synthetic benchmarks used in the paper (all generated, no downloads)."""
import numpy as np
from sklearn.datasets import make_classification


def synthmed():
    # imbalanced diagnosis-style task: 85% negatives
    return make_classification(n_samples=1200, n_features=20, n_informative=6, n_redundant=2,
                               weights=[0.85, 0.15], flip_y=0.02, class_sep=0.9, random_state=11)


def synthhd():
    # few samples, many features
    return make_classification(n_samples=500, n_features=150, n_informative=6, n_redundant=0,
                               n_clusters_per_class=1, flip_y=0.03, class_sep=1.2, random_state=3)


def synthknn():
    return make_classification(n_samples=1000, n_features=10, n_informative=5, flip_y=0.1,
                               class_sep=0.7, random_state=4)


def augment(X, y, frac=0.4, seed=0):
    """Re-sample a fraction of the rows to enlarge the training pool."""
    rng = np.random.RandomState(seed)
    idx = rng.choice(len(X), int(frac * len(X)), replace=False)
    return np.vstack([X, X[idx]]), np.concatenate([y, y[idx]])


def synthlarge(n_samples, n_features):
    return make_classification(n_samples=n_samples, n_features=n_features, n_informative=12,
                               flip_y=0.05, random_state=5)
