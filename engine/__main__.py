"""Command line: python -m engine audit <paper_dir> [--out report.md] [--json result.json] [--sandbox subprocess]

<paper_dir> holds paper.md and repo/. The same engine runs in the browser demo.
"""
import argparse
import json
import sys

from . import DockerExecutor, SubprocessExecutor, InProcessExecutor, audit, load_paper_dir, safe_json


def main(argv=None):
    ap = argparse.ArgumentParser(prog="preflight")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="audit a paper directory (paper.md + repo/)")
    a.add_argument("paper_dir")
    a.add_argument("--out", help="write the Markdown report here")
    a.add_argument("--json", help="write the full evidence JSON here")
    a.add_argument("--badge", help="write a README badge (SVG) here")
    a.add_argument("--card", help="write the Reproducibility Card (YAML) here")
    a.add_argument("--sandbox", choices=["inprocess", "subprocess", "docker"], default="inprocess",
                   help="subprocess runs each experiment as `python script.py` with a timeout")
    a.add_argument("--quiet", action="store_true")
    e = sub.add_parser("extract", help="AI paper reader: PDF or text -> paper.md (needs ANTHROPIC_API_KEY)")
    e.add_argument("paper")
    e.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "extract":
        from .extract import main as extract_main
        return extract_main([args.paper, "--out", args.out])

    paper, files, key = load_paper_dir(args.paper_dir)

    def emit(kind, data):
        if kind == "log" and not args.quiet:
            print(f"[{data['stage']:>9}] {data['text']}", file=sys.stderr)

    ex = {"subprocess": SubprocessExecutor, "docker": DockerExecutor}.get(args.sandbox, InProcessExecutor)()
    res = audit(paper, files, key, executor=ex, emit=emit)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(res["artifacts"]["report_md"])
    for path, key in ((args.badge, "badge_svg"), (args.card, "card")):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(res["artifacts"][key])
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(safe_json(res))
    print(f"Replicability Index {res['index']['score']:.0f}/100 · "
          + ", ".join(f"{c['id']} {c['verdict']}" for c in res["claims"]))
    if res.get("benchmark") and res["benchmark"]["total"]:
        b = res["benchmark"]
        print(f"Planted issues caught {b['caught']}/{b['total']}, false alarms {len(b['false_alarms'])}")


if __name__ == "__main__":
    main()
