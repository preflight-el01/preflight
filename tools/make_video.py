"""Build dist/preflight-demo.mp4: a ~90 s walkthrough made from the guided tour.

Needs the preview server on :8765 (python -m http.server 8765 --directory dist) and Chrome.
Every frame is a screenshot of the real page; the numbers on screen come from the recorded runs.
"""
import os
import sys

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "frames")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W, H, FPS, HOLD, FADE = 1440, 904, 24, 5.9, 0.5
STEPS = 12
FONT_DIR = r"C:\Windows\Fonts"


def font(name, size):
    for n in (name, "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(FONT_DIR, n), size)
        except OSError:
            continue
    return ImageFont.load_default()


def shots():
    """One browser session: wait for live Python, then step through the guided tour."""
    from playwright.sync_api import sync_playwright
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": W, "height": 900}, color_scheme="light")
        page.goto("http://localhost:8765/")
        page.wait_for_function("typeof S !== 'undefined' && S.runtime !== 'loading'", timeout=180000)
        page.evaluate("S.instant = true")
        for i in range(STEPS):
            page.evaluate(f"tourGo({i})")
            page.wait_for_timeout(1200)
            path = os.path.join(OUT, f"step{i:02d}.png")
            page.screenshot(path=path)
            paths.append(path)
            print("step", i, file=sys.stderr)
        browser.close()
    return paths


def card(lines, path):
    img = Image.new("RGB", (W, H), (13, 21, 34))
    d = ImageDraw.Draw(img)
    y = 300
    for text, size, color, weight in lines:
        f = font("segoeuib.ttf" if weight == "b" else "segoeui.ttf", size)
        w = d.textlength(text, font=f)
        d.text(((W - w) / 2, y), text, font=f, fill=color)
        y += int(size * 1.45)
    # DEP -> ARR dashed flight line
    for x in range(420, 1020, 24):
        d.line([(x, 240), (x + 12, 240)], fill=(132, 143, 159), width=3)
    d.text((380, 226), "DEP", font=font("consola.ttf", 20), fill=(255, 210, 63))
    d.text((1030, 226), "ARR", font=font("consola.ttf", 20), fill=(255, 210, 63))
    img.save(path)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    frames = [card([("Preflight", 96, (233, 238, 245), "b"),
                    ("Should you believe this ML paper?", 44, (166, 177, 193), "r"),
                    ("It re-runs every reported number and shows why it holds or fails.", 30, (132, 143, 159), "r")],
                   os.path.join(OUT, "intro.png"))]
    frames += shots()
    frames.append(card([("13 / 13 planted issues caught · 0 false alarms", 46, (233, 238, 245), "b"),
                        ("4 papers · one real · 497 sandboxed runs · runs live in the browser", 32, (166, 177, 193), "r"),
                        ("AI reads the paper. Re-runs decide the verdict.", 36, (78, 224, 160), "b")],
                       os.path.join(OUT, "outro.png")))
    imgs = [np.asarray(Image.open(p).convert("RGB").resize((W, H))) for p in frames]
    out = os.path.join(ROOT, "dist", "preflight-demo.mp4")
    writer = imageio.get_writer(out, fps=FPS, codec="libx264", quality=8, macro_block_size=8)
    hold, fade = int(HOLD * FPS), int(FADE * FPS)
    for k, img in enumerate(imgs):
        for _ in range(hold):
            writer.append_data(img)
        if k + 1 < len(imgs):
            nxt = imgs[k + 1].astype(np.float32)
            cur = img.astype(np.float32)
            for t in range(fade):
                a = (t + 1) / (fade + 1)
                writer.append_data((cur * (1 - a) + nxt * a).astype(np.uint8))
    writer.close()
    secs = len(imgs) * HOLD + (len(imgs) - 1) * FADE
    print(f"wrote {out} ({secs:.0f} s, {os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
