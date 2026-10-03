"""Server mode: submit an audit over HTTP, poll it to completion, check idempotency and limits."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PREFLIGHT_SANDBOX", "subprocess")

from fastapi.testclient import TestClient  # noqa: E402

from engine import load_paper_dir  # noqa: E402
from server.app import app  # noqa: E402

client = TestClient(app)


def test_audit_over_http():
    paper, files, _ = load_paper_dir(os.path.join(ROOT, "papers", "paper_b"))
    r = client.post("/api/audits", json={"paper": paper, "files": files})
    assert r.status_code == 202, r.text
    jid = r.json()["id"]
    for _ in range(240):
        s = client.get(f"/api/audits/{jid}").json()
        if s["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert s["status"] == "done", s
    assert [c["verdict"] for c in s["result"]["claims"]] == ["reproduced", "reproduced"]
    assert s["result"]["executor"] == "subprocess"
    ev = client.get(f"/api/audits/{jid}/events?after=0").json()
    assert ev["next"] > 10
    again = client.post("/api/audits", json={"paper": paper, "files": files})
    assert again.status_code == 200 and again.json()["id"] == jid and again.json()["cached"]


def test_bad_input_and_health():
    assert client.post("/api/audits", json={"paper": "x"}).status_code == 400
    assert client.get("/api/audits/nope").status_code == 404
    assert client.get("/healthz").json()["ok"]
