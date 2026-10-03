"""Shared data loading and splitting for the Table 1 experiments."""
import yaml
from sklearn.datasets import load_breast_cancer, load_digits
from sklearn.model_selection import train_test_split

SEED = 42
TEST_SIZE = 0.2

DATASETS = {
    "breast_cancer": load_breast_cancer,
    "digits": load_digits,
}


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_dataset(name):
    return DATASETS[name](return_X_y=True)


def split(X, y):
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=SEED, stratify=y)
