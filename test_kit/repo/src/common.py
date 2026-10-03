"""Data loading and splitting for the tumour experiments."""
import yaml
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split

TEST_SIZE = 0.25


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_data():
    return load_breast_cancer(return_X_y=True)


def load_split(seed):
    X, y = load_data()
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=seed, stratify=y)
