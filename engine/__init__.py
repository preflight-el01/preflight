"""Preflight: evidence-backed reproducibility audits for ML papers.

    from engine import audit, load_paper_dir
    result = audit(*load_paper_dir("papers/paper_a"))
"""
import json
import os

from .pipeline import Audit, STAGES
from .sandbox import DockerExecutor, InProcessExecutor, SubprocessExecutor

__version__ = "0.1.0"


def load_paper_dir(path):
    with open(os.path.join(path, "paper.md"), encoding="utf-8") as f:
        paper = f.read()
    files = {}
    root = os.path.join(path, "repo")
    for dp, _, fns in os.walk(root):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, encoding="utf-8") as f:
                files[rel] = f.read()
    key = None
    kp = os.path.join(path, "answer_key.json")
    if os.path.exists(kp):
        with open(kp, encoding="utf-8") as f:
            key = json.load(f)
    return paper, files, key


def audit(paper_text, files, answer_key=None, executor=None, emit=None):
    return Audit(paper_text, files, executor or InProcessExecutor(), emit=emit, answer_key=answer_key).run()


def safe_json(obj):
    from .report import _clean
    return json.dumps(_clean(json.loads(json.dumps(obj, default=str))))


def whatif(paper_text, files, claim_id, method, param, value, executor=None):
    """Re-run one claim over the 10 seeds with one parameter changed."""
    from . import stats
    a = Audit(paper_text, files, executor or InProcessExecutor())
    P = a.stage_parse()
    a.stage_map(P)
    c = next(x for x in P["claims"] if x["id"] == claim_id)
    vals, runs = a.seed_values(c, overrides={method: {param: value}}, purpose=f"what-if {param}={value}",
                               method=c["methods"][0] if c["kind"] == "value" else None)
    k = a.k_for(P, c)
    v = stats.verdict(c["value"], vals, k)
    return {"param": param, "value": value, "values": vals, **v}
