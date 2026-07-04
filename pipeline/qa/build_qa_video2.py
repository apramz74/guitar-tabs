#!/usr/bin/env python3
"""Build QA page for video 2 (full-screen tab app, Capo 6 song)."""
import base64
import html as html_mod
import json
from pathlib import Path

import cv2

SCRATCH = Path("/private/tmp/claude-501/-Users-apramono/942b365c-0b2a-4d83-9d42-dd8c5260c263/scratchpad")
CV = SCRATCH / "cv2"
data = json.loads((CV / "extraction.json").read_text())

LABELS = {0: "x", 1: "0", 2: "8", 3: "7", 4: "x", 5: "5", 6: "3",
          7: "1", 8: "2", 9: "x", 10: "x", 11: "x", 12: "4"}

PAGE_CHIPS = {
    1: ("check", "Two screenshots of this page disagreed (20 vs 18 notes) — fuller one kept, please verify"),
    2: ("clean", "Measures 3-4"),
}


def img_uri(path: Path, max_w: int = 1400) -> str:
    img = cv2.imread(str(path))
    if img.shape[1] > max_w:
        s = max_w / img.shape[1]
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


flashcards = []
for ci in sorted(LABELS):
    digit = LABELS[ci]
    shown = digit if digit != "x" else "—"
    note = "note digit" if digit != "x" else "not a note (ignored)"
    flashcards.append(f"""
    <div class="flash">
      <img src="{img_uri(CV / f'glyph_cluster_{ci}.png', 70)}" alt="glyph cluster {ci}">
      <div class="flash-digit">{shown}</div>
      <div class="flash-ai">{note}</div>
    </div>""")

cards = []
for p in data["pages"]:
    kind, label = PAGE_CHIPS.get(p["page"], ("clean", "Verify"))
    cards.append(f"""
<section class="card">
  <div class="card-head">
    <span class="eyebrow">Page {p["page"]} · shown @ {p["ts"]:.1f}s</span>
    <span class="chip chip-{kind}">{label}</span>
  </div>
  <figure>
    <img src="{img_uri(CV / p["annotated"])}" alt="Measured geometry, page {p['page']}">
    <figcaption>Source with measurements overlaid — blue: detected string lines ·
    green: measure bars · red: every symbol counted as a note</figcaption>
  </figure>
  <div class="extract">
    <div class="extract-label">Extracted tab ({len(p["measures"])} measures)</div>
    <pre>{html_mod.escape(p["ascii"])}</pre>
  </div>
</section>""")

page = """<title>Second song (Capo 6) — Tab QA</title>
<style>
  :root {
    --paper: #FBFAF6; --card: #FFFFFF; --ink: #201D18; --muted: #6E675C;
    --brass: #8F6B2A; --line: #E5E0D5;
    --ok-bg: #EAF0E4; --ok-ink: #3E5B2C; --warn-bg: #F5EBD8; --warn-ink: #7A5A1E;
  }
  body { background: var(--paper); color: var(--ink);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    margin: 0; padding: 48px 20px 80px; }
  main { max-width: 860px; margin: 0 auto; display: flex; flex-direction: column; gap: 36px; }
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
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .eyebrow { font-size: 11.5px; font-weight: 650; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--brass); font-variant-numeric: tabular-nums; }
  .chip { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 99px; }
  .chip-clean { background: var(--ok-bg); color: var(--ok-ink); }
  .chip-check { background: var(--warn-bg); color: var(--warn-ink); }
  figure { margin: 0; }
  figure img { display: block; max-width: 100%; border: 1px solid var(--line); border-radius: 2px; }
  figcaption, .extract-label { font-size: 12.5px; color: var(--muted); margin-top: 6px; }
  .extract-label { margin: 0 0 6px; }
  pre { margin: 0; padding: 14px 16px; overflow-x: auto;
    background: var(--paper); border: 1px solid var(--line); border-radius: 2px;
    font: 13.5px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace; color: var(--ink); }
  .flashrow { display: flex; gap: 14px; flex-wrap: wrap; }
  .flash { display: flex; flex-direction: column; align-items: center; gap: 4px;
    background: var(--card); border: 1px solid var(--line); border-radius: 3px;
    padding: 12px 16px 10px; }
  .flash img { height: 56px; image-rendering: pixelated; }
  .flash-digit { font: 600 20px/1 ui-monospace, Menlo, monospace; }
  .flash-ai { font-size: 11px; color: var(--muted); }
  footer { font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; }
  h2 { font-size: 15px; font-weight: 650; margin: 0 0 10px; }
</style>
<main>
  <header>
    <h1>Second song (Capo 6) — extraction QA</h1>
    <p class="sub">Full-screen tab app recording · CV-geometry extraction · digits human-verified · no AI in the trust path</p>
    <div class="meta">
      <span>Capo 6 — shown in video, not yet extracted</span>
      <span>4 measures of music across 2 pages (duplicates auto-merged)</span>
      <span>8 digit shapes + 5 ignored symbols</span>
      <span>Positions measured by OpenCV, not AI</span>
    </div>
  </header>
  <div class="howto">
    <strong>How to QA:</strong> in each card, check the red boxes on the source image —
    every box should sit on a real fret number with the right s&lt;string&gt; label, and
    nothing real should be unboxed. Then check the extracted tab below it.
    <ul>
      <li>The app scrolls as the song plays, so the same measures appear on more than one screenshot. Duplicates are now detected and merged automatically; if the copies disagreed, the page gets a warning chip.</li>
      <li>Clef letters, rests, the time signature, and "Capo 6" are recognized as non-notes and ignored.</li>
      <li>Page 2's strip has no left border bar — measure 1 starts at the screen edge. That's normal for this app.</li>
    </ul>
  </div>
  <div>
    <h2>The symbol flashcards (how digits were named)</h2>
    <div class="flashrow">__FLASH__</div>
  </div>
__CARDS__
  <footer>
    Source video: ~/Downloads/ScreenRecording_07-03-2026&nbsp;18-15-36_1.MP4 ·
    Pipeline: guitar-tabs/pipeline/extract_cv.py · Digit labels human-verified from flashcards.
  </footer>
</main>
"""

page = page.replace("__FLASH__", "\n".join(flashcards)).replace("__CARDS__", "\n".join(cards))
out = SCRATCH / "tab-qa-song2.html"
out.write_text(page)
print(f"wrote {out} ({len(page) // 1024} KB)")
