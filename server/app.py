"""Preflight server mode: the same engine behind an HTTP API, with a job queue.

    uvicorn server.app:app --port 8000
    PREFLIGHT_SANDBOX=docker uvicorn server.app:app      # one container per experiment run

Endpoints
  POST /api/audits            submit {paper, files | repo_url} or multipart (paper / paper_pdf, repo_zip | repo_url)
  GET  /api/audits/{id}       status, progress and (when done) the full evidence JSON
  GET  /api/audits/{id}/events?after=N   events since N (the browser UI polls this)
  GET  /api/audits/{id}/stream           the same as server-sent events
  POST /api/extract           AI paper reader: PDF or text -> Preflight Markdown (needs ANTHROPIC_API_KEY)
  GET  /healthz               liveness + queue depth
  GET  /                      the web UI (dist/index.html)

Scaling: the API is stateless apart from the job store. Swap JobStore for Redis and
the thread pool for RQ/Celery workers to run many API replicas and an autoscaled
worker pool; runs are cached by content hash, so a repeated submission is free.
"""
import asyncio
import hashlib
import io
import json
import os
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402

from engine import Audit, DockerExecutor, InProcessExecutor, SubprocessExecutor, safe_json  # noqa: E402

MAX_FILES, MAX_FILE_BYTES, MAX_ZIP_BYTES = 200, 300_000, 20_000_000
TEXT_EXT = (".py", ".yaml", ".yml", ".json", ".txt", ".md", ".cfg", ".toml", ".ini")
WORKERS = int(os.environ.get("PREFLIGHT_WORKERS", "2"))
SANDBOX = os.environ.get("PREFLIGHT_SANDBOX", "subprocess")
RATE = float(os.environ.get("PREFLIGHT_RATE_PER_MIN", "6"))


def make_executor():
    if SANDBOX == "docker":
        return DockerExecutor(image=os.environ.get("PREFLIGHT_RUNNER_IMAGE", "preflight-runner"))
    if SANDBOX == "inprocess":
        return InProcessExecutor()
    return SubprocessExecutor(timeout=int(os.environ.get("PREFLIGHT_RUN_TIMEOUT", "120")))


class JobStore:
    """In-memory job store. Same interface as a Redis-backed store for multi-replica deployments."""

    def __init__(self):
        self.jobs, self.by_hash, self.lock = {}, {}, threading.Lock()

    def create(self, digest):
        with self.lock:
            if digest in self.by_hash:  # idempotent: the same paper + repo returns the same job
                return self.jobs[self.by_hash[digest]], False
            job = {"id": uuid.uuid4().hex[:12], "hash": digest, "status": "queued", "created": time.time(),
                   "events": [], "result": None, "error": None}
            self.jobs[job["id"]] = job
            self.by_hash[digest] = job["id"]
            return job, True

    def get(self, jid):
        return self.jobs.get(jid)

    def forget(self, job):
        with self.lock:
            self.by_hash.pop(job["hash"], None)

    def depth(self):
        return sum(1 for j in self.jobs.values() if j["status"] in ("queued", "running"))


store = JobStore()
pool = ThreadPoolExecutor(max_workers=WORKERS)
buckets = {}
app = FastAPI(title="Preflight", version="0.2.0")


def rate_limit(ip):
    """Token bucket per client IP: RATE audits per minute, bursts of up to RATE."""
    now = time.time()
    tokens, last = buckets.get(ip, (RATE, now))
    tokens = min(RATE, tokens + (now - last) * RATE / 60)
    if tokens < 1:
        raise HTTPException(429, "Too many audits from this address. Try again in a minute.")
    buckets[ip] = (tokens - 1, now)


def run_job(job, paper, files):
    job["status"] = "running"

    def emit(kind, data):
        job["events"].append({"kind": kind, "data": json.loads(safe_json(data))})

    try:
        res = Audit(paper, files, make_executor(), emit=emit).run()
        job["result"] = json.loads(safe_json(res))
        job["status"] = "done"
    except Exception as e:  # graceful degradation: keep the events, report the failure
        job["error"] = f"{type(e).__name__}: {e}"
        job["status"] = "failed"
        store.forget(job)  # allow a retry of the same submission


def clean_files(files):
    out = {}
    for path, text in list(files.items())[:MAX_FILES]:
        path = path.replace("\\", "/").lstrip("/")
        if ".." in path.split("/") or not path.endswith(TEXT_EXT) and not path.endswith("README"):
            continue
        if len(text) <= MAX_FILE_BYTES:
            out[path] = text
    if not out:
        raise HTTPException(400, "No usable source files in the repository.")
    return out


def files_from_zip(data):
    if len(data) > MAX_ZIP_BYTES:
        raise HTTPException(413, "The zip is larger than 20 MB.")
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        prefix = os.path.commonprefix(names)
        prefix = prefix[: prefix.rfind("/") + 1] if "/" in prefix else ""
        for n in names:
            if n.endswith(TEXT_EXT) or n.endswith("README"):
                out[n[len(prefix):]] = z.read(n).decode("utf-8", errors="replace")
    return out


def files_from_github(spec):
    import urllib.request
    parts = spec.strip().replace("https://github.com/", "").removesuffix(".git").split("/")
    if len(parts) < 2:
        raise HTTPException(400, "Use the form owner/repo.")
    url = f"https://codeload.github.com/{parts[0]}/{parts[1]}/zip/HEAD"
    with urllib.request.urlopen(url, timeout=30) as r:
        return files_from_zip(r.read())


def submit(paper, files):
    files = clean_files(files)
    digest = hashlib.sha256((paper + json.dumps(files, sort_keys=True)).encode()).hexdigest()
    job, new = store.create(digest)
    if new:
        pool.submit(run_job, job, paper, files)
    return job, new


@app.post("/api/audits")
async def create_audit(request: Request, paper: str = Form(None), paper_pdf: UploadFile = File(None),
                       repo_zip: UploadFile = File(None), repo_url: str = Form(None)):
    rate_limit(request.client.host if request.client else "?")
    files = None
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        paper, files, repo_url = body.get("paper"), body.get("files"), body.get("repo_url")
    if paper_pdf is not None and not paper:
        from engine.extract import extract
        paper = (await asyncio.to_thread(extract, pdf_bytes=await paper_pdf.read()))["markdown"]
    if not paper:
        raise HTTPException(400, "Send the paper as Markdown (paper) or a PDF (paper_pdf).")
    if files is None:
        if repo_zip is not None:
            files = files_from_zip(await repo_zip.read())
        elif repo_url:
            files = await asyncio.to_thread(files_from_github, repo_url)
        else:
            raise HTTPException(400, "Send the repository as files, repo_zip or repo_url.")
    job, new = submit(paper, files)
    return JSONResponse({"id": job["id"], "status": job["status"], "cached": not new}, status_code=202 if new else 200)


@app.get("/api/audits/{jid}")
def get_audit(jid: str):
    job = store.get(jid) or (_ for _ in ()).throw(HTTPException(404, "No such audit."))
    stages = [e["data"] for e in job["events"] if e["kind"] == "stage" and e["data"].get("status") == "done"]
    return {"id": jid, "status": job["status"], "error": job["error"], "stages_done": len(stages),
            "events": len(job["events"]), "result": job["result"]}


@app.get("/api/audits/{jid}/events")
def get_events(jid: str, after: int = 0):
    job = store.get(jid) or (_ for _ in ()).throw(HTTPException(404, "No such audit."))
    return {"status": job["status"], "next": len(job["events"]), "events": job["events"][after:]}


@app.get("/api/audits/{jid}/stream")
async def stream(jid: str):
    job = store.get(jid) or (_ for _ in ()).throw(HTTPException(404, "No such audit."))

    async def gen():
        i = 0
        while True:
            while i < len(job["events"]):
                yield f"event: {job['events'][i]['kind']}\ndata: {json.dumps(job['events'][i]['data'])}\n\n"
                i += 1
            if job["status"] in ("done", "failed") and i >= len(job["events"]):
                yield f"event: end\ndata: {json.dumps({'status': job['status']})}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/extract")
async def extract_paper(request: Request, paper_pdf: UploadFile = File(None), text: str = Form(None)):
    rate_limit(request.client.host if request.client else "?")
    from engine.extract import extract
    if paper_pdf is not None:
        return await asyncio.to_thread(extract, pdf_bytes=await paper_pdf.read())
    if text:
        return await asyncio.to_thread(extract, text=text)
    raise HTTPException(400, "Send paper_pdf or text.")


@app.get("/healthz")
def healthz():
    return {"ok": True, "sandbox": SANDBOX, "workers": WORKERS, "queue_depth": store.depth()}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "dist", "index.html"))
