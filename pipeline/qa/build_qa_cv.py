#!/usr/bin/env python3
"""Build QA page v2: CV-geometry extraction, per page: annotated source + tab."""
import base64
import html as html_mod
import json
from pathlib import Path

import cv2

SCRATCH = Path("/private/tmp/claude-501/-Users-apramono/942b365c-0b2a-4d83-9d42-dd8c5260c263/scratchpad")
CV = SCRATCH / "cv"
data = json.loads((CV / "extraction.json").read_text())

LABELS = {0: "0", 1: "5", 2: "5", 3: "0", 4: "4", 5: "3", 6: "0", 7: "2", 8: "x", 9: "0"}


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
    note = "note digit" if digit != "x" else "slide/strum mark (ignored)"
    flashcards.append(f"""
    <div class="flash">
      <img src="{img_uri(CV / f'glyph_cluster_{ci}.png', 60)}" alt="glyph cluster {ci}">
      <div class="flash-digit">{shown}</div>
      <div class="flash-ai">{note}</div>
    </div>""")

cards = []
for p in data["pages"]:
    if p["consistent"]:
        chip = '<span class="chip chip-clean">Both observations agree</span>'
    else:
        counts = " vs ".join(str(c) for c in p["obs_glyph_counts"])
        chip = f'<span class="chip chip-check">Observations disagreed ({counts} glyphs) — double-check</span>'
    cards.append(f"""
<section class="card">
  <div class="card-head">
    <span class="eyebrow">Page {p["page"]} · first shown @ {p["ts"]:.1f}s</span>
    {chip}
  </div>
  <figure>
    <img src="{img_uri(CV / p["annotated"])}" alt="Measured geometry, page {p['page']}">
    <figcaption>Source with measurements overlaid — blue: detected string lines ·
    green: measure bars · red: each digit found, labeled s&lt;string&gt;:&lt;fret&gt;</figcaption>
  </figure>
  <div class="extract">
    <div class="extract-label">Extracted tab ({len(p["measures"])} measures)</div>
    <pre>{html_mod.escape(p["ascii"])}</pre>
  </div>
</section>""")

page = """<title>Cannock Chase — Tab QA</title>
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
  .flash-ai { font-size: 11px; }
  .flash-ai-ok { color: var(--ok-ink); }
  .flash-ai-warn { color: var(--warn-ink); font-weight: 600; }
  footer { font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; }
  h2 { font-size: 15px; font-weight: 650; margin: 0 0 10px; }
</style>
<main>
  <header>
    <h1>Cannock Chase — extraction QA, round 2</h1>
    <p class="sub">Tutorial by jmu.sikk · CV-geometry extraction · digits human-verified · no AI in the trust path</p>
    <div class="meta">
      <span>Capo 2 — shown in video, not yet extracted</span>
      <span>4 unique pages, each measured twice</span>
      <span>8 measures · 64 digits · 5 unique glyphs</span>
      <span>Positions measured by OpenCV, not AI</span>
    </div>
  </header>
  <div class="howto">
    <strong>What changed since round 1:</strong> positions now come from pixel measurement —
    every string line, bar line, and digit box is drawn on the source image below so you can
    see exactly what was measured. Digits were named by matching identical glyphs and
    verifying the five unique shapes by eye.
    <ul>
      <li>QA each page: does every red box sit on a real digit, with the right s&lt;string&gt;:&lt;fret&gt; label? Is anything unboxed?</li>
      <li>Page 1: the B0 and D5 render as simultaneous — the source shows them slightly offset. Verify which is musically right.</li>
      <li>Pages may carry a "double-check" flag when their two observations counted different glyphs; the previously-verified 16-glyph reading is the one kept in every case.</li>
      <li>Several near-identical glyph shapes are kept as separate flashcards on purpose — merging too eagerly once hid an 8 inside another symbol.</li>
    </ul>
  </div>
  <div>
    <h2>The five glyphs (whole song uses only these)</h2>
    <div class="flashrow">__FLASH__</div>
  </div>
__CARDS__
  <footer>
    Source video: ~/Downloads/ScreenRecording_07-03-2026&nbsp;17-10-24_1.MP4 ·
    Pipeline: guitar-tabs/pipeline/extract_cv.py ·
    Flashcard experiment: AI named 4/5 glyphs correctly (called the 5 a 3) — human labels used instead.
  </footer>
</main>
"""

page = page.replace("__FLASH__", "\n".join(flashcards)).replace("__CARDS__", "\n".join(cards))
out = SCRATCH / "tab-qa.html"
out.write_text(page)
print(f"wrote {out} ({len(page) // 1024} KB)")
