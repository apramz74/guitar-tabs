"""Add a song without the terminal.

Local web app: paste a YouTube/Instagram link or drop a screen
recording, watch extraction run, confirm the glyph flashcards (mostly
prefilled from pipeline/glyph_library/), eyeball the tab next to the
video, then publish — save_song + git commit + push.

Run:  .venv/bin/python pipeline/intake.py   (opens the browser itself)

Instagram downloads borrow the Chrome login (user's explicit choice,
2026-07-07; ToS-gray at personal scale). Any download failure points at
the screen-record fallback — the fragile path never blocks adding a song.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_cv import LABEL_SLUGS, match_library  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
RUNS = ROOT / ".intake-runs"
LIBRARY = PIPE / "glyph_library"
UI = PIPE / "intake_ui"
PY = sys.executable
PORT = 8765

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 ** 3
runs = {}   # id -> state dict (single user, in memory)


def new_run():
    rid = time.strftime("%Y%m%d-%H%M%S")
    d = RUNS / rid
    d.mkdir(parents=True, exist_ok=True)
    runs[rid] = {"id": rid, "dir": str(d), "step": "starting", "log": [],
                 "error": None, "clusters": 0, "prefill": {}, "labels": {},
                 "mode": "tab", "diagrams": [], "chord_suggestions": None,
                 "pages": [], "flags": [], "meta": None, "published": None}
    return runs[rid]


def log(run, msg):
    run["log"].append(msg)


def background(fn, *a):
    def wrap():
        try:
            fn(*a)
        except Exception as e:  # surfaced to the UI, never a stack trace
            runs_val = a[0]
            runs_val["step"] = "error"
            runs_val["error"] = str(e)
            log(runs_val, f"ERROR: {e}")
    threading.Thread(target=wrap, daemon=True).start()


# ---------------------------------------------------------------- video in

def do_download(run, link):
    import yt_dlp
    run["step"] = "download"
    is_ig = "instagram.com" in link
    log(run, f"downloading {'from Instagram (using your Chrome login)' if is_ig else 'from the link'} …")
    opts = {
        "outtmpl": str(Path(run["dir"]) / "video.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b",
        "noplaylist": True,
        "quiet": True, "no_warnings": True,
        "progress_hooks": [lambda d: _dl_hook(run, d)],
    }
    if is_ig:
        opts["cookiesfrombrowser"] = ("chrome",)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([link])
    except Exception as e:
        hint = ("Instagram said no — your Chrome login may be missing or expired, "
                "or Instagram changed something. Screen-record the reel instead "
                "and drop the file in; that always works.") if is_ig else \
               ("Couldn't download that link. Screen-record the video instead "
                "and drop the file in; that always works.")
        run["step"] = "error"
        run["error"] = hint
        log(run, f"download failed: {e}")
        return
    vids = sorted(Path(run["dir"]).glob("video.*"))
    if not vids:
        run["step"] = "error"
        run["error"] = "Download finished but no video file appeared."
        return
    run["video"] = vids[0].name
    log(run, f"downloaded {vids[0].name}")
    do_extract(run)


def _dl_hook(run, d):
    if d.get("status") == "finished":
        log(run, "download finished, merging …")


# ---------------------------------------------------------------- extract

def do_extract(run):
    run["step"] = "extract"
    video = Path(run["dir"]) / run["video"]
    debug = Path(run["dir"]) / "debug"
    debug.mkdir(exist_ok=True)
    log(run, "reading the video — this takes a minute or two …")
    p = subprocess.Popen([PY, str(PIPE / "extract_cv.py"), str(video),
                          "--debug-dir", str(debug)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log(run, line)
    if p.wait() != 0:
        run["step"] = "error"
        run["error"] = "Extraction failed — see the log above."
        return

    ext = json.loads((debug / "extraction.json").read_text())
    if ext.get("mode") == "chords" and ext.get("diagrams"):
        run["mode"] = "chords"
        run["diagrams"] = ext["diagrams"]
        run["step"] = "chords"
        log(run, f"{len(ext['diagrams'])} chord diagrams found — confirm each name "
                 "and base fret (the little 'Fr N' under the grid)")
        return

    cards = sorted(debug.glob("glyph_cluster_*.png"))
    if not cards:
        _frames_sheet(video, Path(run["dir"]) / "frames.png")
        run["step"] = "notab"
        run["error"] = ("Couldn't find a readable tab or chord diagrams in this video. "
                        "Either it has no on-screen notation, or it's a style the "
                        "pipeline doesn't know yet. Here's what it looks like to the "
                        "pipeline:")
        return

    run["clusters"] = len(cards)
    run["prefill"] = {str(k): v for k, v in match_library(debug, LIBRARY).items()}
    run["labels"] = dict(run["prefill"])
    run["step"] = "label"
    log(run, f"{len(cards)} shapes found; {len(run['prefill'])} recognized from earlier songs")


def _frames_sheet(video, out):
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    tiles = []
    for f in (0.25, 0.5, 0.75):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * f))
        ok, fr = cap.read()
        if ok:
            tiles.append(cv2.resize(fr, (480, int(480 * fr.shape[0] / fr.shape[1]))))
    cap.release()
    if tiles:
        cv2.imwrite(str(out), np.hstack(tiles) if len({t.shape for t in tiles}) == 1 else tiles[0])


# ---------------------------------------------------------------- label -> check

def _rebuild(run, extra_args, what):
    run["step"] = "build"
    debug = Path(run["dir"]) / "debug"
    log(run, f"building the tab with your {what} …")
    video = Path(run["dir"]) / run["video"]
    p = subprocess.Popen([PY, str(PIPE / "extract_cv.py"), str(video),
                          "--debug-dir", str(debug)] + extra_args,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log(run, line)
    if p.wait() != 0:
        run["step"] = "error"
        run["error"] = "Tab build failed — see the log above."
        return None
    return json.loads((debug / "extraction.json").read_text())


def do_build(run):
    debug = Path(run["dir"]) / "debug"
    labels_file = debug / "labels.json"
    labels_file.write_text(json.dumps(run["labels"]))
    ext = _rebuild(run, ["--labels-json", str(labels_file)], "labels")
    if ext is None:
        return
    run["pages"] = [{"ascii": p["ascii"], "annotated": p["annotated"]} for p in ext["pages"]]
    run["flags"] = [
        {"measure": i + 1,
         **({"boundary": m["boundary"]} if "boundary" in m else {}),
         **({"suspect": True} if m.get("suspect") else {}),
         **({"repeat_of": m["repeat_of"] + 1} if "repeat_of" in m else {})}
        for i, m in enumerate(ext["measures"])
        if m.get("suspect") or "boundary" in m or "repeat_of" in m]
    run["measure_count"] = len(ext["measures"])
    run["step"] = "check"
    if run["meta"] is None:
        background(do_metadata, run)


def do_build_chords(run, frets, names, flip):
    args = ["--frets", ",".join(str(f) for f in frets),
            "--names", ",".join(names)]
    if flip:
        args.append("--flip-strings")
    ext = _rebuild(run, args, "chords")
    if ext is None:
        return
    run["diagrams"] = ext.get("diagrams", [])
    run["pages"] = [{"ascii": p["ascii"], "annotated": p["annotated"]} for p in ext["pages"]]
    run["flags"] = [
        {"measure": i + 1,
         **({"suspect": True} if m.get("suspect") else {}),
         **({"repeat_of": m["repeat_of"] + 1} if "repeat_of" in m else {})}
        for i, m in enumerate(ext["measures"])
        if m.get("suspect") or "repeat_of" in m]
    run["measure_count"] = len(ext["measures"])
    run["step"] = "check"
    if run["meta"] is None:
        background(do_metadata, run)


def do_suggest_chords(run):
    """One Gemini call over the name + fret crops; suggestions only."""
    from m1_spike import call_gemini
    from google import genai
    from google.genai import types
    from dotenv import load_dotenv
    import os
    load_dotenv(ROOT / ".env")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    debug = Path(run["dir"]) / "debug"
    parts = []
    for d in run["diagrams"]:
        for crop in (d["name_crop"], d["fret_crop"]):
            f = debug / crop
            if f.is_file():
                parts.append(types.Part.from_bytes(data=f.read_bytes(), mime_type="image/png"))
    n = len(run["diagrams"])
    parts.append(
        f"These are {2 * n} images: for each of {n} chord diagrams, first its chord NAME "
        "(e.g. Bm7, C#m/E), then its base-fret label (e.g. 'Fr 7'). Report ONLY the text "
        "you see. Respond with ONLY a JSON list of " + str(n) + " objects like "
        '[{"name": "Bm7", "fr": 7}, ...], null for anything unreadable.')
    resp = call_gemini(client, parts)
    text = (resp.text or "").strip().strip("`")
    text = text[4:] if text.startswith("json") else text
    run["chord_suggestions"] = json.loads(text)
    log(run, "AI read the names and frets — every one still needs your confirmation")


def do_metadata(run):
    try:
        from read_metadata import read
        run["meta"] = read(str(Path(run["dir"]) / run["video"]))
        log(run, "read the on-screen song info — confirm it below")
    except Exception as e:
        run["meta"] = {}
        log(run, f"(couldn't read on-screen song info: {e} — fill it in by hand)")


def do_suggest(run):
    """One batched Gemini call naming the flashcards; suggestions only."""
    import cv2
    from m1_spike import call_gemini
    from google import genai
    from google.genai import types
    from dotenv import load_dotenv
    import os
    load_dotenv(ROOT / ".env")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    debug = Path(run["dir"]) / "debug"
    cards = sorted(debug.glob("glyph_cluster_*.png"), key=lambda p: int(p.stem.split("_")[-1]))
    parts = []
    for c in cards:
        parts.append(types.Part.from_bytes(data=c.read_bytes(), mime_type="image/png"))
    parts.append(
        f"You are shown {len(cards)} images, each one character from a guitar tab: a digit "
        "0-9, or a mark: an arc, a slide slash, a parenthesis, a letter (h/p/x), or junk. "
        'Answer with ONLY a JSON object mapping image number (1-based) to one of: '
        '"0".."9", "arc", "slide/", "slide\\\\", "(", ")", "h", "p", "x" (x = junk/other).')
    resp = call_gemini(client, parts)
    text = (resp.text or "").strip().strip("`")
    text = text[4:] if text.startswith("json") else text
    sug = {str(int(k) - 1): v for k, v in json.loads(text).items()}
    run["suggestions"] = sug
    log(run, "AI suggestions ready — every card still needs your confirmation")


# ---------------------------------------------------------------- publish

def do_publish(run, meta, push):
    run["step"] = "publishing"
    debug = Path(run["dir"]) / "debug"
    cmd = [PY, str(PIPE / "save_song.py"), str(debug / "extraction.json"),
           "--title", meta["title"], "--artist", meta.get("artist", ""),
           "--source", run.get("source_link") or run.get("video", ""),
           "--tuning", meta.get("tuning") or "EADGBE",
           "--capo", str(meta.get("capo") or 0), "--qa", "draft"]
    if meta.get("time_signature"):
        cmd += ["--time-sig", meta["time_signature"]]
    p = subprocess.run(cmd, capture_output=True, text=True)
    for line in (p.stdout + p.stderr).splitlines():
        if line.strip():
            log(run, line.strip())
    if p.returncode != 0:
        run["step"] = "error"
        run["error"] = "Saving the song file failed — see the log."
        return

    # confirmed labels become library knowledge for the next song
    added = 0
    for ci, label in run["labels"].items():
        src = debug / f"glyph_cluster_{ci}.png"
        if not src.is_file() or not label:
            continue
        slug = LABEL_SLUGS.get(label, label)
        h = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
        dst = LIBRARY / f"{slug}__{h}.png"
        if not dst.exists():
            LIBRARY.mkdir(exist_ok=True)
            shutil.copy(src, dst)
            added += 1
    if added:
        log(run, f"remembered {added} new shape(s) for future songs")

    slug = re.sub(r"[^a-z0-9]+", "-", meta["title"].lower()).strip("-")
    if push:
        for cmd in (["git", "add", "data/", "pipeline/glyph_library/"],
                    ["git", "commit", "-m", f"Add {meta['title']} (intake)"],
                    ["git", "push"]):
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            if p.returncode != 0:
                run["step"] = "error"
                run["error"] = f"`{' '.join(cmd)}` failed: {p.stderr.strip()[:300]}"
                return
        log(run, "committed and pushed — the site updates in about a minute")
        run["published"] = {"url": f"https://apramz74.github.io/guitar-tabs/web/#/s/{slug}.json"}
    else:
        log(run, "saved to data/songs/ — NOT committed (push was off)")
        run["published"] = {"url": f"/../web/index.html#/s/{slug}.json", "local": True}
    run["step"] = "done"


# ---------------------------------------------------------------- routes

@app.get("/")
def home():
    return send_from_directory(UI, "index.html")


@app.get("/ui/<path:name>")
def ui_file(name):
    return send_from_directory(UI, name)


@app.post("/api/runs")
def create_run():
    run = new_run()
    if request.files.get("file"):
        f = request.files["file"]
        ext = Path(f.filename or "video.mp4").suffix or ".mp4"
        f.save(Path(run["dir"]) / f"video{ext}")
        run["video"] = f"video{ext}"
        run["source_link"] = f.filename       # song "source" = original file name
        log(run, f"got your file ({f.filename})")
        background(do_extract, run)
    else:
        link = (request.get_json(silent=True) or {}).get("link", "").strip()
        if not link:
            return jsonify({"error": "no link or file"}), 400
        run["source_link"] = link
        background(do_download, run, link)
    return jsonify({"id": run["id"]})


@app.get("/api/runs/<rid>")
def run_state(rid):
    run = runs.get(rid)
    if not run:
        return jsonify({"error": "unknown run"}), 404
    return jsonify({k: v for k, v in run.items() if k != "dir"})


@app.get("/api/runs/<rid>/file/<path:name>")
def run_file(rid, name):
    run = runs.get(rid)
    return send_from_directory(run["dir"], name, conditional=True)


@app.post("/api/runs/<rid>/labels")
def set_labels(rid):
    run = runs[rid]
    run["labels"] = {str(k): v for k, v in (request.get_json() or {}).get("labels", {}).items() if v}
    background(do_build, run)
    return jsonify({"ok": True})


@app.post("/api/runs/<rid>/suggest")
def suggest(rid):
    run = runs[rid]
    background(do_suggest_chords if run.get("mode") == "chords" else do_suggest, run)
    return jsonify({"ok": True})


@app.post("/api/runs/<rid>/chords")
def build_chords(rid):
    body = request.get_json() or {}
    frets = [int(f) for f in body.get("frets", [])]
    names = [str(n) for n in body.get("names", [])]
    run = runs[rid]
    if len(frets) != len(run.get("diagrams", [])):
        return jsonify({"error": "one base fret per diagram required"}), 400
    background(do_build_chords, run, frets, names, bool(body.get("flip")))
    return jsonify({"ok": True})


@app.post("/api/runs/<rid>/back-to-chords")
def back_to_chords(rid):
    runs[rid]["step"] = "chords"
    return jsonify({"ok": True})


@app.post("/api/runs/<rid>/back-to-labels")
def back_to_labels(rid):
    runs[rid]["step"] = "label"
    return jsonify({"ok": True})


@app.post("/api/runs/<rid>/publish")
def publish(rid):
    body = request.get_json() or {}
    meta = body.get("meta", {})
    if not meta.get("title"):
        return jsonify({"error": "title required"}), 400
    background(do_publish, runs[rid], meta, bool(body.get("push", True)))
    return jsonify({"ok": True})


def main():
    RUNS.mkdir(exist_ok=True)
    threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    print(f"Intake running at http://127.0.0.1:{PORT}/  (Ctrl-C to stop)")
    app.run(host="127.0.0.1", port=PORT, debug=False)


if __name__ == "__main__":
    main()
