#!/usr/bin/env python3
"""M1 feasibility spike: video file -> key frames -> Gemini reads tabs -> naive stitch -> printed tab.

This is deliberately a spike, not production code. Goal (per PRD §8): on a real
tutorial video, is the printed tab recognizable as the song?

Usage:
    python pipeline/m1_spike.py path/to/tutorial.mp4
    python pipeline/m1_spike.py path/to/tutorial.mp4 --debug-frames frames/ --max-frames 20
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# tried in order when a model is overloaded/unavailable
MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
MAX_ATTEMPTS = 4  # per frame, spread across models

# ---------------------------------------------------------------- frame extraction

def extract_key_frames(video_path: str, sample_fps: float = 2.0, diff_threshold: float = 12.0,
                       max_frames: int = 30):
    """Sample the video at ~sample_fps and keep frames that visibly differ from
    the last kept frame (mean absolute grayscale diff > threshold).

    Returns list of (timestamp_seconds, bgr_frame). Known limitation (PRD §9):
    a scrolling tab differs on *every* frame — max_frames caps the damage and
    the stitcher deals with the overlap.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"error: could not open video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(video_fps / sample_fps))

    kept = []
    last_gray = None
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
            if last_gray is None or cv2.absdiff(gray, last_gray).mean() > diff_threshold:
                kept.append((frame_idx / video_fps, frame))
                last_gray = gray
        frame_idx += 1
    cap.release()

    if len(kept) > max_frames:
        # keep an even spread rather than just the first N
        idxs = [round(i * (len(kept) - 1) / (max_frames - 1)) for i in range(max_frames)]
        kept = [kept[i] for i in sorted(set(idxs))]
    return kept


# ---------------------------------------------------------------- tab region crop

def crop_tab_region(frame):
    """If the frame contains a wide, light-colored band (the typical white tab
    strip overlaid on tutorial videos), crop to it and upscale — the tab is a
    tiny fraction of a phone frame, and the model reads a close-up far better.
    Falls back to the full frame when no such band is found.
    """
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    white = (gray > 185).astype(np.uint8)
    # bridge the tab's black lines/digits so the strip reads as one solid run
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((9, 31), np.uint8))

    def longest_run(row):
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row, [0]))))
        return int((idx[1::2] - idx[::2]).max()) if len(idx) else 0

    runs = np.array([longest_run(white[y]) for y in range(h)])
    band_rows = runs > 0.6 * w  # rows dominated by one long white run = tab strip

    # find the tallest contiguous band of such rows
    idx = np.flatnonzero(np.diff(np.concatenate(([0], band_rows.view(np.int8), [0]))))
    if len(idx) == 0:
        return frame
    starts, ends = idx[::2], idx[1::2]
    tallest = int(np.argmax(ends - starts))
    y0, y1 = int(starts[tallest]), int(ends[tallest])
    if y1 - y0 < 0.015 * h:  # too thin to be a tab strip
        return frame

    # x-extent: columns that are mostly white within the band
    col_white = white[y0:y1].mean(axis=0) > 0.5
    xs = np.flatnonzero(col_white)
    x0, x1 = (int(xs[0]), int(xs[-1])) if len(xs) else (0, w)

    pad = int(0.015 * h)
    crop = frame[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]
    return cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)


# ---------------------------------------------------------------- gemini reading

READ_PROMPT = """\
This frame is from a guitar tutorial video. It may show guitar TAB notation:
6 horizontal lines (the strings) with fret numbers written on them.

How to read guitar TAB correctly — follow these exactly:
- The TAB has exactly 6 lines. The TOP line is string 1 (high e, thinnest).
  The BOTTOM line is string 6 (low E, thickest).
- Determine each number's string by its position among ALL 6 lines counted from
  the top — including lines that have no numbers on them. Never skip an empty
  line when counting.
- Time flows LEFT to RIGHT. Each number is one note, at its horizontal position.
- Numbers are a CHORD (played together) ONLY if they are vertically aligned at
  the same horizontal position. Numbers at different horizontal positions are
  separate sequential notes — never merge them into a chord.
- Vertical bar lines divide measures. Report exactly as many measures as are
  visible; read them left to right.

Respond with ONLY a JSON object, no markdown fences:
{"has_tab": true,
 "measures": [
   {"notes": [
     {"string": 5, "fret": 0},
     {"string": 2, "fret": 3},
     {"chord": [{"string": 3, "fret": 4}, {"string": 4, "fret": 4}]}
   ]}
 ]}

- string: 1 = high e (top line) ... 6 = low E (bottom line). fret: 0 = open.
- Preserve the exact left-to-right playing order of notes within each measure.
- Use "chord" only for vertically aligned numbers.
- Read ONLY clearly legible numbers. Skip anything blurry or cut off.
- If there is no readable tab in the frame: {"has_tab": false}
"""


def call_gemini(client: genai.Client, contents):
    """generate_content with transient-error retry, falling through MODELS
    (free-tier congestion on one model often doesn't affect the others)."""
    for attempt in range(MAX_ATTEMPTS):
        model = MODELS[min(attempt, len(MODELS) - 1)]
        try:
            return client.models.generate_content(model=model, contents=contents)
        except genai_errors.APIError as e:
            transient = e.code in (429, 500, 503)
            if not transient or attempt == MAX_ATTEMPTS - 1:
                raise
            # free-tier 429s are per-minute quotas — short waits just burn attempts
            wait = 30 * (attempt + 1) if e.code == 429 else 2 ** (attempt + 1)
            print(f"      ({model}: {e.code} {e.status} — retrying in {wait}s)")
            time.sleep(wait)


def read_frame(client: genai.Client, frame) -> dict:
    """Send one frame to Gemini, return parsed JSON reading."""
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return {"has_tab": False, "error": "jpeg encode failed"}
    try:
        resp = call_gemini(client, [
            types.Part.from_bytes(data=jpg.tobytes(), mime_type="image/jpeg"),
            READ_PROMPT,
        ])
    except genai_errors.APIError as e:
        return {"has_tab": False, "error": f"{e.code} {e.status}"}

    text = (resp.text or "").strip()
    if text.startswith("```"):  # tolerate fenced output despite instructions
        text = text.strip("`\n")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"has_tab": False, "error": f"unparseable response: {text[:200]}"}


# ---------------------------------------------------------------- batched ascii mode

BATCH_PROMPT = """\
You are given {n} frames, in chronological order, from ONE guitar tutorial
video. Each frame may show guitar TAB notation: 6 horizontal lines (strings)
with fret numbers on them. The frames together cover the whole song, in order.

- Consecutive frames may show the SAME tab section — transcribe it once.
- A frame showing a NEW section continues the song — transcribe it after.
- Ignore any frame with no readable tab.

Transcribe the COMPLETE song as classic ASCII guitar tab — literally redraw
what you see:
- Each system is exactly 6 lines, labeled e| B| G| D| A| E| top to bottom
  (e = string 1 = the TOP line in the video's tab, E = string 6 = the BOTTOM).
- Copy each fret number onto the SAME line and at the same relative horizontal
  position as in the video. Use - for empty space and | for bar lines you see.
- Preserve the exact left-to-right order of the numbers. Do not invent,
  normalize, or "fix" anything — transcribe only clearly legible numbers.
- For multiple sections, output multiple 6-line systems separated by one blank
  line, in song order.

Output ONLY the ASCII tab. No commentary, no code fences.
"""


def read_song_batched(client: genai.Client, crops) -> str:
    """All crops in one API call -> model transcribes the whole song as ASCII
    tab. One call instead of N (free-tier friendly), and the model sees the
    sections in context, which replaces client-side stitching for static tabs.
    """
    parts = []
    for _, crop in crops:
        ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            parts.append(types.Part.from_bytes(data=jpg.tobytes(), mime_type="image/jpeg"))
    parts.append(BATCH_PROMPT.format(n=len(parts)))
    resp = call_gemini(client, parts)
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`\n")
    return text


def parse_ascii_tab(text: str) -> list:
    """Deterministically parse ASCII tab into the measures/notes structure.
    The model redraws what it sees (a task vision models are good at); turning
    columns into note events is plain string-walking we do ourselves.
    """
    # collect 6-line systems: consecutive lines that look like tab lines
    blocks, cur = [], []
    for line in text.splitlines():
        if line.count("-") >= 3:
            cur.append(line.rstrip())
        else:
            if len(cur) >= 6:
                blocks.append(cur[:6])
            cur = []
    if len(cur) >= 6:
        blocks.append(cur[:6])

    measures = []
    for block in blocks:
        # strip the "e|" style label prefix if present
        norm = []
        for line in block:
            bar = line.find("|")
            norm.append(line[bar + 1:] if 0 <= bar <= 3 else line)
        width = max(len(l) for l in norm)
        norm = [l.ljust(width, "-") for l in norm]

        current = {"notes": []}
        col = 0
        while col < width:
            if any(norm[s][col] == "|" for s in range(6)):
                if current["notes"]:
                    measures.append(current)
                    current = {"notes": []}
                col += 1
                continue
            consumed = 1
            column_notes = []
            for s in range(6):
                ch = norm[s][col]
                if ch.isdigit():
                    nxt = norm[s][col + 1] if col + 1 < width else ""
                    if nxt.isdigit() and int(ch + nxt) <= 24:  # two-digit fret
                        column_notes.append((s + 1, int(ch + nxt)))
                        consumed = 2
                    else:
                        column_notes.append((s + 1, int(ch)))
            if len(column_notes) == 1:
                s, f = column_notes[0]
                current["notes"].append({"string": s, "fret": f})
            elif column_notes:
                current["notes"].append(
                    {"chord": [{"string": s, "fret": f} for s, f in column_notes]})
            col += consumed
        if current["notes"]:
            measures.append(current)
    return measures


# ---------------------------------------------------------------- naive stitch

def measure_notes(measure: dict) -> set:
    """Flatten a measure to a set of (string, fret) pairs for fuzzy comparison."""
    pairs = set()
    for event in measure.get("notes", []):
        if not isinstance(event, dict):
            continue
        for n in event.get("chord", [event]):
            try:
                pairs.add((int(n["string"]), int(n["fret"])))
            except (KeyError, TypeError, ValueError):
                continue
    return pairs


def measures_similar(a: dict, b: dict, threshold: float = 0.6) -> bool:
    """Fuzzy equality: Jaccard similarity of note sets. Survives small read
    differences (an off-by-one string on one note) that exact matching can't."""
    na, nb = measure_notes(a), measure_notes(b)
    if not na and not nb:
        return True
    if not na or not nb:
        return False
    return len(na & nb) / len(na | nb) >= threshold


def stitch(readings: list) -> list:
    """Merge per-frame measure lists into one sequence.

    Overlap merge with fuzzy matching: for each new frame, find the longest
    suffix of the stitched-so-far measures that (fuzzily) matches a prefix of
    the new frame's measures, and append only the remainder. Handles a static
    tab shown across many frames (full overlap -> nothing appended) and a
    scrolling tab (partial overlap -> tail appended). Fuzzy matching lets a
    slightly-misread duplicate frame still merge instead of duplicating.
    """
    stitched = []
    for reading in readings:
        measures = reading.get("measures") or []
        if not measures:
            continue
        overlap = 0
        for k in range(min(len(measures), len(stitched)), 0, -1):
            if all(measures_similar(stitched[-k + i], measures[i]) for i in range(k)):
                overlap = k
                break
        stitched.extend(measures[overlap:])
    return stitched


# ---------------------------------------------------------------- ascii rendering

def render_ascii(measures: list) -> str:
    """Render measures as classic 6-line ASCII tab. A note may carry
    "legato_next" ("h", "p", "/", "\\") — drawn as the connector to the
    following note on that string, the way guitarists write 5h6 or 7/11."""
    string_names = ["e", "B", "G", "D", "A", "E"]  # index 0 = string 1 (high e)
    lines = [[] for _ in range(6)]

    def emit_column(cells: dict, conns: dict):
        width = max((len(v) for v in cells.values()), default=1)
        for s in range(6):
            lines[s].append(cells.get(s + 1, "-" * width).rjust(width, "-"))
            lines[s].append(conns.get(s + 1, "-"))

    for mi, measure in enumerate(measures):
        for event in measure.get("notes", []):
            notes = event.get("chord", [event]) if isinstance(event, dict) else []
            cells, conns = {}, {}
            for n in notes:
                try:
                    cells[int(n["string"])] = str(int(n["fret"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if n.get("legato_next"):
                    conns[int(n["string"])] = n["legato_next"]
            if cells:
                emit_column(cells, conns)
        if mi < len(measures) - 1:
            for s in range(6):
                lines[s].append("|-")

    return "\n".join(f"{string_names[s]}|-" + "".join(lines[s]) for s in range(6))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", help="path to a local tutorial video file")
    ap.add_argument("--max-frames", type=int, default=30, help="cap on frames sent to Gemini")
    ap.add_argument("--debug-frames", help="directory to dump the selected key frames as JPEGs")
    ap.add_argument("--per-frame", action="store_true",
                    help="read each frame in its own API call and stitch client-side "
                         "(default: one batched call for the whole song)")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("error: GEMINI_API_KEY not set — create guitar-tabs/.env (see .env.example)")
    client = genai.Client(api_key=api_key)

    print(f"[1/3] extracting key frames from {args.video} ...")
    frames = extract_key_frames(args.video, max_frames=args.max_frames)
    print(f"      kept {len(frames)} frames")

    print("      cropping to tab region where detected ...")
    crops = [(ts, crop_tab_region(frame)) for ts, frame in frames]

    # drop consecutive crops showing the same tab content — each API call is
    # precious on the free tier, and re-reads of one section stitch imperfectly
    deduped = []
    last_small = None
    for ts, crop in crops:
        small = cv2.cvtColor(cv2.resize(crop, (128, 32)), cv2.COLOR_BGR2GRAY)
        if last_small is None or cv2.absdiff(small, last_small).mean() > 8.0:
            deduped.append((ts, crop))
        last_small = small
    if len(deduped) < len(crops):
        print(f"      deduped {len(crops)} crops -> {len(deduped)} distinct sections")
    crops = deduped

    if args.debug_frames:
        Path(args.debug_frames).mkdir(parents=True, exist_ok=True)
        for (ts, frame), (_, crop) in zip(frames, crops):
            cv2.imwrite(str(Path(args.debug_frames) / f"frame_{ts:07.2f}s.jpg"), frame)
            cv2.imwrite(str(Path(args.debug_frames) / f"crop_{ts:07.2f}s.jpg"), crop)
        print(f"      wrote debug frames + crops to {args.debug_frames}/")

    if args.per_frame:
        print(f"[2/3] reading frames with {MODELS[0]} (fallbacks: {', '.join(MODELS[1:])}) ...")
        readings = []
        for i, (ts, frame) in enumerate(crops):
            r = read_frame(client, frame)
            n = len(r.get("measures") or [])
            status = f"{n} measure(s)" if r.get("has_tab") else r.get("error", "no tab")
            print(f"      frame {i + 1}/{len(crops)} @ {ts:6.1f}s: {status}")
            readings.append(r)
        print("[3/3] stitching ...")
        measures = stitch(readings)
    else:
        print(f"[2/3] reading all {len(crops)} sections in ONE batched call ({MODELS[0]}) ...")
        try:
            ascii_tab = read_song_batched(client, crops)
        except genai_errors.APIError as e:
            sys.exit(f"error: batched call failed after retries: {e.code} {e.status}")
        print("\n=== model transcription (raw) ===\n")
        print(ascii_tab)
        print("\n[3/3] parsing transcription ...")
        measures = parse_ascii_tab(ascii_tab)
    if not measures:
        print("\nNo tab content was read from any frame. Feasibility check: FAILED for this video.")
        return

    print(f"\n=== stitched tab ({len(measures)} measures) ===\n")
    print(render_ascii(measures))
    print("\n=== raw json ===\n")
    print(json.dumps(measures, indent=2))


if __name__ == "__main__":
    main()
