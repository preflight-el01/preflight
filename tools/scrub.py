"""Strip machine-specific paths (user name, temp and venv folders) from recorded output.

Tracebacks from the recording machine would otherwise show C:\\Users\\<name>\\... in the replay.
Paths inside the per-run sandbox become repo-relative; library paths keep only the part after site-packages.
"""
import re

SITE = re.compile(r"[A-Za-z]:[\\/][^\"'\n]*?[\\/](?:site|dist)-packages[\\/]")
SANDBOX = re.compile(r"[A-Za-z]:[\\/][^\"'\n]*?[\\/](?:pf_run|pfrun|pf_|tmp)[A-Za-z0-9_]+[\\/](?:repo[\\/])?")
PYHOME = re.compile(r"[A-Za-z]:[\\/][^\"'\n]*?[\\/](?:Python\d+|pf18)[\\/](?:Lib[\\/])?")
ENGINE = re.compile(r"[A-Za-z]:[\\/][^\"'\n]*?[\\/]engine[\\/]")
ANYUSER = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\"'\n]+[\\/][^\"'\n]*?([^\\/\"'\n]+\.py)")


def scrub_str(s):
    if ":\\" not in s and ":/" not in s:
        return s
    s = SITE.sub("<site-packages>/", s)
    s = SANDBOX.sub("", s)
    s = PYHOME.sub("<python>/", s)
    s = ANYUSER.sub(r"\1", s)
    return s


def scrub(x):
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    if isinstance(x, str):
        return scrub_str(x)
    return x


if __name__ == "__main__":
    import collections
    import json
    import os
    import sys
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "recorded.json")
    data = json.load(open(path, encoding="utf-8"))
    found = collections.Counter()

    def walk(x):
        if isinstance(x, dict):
            [walk(v) for v in x.values()]
        elif isinstance(x, list):
            [walk(v) for v in x]
        elif isinstance(x, str):
            for m in re.findall(r"[A-Za-z]:[\\/][^\"'\n]{0,120}", x):
                found[m[:110]] += 1

    if "--show" in sys.argv:
        walk(data)
        for k, v in found.most_common(15):
            print(v, k)
        sys.exit()
    clean = scrub(data)
    walk(clean)
    print("remaining local paths:", sum(found.values()))
    for k, v in found.most_common(5):
        print(v, k)
    if "--write" in sys.argv:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, separators=(",", ":"))
        print("wrote", path)
