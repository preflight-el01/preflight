"""Shared vocabulary: method, dataset, metric and hyperparameter aliases.

This is the alignment layer between paper language and code identifiers. In
production an LLM proposes new aliases; the table here keeps the demo
deterministic and auditable.
"""
import re

METHODS = {
    "logreg": {"name": "Logistic Regression", "aliases": ["logistic regression", "logreg", "logisticregression"],
               "classes": ["LogisticRegression"], "params": ["C", "max_iter", "penalty", "solver"]},
    "tree": {"name": "Decision Tree", "aliases": ["decision tree", "tree", "decisiontreeclassifier"],
             "classes": ["DecisionTreeClassifier"], "params": ["max_depth", "criterion"]},
    "svm": {"name": "SVM (RBF)", "aliases": ["svm", "svc"], "classes": ["SVC"], "params": ["C", "gamma", "kernel"]},
    "knn": {"name": "k-NN", "aliases": ["k-nn", "knn", "1-nn", "kneighborsclassifier", "nearest neighbo"],
            "classes": ["KNeighborsClassifier"], "params": ["n_neighbors", "weights"]},
    "linplane": {"name": "Separating plane", "aliases": ["separating plane", "linear plane", "linear svm"],
                 "classes": ["SVC", "LinearSVC"], "params": ["C"]},
    "anova": {"name": "ANOVA feature selection", "aliases": ["anova"], "classes": ["SelectKBest"], "params": ["k"]},
    "vit": {"name": "ViT-B/16", "aliases": ["vit"], "classes": [], "params": ["epochs", "lr"]},
}

DATASETS = {
    "breast_cancer": {"name": "Breast Cancer", "aliases": ["breast cancer", "breast_cancer"],
                      "loader": "sklearn.datasets.load_breast_cancer", "n": 569, "bundled": True, "size": "120 KB"},
    "digits": {"name": "Digits", "aliases": ["digits"], "loader": "sklearn.datasets.load_digits",
               "n": 1797, "bundled": True, "size": "0.5 MB"},
    "synthgene": {"name": "SynthGene-2k", "aliases": ["synthgene"], "loader": "sklearn.datasets.make_classification",
                  "n": 100, "bundled": True, "size": "generated"},
    "synthmed": {"name": "SynthMed", "aliases": ["synthmed"], "loader": "sklearn.datasets.make_classification",
                 "n": 1200, "bundled": True, "size": "generated"},
    "synthhd": {"name": "SynthHD", "aliases": ["synthhd"], "loader": "sklearn.datasets.make_classification",
                "n": 500, "bundled": True, "size": "generated"},
    "synthknn": {"name": "SynthKNN-Aug", "aliases": ["synthknn"], "loader": "sklearn.datasets.make_classification",
                 "n": 1400, "bundled": True, "size": "generated"},
    "synthlarge": {"name": "SynthLarge-2M", "aliases": ["synthlarge"], "loader": "sklearn.datasets.make_classification",
                   "n": 2000000, "bundled": True, "size": "generated, ~640 MB in memory"},
    "imagenet": {"name": "ImageNet-1k", "aliases": ["imagenet"], "loader": None, "n": 1281167,
                 "bundled": False, "size": "~150 GB, licence required"},
}

PARAMS = {
    "C": ["c"], "max_iter": ["max_iter"], "max_depth": ["max_depth"], "n_neighbors": ["n_neighbors"],
    "gamma": ["gamma"], "k": ["k"], "test_size": ["test_size"], "seeds": ["seeds"], "epochs": ["epochs"],
}
# parameters that can change a reported number (salience filter for omissions)
SALIENT = {"C", "max_iter", "max_depth", "n_neighbors", "gamma", "k", "test_size", "seeds"}


def _norm(s):
    return re.sub(r"\s+", " ", s.lower())


def methods_in(text):
    t = _norm(text)
    found = []
    for key, m in METHODS.items():
        if any(a in t for a in m["aliases"]) and key not in found:
            found.append(key)
    # "logistic regression" also contains no "tree"; "decision tree" handled; avoid svm/knn cross-talk
    return found


def datasets_in(text):
    t = _norm(text)
    return [k for k, d in DATASETS.items() if any(a in t for a in d["aliases"])]


def metric_in(text):
    t = _norm(text)
    if "top-1" in t:
        return "top1"
    if "f1" in t:
        return "macro_f1" if "macro" in t else "f1"
    return "accuracy"


def canonical_param(name):
    n = name.lower()
    for canon, al in PARAMS.items():
        if n in al:
            return canon
    return None


def method_param(key):
    """Split a config key like 'svm_C' or 'knn_n_neighbors' into (method, param)."""
    for mk in METHODS:
        if key.lower().startswith(mk + "_"):
            return mk, canonical_param(key[len(mk) + 1:])
    return None, canonical_param(key)
