"""Controlled execution of repo scripts.

Every run gets a fresh copy of the repo with its edits applied (parameter swaps,
seed injection, patches), a hash over everything that can change the result, an
instrumented sklearn (probe), captured stdout/stderr, and a cache keyed by hash.

Executors:
  InProcessExecutor   runs the script with runpy in this interpreter. Used in the
                      browser (Pyodide/WASM: no network, no host filesystem) and
                      for the recorded replay, so both share one code path.
  SubprocessExecutor  `python script.py` in a temp dir with a timeout.
  DockerExecutor      the same inside a throwaway container: --network none, CPU and
                      RAM caps, a PID limit, a read-only root filesystem.
Child processes get the same sklearn probe through an injected sitecustomize.py.
"""
import hashlib
import io
import json
import os
import runpy
import sys
import tempfile
import time
import traceback
import contextlib

from .probe import Probe

def runtime_versions():
    import platform
    import numpy
    import sklearn
    import scipy
    return {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": numpy.__version__,
            "scipy": scipy.__version__, "platform": sys.platform}


# ----------------------------------------------------------------------------- executors
class InProcessExecutor:
    name = "in-process (runpy)"

    def __init__(self, root=None):
        self.root = root or os.path.join(tempfile.gettempdir(), "preflight_sandbox")

    def execute(self, files, script, argv, run_id, probe_opts=None):
        work = os.path.join(self.root, run_id)
        for path, text in files.items():
            full = os.path.join(work, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(text)
        script_dir = os.path.dirname(os.path.join(work, script))
        local = {os.path.splitext(os.path.basename(p))[0] for p in files if p.endswith(".py")}
        old = (os.getcwd(), list(sys.path), list(sys.argv))
        for m in local:
            sys.modules.pop(m, None)
        out, err = io.StringIO(), io.StringIO()
        probe = Probe(**(probe_opts or {})).install()
        rc = 0
        t0 = time.perf_counter()
        try:
            os.chdir(work)
            sys.path.insert(0, script_dir)
            sys.argv = [script] + argv
            import warnings
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    runpy.run_path(os.path.join(work, script), run_name="__main__")
                except SystemExit as e:
                    rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                except BaseException:
                    traceback.print_exc()
                    rc = 1
        finally:
            seconds = time.perf_counter() - t0
            probe.uninstall()
            os.chdir(old[0])
            sys.path[:] = old[1]
            sys.argv[:] = old[2]
            for m in local:
                sys.modules.pop(m, None)
        return {"stdout": out.getvalue(), "stderr": _clean_tb(err.getvalue(), work), "returncode": rc,
                "seconds": round(seconds, 3), "probe": probe.events}


PROBE_TAG = "##PREFLIGHT "
SITECUSTOMIZE = """import atexit, json, os, sys
from preflight_probe import Probe
_p = Probe(dedupe=os.environ.get("PREFLIGHT_DEDUPE") == "1").install()
atexit.register(lambda: sys.stderr.write("\\n##PREFLIGHT " + json.dumps(_p.events) + "\\n"))
"""


def _stage(files, run_id):
    """Write the repo copy plus the probe into a fresh temp dir."""
    work = tempfile.mkdtemp(prefix=f"pf_{run_id[:8]}_")
    for path, text in files.items():
        full = os.path.join(work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
    os.makedirs(os.path.join(work, "_pf"), exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__), "probe.py"), encoding="utf-8") as f:
        probe_src = f.read()
    with open(os.path.join(work, "_pf", "preflight_probe.py"), "w", encoding="utf-8") as f:
        f.write(probe_src)
    with open(os.path.join(work, "_pf", "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(SITECUSTOMIZE)
    return work


def _split_probe(stderr):
    events, keep = [], []
    for ln in stderr.splitlines():
        if ln.startswith(PROBE_TAG):
            try:
                events = json.loads(ln[len(PROBE_TAG):])
            except ValueError:
                pass
        else:
            keep.append(ln)
    return events, "\n".join(keep).strip()


class SubprocessExecutor:
    name = "subprocess"

    def __init__(self, python=sys.executable, timeout=120):
        self.python, self.timeout = python, timeout

    def _cmd(self, work, script, argv, probe_opts):
        env = dict(os.environ, PYTHONPATH=os.path.join(work, "_pf"),
                   PREFLIGHT_DEDUPE="1" if (probe_opts or {}).get("dedupe") else "0", PYTHONHASHSEED="0")
        return [self.python, script] + argv, env

    def execute(self, files, script, argv, run_id, probe_opts=None):
        import subprocess
        work = _stage(files, run_id)
        cmd, env = self._cmd(work, script, argv, probe_opts)
        t0 = time.perf_counter()
        try:
            p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=self.timeout, env=env)
            rc, so, se = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            rc, so, se = 124, "", f"timeout after {self.timeout}s"
        events, se = _split_probe(se)
        return {"stdout": so, "stderr": _clean_tb(se, work), "returncode": rc,
                "seconds": round(time.perf_counter() - t0, 3), "probe": events}


class DockerExecutor(SubprocessExecutor):
    """One throwaway container per run. Build the image from Dockerfile.runner first."""
    name = "docker"

    def __init__(self, image="preflight-runner", cpus="1", memory="2g", timeout=300):
        super().__init__(timeout=timeout)
        self.image, self.cpus, self.memory = image, cpus, memory

    def _cmd(self, work, script, argv, probe_opts):
        dedupe = "1" if (probe_opts or {}).get("dedupe") else "0"
        cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", self.cpus, "--memory", self.memory,
               "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp", "--security-opt", "no-new-privileges",
               "-v", f"{work}:/work", "-w", "/work", "-e", "PYTHONPATH=/work/_pf", "-e", f"PREFLIGHT_DEDUPE={dedupe}",
               "-e", "PYTHONHASHSEED=0", self.image, "python", script] + argv
        return cmd, dict(os.environ)


def _clean_tb(text, work):
    text = text.replace(work + os.sep, "").replace(work.replace("\\", "/") + "/", "")
    lines = [ln for ln in text.splitlines() if "runpy" not in ln and "<frozen" not in ln]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- sandbox
def apply_edit(text, edit):
    """edit: {line, col, end_col, new} replaces a span on one line (1-based line)."""
    lines = text.split("\n")
    i = edit["line"] - 1
    ln = lines[i]
    end = edit.get("end_col")
    if end is None:
        end = len(ln.split("#")[0].rstrip())
    lines[i] = ln[:edit["col"]] + edit["new"] + ln[end:]
    return "\n".join(lines)


class Sandbox:
    def __init__(self, files, executor, emit=None):
        self.files = dict(files)
        self.executor = executor
        self.emit = emit or (lambda *a, **k: None)
        self.cache = {}
        self.runs = []
        self.versions = runtime_versions()

    def run(self, script, argv=(), edits=(), patches=None, label="", purpose="", claim=None, probe_opts=None):
        files = dict(self.files)
        if patches:
            files.update(patches)
        # apply span edits bottom-up per file so columns stay valid
        by_file = {}
        for e in edits:
            by_file.setdefault(e["file"], []).append(e)
        for f, es in by_file.items():
            text = files[f]
            for e in sorted(es, key=lambda e: (e["line"], e["col"]), reverse=True):
                text = apply_edit(text, e)
            files[f] = text
        argv = list(argv)
        h = hashlib.sha256()
        for p in sorted(files):
            h.update(p.encode())
            h.update(files[p].encode())
        h.update(json.dumps([script, argv, self.versions, probe_opts or {}], sort_keys=True).encode())
        digest = h.hexdigest()
        command = " ".join(["python", script] + argv)
        if digest in self.cache:
            res = dict(self.cache[digest])
            res.update({"cached": True, "label": label, "purpose": purpose, "claim": claim,
                        "id": f"r{len(self.runs) + 1}"})
            self.runs.append(res)
            self.emit("run", res)
            return res
        out = self.executor.execute(files, script, argv, digest[:16], probe_opts)
        res = {"id": f"r{len(self.runs) + 1}", "hash": digest[:12], "command": command, "label": label,
               "purpose": purpose, "claim": claim, "edits": [_edit_summary(e) for e in edits],
               "patched_files": sorted((patches or {}).keys()), "cached": False, **out}
        self.cache[digest] = res
        self.runs.append(res)
        self.emit("run", res)
        return res


def _edit_summary(e):
    return {"file": e["file"], "line": e["line"], "new": e["new"], "why": e.get("why", "")}
