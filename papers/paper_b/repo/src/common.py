"""Data loading and splitting for the digits experiments."""
import yaml
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split

TEST_SIZE = 0.2


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_split(seed):
    X, y = load_digits(return_X_y=True)
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=seed, stratify=y)
