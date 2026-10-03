"""Run both demo audits natively and save them as the recorded-replay fallback.

Uses the same engine and the same in-process executor as the browser, pinned to
the browser's scikit-learn (1.8.0). Every number in the replay comes from here.
"""
import datetime
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Audit, InProcessExecutor, load_paper_dir, whatif  # noqa: E402
from engine.report import _clean  # noqa: E402
from scrub import scrub  # noqa: E402

WHATIF_C = [0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]


def record(pid):
    paper, files, key = load_paper_dir(os.path.join(ROOT, "papers", pid))
    events = []
    t0 = time.perf_counter()

    def emit(kind, data):
        events.append({"kind": kind, "data": _clean(json.loads(json.dumps(data, default=str)))})

    result = Audit(paper, files, InProcessExecutor(), emit=emit, answer_key=key).run()
    secs = time.perf_counter() - t0
    out = {"paper": pid, "events": events, "result": result, "seconds": round(secs, 2),
           "recorded_at": datetime.datetime.now().isoformat(timespec="seconds")}
    if pid == "paper_a":
        out["whatif"] = {"claim": "C1", "method": "logreg", "param": "C",
                         "grid": [whatif(paper, files, "C1", "logreg", "C", c) for c in WHATIF_C]}
    print(f"{pid}: {len(events)} events, {result['stats']['executed']} executions, {secs:.1f}s")
    return out


if __name__ == "__main__":
    data = {pid: record(pid) for pid in ("paper_a", "paper_b", "paper_c", "paper_r")}
    os.makedirs(os.path.join(ROOT, "web"), exist_ok=True)
    with open(os.path.join(ROOT, "web", "recorded.json"), "w", encoding="utf-8") as f:
        json.dump(scrub(_clean(data)), f, separators=(",", ":"))
    print("wrote web/recorded.json", os.path.getsize(os.path.join(ROOT, "web", "recorded.json")) // 1024, "KB")
