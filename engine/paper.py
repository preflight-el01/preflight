"""Paper parsing: sections, sentences, tables -> structured claims and stated setup.

The demo papers are Markdown. In production the same schema is filled from a PDF
by GROBID (structure + tables) followed by an LLM pass that maps table cells to
claims; everything downstream of this module consumes only the schema below.
"""
import re

from . import vocab

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}

# Stated-setup patterns. Each returns (param, value, matched_text).
PARAM_EQ = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(-?[0-9]+(?:\.[0-9]+)?(?:e-?[0-9]+)?|[a-z_]+)")
SEEDS = re.compile(r"(?:averaged over|mean over)\s+(\d+|one|two|three|four|five|ten)\s+(?:random\s+)?seeds", re.I)
SPLIT_PAIR = re.compile(r"\b(\d{2})\s*/\s*(\d{2})\s+(?:train\s*/\s*test\s+)?split", re.I)
SPLIT_HOLDOUT = re.compile(r"hold out\s+(\d{1,2})%\s+of\s+samples", re.I)
SIGNIF = re.compile(r"(significantly|substantially|clearly|consistently)\s+outperforms", re.I)
COMPARE = re.compile(
    r"(?:The\s+)?(?P<a>[A-Z][\w\-() /]*?)\s+(?P<adv>significantly|substantially|clearly|consistently)?\s*outperforms\s+(?:the\s+)?(?P<b>[A-Za-z][\w\- ()]*?)\s+on\s+"
    r".*?by\s+(?P<margin>[0-9.]+)\s+points", re.I)


def _coerce(v):
    try:
        f = float(v)
        return int(f) if re.fullmatch(r"-?\d+", v) else f
    except ValueError:
        return v


def parse(text):
    meta, body = {}, text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for line in fm.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()

    sections, tables, sentences = [], [], []
    current = {"id": "front", "heading": "", "level": 1, "parent": None}
    sections.append(current)
    lines = body.strip().splitlines()
    i = 0
    pending_caption = None
    while i < len(lines):
        line = lines[i].rstrip()
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            parent = None
            if level == 3:
                parent = next((s["id"] for s in reversed(sections) if s["level"] == 2), None)
            current = {"id": f"s{len(sections)}", "heading": m.group(2).strip(), "level": level, "parent": parent}
            sections.append(current)
            i += 1
            continue
        cap = re.match(r"^(Table\s+\d+):\s*(.*)$", line)
        if cap:
            pending_caption = (cap.group(1), cap.group(2))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"-+", c) for c in cells):
                    rows.append({"cells": cells, "line": i})
                i += 1
            label, caption = pending_caption or (f"Table {len(tables) + 1}", "")
            tables.append({"id": label.lower().replace(" ", ""), "label": label, "caption": caption,
                           "header": rows[0]["cells"], "rows": [r["cells"] for r in rows[1:]],
                           "section": current["id"]})
            pending_caption = None
            continue
        if line.strip():
            for s in SENT_SPLIT.split(line.strip()):
                sentences.append({"id": f"q{len(sentences)}", "text": s, "section": current["id"]})
        i += 1

    paper = {"meta": meta, "sections": sections, "tables": tables, "sentences": sentences}
    paper["setup"] = extract_setup(paper)
    paper["claims"] = extract_claims(paper)
    return paper


def section_methods(paper, section_id):
    """Methods a section is about, read from its heading."""
    sec = next(s for s in paper["sections"] if s["id"] == section_id)
    return vocab.methods_in(sec["heading"])


def extract_setup(paper):
    """Stated experimental settings, each tied to the sentence that states it."""
    out = []
    for s in paper["sentences"]:
        sec = next(x for x in paper["sections"] if x["id"] == s["section"])
        scope = vocab.methods_in(sec["heading"]) or vocab.methods_in(s["text"])
        datasets = vocab.datasets_in(sec["heading"]) or vocab.datasets_in(s["text"])
        is_global = "protocol" in sec["heading"].lower()
        base = {"sentence": s["id"], "section": s["section"], "scope": scope,
                "datasets": datasets, "global": is_global}

        # In a section covering two methods, each "name = value" belongs to the
        # nearest method named before it in the sentence.
        for m in PARAM_EQ.finditer(s["text"]):
            name = vocab.canonical_param(m.group(1))
            if not name:
                continue
            owner = scope
            if len(scope) > 1:
                prefix = s["text"][: m.start()]
                hits = [(prefix.lower().rfind(a), meth) for meth in scope for a in vocab.METHODS[meth]["aliases"]]
                hits = [h for h in hits if h[0] >= 0]
                if hits:
                    owner = [max(hits)[1]]
            out.append({**base, "scope": owner, "param": name, "value": _coerce(m.group(2)),
                        "text": m.group(0)})
        m = SEEDS.search(s["text"])
        if m:
            n = m.group(1).lower()
            out.append({**base, "param": "seeds", "value": NUM_WORDS.get(n, int(n) if n.isdigit() else n),
                        "text": m.group(0)})
        m = SPLIT_PAIR.search(s["text"])
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.append({**base, "param": "test_size", "value": round(b / (a + b), 4), "text": m.group(0)})
        m = SPLIT_HOLDOUT.search(s["text"])
        if m:
            out.append({**base, "param": "test_size", "value": int(m.group(1)) / 100, "text": m.group(0)})
    return out


def extract_claims(paper):
    claims = []
    for t in paper["tables"]:
        col_head = t["header"][1:]
        for r, row in enumerate(t["rows"]):
            method_label = row[0]
            methods = vocab.methods_in(method_label)
            for c, cell in enumerate(row[1:]):
                try:
                    value = float(cell)
                except ValueError:
                    continue
                head = col_head[c]
                ds = vocab.datasets_in(head)
                claims.append({
                    "id": f"C{len(claims) + 1}",
                    "kind": "value",
                    "label": f"{method_label} on {vocab.DATASETS[ds[0]]['name'] if ds else head}",
                    "method_label": method_label,
                    "methods": methods,
                    "dataset": ds[0] if ds else None,
                    "metric": vocab.metric_in(head),
                    "value": value,
                    "decimals": len(cell.split(".")[1]) if "." in cell else 0,
                    "source": {"table": t["id"], "table_label": t["label"], "row": r, "col": c + 1,
                               "cell": cell, "caption": t["caption"]},
                })
    for s in paper["sentences"]:
        m = COMPARE.search(s["text"])
        if not m:
            continue
        a = vocab.methods_in(m.group("a"))
        b = vocab.methods_in(m.group("b"))
        if not a or not b:
            continue
        ds = vocab.datasets_in(s["text"])
        claims.append({
            "id": f"C{len(claims) + 1}",
            "kind": "comparison",
            "label": f"{vocab.METHODS[a[0]]['name']} beats {vocab.METHODS[b[0]]['name']}",
            "a": a[0], "b": b[0],
            "methods": [a[0], b[0]],
            "dataset": ds[0] if ds else None,
            "metric": "accuracy",
            "value": float(m.group("margin")),
            "decimals": 2,
            "wording": (m.group("adv") or "").lower() or None,
            "source": {"sentence": s["id"], "text": s["text"]},
        })
    # each value claim also points at the sentences stating its setup
    return claims
