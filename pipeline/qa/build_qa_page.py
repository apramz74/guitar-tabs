#!/usr/bin/env python3
"""Build the tab QA artifact page: per section, source crop + parsed/re-rendered tab."""
import base64
import html as html_mod
import sys
from pathlib import Path

import cv2

sys.path.insert(0, "/Users/apramono/guitar-tabs/pipeline")
from m1_spike import parse_ascii_tab, render_ascii  # noqa: E402

SCRATCH = Path("/private/tmp/claude-501/-Users-apramono/942b365c-0b2a-4d83-9d42-dd8c5260c263/scratchpad")
OUTPUT_LOG = SCRATCH.parent / "tasks" / "bz1te1b63.output"

# ---- pull the model's raw ASCII transcription out of the run log
log = OUTPUT_LOG.read_text()
raw = log.split("=== model transcription (raw) ===")[1].split("[3/3]")[0]
raw = "\n".join(l.split("\t", 1)[1] if "\t" in l else l for l in raw.splitlines()).strip("\n")
systems = [s.strip("\n") for s in raw.split("\n\n") if s.strip()]
assert len(systems) == 4, f"expected 4 systems, got {len(systems)}"

SECTIONS = [
    {"ts": "0:00", "crop": "crop_0000.50s.jpg",
     "verdict": ("fail", "User QA: wrong — confabulated pattern")},
    {"ts": "0:02", "crop": "crop_0002.50s.jpg", "verdict": ("fail", "User QA: errors found")},
    {"ts": "0:08", "crop": "crop_0008.51s.jpg", "verdict": ("fail", "User QA: errors found")},
    {"ts": "0:15", "crop": "crop_0015.02s.jpg", "verdict": ("fail", "User QA: errors found")},
]

def img_data_uri(path: Path, max_w: int = 1400) -> str:
    img = cv2.imread(str(path))
    if img.shape[1] > max_w:
        scale = max_w / img.shape[1]
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()

cards = []
total_measures = 0
for i, (sec, system) in enumerate(zip(SECTIONS, systems), 1):
    measures = parse_ascii_tab(system)
    total_measures += len(measures)
    rendered = render_ascii(measures)
    kind, label = sec["verdict"]
    cards.append(f"""
<section class="card">
  <div class="card-head">
    <span class="eyebrow">Section {i} · frame @ {sec["ts"]}</span>
    <span class="chip chip-{kind}">{label}</span>
  </div>
  <figure>
    <img src="{img_data_uri(SCRATCH / 'frames' / sec['crop'])}" alt="Source tab, section {i}">
    <figcaption>Source — what the video shows</figcaption>
  </figure>
  <div class="extract">
    <div class="extract-label">Extracted — what the pipeline read ({len(measures)} measures)</div>
    <pre>{html_mod.escape(rendered)}</pre>
  </div>
  <details>
    <summary>Model's raw transcription</summary>
    <pre>{html_mod.escape(system)}</pre>
  </details>
</section>""")

page = """<title>Cannock Chase — Tab QA</title>
<style>
  :root {
    --paper: #FBFAF6; --card: #FFFFFF; --ink: #201D18; --muted: #6E675C;
    --brass: #8F6B2A; --line: #E5E0D5;
    --ok-bg: #EAF0E4; --ok-ink: #3E5B2C; --warn-bg: #F5EBD8; --warn-ink: #7A5A1E;
  }
  body {
    background: var(--paper); color: var(--ink);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    margin: 0; padding: 48px 20px 80px;
  }
  main { max-width: 860px; margin: 0 auto; display: flex; flex-direction: column; gap: 36px; }
  header h1 {
    font-size: 34px; font-weight: 650; letter-spacing: -0.02em;
    margin: 0 0 6px; text-wrap: balance;
  }
  header .sub { color: var(--muted); margin: 0 0 14px; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; }
  .meta span {
    font-size: 12.5px; color: var(--muted); background: var(--card);
    border: 1px solid var(--line); border-radius: 3px; padding: 3px 10px;
    font-variant-numeric: tabular-nums;
  }
  .howto {
    background: var(--card); border: 1px solid var(--line); border-radius: 3px;
    padding: 16px 20px; font-size: 14.5px; color: var(--muted);
  }
  .howto strong { color: var(--ink); font-weight: 600; }
  .howto ul { margin: 8px 0 0; padding-left: 20px; }
  .howto li { margin: 3px 0; }
  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: 3px;
    padding: 22px 24px 18px; display: flex; flex-direction: column; gap: 14px;
  }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .eyebrow {
    font-size: 11.5px; font-weight: 650; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--brass);
    font-variant-numeric: tabular-nums;
  }
  .chip {
    font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 99px;
  }
  .chip-clean { background: var(--ok-bg); color: var(--ok-ink); }
  .chip-check { background: var(--warn-bg); color: var(--warn-ink); }
  .chip-fail { background: #F3E3DE; color: #8A3B24; }
  figure { margin: 0; }
  figure img {
    display: block; max-width: 100%; border: 1px solid var(--line); border-radius: 2px;
  }
  figcaption, .extract-label {
    font-size: 12.5px; color: var(--muted); margin-top: 6px;
  }
  .extract-label { margin: 0 0 6px; }
  pre {
    margin: 0; padding: 14px 16px; overflow-x: auto;
    background: var(--paper); border: 1px solid var(--line); border-radius: 2px;
    font: 13.5px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    color: var(--ink);
  }
  details summary {
    font-size: 12.5px; color: var(--muted); cursor: pointer; user-select: none;
  }
  details summary:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
  details[open] summary { margin-bottom: 8px; }
  footer { font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; }
</style>
<main>
  <header>
    <h1>Cannock Chase — extraction QA</h1>
    <p class="sub">Tutorial by jmu.sikk · extracted 2026-07-03 · M1 feasibility spike</p>
    <div class="meta">
      <span>Capo 2 — shown in video, not yet extracted</span>
      <span>__NSEC__ sections</span>
      <span>__NMEAS__ measures</span>
      <span>gemini-2.5-flash, one batched call</span>
    </div>
  </header>
  <div class="howto">
    <strong>Verdict (user QA, 2026-07-03): extraction failed.</strong> Errors were found in
    all four sections, including confabulated patterns — the model composed plausible tab
    instead of reading the frame. This page is kept as the record of that finding; the
    extractor is being rebuilt around deterministic CV geometry.
    <ul>
      <li>To recheck any section: compare extracted vs. source — same string (line), same fret number, same left-to-right order.</li>
      <li>String names: e = thinnest (top line), E = thickest (bottom line).</li>
    </ul>
  </div>
__CARDS__
  <footer>
    Source video: ~/Downloads/ScreenRecording_07-03-2026&nbsp;17-10-24_1.MP4 ·
    Pipeline: guitar-tabs/pipeline/m1_spike.py (batched ASCII mode)
  </footer>
</main>
"""

page = (page.replace("__CARDS__", "\n".join(cards))
            .replace("__NSEC__", str(len(SECTIONS)))
            .replace("__NMEAS__", str(total_measures)))
out = SCRATCH / "tab-qa.html"
out.write_text(page)
print(f"wrote {out} ({len(page) // 1024} KB)")
