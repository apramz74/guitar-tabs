#!/usr/bin/env python3
"""CV-first tab extractor (post-M1 pivot).

All GEOMETRY is measured deterministically with OpenCV — string lines, digit
positions, ordering, measure boundaries. AI (or template matching) is only
asked "which digit is this glyph?", per-glyph, and its answers are meant to be
human-verified. See PRD §4.

Usage:
    python pipeline/extract_cv.py video.mp4 --debug-dir out/          # geometry only
    python pipeline/extract_cv.py video.mp4 --debug-dir out/ --ai     # + AI digit naming
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_spike import crop_tab_region  # noqa: E402  (strip finder, 2x upscaled)

SAMPLE_FPS = 2.0


# ---------------------------------------------------------------- sections (crop-space diff)

def find_sections(video_path: str):
    """Sample the video, crop the tab strip from EVERY sampled frame, and
    detect section changes in crop space — background motion is invisible here,
    and any tab change is a large signal."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"error: could not open video: {video_path}")
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(video_fps / SAMPLE_FPS))

    sections = []
    last_small = None
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            crop = crop_tab_region(frame)
            if crop.shape != frame.shape:  # strip found (fallback returns frame as-is)
                small = cv2.cvtColor(cv2.resize(crop, (160, 40)), cv2.COLOR_BGR2GRAY)
                if last_small is None or cv2.absdiff(small, last_small).mean() > 8.0:
                    sections.append((frame_idx / video_fps, crop))
                last_small = small
        frame_idx += 1
    cap.release()
    return sections


# ---------------------------------------------------------------- geometry

def measure_section(crop):
    """Measure one tab-strip crop. Returns dict with line ys, bar xs, and glyph
    blobs (each: centroid, bbox, string index, image) — or None if the strip
    doesn't measure like a 6-line tab."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # tighten to the white strip proper (crop has a little scene padding).
    # rows first; then columns measured ONLY within those rows. Background that
    # still leaks in is handled downstream by the border-bar glyph filter.
    white = gray > 200
    white_rows = np.flatnonzero(white.mean(axis=1) > 0.55)
    if not len(white_rows):
        return None
    y0, y1 = white_rows[0], white_rows[-1] + 1
    white_cols = np.flatnonzero(white[y0:y1].mean(axis=0) > 0.75)
    if not len(white_cols):
        return None
    x0, x1 = white_cols[0], white_cols[-1] + 1
    roi = gray[y0:y1, x0:x1]
    H, W = roi.shape

    _, ink = cv2.threshold(roi, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # string lines: rows where ink spans most of the width
    line_rows = (ink.mean(axis=1) > 0.5).astype(np.int8)
    idx = np.flatnonzero(np.diff(np.concatenate(([0], line_rows, [0]))))
    line_ys = [int((s + e) / 2) for s, e in zip(idx[::2], idx[1::2])]
    if len(line_ys) != 6:
        return {"error": f"expected 6 string lines, found {len(line_ys)}", "roi": roi}

    top, bot = line_ys[0], line_ys[-1]
    # bar lines: columns whose ink spans (almost) the full line block
    col_span = ink[top:bot + 1].mean(axis=0)
    bar_cols = (col_span > 0.75).astype(np.int8)
    idx = np.flatnonzero(np.diff(np.concatenate(([0], bar_cols, [0]))))
    bar_xs = [int((s + e) / 2) for s, e in zip(idx[::2], idx[1::2])]
    # merge doubled detections (thick end-bars read as two)
    merged, gap0 = [], (bot - top) / 5.0
    for b in bar_xs:
        if merged and b - merged[-1] < 0.5 * gap0:
            merged[-1] = (merged[-1] + b) // 2
        else:
            merged.append(b)
    bar_xs = merged

    # erase lines and bars; what's left is glyph ink
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, W // 8), np.uint8))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(8, (bot - top) // 2), 1), np.uint8))
    nonline = ink & ~horiz & ~vert
    # erasing a line cuts digits sitting on it in half. Restore line pixels
    # ONLY where glyph ink sits just above/below (a digit stroke crossing the
    # line) — a blind vertical bridge would fuse chord digits on adjacent
    # lines, which sit only a few px apart
    thick = max(3, int(round(0.12 * gap0)))
    support = cv2.dilate(nonline, np.ones((2 * thick + 1, 1), np.uint8))
    glyph_ink = (nonline | (horiz & support)).astype(np.uint8)
    glyph_ink = cv2.morphologyEx(glyph_ink, cv2.MORPH_CLOSE, np.ones((5, 3), np.uint8))

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(glyph_ink, connectivity=8)
    gap = (bot - top) / 5.0  # inter-line spacing
    glyphs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        # plausible digit: digits run ~0.85 line-gaps tall; line-erasure debris
        # is much shorter and wide — reject anything under ~0.55 gaps.
        # area floor stays low: a "1" is a thin bar with little ink
        if not (0.55 * gap < h < 1.8 * gap) or area < 0.03 * gap * gap or w > 2.5 * gap:
            continue
        cx, cy = centroids[i]
        string = int(np.argmin([abs(cy - ly) for ly in line_ys])) + 1
        glyphs.append({
            "cx": float(cx), "cy": float(cy), "bbox": (int(x), int(y), int(w), int(h)),
            "string": string,
            "img": (glyph_ink[y:y + h, x:x + w] * 255).astype(np.uint8),
        })
    # notes live ON the 6 lines — text above (titles, "Capo N") and rhythm
    # notation below are outside the line band and are not notes
    glyphs = [g for g in glyphs if top - 0.6 * gap < g["cy"] < bot + 0.6 * gap]
    # nothing outside the tab's own border bars is a note
    if len(bar_xs) >= 2:
        glyphs = [g for g in glyphs if bar_xs[0] - gap < g["cx"] < bar_xs[-1] + gap]
    glyphs.sort(key=lambda g: g["cx"])
    return {"roi": roi, "line_ys": line_ys, "bar_xs": bar_xs, "glyphs": glyphs, "gap": gap}


def annotate(section, path: Path):
    """Draw measured geometry onto the ROI for visual verification."""
    vis = cv2.cvtColor(section["roi"], cv2.COLOR_GRAY2BGR)
    for ly in section.get("line_ys", []):
        cv2.line(vis, (0, ly), (vis.shape[1], ly), (255, 160, 0), 1)
    for bx in section.get("bar_xs", []):
        cv2.line(vis, (bx, 0), (bx, vis.shape[0]), (0, 180, 0), 2)
    for g in section.get("glyphs", []):
        x, y, w, h = g["bbox"]
        cv2.rectangle(vis, (x - 2, y - 2), (x + w + 2, y + h + 2), (0, 0, 255), 2)
        label = f"s{g['string']}" + (f":{g['digit']}" if "digit" in g else "")
        cv2.putText(vis, label, (x - 2, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    cv2.imwrite(str(path), vis)


# ---------------------------------------------------------------- glyph clustering

def normalize_glyph(img):
    return cv2.resize(img, (20, 28), interpolation=cv2.INTER_AREA) > 127


def cluster_glyphs(all_glyphs, max_dist=0.12):
    """Group visually identical glyphs (same rendered font within a video).
    Returns cluster representative images; tags each glyph with cluster id.

    The threshold errs tight on purpose: a false SPLIT costs one extra
    flashcard to label; a false MERGE silently corrupts the tab (measured:
    8-vs-0 = 0.223, 8-vs-letter-B < 0.22 in the second test video)."""
    reps = []  # (normalized, rep_img)
    for g in all_glyphs:
        norm = normalize_glyph(g["img"])
        best, best_d = None, 1.0
        for ci, (rnorm, _) in enumerate(reps):
            d = float(np.mean(norm != rnorm))
            if d < best_d:
                best, best_d = ci, d
        if best is not None and best_d <= max_dist:
            g["cluster"] = best
        else:
            g["cluster"] = len(reps)
            reps.append((norm, g["img"]))
    return [img for _, img in reps]


# ---------------------------------------------------------------- assemble measures

def build_measures(section):
    """Glyphs -> ordered note events, split into measures at bar lines.
    Chord = glyphs at (nearly) the same x. Requires digits already assigned."""
    gap = section["gap"]
    inner_bars = [b for b in section["bar_xs"]
                  if 0.02 * section["roi"].shape[1] < b < 0.98 * section["roi"].shape[1]]
    boundaries = sorted(inner_bars) + [section["roi"].shape[1] + 1]

    measures = [{"notes": []} for _ in boundaries]
    i = 0
    glyphs = section["glyphs"]
    while i < len(glyphs):
        group = [glyphs[i]]
        while i + 1 < len(glyphs) and glyphs[i + 1]["cx"] - glyphs[i]["cx"] < 0.45 * gap:
            i += 1
            group.append(glyphs[i])
        mi = next(k for k, b in enumerate(boundaries) if group[0]["cx"] < b)
        notes = [{"string": g["string"], "fret": g.get("digit", -1)} for g in group]
        measures[mi]["notes"].append(notes[0] if len(notes) == 1 else {"chord": notes})
        i += 1
    return [m for m in measures if m["notes"]]


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("--debug-dir", required=True, help="annotated images + glyph flashcards go here")
    ap.add_argument("--ai", action="store_true", help="name digit clusters with one batched Gemini call")
    ap.add_argument("--label", action="append", default=[], metavar="CLUSTER=DIGIT",
                    help="verified digit for a cluster (e.g. --label 1=5); overrides AI")
    args = ap.parse_args()
    dbg = Path(args.debug_dir)
    dbg.mkdir(parents=True, exist_ok=True)

    print("[1/4] finding sections (crop-space change detection) ...")
    sections_raw = find_sections(args.video)
    print(f"      {len(sections_raw)} distinct tab sections")

    # merge repeats: tutorials often show each page more than once. Repeats are
    # free redundancy — two independent measurements of the same page must agree
    pages = []
    for ts, crop in sections_raw:
        small = cv2.cvtColor(cv2.resize(crop, (160, 40)), cv2.COLOR_BGR2GRAY)
        for p in pages:
            if cv2.absdiff(small, p["small"]).mean() < 8.0:
                p["obs"].append((ts, crop))
                break
        else:
            pages.append({"small": small, "obs": [(ts, crop)]})
    print(f"      {len(pages)} unique pages "
          f"({', '.join(str(len(p['obs'])) + ' obs' for p in pages)})")

    print("[2/4] measuring geometry (every observation of every page) ...")
    sections = []
    for pi, p in enumerate(pages):
        meas = []
        for ts, crop in p["obs"]:
            m = measure_section(crop)
            if m and "error" not in m:
                m["ts"] = ts
                meas.append(m)
            else:
                why = m["error"] if m else "no measurable strip"
                print(f"      page {pi + 1} obs @ {ts:6.1f}s: {why} — dropped")
        if not meas:
            continue
        counts = [len(m["glyphs"]) for m in meas]
        agree = len(set(counts)) == 1
        # keep the modal-count observation; disagreement is flagged, not hidden
        modal = max(set(counts), key=counts.count)
        chosen = next(m for m in meas if len(m["glyphs"]) == modal)
        chosen["consistent"] = agree
        chosen["obs_counts"] = counts
        sections.append(chosen)
        flag = "" if agree else f"  <-- OBSERVATIONS DISAGREE {counts}: verify this page"
        print(f"      page {pi + 1} @ {chosen['ts']:5.1f}s: 6 lines, "
              f"{len(chosen['bar_xs'])} bars, {modal} glyphs, {len(meas)} obs{flag}")

    print("[3/4] clustering glyphs across the song ...")
    all_glyphs = [g for s in sections for g in s["glyphs"]]
    reps = cluster_glyphs(all_glyphs)
    print(f"      {len(all_glyphs)} glyphs -> {len(reps)} unique shapes")
    for ci, rep in enumerate(reps):
        big = cv2.resize(rep, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(dbg / f"glyph_cluster_{ci}.png"), 255 - big)

    digits = {}
    if args.ai:
        print("[4/4] naming clusters (one batched flashcard call) ...")
        from m1_spike import call_gemini  # noqa: E402
        from google import genai
        from google.genai import types
        from dotenv import load_dotenv
        import os
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        parts = []
        for ci, rep in enumerate(reps):
            big = 255 - cv2.resize(rep, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
            ok, png = cv2.imencode(".png", big)
            parts.append(types.Part.from_bytes(data=png.tobytes(), mime_type="image/png"))
        parts.append(
            f"You are shown {len(reps)} images, each containing exactly one character "
            "from a guitar tab (a digit 0-24, occasionally a letter such as h/p/x). "
            "For image N reply with what it shows. Respond with ONLY a JSON object "
            'mapping image number (1-based, in the order given) to the character, e.g. {"1": "5"}.')
        resp = call_gemini(client, parts)
        text = (resp.text or "").strip().strip("`")
        text = text[4:] if text.startswith("json") else text
        digits = {int(k) - 1: v for k, v in json.loads(text).items()}
        print(f"      AI answers: { {k: digits[k] for k in sorted(digits)} }")
        print("      VERIFY these against the glyph_cluster_*.png flashcards before trusting.")
    else:
        print("[4/4] no AI naming (--ai not set)")

    for spec in args.label:  # human-verified labels always win
        k, v = spec.split("=")
        digits[int(k)] = v
    if args.label:
        print(f"      human labels applied: { {k: digits[k] for k in sorted(digits)} }")

    for g in all_glyphs:
        val = digits.get(g["cluster"], "-1")
        g["digit"] = int(val) if str(val).lstrip("-").isdigit() else str(val)
    # clusters labeled "x" are non-note symbols (rests, ornaments) — drop them
    for s in sections:
        s["glyphs"] = [g for g in s["glyphs"] if g["digit"] != "x"]

    from m1_spike import render_ascii  # noqa: E402
    song, page_dump = [], []
    for i, s in enumerate(sections, 1):
        annotate(s, dbg / f"page_{i}_annotated.png")
        measures = build_measures(s)
        song.extend(measures)
        page_dump.append({
            "page": i, "ts": s["ts"], "measures": measures,
            "ascii": render_ascii(measures),
            "consistent": s.get("consistent", True),
            "obs_glyph_counts": s.get("obs_counts", []),
            "annotated": f"page_{i}_annotated.png",
        })

    out = {"pages": page_dump, "measures": song,
           "clusters": {i: digits.get(i, "?") for i in range(len(reps))}}
    (dbg / "extraction.json").write_text(json.dumps(out, indent=2))
    print(f"\n{len(song)} measures across {len(sections)} pages -> {dbg / 'extraction.json'}")
    for p in page_dump:
        print(f"\n--- page {p['page']} @ {p['ts']:.1f}s ---")
        print(p["ascii"])
    print(f"\nannotated geometry images in {dbg}/ — verify visually.")


if __name__ == "__main__":
    main()
