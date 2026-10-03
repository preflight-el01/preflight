"""Build the 8-slide Elevate submission deck on the official template.

    python tools/make_deck.py --team "Team name" --demo-url https://... --repo-url https://... --video-url https://...

Every number comes from web/recorded.json (the recorded runs) or the live timings noted below.
Screenshots come from tools/deck_shots.py. Output: deck/EL-01_<team>.pptx
"""
import argparse
import copy
import json
import os
import re

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECK = os.path.join(ROOT, "deck")
SHOTS = os.path.join(DECK, "shots")

NAVY, PEACH, ORANGE, WHITE = "003470", "FFCD82", "FF914D", "FFFFFF"
INK2, OK, WARN, BAD, MUTED = "35507A", "0A7A51", "A06200", "C52F3B", "6A7A90"
TITLE_FONT, BODY, BODY_B = "Anton", "Agrandir", "Agrandir Bold"
FS_TEXT, FS_TABLE = 1.4, 1.22  # the template canvas is 20 in wide: scale type for the projector
LIVE_SECONDS = {"paper_a": 6.0, "paper_b": 2.6, "paper_c": 55, "paper_r": 13.3}  # measured in Chrome, Pyodide 314.0.7


def rgb(h):
    return RGBColor.from_string(h)


# ----------------------------------------------------------------------------- primitives
def box(slide, x, y, w, h, fill=WHITE, alpha=82, line=None, radius=0.06, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if alpha < 100:
        clr = s.fill._xPr.find(qn("a:solidFill"))[0]
        etree.SubElement(clr, qn("a:alpha")).set("val", str(int(alpha * 1000)))
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1.25)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    s.text_frame.text = ""
    if name:
        s.name = name
    return s


def text(slide, x, y, w, h, paras, size=16, color=NAVY, font=BODY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         spacing=1.05, after=4, name=None):
    """paras: list of paragraphs; each paragraph is a str or a list of (text, {bold, color, size, font}) runs."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    urls, plain = set(), False
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(after)
        runs = [(para, {})] if isinstance(para, str) else para
        runs = [(r, {}) if isinstance(r, str) else r for r in runs]
        for t, o in runs:
            r = p.add_run()
            r.text = t
            f = r.font
            f.name = o.get("font", BODY_B if o.get("bold") else font)
            f.size = Pt(round(o.get("size", size) * FS_TEXT, 1))
            f.bold = False
            f.color.rgb = rgb(o.get("color", color))
            if o.get("link"):
                link_run(r, o["link"])
                urls.add(o["link"])
            elif t.strip():
                plain = True
    if len(urls) == 1 and not plain:  # a box that is one link: link the shape too (PDF export keeps shape links)
        tb.click_action.hyperlink.address = urls.pop()
    if name:
        tb.name = name
    return tb


HLINK_CLR = "{A12FA001-AC4F-418D-AE19-62706E023703}"
AHYP = "http://schemas.microsoft.com/office/drawing/2018/hyperlinkcolor"


def link_run(r, url):
    """Clickable in edit mode, slideshow and PDF; keeps the run's own colour instead of theme blue."""
    r.hyperlink.address = url
    r.font.underline = True
    h = r._r.find(qn("a:rPr")).find(qn("a:hlinkClick"))
    ext = etree.SubElement(etree.SubElement(h, qn("a:extLst")), qn("a:ext"))
    ext.set("uri", HLINK_CLR)
    etree.SubElement(ext, "{%s}hlinkClr" % AHYP, nsmap={"ahyp": AHYP}).set("val", "tx")


def link_pic(pic, url):
    pic.click_action.hyperlink.address = url
    return pic


def picture(slide, path, x, y, w=None, h=None, crop_h=None, border=True, crop_w=None):
    img = Image.open(path)
    if crop_h or crop_w:
        img = img.crop((0, 0, int(img.width * (crop_w or 1)), int(img.height * (crop_h or 1))))
        path = path.replace(".png", f"_crop{int((crop_h or 1) * 100)}x{int((crop_w or 1) * 100)}.png")
        img.save(path)
    ar = img.width / img.height
    if w and h:
        if w / h > ar:
            w = h * ar
        else:
            h = w / ar
    elif w:
        h = w / ar
    else:
        w = h * ar
    if border:
        box(slide, x - 0.06, y - 0.06, w + 0.12, h + 0.12, fill=WHITE, alpha=100, radius=0.03)
    slide._last_pic = slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
    return w, h


def arrow(slide, x1, y1, x2, y2, color=NAVY):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(2)
    ln = c.line._get_or_add_ln()
    etree.SubElement(ln, qn("a:tailEnd")).set("type", "triangle")
    return c


def table(slide, x, y, w, rows, col_w, size=12, head_fill=NAVY, row_h=0.42, first_bold=True, colors=None):
    t = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows))).table
    tblPr = t._tbl.tblPr
    for attr in ("bandRow", "firstRow"):
        tblPr.set(attr, "0")
    for j, cw in enumerate(col_w):
        t.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        t.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            cell = t.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.1)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if i == 0:
                cell.fill.fore_color.rgb = rgb(head_fill)
            else:
                cell.fill.fore_color.rgb = rgb("FFFFFF" if i % 2 else "EEF3FA")
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = ""
            r = p.add_run()
            r.text = str(val)
            f = r.font
            f.size = Pt(round(size * FS_TABLE, 1))
            if i == 0:
                f.name, f.color.rgb = BODY_B, rgb(WHITE)
            else:
                f.name = BODY_B if (j == 0 and first_bold) else BODY
                f.color.rgb = rgb(colors(i, j, val) if colors else NAVY)
    return t


def set_title(slide, title):
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip() and "DEP" not in sh.text_frame.text and \
                sh.top < Inches(1.5) and sh.left < Inches(2):
            runs = [r for p in sh.text_frame.paragraphs for r in p.runs]
            runs[0].text = title
            for r in runs[1:]:
                r.text = ""
            sh.width = Inches(16)
            return sh


def drop_shape(slide, contains):
    for sh in list(slide.shapes):
        if sh.has_text_frame and contains in sh.text_frame.text:
            sh._element.getparent().remove(sh._element)


def notes(slide, t):
    slide.notes_slide.notes_text_frame.text = t


def takeaway(slide, lead, rest):
    """The one line a judge should remember, beside the title."""
    box(slide, 12.95, 0.62, 5.45, 1.38, fill=NAVY, alpha=100, radius=0.12, name="Takeaway")
    text(slide, 13.22, 0.74, 5.0, 0.3, ["THE POINT"], size=8.5, font=BODY_B, color=ORANGE)
    text(slide, 13.22, 1.04, 5.0, 0.95, [[(lead, {"bold": True, "color": PEACH}), (rest, {})]],
         size=11.5, color=WHITE, spacing=1.0, name="Takeaway text")


def chip(slide, x, y, label, fill=NAVY, color=WHITE, size=11, w=None):
    w = w or (0.16 + 0.095 * len(label) * size / 11)
    b = box(slide, x, y, w, 0.34, fill=fill, alpha=100, radius=0.5)
    text(slide, x, y + 0.035, w, 0.3, [label], size=size, color=color, font=BODY_B, align=PP_ALIGN.CENTER)
    return w


# ----------------------------------------------------------------------------- data
def load():
    with open(os.path.join(ROOT, "web", "recorded.json"), encoding="utf-8") as f:
        rec = json.load(f)
    R = {k: v["result"] for k, v in rec.items()}
    caught = sum(r["benchmark"]["caught"] for r in R.values() if r["benchmark"])
    planted = sum(r["benchmark"]["total"] for r in R.values() if r["benchmark"])
    fa = sum(len(r["benchmark"]["false_alarms"]) for r in R.values() if r["benchmark"])
    runs = sum(r["stats"]["runs"] for r in R.values())
    claims = sum(len(r["claims"]) for r in R.values())
    return R, dict(caught=caught, planted=planted, fa=fa, runs=runs, claims=claims)


def qr(url, path):
    import qrcode
    q = qrcode.QRCode(border=1, box_size=12)
    q.add_data(url)
    q.make(fit=True)
    q.make_image(fill_color="#003470", back_color="white").save(path)
    return path


# ----------------------------------------------------------------------------- slides
def slide1(s, a, T):
    for sh in s.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text
        if t.startswith("Team Name"):
            sh.text_frame.paragraphs[0].runs[-1].text = "Team Name: "
            r = sh.text_frame.paragraphs[0].add_run()
            r.text = a.team
            r.font.size, r.font.name, r.font.color.rgb = Pt(26), BODY, rgb(NAVY)
            sh.width = Inches(8.2)
        elif t.startswith("PS ID"):
            r = sh.text_frame.paragraphs[0].add_run()
            r.text = " EL-01"
            r.font.size, r.font.name, r.font.color.rgb = Pt(26), BODY, rgb(NAVY)
            sh.width = Inches(8.2)
        elif t.startswith("PS Name"):
            r = sh.text_frame.paragraphs[0].add_run()
            r.text = " AI-Powered ML Paper Reproducibility Platform"
            r.font.size, r.font.name, r.font.color.rgb = Pt(19), BODY, rgb(NAVY)
            sh.width = Inches(8.3)
    text(s, 2.14, 7.04, 8.2, 0.5, [[("Product: ", {"bold": True}), ("Preflight. Should you believe this ML paper?", {})]],
         size=15, name="Product line")
    text(s, 11.27, 6.9, 4.75, 2.55, [
        [("Preflight", {"bold": True}), (" re-runs every number in an ML paper over ten seeds, explains each gap "
                                       "with a counterfactual re-run, and flags results inflated by leakage, unfair "
                                       "baselines, wrong metrics or lucky seeds.", {})],
        [("Claude reads the paper; re-runs decide. ", {"bold": True}),
         (f"{T['caught']}/{T['planted']} planted issues caught, {T['fa']} false alarms.", {})]],
        size=10.8, spacing=1.0, after=4, name="Abstract text")
    if a.demo_url:
        link_pic(s.shapes.add_picture(qr(a.demo_url, os.path.join(DECK, "qr_demo.png")), Inches(16.2), Inches(6.95),
                                      Inches(1.6), Inches(1.6)), a.demo_url)
        text(s, 15.75, 8.62, 2.5, 0.4, [[("Open the live demo", {"link": a.demo_url, "bold": True})]], size=11,
             align=PP_ALIGN.CENTER)
    else:
        b = box(s, 16.2, 6.95, 1.6, 1.6, fill=WHITE, alpha=100, line=ORANGE, radius=0.05)
        b.line.dash_style = 4
        text(s, 16.2, 7.45, 1.6, 0.6, ["QR code", "live demo"], size=11, color=ORANGE, align=PP_ALIGN.CENTER, font=BODY_B)
    notes(s, "Preflight answers one question for any ML paper: should you believe it? It re-runs every reported number and "
             "explains every gap with a re-run, not an opinion.")


def slide2(s, R, T, D):
    set_title(s, "PROPOSED SOLUTION")
    drop_shape(s, "Proposed Solution and Core Concept")
    takeaway(s, "Reproducing is not enough. ", "We show whether to believe a result, and prove it with a re-run.")
    text(s, 0.66, 2.68, 11.3, 1.1, [[("The problem: ", {"bold": True, "color": ORANGE}),
                                     ("ML results can reproduce and still mislead: leaked test data, untuned baselines, lucky seeds.", {})],
                                    [("Today's tools ", {"bold": True}), ("stop at “does it run?”. Preflight asks “should you believe it?”", {})]],
         size=13, spacing=1.0, after=3)
    steps = [("1", "Paper + repo", "PDF read by Claude; repo by folder or GitHub"),
             ("2", "Claims", "every table cell and comparison"),
             ("3", "Runs", "sandboxed, over 10 seeds"),
             ("4", "Verdicts", "four levels, seed-aware"),
             ("5", "Why", "re-runs that explain each gap")]
    x0, w, gap, y = 0.66, 2.0, 0.32, 3.85
    for i, (n, t, d) in enumerate(steps):
        x = x0 + i * (w + gap)
        box(s, x, y, w, 2.1, alpha=88, name=f"Step {n}")
        text(s, x + 0.18, y + 0.1, w - 0.3, 0.6, [n], size=20, font=TITLE_FONT, color=ORANGE)
        text(s, x + 0.18, y + 0.68, w - 0.3, 0.45, [t], size=12.5, font=BODY_B)
        text(s, x + 0.18, y + 1.12, w - 0.32, 0.95, [d], size=10, color=INK2, spacing=1.0)
        if i < 4:
            arrow(s, x + w + 0.03, y + 1.05, x + w + gap - 0.03, y + 1.05)
    rows = [["What EL-01 asks for", "What Preflight does"],
            ["Understand the methodology", "AI reader extracts claims and stated settings; you confirm"],
            ["Find the implementation and config", "README, config and AST mapping down to file:line"],
            ["Execute in a controlled environment", "Sandbox: browser WASM, subprocess or Docker; 10 seeds"],
            ["Compare with reported results", "Seed-aware verdict with a k-seed tolerance"],
            ["Explain why results differ", "Shapley gap attribution and missing-detail inference"],
            ["Go beyond code exists", "Leakage, metric, fair-baseline and fragility re-runs"],
            ["Evidence-backed, per experiment", "Claim Ledger: table cell, code line, command, log, hash"],
            ["Lightweight CPU-only papers", "CPU triage: full, scaled or untestable, with the reason"]]
    table(s, 0.66, 6.22, 11.3, rows, [4.3, 7.0], size=11.5, row_h=0.5)
    w2, h2 = picture(s, os.path.join(SHOTS, "claims.png"), 12.55, 2.78, w=6.75)
    text(s, 12.55, 2.78 + h2 + 0.14, 6.75, 0.4, ["Claim Ledger for Paper A: every number, its verdict and its cause"],
         size=11, color=INK2)
    if D:
        link_pic(s._last_pic, D + "#paper_a-claims")
        text(s, 12.55, 2.78 + h2 + 0.62, 6.75, 0.4,
             [[("Open this ledger live \u2192", {"link": D + "#paper_a-claims", "bold": True, "color": ORANGE})]], size=12)
    notes(s, "Five steps from paper to verdict to why. The table maps every objective in the problem statement to a feature.")


def slide3(s, R, T):
    set_title(s, "TECHNICAL APPROACH")
    drop_shape(s, "System Architecture")
    row1 = [("AI paper reader", "Claude Opus 5.5 · PDF → claims", True), ("Parse", "tables, settings, comparisons", False),
            ("Map repo", "README · config · AST", False), ("CPU triage", "full / scaled / untestable", False),
            ("Static audit", "diff · leakage · metric · budget", False), ("Execute", "sandbox · 10 seeds · self-heal", False)]
    row2 = [("Compare", "k-seed tolerance", False), ("Attribute", "Shapley over re-runs", False),
            ("Infer", "GRIM + sweep", False), ("Validity re-runs", "leak · dupes · metric · baseline", False),
            ("Fragility", "seeds · splits · ±10%", False), ("Report", "ledger · card · issues · badge", False)]
    w, h, gap = 2.82, 1.12, 0.33
    for r, row in enumerate((row1, row2)):
        y = 2.72 + r * 1.36
        for i, (t, d, ai) in enumerate(row):
            x = 0.66 + i * (w + gap)
            b = box(s, x, y, w, h, fill=PEACH if ai else WHITE, alpha=95, line=ORANGE if ai else None)
            if ai:
                b.line.dash_style = 4
            text(s, x + 0.15, y + 0.1, w - 0.3, 0.4, [t], size=13, font=BODY_B)
            text(s, x + 0.15, y + 0.56, w - 0.25, 0.5, [d], size=9.3, color=INK2, spacing=1.0)
            if i < 5:
                arrow(s, x + w + 0.03, y + h / 2, x + w + gap - 0.03, y + h / 2)
    xr, xl, ym = 0.66 + 5 * (w + gap) + w / 2, 0.66 + w / 2, 2.72 + h + 0.12
    for x1, y1, x2, y2 in ((xr, 2.72 + h, xr, ym), (xr, ym, xl, ym)):
        c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        c.line.color.rgb, c.line.width = rgb(MUTED), Pt(2)
    arrow(s, xl, ym, xl, 2.72 + 1.36, color=MUTED)
    takeaway(s, "One AI step. ", "Everything after it is deterministic, sandboxed and repeatable.")
    text(s, 0.66, 5.32, 18.6, 0.75, [[("Dashed = the only AI step (claim extraction, checked by a person). ", {"bold": True, "color": ORANGE}),
                                    ("Everything after it is deterministic: static analysis, sandboxed execution, statistics and counterfactual re-runs.", {})]],
         size=11.5, spacing=1.0)
    cards = [("Verdict rule", ["tol = max(2σ/√k, 0.5 pt)", "k = seeds paper averaged", "Partial: ≤ 3σ/√k", "        or a scaled run"]),
             ("Gap attribution", ["φᵢ = Σ |S|!(n−|S|−1)!/n!", "     · [v(S∪{i}) − v(S)]", "v(S): 10-seed mean,", "S set to paper values"]),
             ("Sandbox", ["fresh repo copy, hashed", "seed set at the code's seed site", "Docker: no network, CPU/RAM caps", "probe: fits, splits, row hashes"]),
             ("Stack", ["Python 3.14 · scikit-learn 1.8", "Pyodide (WASM), Web Worker", "FastAPI · queue · Docker", "Claude Opus 5.5, JSON output"])]
    cw, cg = 4.42, 0.31
    for i, (t, lines) in enumerate(cards):
        x = 0.66 + i * (cw + cg)
        box(s, x, 6.15, cw, 3.0, alpha=88)
        text(s, x + 0.22, 6.3, cw - 0.4, 0.45, [t], size=15, font=BODY_B)
        text(s, x + 0.22, 6.92, cw - 0.35, 2.2, lines, size=10.5 if i >= 2 else 10, font="Consolas" if i < 2 else BODY, spacing=1.0, after=5)
    picture(s, os.path.join(SHOTS, "flight.png"), 0.72, 9.45, w=16.2, border=True)
    text(s, 17.15, 9.5, 2.15, 1.4, ["The same 11 stages, live in the app"], size=10, color=INK2, spacing=1.0)
    notes(s, "One Python engine, three runtimes: the browser via Pyodide, a CLI, and a FastAPI server with Docker workers. "
             "The LLM only reads the paper.")


def slide4(s, R, T):
    set_title(s, "INNOVATION AND UNIQUENESS")
    takeaway(s, "Others say whether. ", "Preflight shows why, and catches results that reproduce but mislead.")
    drop_shape(s, "Innovative Approach")
    cols = ["", "Runs code", "Per-claim verdict", "Explains why (re-run)", "Leakage check", "Fragility / seeds",
            "False-alarm control", "Metric & baseline audit"]
    data = [["VERITAS (2026)", "Yes", "Yes", "Partly", "No", "No", "No", "No"],
            ["CORE-Bench agents", "Yes", "Partly", "No", "No", "No", "No", "No"],
            ["REPRO-Bench agents", "Yes", "Partly", "Partly", "No", "No", "No", "No"],
            ["Code Ocean", "Yes", "No", "No", "No", "No", "No", "No"],
            ["SciCoQA / Dude", "No", "Partly", "Partly", "No", "No", "LLM", "No"],
            ["Preflight", "Yes", "Yes", "Yes", "Yes", "Yes", "Re-run", "Yes"]]

    def colr(i, j, v):
        if j == 0:
            return NAVY
        return {"Yes": OK, "Re-run": OK, "Partly": WARN, "LLM": WARN, "No": "9AA6B5"}.get(v, NAVY)

    t = table(s, 0.66, 2.78, 11.6, [cols] + data, [2.55] + [1.293] * 7, size=11.5, row_h=0.62, colors=colr)
    for j in range(8):
        c = t.cell(6, j)
        c.fill.solid()
        c.fill.fore_color.rgb = rgb(PEACH)
    text(s, 0.66, 7.4, 11.6, 0.4, ["Based on each tool's published description. Partly: covers part of the column."],
         size=9.5, color=MUTED)
    box(s, 0.66, 7.9, 11.6, 2.95, alpha=88)
    text(s, 0.95, 8.05, 11.0, 2.7, [
        [("“How is this different from VERITAS?” ", {"bold": True, "size": 15})],
        ["VERITAS tells you whether a claim replicates. Preflight tells you why it failed, whether a passing result "
         "is inflated, and how fragile it is, and backs each finding with a counterfactual re-run."],
        [("Original: ", {"bold": True}), ("a GRIM check rules out split ratios that cannot produce the reported accuracy "
                                          "before anything runs; seeds are injected at the code's own seed site; "
                                          "every flag must survive a re-run (Dude's false-positive problem).", {})]],
         size=13, spacing=1.02, after=7)
    stats = [("96%", "of a 2.46-pt gap explained by one config value (C), via Shapley re-runs", OK),
             ("−28.8 pt", "a result that reproduces, but only because feature selection saw the test set", BAD),
             ("+1.52 → −0.56", "a claimed win that flips once the baseline gets the same tuning budget", BAD),
             ("15 / 30", "conditions where “significantly outperforms” still holds", WARN)]
    for i, (big, cap, col) in enumerate(stats):
        x = 12.75 + (i % 2) * 3.32
        y = 2.78 + (i // 2) * 2.55
        box(s, x, y, 3.12, 2.35, alpha=90)
        text(s, x + 0.2, y + 0.18, 2.8, 0.85, [big], size=30 if len(big) < 9 else 24, font=TITLE_FONT, color=col)
        text(s, x + 0.2, y + 1.05, 2.75, 1.25, [cap], size=11.5, color=INK2, spacing=1.0)
    box(s, 12.75, 7.95, 6.44, 2.85, fill=NAVY, alpha=100)
    text(s, 13.05, 8.15, 5.9, 0.9, [f"{T['caught']} / {T['planted']}"], size=46, font=TITLE_FONT, color=PEACH)
    text(s, 13.05, 9.2, 5.9, 1.5, [f"planted issues caught across the test papers, with {T['fa']} false alarms on the clean control. "
                                   "One real 1993 paper audited end to end."], size=13, color=WHITE, spacing=1.02)
    notes(s, "Every competitor stops at whether. We go to why, and to whether a passing number deserves trust.")


def slide5(s, R, T, D):
    set_title(s, "FEASIBILITY AND VIABILITY")
    takeaway(s, "Built and running today. ", "Every demo audit finishes within a minute, on a CPU, in the browser.")
    drop_shape(s, "Technical and Operational")
    names = {"paper_a": "A · planted (7 claims)", "paper_b": "B · clean control", "paper_c": "C · planted (6 claims)",
             "paper_r": "R · real, Street et al. 1993"}
    rows = [["Paper", "Sandboxed runs", "From cache", "CPU-s (laptop)", "Live in browser"]]
    for pid in ("paper_a", "paper_b", "paper_c", "paper_r"):
        st = R[pid]["stats"]
        rows.append([names[pid], str(st["runs"]), str(st["cache_hits"]), f"{st['cpu_seconds']:.1f}", f"{LIVE_SECONDS[pid]:g} s"])
    text(s, 0.66, 2.72, 9.0, 0.45, ["Every demo audit runs on a CPU in seconds"], size=17, font=BODY_B)
    table(s, 0.66, 3.25, 9.0, rows, [3.3, 1.55, 1.25, 1.45, 1.45], size=12, row_h=0.5)
    text(s, 0.66, 5.82, 9.0, 0.4, ["Browser: Pyodide 314.0.7 in Chrome. Live and recorded runs match exactly."], size=10, color=MUTED)
    if D:
        text(s, 4.9, 2.78, 4.76, 0.4, [[("Run Paper A live \u2192", {"link": D + "#paper_a", "bold": True, "color": ORANGE})]],
             size=11.5, align=PP_ALIGN.RIGHT)
    rows2 = [["Risk", "Mitigation"],
             ["PDF tables misread", "Claude with a JSON schema, then a person confirms the claims"],
             ["LLM hallucination", "LLM only extracts; every finding is a re-run"],
             ["Repo breaks on new libraries", "self-heal rules, patch shown, logged as impediment"],
             ["Experiment too big for CPU", "triage: scale rows to the RAM budget, verdict ≤ Partial"],
             ["Hostile code", "Docker: no network, CPU/RAM/PID caps, read-only root"],
             ["Venue wifi fails", "recorded replay, labelled as recorded"]]
    text(s, 0.66, 6.38, 9.0, 0.45, ["Risks and mitigations"], size=17, font=BODY_B)
    table(s, 0.66, 6.95, 9.0, rows2, [3.0, 6.0], size=11.5, row_h=0.55)
    modes = [("Browser", "Pyodide in a Web Worker. Zero server cost, nothing leaves the laptop. Works today."),
             ("Server", "FastAPI, job queue, one Docker container per run, result cache by content hash. Tested."),
             ("CI / author mode", "The CLI writes a GitHub Action that re-audits on every push, plus a README badge.")]
    text(s, 10.3, 2.72, 9.0, 0.45, ["Three ways to deploy, one engine"], size=17, font=BODY_B)
    for i, (t, d) in enumerate(modes):
        y = 3.3 + i * 1.32
        box(s, 10.3, y, 9.0, 1.15, alpha=88)
        text(s, 10.55, y + 0.15, 2.3, 0.8, [t], size=15, font=BODY_B)
        text(s, 12.85, y + 0.15, 6.25, 0.9, [d], size=12.5, color=INK2, spacing=1.0)
    box(s, 10.3, 7.35, 9.0, 3.45, fill=NAVY, alpha=100)
    text(s, 10.6, 7.55, 8.4, 3.1, [
        [("Sustainability", {"bold": True, "size": 17, "color": PEACH})],
        ["Open-source core (MIT) so labs can self-host and trust the checks."],
        ["Hosted tier for conferences and journals: batch audits of artifact submissions, badge issuing, reviewer reports."],
        ["Compute cost scales with papers audited, and small papers cost nothing because they run in the visitor's browser."]],
         size=13, color=WHITE, after=7)
    notes(s, "All numbers on this slide are measured. Paper C takes about a minute in the browser because it tunes an SVM 12 ways per run.")


def slide6(s, R, T):
    set_title(s, "IMPACT AND SCALING")
    takeaway(s, "Success is cheap. ", "Audits run in the user's browser, so 10× users is mostly static hosting.")
    drop_shape(s, "Target Users")
    users = [("Reviewers & repro chairs", "triage artifact submissions in minutes, with evidence to cite"),
             ("Students & MLRC", "reproduce a paper for coursework and learn why it differs"),
             ("ML teams", "check a paper's claims before building on them"),
             ("Authors", "pre-submission check and a README badge")]
    text(s, 0.66, 2.72, 9.0, 0.45, ["Who it is for"], size=17, font=BODY_B)
    for i, (t, d) in enumerate(users):
        x, y = 0.66 + (i % 2) * 4.6, 3.25 + (i // 2) * 1.75
        box(s, x, y, 4.4, 1.55, alpha=88)
        text(s, x + 0.2, y + 0.15, 4.0, 0.7, [t], size=14, font=BODY_B, spacing=1.0)
        text(s, x + 0.2, y + 0.82, 4.0, 0.7, [d], size=11.5, color=INK2, spacing=1.0)
    text(s, 0.66, 6.95, 9.0, 0.45, ["Tested, not promised"], size=17, font=BODY_B)
    tests = [f"{T['caught']}/{T['planted']} planted issues caught, {T['fa']} false alarms (clean control: 0 findings)",
             "11 automated tests: planted, clean, live edits, real paper, server API",
             "Browser and laptop runs give identical numbers",
             "Live edits re-audited: fixing C turns C1 green; a new scaler leak is caught",
             "Server mode: HTTP submit, poll, idempotent cache, rate limits",
             "Real 1993 paper: one claim exact, one flagged with the paper's own reason"]
    box(s, 0.66, 7.45, 9.0, 3.35, alpha=88)
    text(s, 0.9, 7.62, 8.6, 3.1, [[("✓  ", {"color": OK, "font": "Segoe UI Symbol"}), (t, {})] for t in tests],
         size=12.5, after=7)
    box(s, 10.2, 2.72, 9.1, 8.08, fill=NAVY, alpha=100)
    text(s, 10.5, 2.92, 8.5, 1.1, [[("YC says yes tomorrow. ", {"bold": True, "color": PEACH, "size": 19}),
                                    ("Can it handle success next week?", {"size": 19})]], color=WHITE, spacing=1.0)
    plan = [("Users", "Most audits run in the visitor's browser, so 10× traffic is mostly static file hosting."),
            ("Load", "Stateless API + queue; autoscaled Docker workers; one container per run."),
            ("Repeat work", "Runs cached by hash of files, command and library versions; duplicate submissions are free."),
            ("Breaks", "Per-run CPU, RAM, PID and time caps; network off; rate limit per client."),
            ("Crashes", "Self-heal known API breaks; failed jobs keep their events; static audit still reports."),
            ("Robustness", "Idempotent jobs and retries; recorded replay if live compute is down.")]
    for i, (t, d) in enumerate(plan):
        y = 4.1 + i * 1.1
        text(s, 10.5, y, 2.1, 0.9, [t], size=14, font=BODY_B, color=PEACH)
        text(s, 12.6, y, 6.45, 1.0, [d], size=12.5, color=WHITE, spacing=1.0)
    notes(s, "Our scaling story is unusual: compute moves to the visitor's browser by default, and the server path is "
             "a classic queue plus workers with a content-hash cache.")


def slide7(s, R, T, a):
    set_title(s, "RESEARCH AND REFERENCES")
    takeaway(s, "Still unsolved. ", "Top agents replicate under a third of papers; top LLMs find under half the discrepancies.")
    drop_shape(s, "Research Background")
    facts = [("21–27%", "best agents on PaperBench vs 41% for ML PhDs: replication is still hard (OpenAI, 2025)"),
             ("46.7%", "of real paper–code discrepancies found by the best LLMs (SciCoQA, ACL 2026)"),
             ("294+", "papers in 17 fields affected by leakage (Kapoor & Narayanan, Patterns 2023)"),
             ("68%", "full replication by VERITAS after automated fixes; it reports whether, not why (arXiv 2607.02931)")]
    for i, (big, cap) in enumerate(facts):
        x, y = 0.66 + (i % 2) * 4.6, 2.78 + (i // 2) * 2.0
        box(s, x, y, 4.4, 1.8, alpha=88)
        text(s, x + 0.2, y + 0.12, 4.0, 0.7, [big], size=28, font=TITLE_FONT, color=ORANGE)
        text(s, x + 0.2, y + 0.85, 4.0, 0.95, [cap], size=11, color=INK2, spacing=1.0)
    refs = ["Kapoor & Narayanan. Leakage and the reproducibility crisis in ML-based science. Patterns, 2023",
            "Starace et al. PaperBench. OpenAI, 2025 · Siegel et al. CORE-Bench, 2024 · REPRO-Bench, ACL 2025",
            "SciCoQA: paper–code alignment, ACL 2026 (arXiv 2601.12910) · Dude, arXiv 2609.03416",
            "VERITAS: a general-purpose replication tool, arXiv 2607.02931",
            "Brown & Heathers. The GRIM test. Social Psychological and Personality Science, 2017",
            "Pineau et al. ML Reproducibility Checklist, 2021 · Kapoor et al. REFORMS, 2023",
            "Street, Wolberg & Mangasarian. Nuclear feature extraction for breast tumor diagnosis. SPIE, 1993"]
    text(s, 0.66, 6.95, 9.0, 0.45, ["Sources"], size=17, font=BODY_B)
    text(s, 0.66, 7.45, 9.2, 3.4, refs, size=11, color=INK2, spacing=1.0, after=5)
    box(s, 10.25, 2.78, 9.05, 4.75, fill=NAVY, alpha=100)
    text(s, 10.55, 2.98, 8.5, 0.5, ["Try it"], size=19, font=BODY_B, color=PEACH)
    links = [("Live demo", a.demo_url, a.demo_url and a.demo_url.replace("https://", "").rstrip("/")),
             ("Code (MIT)", a.repo_url, a.repo_url and a.repo_url.replace("https://", "")),
             ("Video", a.video_url, "Watch the 90-second walkthrough"),
             ("Test kit", a.kit_url, "A test paper with planted bugs")]
    for i, (t, u, shown) in enumerate(links):
        y = 3.62 + i * 0.68
        text(s, 10.55, y, 2.2, 0.5, [t], size=14, font=BODY_B, color=WHITE)
        text(s, 12.75, y + 0.04, 4.5, 0.6, [[(shown if u else "add link before submitting",
                                              {"link": u, "color": PEACH if u else ORANGE})]], size=11.5, spacing=1.0)
    if a.demo_url:
        link_pic(s.shapes.add_picture(qr(a.demo_url, os.path.join(DECK, "qr_demo.png")), Inches(17.4), Inches(3.55),
                                      Inches(1.65), Inches(1.65)), a.demo_url)
    tour = [("Tour", {"link": a.demo_url + "#tour", "bold": True, "color": PEACH})] if a.demo_url else [("Tour", {})]
    text(s, 10.55, 6.5, 8.5, 0.9, [[("In the app: press ", {})] + tour +
                                   [(" for a guided walkthrough, Ctrl K to search, Audit your own to upload a PDF.", {})]],
         size=12, color=WHITE, spacing=1.0)
    box(s, 10.25, 7.75, 9.05, 3.05, alpha=88)
    text(s, 10.55, 7.92, 8.5, 2.8, [
        [("Datasets", {"bold": True})],
        ["Bundled with scikit-learn: Wisconsin Diagnostic Breast Cancer (569 cases), Digits. Generated: SynthGene-2k, "
         "SynthMed, SynthHD, SynthKNN-Aug, SynthLarge-2M."],
        [("Papers", {"bold": True})],
        ["Three fictional test papers with an answer key (A, B, C) and one real paper (Street et al., 1993). "
         "Every number shown comes from a logged sandbox run."]], size=12, spacing=1.0, after=5)
    notes(s, "Every number in this deck is measured. The competitor numbers come from their papers.")


def slide8(s, R, T, D):
    set_title(s, "LIVE PROOF")
    takeaway(s, "Proof, not promises. ", "Four findings from the real app, each backed by a re-run.")
    drop_shape(s, "Research Background")
    text(s, 0.66, 2.72, 18.6, 0.5, ["Each screen is a re-run, not an opinion. Click any one to open it live in the app."],
         size=16, font=BODY_B)
    panels = [("attr.png", None, "Why C1 fails: one config value explains 96% of the gap", "#paper_a-C1"),
              ("leak.png", 0.42, "Why C5 cannot be trusted: the leak, the patch, the drop", "#paper_a-C5"),
              ("frag.png", None, "Why C7 is fragile: 15 of 30 conditions", "#paper_a-C7"),
              ("real.png", None, "A real paper: one claim exact, one optimistic, and its reason", "#paper_r")]
    slots = [(0.66, 3.35, 9.05, 3.5), (10.25, 3.35, 9.05, 3.5), (0.66, 7.55, 9.05, 2.75), (10.25, 7.55, 9.05, 2.75)]
    for (img, crop, cap, anchor), (x, y, w, h) in zip(panels, slots):
        url = D + anchor if D else None
        cap_runs = [[(cap + (" \u2192" if url else ""), {"link": url} if url else {})]]
        if img == "real.png":
            pw, ph = picture(s, os.path.join(SHOTS, img), x + 0.06, y, h=h, crop_w=0.665)
            cx = x + pw + 0.35
            box(s, cx, y - 0.06, x + w - cx, ph + 0.12, fill=NAVY, alpha=100)
            text(s, cx + 0.22, y + 0.12, x + w - cx - 0.4, ph - 0.2, [
                [("Real paper", {"bold": True, "color": PEACH, "size": 13})],
                ["Street, Wolberg & Mangasarian, 1993."],
                ["The authors released no code, so the repo is our reproduction."]],
                size=11, color=WHITE, spacing=1.0, after=5)
            if url:
                link_pic(s._last_pic, url)
            text(s, x, y + ph + 0.14, w, 0.4, cap_runs, size=12, color=NAVY, font=BODY_B)
            continue
        pw, ph = picture(s, os.path.join(SHOTS, img), x + 0.06, y, w=w - 0.12, h=h, crop_h=crop)
        if url:
            link_pic(s._last_pic, url)
        text(s, x, y + ph + 0.14, w, 0.4, cap_runs, size=12, color=NAVY, font=BODY_B)
    notes(s, "These are screenshots of the real app. The full report exports as Markdown and JSON with run hashes.")


def delete_slide(prs, index):
    sld = prs.slides._sldIdLst[index]
    prs.part.drop_rel(sld.get(qn("r:id")))
    prs.slides._sldIdLst.remove(sld)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="Team Preflight")
    ap.add_argument("--demo-url")
    ap.add_argument("--repo-url")
    ap.add_argument("--video-url")
    ap.add_argument("--kit-url")
    a = ap.parse_args()
    R, T = load()
    prs = Presentation(os.path.join(DECK, "base.pptx"))
    delete_slide(prs, 9)  # blank
    delete_slide(prs, 8)  # instructions
    S = prs.slides
    slide1(S[0], a, T)
    a.kit_url = a.kit_url or (a.demo_url and a.demo_url.rstrip("/") + "/preflight-test-kit.zip")
    D = a.demo_url.rstrip("/") + "/" if a.demo_url else None
    slide2(S[1], R, T, D)
    slide3(S[2], R, T)
    slide4(S[3], R, T)
    slide5(S[4], R, T, D)
    slide6(S[5], R, T)
    slide7(S[6], R, T, a)
    slide8(S[7], R, T, D)
    name = "EL-01_" + re.sub(r"[^A-Za-z0-9]+", "", a.team.replace("Team", "")) + ".pptx"
    out = os.path.join(DECK, name)
    prs.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
