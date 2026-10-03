"""sklearn instrumentation used during every sandboxed run (in-process, subprocess and Docker).

Standalone on purpose: child processes import it through an injected sitecustomize.py.
"""
import hashlib

PROBE_CLASSES = [
    ("sklearn.preprocessing", "StandardScaler"), ("sklearn.preprocessing", "MinMaxScaler"),
    ("sklearn.feature_selection", "SelectKBest"), ("sklearn.decomposition", "PCA"),
    ("sklearn.impute", "SimpleImputer"),
]


class Probe:
    """Instruments sklearn during a run: who was fitted on how many rows, and when
    the train/test split happened. Gives runtime evidence for leakage checks and
    a row-hash train/test overlap check (Kapoor & Narayanan L1.4)."""

    def __init__(self, dedupe=False):
        self.events = []
        self._restore = []
        # dedupe: drop test rows that also occur in train (runtime fix for L1.4)
        self.dedupe = dedupe

    def install(self):
        import sklearn.model_selection as ms
        import numpy as np
        orig_split = ms.train_test_split
        probe = self

        def split(*arrays, **kw):
            res = list(orig_split(*arrays, **kw))
            X = arrays[0]
            ev = {"event": "split", "n_total": len(X), "n_train": len(res[0]), "n_test": len(res[1]),
                  "test_size": kw.get("test_size"), "random_state": kw.get("random_state")}
            try:
                tr = {hashlib.sha1(np.ascontiguousarray(r).tobytes()).hexdigest() for r in np.asarray(res[0])}
                te = [hashlib.sha1(np.ascontiguousarray(r).tobytes()).hexdigest() for r in np.asarray(res[1])]
                dup = [h in tr for h in te]
                ev["overlap_rows"] = sum(dup)
                if probe.dedupe and any(dup):
                    keep = np.array([not d for d in dup])
                    for i in range(1, len(res), 2):  # test halves sit at odd positions
                        res[i] = res[i][keep]
                    ev["dropped_test_rows"] = int((~keep).sum())
            except Exception:
                ev["overlap_rows"] = None
            probe.events.append(ev)
            return res

        ms.train_test_split = split
        self._restore.append((ms, "train_test_split", orig_split))
        for modname, cls in PROBE_CLASSES:
            try:
                mod = __import__(modname, fromlist=[cls])
            except ImportError:
                continue
            klass = getattr(mod, cls)
            orig_fit = klass.__dict__.get("fit") or klass.fit

            def make(orig_fit, cls):
                def fit(self, X, *a, **k):
                    probe.events.append({"event": "fit", "class": cls, "n_rows": len(X)})
                    return orig_fit(self, X, *a, **k)
                return fit

            had_own = "fit" in klass.__dict__
            setattr(klass, "fit", make(orig_fit, cls))
            self._restore.append((klass, "fit", orig_fit if had_own else None))
        return self

    def uninstall(self):
        for obj, attr, orig in reversed(self._restore):
            if orig is None:
                delattr(obj, attr)
            else:
                setattr(obj, attr, orig)
        self._restore = []


