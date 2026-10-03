"""Bundle the engine, demo papers and recorded runs into one self-contained page: dist/index.html."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import STAGES, load_paper_dir  # noqa: E402


def main():
    engine = {}
    for fn in sorted(os.listdir(os.path.join(ROOT, "engine"))):
        if fn.endswith(".py"):
            with open(os.path.join(ROOT, "engine", fn), encoding="utf-8") as f:
                engine[f"engine/{fn}"] = f.read()
    papers = {}
    for pid in ("paper_a", "paper_b", "paper_c", "paper_r"):
        paper, files, key = load_paper_dir(os.path.join(ROOT, "papers", pid))
        papers[pid] = {"paper": paper, "files": files, "key": key}
    import base64
    from engine import extract as ex
    with open(os.path.join(ROOT, "papers", "paper_c", "paper.pdf"), "rb") as f:
        sample_pdf = base64.b64encode(f.read()).decode()
    bundle = {"engine": engine, "papers": papers, "sample_pdf": sample_pdf,
              "extract": {"model": ex.MODEL, "system": ex.SYSTEM, "schema": ex.SCHEMA, "instruction": ex.INSTRUCTION},
              "stages": [{"id": s, "title": t, "desc": d} for s, t, d in STAGES]}
    with open(os.path.join(ROOT, "web", "recorded.json"), encoding="utf-8") as f:
        recorded = f.read()
    with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
        page = f.read()

    def safe(s):
        return s.replace("</", "<\\/")

    page = page.replace("__BUNDLE__", safe(json.dumps(bundle, separators=(",", ":"))), 1)
    page = page.replace("__RECORDED__", safe(recorded), 1)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    # artifact.html: body-only page for the claude.ai Artifact host (it adds the skeleton)
    # index.html: standalone page for GitHub Pages / any static host / a USB stick
    head = ['<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">']
    standalone = "\n".join(head) + "\n" + page + "\n</html>\n"
    for name, text in (("artifact.html", page), ("index.html", standalone)):
        out = os.path.join(ROOT, "dist", name)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
