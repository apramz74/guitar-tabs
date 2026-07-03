# guitar-tabs

Turn guitar tutorial videos (e.g. Instagram Reels) into readable, browsable
guitar tabs — so you can go to a library and practice a song instead of scrubbing
through a video and pausing at every key frame.

## Status: prototype

Right now this is **proving the hardest part**: can we reliably read tab notation
off video frames? Everything else (the web library/viewer, ingest automation) is
deferred until this works on real videos.

## How it works (current plan)

```
video file ──▶ extract key frames ──▶ Gemini reads tabs ──▶ stitch ──▶ song JSON ──▶ web viewer
   (you)        (opencv + diff)        (free API tier)      (merge)     (data/)      (GitHub Pages)
```

- **The pipeline is NOT static** and cannot run on GitHub Pages. It runs on your
  machine (or later a server). It downloads/reads a video, extracts frames, and
  calls a vision model.
- **The web viewer CAN be static.** It reads the finished `data/songs/*.json`
  files and renders them. That part is what eventually goes on GitHub Pages.

## Layout

```
guitar-tabs/
  PRD.md               # product requirements — read this first
  pipeline/            # Python — the hard part
    m1_spike.py          # M1 feasibility spike: video → frames → Gemini → tab
    notebooks/           # experiment here
  data/songs/          # extracted tabs, one JSON per song
  web/                 # static frontend (future) → GitHub Pages
  requirements.txt
  .env                 # GEMINI_API_KEY=... (gitignored, never committed)
```

## Setup

```bash
cd guitar-tabs
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# create .env with your free key from https://aistudio.google.com/apikey
echo 'GEMINI_API_KEY=your-key-here' > .env
```

## Run the M1 spike

```bash
.venv/bin/python pipeline/m1_spike.py path/to/tutorial.mp4

# optional: inspect which frames were selected, cap Gemini calls
.venv/bin/python pipeline/m1_spike.py tutorial.mp4 --debug-frames frames/ --max-frames 20
```

## Notes / open questions

- **Instagram downloading is against their ToS and actively blocked.** For the
  prototype, feed it a local video file you've obtained legitimately. Keep the
  "get the video" step swappable — don't build the project around IG scraping.
- Reading tabs off frames is the real research risk. Prototype on 3–5 *real*
  tutorial videos of different styles before building any UI.
