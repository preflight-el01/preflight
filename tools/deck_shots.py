"""Element screenshots of the real app for the pitch deck (needs the preview server on :8765)."""
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "deck", "shots")

SHOTS = [
    # (name, js to set the view, css selector to capture)
    ("board", "go('library')", ".board2"),
    ("claims", "loadPaper('paper_a'); S.page='audit'; S.tab='claims'; render()", ".rows"),
    ("heads", "loadPaper('paper_a'); S.page='audit'; S.tab='overview'; render()", ".heads"),
    ("trace", "loadPaper('paper_a'); openClaim('C1')", "#sec-trace"),
    ("attr", "loadPaper('paper_a'); openClaim('C1')", "#sec-attr"),
    ("leak", "loadPaper('paper_a'); openClaim('C5')", "#sec-leak"),
    ("frag", "loadPaper('paper_a'); openClaim('C7')", "#sec-frag"),
    ("fair", "loadPaper('paper_c'); openClaim('C6')", "#sec-fair"),
    ("metric", "loadPaper('paper_c'); openClaim('C1')", "#sec-metric"),
    ("real", "loadPaper('paper_r'); S.page='audit'; S.tab='overview'; render()", ".heads"),
    ("upload", "go('library'); S.upMode='pdf'; openUpload()", ".modal .panel"),
    ("flight", "loadPaper('paper_a'); S.page='audit'; S.tab='overview'; render()", ".flight"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1440, "height": 2400}, device_scale_factor=2, color_scheme="light")
        page.goto("http://localhost:8765/")
        page.wait_for_function("typeof S !== 'undefined' && S.runtime !== 'loading'", timeout=180000)
        page.evaluate("S.instant = true; flapped = true")
        page.add_style_tag(content=".top, .jump { display: none !important } .rail, .tabs { position: static !important }")
        for name, js, sel in SHOTS:
            page.evaluate("document.getElementById('modal-root').innerHTML=''; S.tourStep=null; renderTour();")
            page.evaluate(js)
            page.wait_for_timeout(700)
            el = page.locator(sel).first
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            el.screenshot(path=os.path.join(OUT, f"{name}.png"))
            print("shot", name)
        b.close()


if __name__ == "__main__":
    main()
