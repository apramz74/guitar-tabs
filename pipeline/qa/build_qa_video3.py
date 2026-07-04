#!/usr/bin/env python3
"""Build QA page for video 3 (Redbone — dark jump-scroll tab, stitched)."""
import base64
import html as html_mod
import json
from pathlib import Path

import cv2

import argparse
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("debug_dir", help="debug dir of the extraction run to show")
ap.add_argument("-o", "--out", default="tab-qa-song3.html")
args = ap.parse_args()
CV = Path(args.debug_dir)
data = json.loads((CV / "extraction.json").read_text())

# labels for the current pipeline version (cluster 6 = the line-crossing
# arc crown the rescue step now recovers; re-check flashcards after any change)
LABELS = {0: "5", 1: "slide/", 2: "6", 3: "9", 4: "7", 5: "8", 6: "arc",
          7: "(", 8: ")", 9: "x", 10: "x", 11: "slide/", 12: "1", 13: "3",
          14: "4", 15: "slide\\", 16: "6", 17: "arc"}
NOTE_KIND = {"x": "ignored", "slide/": "slide up", "slide\\": "slide down",
             "arc": "slur (h/p) mark",
             "(": "ghost-note paren", ")": "ghost-note paren"}


def img_uri(path_or_img, max_w: int = 1600) -> str:
    img = cv2.imread(str(path_or_img)) if isinstance(path_or_img, (str, Path)) else path_or_img
    if img.shape[1] > max_w:
        s = max_w / img.shape[1]
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


# the stitched panorama is very wide — show it in 4 slices, in song order
pano = cv2.imread(str(CV / "page_1_annotated.png"))
n_slices = 4
sw = pano.shape[1] // n_slices
slices_html = "".join(
    f"""<figure>
    <img src="{img_uri(pano[:, i * sw:(i + 1) * sw + 60])}" alt="song slice {i + 1}">
    <figcaption>Song, part {i + 1} of {n_slices} (slices overlap a little)</figcaption>
  </figure>""" for i in range(n_slices))

flashcards = []
for ci in sorted(LABELS):
    lab = LABELS[ci]
    shown = lab if lab not in NOTE_KIND else {"x": "—", "slide/": "/", "slide\\": "\\",
                                              "arc": "⌒", "(": "(", ")": ")"}[lab]
    note = NOTE_KIND.get(lab, "note digit")
    flashcards.append(f"""
    <div class="flash">
      <img src="{img_uri(CV / f'glyph_cluster_{ci}.png', 80)}" alt="glyph cluster {ci}">
      <div class="flash-digit">{shown}</div>
      <div class="flash-ai">{note}</div>
    </div>""")

page_ascii = html_mod.escape(data["pages"][0]["ascii"])

page = """<title>Redbone — Tab QA (stitched)</title>
<style>
  :root {
    --paper: #FBFAF6; --card: #FFFFFF; --ink: #201D18; --muted: #6E675C;
    --brass: #8F6B2A; --line: #E5E0D5;
    --ok-bg: #EAF0E4; --ok-ink: #3E5B2C; --warn-bg: #F5EBD8; --warn-ink: #7A5A1E;
  }
  body { background: var(--paper); color: var(--ink);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    margin: 0; padding: 48px 20px 80px; }
  main { max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 32px; }
  header h1 { font-size: 34px; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 6px; text-wrap: balance; }
  header .sub { color: var(--muted); margin: 0 0 14px; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; }
  .meta span { font-size: 12.5px; color: var(--muted); background: var(--card);
    border: 1px solid var(--line); border-radius: 3px; padding: 3px 10px;
    font-variant-numeric: tabular-nums; }
  .howto { background: var(--card); border: 1px solid var(--line); border-radius: 3px;
    padding: 16px 20px; font-size: 14.5px; color: var(--muted); }
  .howto strong { color: var(--ink); font-weight: 600; }
  .howto ul { margin: 8px 0 0; padding-left: 20px; }
  .howto li { margin: 3px 0; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 3px;
    padding: 22px 24px 18px; display: flex; flex-direction: column; gap: 14px; }
  figure { margin: 0; }
  figure img { display: block; max-width: 100%; border: 1px solid var(--line); border-radius: 2px; }
  figcaption, .extract-label { font-size: 12.5px; color: var(--muted); margin-top: 6px; }
  .extract-label { margin: 0 0 6px; }
  pre { margin: 0; padding: 14px 16px; overflow-x: auto;
    background: var(--paper); border: 1px solid var(--line); border-radius: 2px;
    font: 13.5px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace; color: var(--ink); }
  .flashrow { display: flex; gap: 12px; flex-wrap: wrap; }
  .flash { display: flex; flex-direction: column; align-items: center; gap: 4px;
    background: var(--card); border: 1px solid var(--line); border-radius: 3px;
    padding: 12px 14px 10px; }
  .flash img { height: 52px; }
  .flash-digit { font: 600 20px/1 ui-monospace, Menlo, monospace; }
  .flash-ai { font-size: 11px; color: var(--muted); }
  footer { font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; }
  h2 { font-size: 15px; font-weight: 650; margin: 0 0 10px; }
</style>
<main>
  <header>
    <h1>Redbone — extraction QA (stitched from a moving tab)</h1>
    <p class="sub">Childish Gambino · levelupguitartabs Reel · white-on-black, jump-scrolling tab · 41 frames stitched into one song</p>
    <div class="meta">
      <span>Standard tuning (shown in video, not yet extracted)</span>
      <span>__COUNTS__</span>
      <span>Each note seen ~4–10× and voted on</span>
      <span>Slides captured (5/6, 7/11, 18\\)</span>
    </div>
  </header>
  <div class="howto">
    <strong>How to QA:</strong> the song below is one continuous stitched strip, shown in
    4 slices. Check that every red box sits on a real digit with the right label, and
    compare the tab at the bottom to what the video plays.
    <ul>
      <li>Two-digit frets (11, 13, 14, 18) are joined automatically.</li>
      <li>Slides are written 5/6 (up) and 18\\ (down); hammer-on/pull-off would be h/p.</li>
      <li>Ghost notes keep their parentheses, exactly as the video shows them:
      (8)-6-8 and (7)/11.</li>
      <li>Slur arcs are written h (pitch up) or p (pitch down): see 7h9 and 6h8.
      The arc over the 6-8 pair (measures 1 and 4) that was missing before is now
      captured — it crossed a string line, which used to break its detection.
      <strong>Please re-check every arc</strong> in the video against the tab.</li>
    </ul>
  </div>
__SLICES__
  <div class="card">
    <div class="extract-label">Extracted tab — the whole song</div>
    <pre>__ASCII__</pre>
  </div>
  <div>
    <h2>The symbol flashcards (how marks were named)</h2>
    <div class="flashrow">__FLASH__</div>
  </div>
  <footer>
    Source video: ~/Downloads/ScreenRecording_07-03-2026&nbsp;23-12-48_1.MP4 ·
    Pipeline: guitar-tabs/pipeline/extract_cv.py · Positions measured by OpenCV; digits and
    legato marks human-verified from flashcards.
  </footer>
</main>
"""

n_notes = sum(len(m["notes"]) for m in data["measures"])
page = (page.replace("__COUNTS__", f"{len(data['measures'])} measures · {n_notes} note events")
            .replace("__SLICES__", slices_html)
            .replace("__ASCII__", page_ascii)
            .replace("__FLASH__", "\n".join(flashcards)))
out = Path(args.out)
out.write_text(page)
print(f"wrote {out} ({len(page) // 1024} KB)")
