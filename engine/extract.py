"""AI paper reader: a PDF (or pasted text) in, Preflight's paper format out.

This is the one step where an LLM is used. Claude reads the paper and writes the
claims, the stated setup and the result tables in the Markdown grammar that
paper.py parses. A person reviews that Markdown before anything runs, and every
verdict afterwards comes from re-runs, never from the model.

The same SYSTEM prompt and SCHEMA are used by the browser (bundled into the page)
and by the CLI / server (below).
"""
import base64
import json

MODEL = "claude-opus-5-5"

SYSTEM = """You convert machine-learning papers into the input format of Preflight, a tool that re-runs a paper's experiments and checks every reported number.

Write the paper as Markdown in exactly this grammar:

---
id: custom
title: <paper title>
authors: <authors as printed in the paper>
venue: Converted by Preflight's AI reader. Check the tables and settings before auditing.
repo: (uploaded)
---

## Abstract

<one to three sentences>

## 1 Experimental protocol

<one or two sentences that state ONLY what the paper states about evaluation, written with these exact phrasings when they apply:
 - the split as "a stratified 80/20 train/test split" (use the paper's numbers), or "We hold out 25% of samples for testing";
 - the number of runs as "averaged over 5 random seeds" (use the paper's number).
 If a dataset name applies only to some results, name it in the sentence.>

## 2 Methods

### 2.1 <method name as in the results table>

<sentences that state this method's settings. Write every numeric or categorical setting as name = value, using the scikit-learn parameter name when there is a direct equivalent: C, max_iter, max_depth, n_neighbors, gamma, k (number of selected features), n_estimators, learning_rate, alpha, kernel. Example: "Logistic regression uses C = 1.0 and max_iter = 1000.">

(one ### section per method)

## 3 Results

Table 1: <caption ending with a period>.

| Method | <Dataset> acc. (%) |
|---|---|
| <method> | <number> |

Rules for tables:
- One table per results table in the paper. The first column holds method names; other columns are datasets, and the header names the dataset and the metric, e.g. "Breast Cancer acc. (%)", "Digits macro-F1 (%)", "ImageNet-1k top-1 (%)".
- Report numbers as percentages, with exactly the decimals printed in the paper. Leave a cell empty if the paper has none.
- Never compute, round differently, or invent a number. Copy only numbers printed in the paper.

Comparative claims: for every sentence that says one method beats another by a stated margin, write one sentence in the Results section of the form
"The <method A> <adverb if the paper uses one, e.g. significantly> outperforms <method B> on <Dataset>, by <margin> points."

General rules:
- Keep the paper's meaning. Do not add settings the paper does not state; missing details are something Preflight checks for.
- Keep sentences about how features were selected, how hyperparameters were tuned, and what data was used for tuning; Preflight checks these for leakage.
- Plain sentences only, no bullet lists, no bold, no citations in brackets.
- In "notes", list anything you were unsure about, numbers you could not read, and claims you left out and why."""

SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string", "description": "The paper in Preflight's Markdown grammar."},
        "notes": {"type": "array", "items": {"type": "string"},
                  "description": "Uncertainties, unreadable numbers, omitted claims."},
        "claims_found": {"type": "integer", "description": "Number of numeric result cells written into tables."},
    },
    "required": ["markdown", "notes", "claims_found"],
    "additionalProperties": False,
}

INSTRUCTION = "Convert this paper into Preflight's format. Return the JSON object only."


def extract(pdf_bytes=None, text=None, client=None):
    """Return {"markdown", "notes", "claims_found"} for a PDF (bytes) or plain text."""
    import anthropic

    client = client or anthropic.Anthropic()
    if pdf_bytes is not None:
        doc = {"type": "document",
               "source": {"type": "base64", "media_type": "application/pdf",
                          "data": base64.standard_b64encode(pdf_bytes).decode()}}
    else:
        doc = {"type": "text", "text": f"<paper>\n{text}\n</paper>"}
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [doc, {"type": "text", "text": INSTRUCTION}]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to read this paper.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("The paper was too long to convert in one pass.")
    out = "".join(b.text for b in response.content if b.type == "text")
    return json.loads(out)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="preflight extract")
    ap.add_argument("paper", help="paper.pdf or paper.txt")
    ap.add_argument("--out", required=True, help="where to write paper.md")
    args = ap.parse_args(argv)
    if args.paper.lower().endswith(".pdf"):
        with open(args.paper, "rb") as f:
            res = extract(pdf_bytes=f.read())
    else:
        with open(args.paper, encoding="utf-8") as f:
            res = extract(text=f.read())
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(res["markdown"])
    print(f"wrote {args.out}: {res['claims_found']} result cells")
    for n in res["notes"]:
        print(" -", n)


if __name__ == "__main__":
    main()
