# guitar-tabs

Turn guitar tutorial videos (screen recordings of Instagram Reels, tab
apps, etc.) into a phone-first tab library — so practice means opening a
song and playing, not scrubbing a video and pausing at every frame.

**The library is live: https://apramz74.github.io/guitar-tabs/web/**

Three docs matter here:
- `README.md` (this file) — what everything is and how to use it.
- `PRD.md` — the goals and the locked decisions, plus what M1 taught us.
- `STATUS.md` — running log between working sessions: what's done, open
  items, and the per-video cluster label sets. Read it first each session.

## The practice site (`web/`)

Static site, no build step, served by GitHub Pages from this repo. It
reads `data/songs/*.json` and renders real tab: big fret numbers on six
string lines, drawn arcs for hammer-ons/pull-offs with the h/p letter on
the curve, slanted slide strokes, ghost notes in parens. Font size
steppers, one-handed layout, dark theme.

Editing (tap **Edit**):
- Tap a note → change fret, string, slide/hammer marks, ghost; delete it.
- Tap a faint `+` → add a note there (on an empty string of an existing
  beat = chord; in a gap = new beat).
- Tap a bar line → measure tools: merge with next, split (then tap where
  the bar belongs), add/delete measure.
- Measures the pipeline repaired or doubts show **⚠ check**; a second
  pass of a looping tutorial shows **repeat?**. After checking against
  the video, hit **Looks right** to clear the flag.
- **⋯ → Song info** edits title, artist, capo, tuning, time signature.

Saving: edits land in the phone's local storage instantly, then
auto-commit to this repo a few seconds later through the GitHub API.
One-time setup per device: **⚙ Settings** → enter GitHub username, repo
name, and a fine-grained personal access token (github.com → Settings →
Developer settings → tokens; access to only this repo; Contents:
read/write). No token = read-only viewing with local-only drafts.
Deleting a song only flags it `archived` — restore from the list page.
Every save is a git commit, so nothing is ever lost.

Run it locally: `python3 -m http.server` from the repo root, then open
`http://localhost:8000/web/`.

## Adding a song (runs on the Mac)

The easy way — the intake app:

```bash
.venv/bin/python pipeline/intake.py
```

A page opens: paste a YouTube or Instagram link (IG uses your Chrome
login) or drop a screen recording; extraction runs; you confirm the
shape flashcards (mostly prefilled from shapes you've named before);
check the tab against the video; publish. Done — it's on your phone in
a minute.

The manual way, step by step:

1. **Screen-record the tutorial** (IG scraping is against ToS and
   fragile; a manual recording always works). Any style works: white tab
   strips with page flips, full-screen tab apps, dark overlays that
   scroll sideways — one pipeline handles all three.
2. **Extract:**
   ```bash
   .venv/bin/python pipeline/extract_cv.py <video> --debug-dir /tmp/run1
   ```
   It finds the tab on every sampled frame, measures every digit's
   position with pixel math, groups identical shapes, and writes
   `glyph_cluster_*.png` flashcards to the debug dir.
3. **Name the flashcards** (the only human step): look at each cluster
   image and re-run with labels — `--label 0=5 --label 1=x ...`
   (`x` = junk, `arc`, `slide/`, `slide\`, `(`, `)` for marks). Or pass
   `--ai` for one Gemini call that suggests names — verify them; only
   human-checked labels count. Labels are only valid for the code
   version they were made on (STATUS.md keeps the working sets).
4. **Check the output**: the run prints the tab as ASCII, writes
   annotated overlay images (detected notes boxed, repaired bars in
   color), and flags anything it changed or doubts. Optionally read the
   on-screen metadata: `pipeline/read_metadata.py <video>` prints
   title/artist/capo/tuning it can see, for you to confirm.
5. **Save and publish:**
   ```bash
   .venv/bin/python pipeline/save_song.py /tmp/run1/extraction.json \
       --title "Song" --artist "Artist" --capo 2 --time-sig 4/4
   git add data/ && git commit -m "Add Song" && git push
   ```
   The site picks it up on the next Pages deploy (~a minute).

## How the pipeline works (one paragraph, honest version)

Sample the video ~2×/second; find the tab strip on each frame by its six
evenly spaced lines; measure every digit's exact position with OpenCV —
**no AI ever decides where a note is**, because vision models confabulate
tab geometry (M1's hard lesson, see PRD §4). Group visually identical
digit shapes and have a human name each shape once. Merge repeated
sightings of the same page; stitch sideways-scrolling tabs onto one long
timeline; every note is seen several times and voted on. Bar lines get a
sanity pass: measures in one video are drawn near-uniform in width, so a
double-width measure means a missed bar (added back in a note-free gap)
and a sliver means a stray bar (removed) — every repair is flagged for
human eyes, in the overlays and in the app. Nothing enters a tab file
that wasn't measured deterministically or verified by a human.

## Layout

```
guitar-tabs/
  PRD.md               # product goals + locked decisions — read first
  STATUS.md            # session log: progress, open items, label sets
  pipeline/
    extract_cv.py        # THE extractor: video -> measured tab data
    save_song.py         # extraction.json + metadata -> data/songs/*.json
    read_metadata.py     # reads on-screen title/capo/etc for confirmation
    m1_spike.py          # legacy M1 spike; still hosts the Gemini helper
    qa/                  # builders for the human-QA artifact pages
  data/songs/          # one JSON per song + index.json (the site reads these)
  web/                 # the practice site (index.html, app.js, style.css)
  requirements.txt
  .env                 # GEMINI_API_KEY=... (gitignored; only AI naming needs it)
```

## Setup (pipeline)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo 'GEMINI_API_KEY=your-key' > .env   # free key: aistudio.google.com/apikey
```
