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

SAMPLE_FPS = 2.0


# ---------------------------------------------------------------- tab band finder

def _thin_line_rows(mask, min_frac=0.75, max_thick=12):
    """Rows where marked pixels cover most of the width, in a band at most a
    few pixels tall — the shape of a drawn tab line. A fraction test (not an
    unbroken-run test) because compressed video breaks thin lines into
    segments. Thick bands (a white page, a dark background) fail the
    thinness check; short text fails the fraction check."""
    dilated = cv2.dilate(mask.astype(np.uint8), np.ones((3, 1), np.uint8))
    hits = dilated.mean(axis=1) > min_frac
    idx = np.flatnonzero(np.diff(np.concatenate(([0], hits.view(np.int8), [0]))))
    ys = []
    for s, e in zip(idx[::2], idx[1::2]):
        if e - s <= max_thick:
            ys.append(int((s + e) / 2))
    return ys


def _uniform_sextets(ys):
    """All windows of 6 candidate rows with even spacing, best (most even) first."""
    cands = []
    for i in range(len(ys) - 5):
        win = ys[i:i + 6]
        gaps = np.diff(win)
        if gaps.min() > 4 and gaps.max() / gaps.min() < 1.35:
            cands.append((float(np.std(gaps) / np.mean(gaps)), win))
    return [w for _, w in sorted(cands)]


def mask_playhead(bgr):
    """Erase the pink/magenta playback cursor some apps draw over the tab.
    In grayscale it would look like a bar line."""
    b, g, r = bgr[..., 0].astype(int), bgr[..., 1].astype(int), bgr[..., 2].astype(int)
    pink = (r - g > 45) & (b - g > 10) & (r > 100)
    out = bgr.copy()
    out[pink] = 0
    return out


def find_tab_band(frame):
    """Locate the 6-line tab in a full frame by its LINES, light or dark theme.
    Returns (crop, polarity) — polarity 'dark_ink' (black on white) or
    'light_ink' (white on black) — or None if no tab is visible."""
    clean = mask_playhead(frame)
    gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    # line darkness/brightness varies by app — sweep a few thresholds and
    # take the first that produces a valid, evenly spaced six-line pattern
    candidates = [("dark_ink", gray < 90), ("dark_ink", gray < 130),
                  ("dark_ink", gray < 170), ("light_ink", gray > 160),
                  ("light_ink", gray > 100)]
    for polarity, mask in candidates:
        wins = _uniform_sextets(_thin_line_rows(mask))
        if wins:
            win = wins[0]
            gap = (win[-1] - win[0]) / 5.0
            y0 = max(0, int(win[0] - 1.6 * gap))
            y1 = min(frame.shape[0], int(win[-1] + 1.6 * gap))
            crop = clean[y0:y1]
            crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            return crop, polarity
    return None, None


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

    samples = []  # every sampled frame that shows a tab: (ts, crop, polarity)
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            crop, polarity = find_tab_band(frame)
            if crop is not None:
                samples.append((frame_idx / video_fps, crop, polarity))
        frame_idx += 1
    cap.release()

    # Keep EVERY sampled frame that shows a tab. No cleverness here on
    # purpose: every earlier attempt to pre-select "interesting" frames
    # silently lost content on some video style. Downstream grouping works
    # on measured, verified note-ink overlap — redundant frames are cheap,
    # missing frames are not.
    return samples


# ---------------------------------------------------------------- geometry

def measure_section(crop, polarity="dark_ink"):
    """Measure one tab-strip crop. Returns dict with per-system line ys, bar
    xs, and glyph blobs — or None if the crop doesn't measure like a tab."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    if polarity == "dark_ink":
        # tighten to the white strip proper (crop has a little scene padding).
        # rows first; then columns measured ONLY within those rows. Background
        # that leaks in is handled downstream by the border-bar glyph filter.
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
        _, ink = cv2.threshold(roi, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        # light ink on dark, often a semi-transparent overlay: no white band
        # to tighten to — use the whole crop, ink = the BRIGHT pixels
        roi = gray
        _, ink = cv2.threshold(roi, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    H, W = roi.shape

    # candidate line rows: rows where ink spans much of the width. This picks
    # up real string lines AND impostors (box borders, rhythm-beam rows) —
    # the sextet test below separates them
    line_rows = (ink.mean(axis=1) > 0.45).astype(np.int8)
    idx = np.flatnonzero(np.diff(np.concatenate(([0], line_rows, [0]))))
    line_ys = [int((s + e) / 2) for s, e in zip(idx[::2], idx[1::2])]

    # a tab SYSTEM is 6 consecutive candidate rows with UNIFORM spacing;
    # borders and beam rows sit at irregular distances. Rank every plausible
    # window by spacing uniformity and take the most-uniform non-overlapping
    # ones — a box border one slightly-off gap away must lose to the true
    # sextet, so "first acceptable" is not good enough
    cands = []
    for i in range(len(line_ys) - 5):
        win = line_ys[i:i + 6]
        gaps = np.diff(win)
        if gaps.min() > 4 and gaps.max() / gaps.min() < 1.35:
            cands.append((float(np.std(gaps) / np.mean(gaps)), i, win))
    system_wins, used = [], set()
    for _, i, win in sorted(cands):
        if not (set(range(i, i + 6)) & used):
            system_wins.append(win)
            used.update(range(i, i + 6))
    system_wins.sort(key=lambda w: w[0])  # top-to-bottom = song order
    if not system_wins:
        return {"error": f"no uniform 6-line system among {len(line_ys)} line rows", "roi": roi}

    gap_med = float(np.median([np.diff(w).mean() for w in system_wins]))

    # erase lines and bars everywhere; what's left is glyph ink
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, W // 8), np.uint8))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                            np.ones((max(8, int(2.5 * gap_med)), 1), np.uint8))
    nonline = ink & ~horiz & ~vert
    # erasing a line cuts digits sitting on it in half. Restore line pixels
    # ONLY where glyph ink sits just above/below (a digit stroke crossing the
    # line) — a blind vertical bridge would fuse chord digits on adjacent
    # lines, which sit only a few px apart
    thick = max(3, int(round(0.12 * gap_med)))
    support = cv2.dilate(nonline, np.ones((2 * thick + 1, 1), np.uint8))
    glyph_ink = (nonline | (horiz & support)).astype(np.uint8)
    glyph_ink = cv2.morphologyEx(glyph_ink, cv2.MORPH_CLOSE, np.ones((5, 3), np.uint8))

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(glyph_ink, connectivity=8)
    raw = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        fill = area / max(w * h, 1)
        # plausible digit: digits run ~0.85 line-gaps tall; line-erasure debris
        # is much shorter and wide — reject anything under ~0.55 gaps.
        # area floor stays low: a "1" is a thin bar with little ink
        is_digit = (0.55 * gap_med < h < 1.8 * gap_med
                    and area >= 0.03 * gap_med ** 2 and w <= 2.5 * gap_med)
        # slur arc: wide, short, and HOLLOW — a thin curve fills little of its
        # box, while straight line-debris of the same size fills nearly all
        is_arc = (0.9 * gap_med < w < 3.5 * gap_med
                  and 0.12 * gap_med < h < 0.65 * gap_med
                  and fill < 0.45 and area >= 0.02 * gap_med ** 2)
        if not (is_digit or is_arc):
            # a slur arc that crosses a string line gets fused with restored
            # line pixels and comes out far too wide for any digit or arc
            # (measured: the Redbone 6-8 arc reads 4.2 gaps wide). Strip the
            # line rows and re-test the biggest piece: a real arc leaves its
            # hollow crown; straight line debris leaves nothing arc-shaped
            if fill < 0.45 and w > 3.0 * gap_med and h < 1.0 * gap_med:
                comp = ((labels[y:y + h, x:x + w] == i)
                        & (horiz[y:y + h, x:x + w] == 0)).astype(np.uint8)
                n2, lab2, st2, cen2 = cv2.connectedComponentsWithStats(comp, connectivity=8)
                # largest piece that still reads as an arc crown wins. The
                # piece fill bound is laxer than is_arc's (the close-morph
                # fattens a lone crown) — safe, the parent already proved
                # hollow, and line debris pieces run fill 0.5+ at 1-2px tall
                best = None
                for j in range(1, n2):
                    x2, y2, w2, h2, a2 = st2[j]
                    f2 = a2 / max(w2 * h2, 1)
                    if (0.9 * gap_med < w2 < 3.5 * gap_med
                            and 0.12 * gap_med < h2 < 0.65 * gap_med
                            and f2 <= 0.5 and a2 >= 0.02 * gap_med ** 2
                            and (best is None or a2 > st2[best][4])):
                        best = j
                if best is not None:
                    x2, y2, w2, h2, a2 = st2[best]
                    raw.append({
                        "cx": float(x + cen2[best][0]), "cy": float(y + cen2[best][1]),
                        "bbox": (int(x + x2), int(y + y2), int(w2), int(h2)),
                        "shape": "arc",
                        "img": ((lab2[y2:y2 + h2, x2:x2 + w2] == best) * 255).astype(np.uint8),
                    })
            continue
        cx, cy = centroids[i]
        raw.append({
            "cx": float(cx), "cy": float(cy), "bbox": (int(x), int(y), int(w), int(h)),
            "shape": "arc" if (is_arc and not is_digit) else "glyph",
            "img": (glyph_ink[y:y + h, x:x + w] * 255).astype(np.uint8),
        })

    systems = []
    for win in system_wins:
        top, bot = win[0], win[-1]
        gap = (bot - top) / 5.0
        # bar lines: columns whose ink spans (almost) the full line block
        col_span = ink[top:bot + 1].mean(axis=0)
        bar_cols = (col_span > 0.75).astype(np.int8)
        idx = np.flatnonzero(np.diff(np.concatenate(([0], bar_cols, [0]))))
        bar_xs = [int((s + e) / 2) for s, e in zip(idx[::2], idx[1::2])]
        merged = []  # merge doubled detections (thick end-bars read as two)
        for b in bar_xs:
            if merged and b - merged[-1] < 0.5 * gap:
                merged[-1] = (merged[-1] + b) // 2
            else:
                merged.append(b)
        bar_xs = merged

        # notes live ON this system's lines — text and rhythm notation outside
        # the line band belong to no system and are not notes. Arcs float
        # higher above their notes, so they get a wider band
        glyphs = [dict(g) for g in raw
                  if (top - (1.2 if g.get("shape") == "arc" else 0.6) * gap
                      < g["cy"] < bot + 0.6 * gap)]
        for g in glyphs:
            g["string"] = int(np.argmin([abs(g["cy"] - ly) for ly in win])) + 1
        # nothing outside the tab's own border bars is a note — but a bar only
        # counts as a border if it actually sits near an edge (a strip cut off
        # at the screen edge has no left border; its first bar is mid-song)
        if bar_xs and bar_xs[0] < 0.2 * W:
            glyphs = [g for g in glyphs if g["cx"] > bar_xs[0] - gap]
        if bar_xs and bar_xs[-1] > 0.8 * W:
            glyphs = [g for g in glyphs if g["cx"] < bar_xs[-1] + gap]
        glyphs.sort(key=lambda g: g["cx"])
        systems.append({"line_ys": win, "bar_xs": bar_xs, "glyphs": glyphs, "gap": gap})

    return {"roi": roi, "systems": systems, "glyph_ink": glyph_ink}


def section_glyphs(section):
    return [g for sys in section["systems"] for g in sys["glyphs"]]


def content_signature(section):
    """What music does this page show? A bag of (string, digit) pairs.
    Unordered on purpose: chord notes sit at nearly the same x, so their
    order can flip between screenshots of the same page."""
    return [(g["string"], str(g.get("digit", g["cluster"])))
            for g in section_glyphs(section)]


def merge_duplicate_neighbors(sections):
    """A scrolling app shows the same measures on more than one screenshot.
    If a page's content is almost the same as the page before it, they are the
    same music: keep one copy (the more complete reading) and flag any
    disagreement. Only NEIGHBORS are compared — a song may genuinely repeat a
    section later, and real repeats must not be deleted.

    Run this AFTER digit labels and junk removal: clutter (clef letters,
    rests) differs between screenshots even when the music is identical."""
    from collections import Counter
    merged = []
    for s in sections:
        if merged:
            prev = merged[-1]
            ca, cb = Counter(content_signature(prev)), Counter(content_signature(s))
            inter = sum((ca & cb).values())
            union = sum((ca | cb).values())
            ratio = inter / union if union else 0.0
            if ratio > 0.8:
                a, b = len(section_glyphs(prev)), len(section_glyphs(s))
                keep = prev if a >= b else s
                keep["ts"] = min(prev["ts"], s["ts"])
                keep["dup_counts"] = [a, b]
                keep["consistent"] = keep.get("consistent", True) and a == b
                merged[-1] = keep
                flag = "" if a == b else f" — readings disagree ({a} vs {b} marks): verify"
                print(f"      merged two screenshots of the same music "
                      f"(match {ratio:.0%}); kept the fuller one{flag}")
                continue
        merged.append(s)
    return merged


def annotate(section, path: Path):
    """Draw measured geometry onto the ROI for visual verification."""
    vis = cv2.cvtColor(section["roi"], cv2.COLOR_GRAY2BGR)
    for sys_ in section.get("systems", []):
        top, bot = sys_["line_ys"][0], sys_["line_ys"][-1]
        for ly in sys_["line_ys"]:
            cv2.line(vis, (0, ly), (vis.shape[1], ly), (255, 160, 0), 1)
        for bx in sys_["bar_xs"]:
            cv2.line(vis, (bx, max(0, top - 10)), (bx, min(vis.shape[0], bot + 10)), (0, 180, 0), 2)
        for g in sys_["glyphs"]:
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


# ---------------------------------------------------------------- scroll stitching

def glyph_shift(sa, sb, probe_w=1024, probe_h=160):
    """How far did the tab content move between two measured sections?
    Compares NOTE INK only — the tab lines look identical under any shift and
    would drag the estimate toward zero. Returns (dx in pixels, confidence)."""
    fa = cv2.resize(sa["glyph_ink"].astype(np.float32) * 255, (probe_w, probe_h))
    fb = cv2.resize(sb["glyph_ink"].astype(np.float32) * 255, (probe_w, probe_h))
    (dx, _), conf = cv2.phaseCorrelate(fa, fb)
    scale = sa["roi"].shape[1] / probe_w
    return dx * scale, conf


def overlap_score(sa, sb, dx):
    """Do two sections really show the same tab shifted by dx? Lay the note
    ink of one over the other at that shift and measure agreement (0..1).
    Ink is thickened first so a couple of pixels of misalignment don't zero
    out thin digit strokes."""
    kernel = np.ones((5, 5), np.uint8)
    A = cv2.dilate(sa["glyph_ink"], kernel)
    B = cv2.dilate(sb["glyph_ink"], kernel)
    h = min(A.shape[0], B.shape[0])
    A, B = A[:h] > 0, B[:h] > 0
    W = min(A.shape[1], B.shape[1])
    d = int(round(dx))
    lo, hi = max(0, -d), W - max(0, d)
    if hi - lo < 200:
        return 0.0
    Ao = A[:, lo:hi]
    Bo = B[:, lo + d:hi + d]
    union = (Ao | Bo).sum()
    return float((Ao & Bo).sum() / union) if union else 0.0


def link_sections(sa, sb):
    """Best (score, dx) linking two sections as 'same tab, shifted sideways'.

    Phase correlation is circular: a big leftward jump on a W-wide window
    aliases to a small rightward dx. Try the raw estimate and its wrapped
    twins, then refine locally for the best ink agreement."""
    dx0, _ = glyph_shift(sa, sb)
    W = min(sa["glyph_ink"].shape[1], sb["glyph_ink"].shape[1])
    best_score, best_dx = 0.0, 0.0
    for cand in (dx0, dx0 - W, dx0 + W):
        if abs(cand) > 0.95 * W:
            continue
        for d in np.arange(cand - 42, cand + 43, 6):
            s = overlap_score(sa, sb, d)
            if s > best_score:
                best_score, best_dx = s, float(d)
    return best_score, best_dx


def stitch_scroll(sections, offsets):
    """Combine overlapping windows of one horizontally moving tab into a
    single long virtual page.

    Every note lands on one global x-axis (window x + that window's offset);
    sightings of the same note (same string, same global spot) merge, with a
    vote on the note's shape. Returns one section dict."""
    rois = [s["roi"] for s in sections]
    h = min(r.shape[0] for r in rois)
    w = min(r.shape[1] for r in rois)

    gap = float(np.median([s["systems"][0]["gap"] for s in sections]))

    # collect note sightings in global coordinates; skip window edges where
    # digits may be cut in half
    obs = []
    for s, off in zip(sections, offsets):
        W = s["roi"].shape[1]
        for g in s["systems"][0]["glyphs"]:
            if 0.03 * W < g["cx"] < 0.97 * W:
                o = dict(g)
                o["gx"] = g["cx"] + off
                o["off"] = off
                obs.append(o)

    # merge sightings: per string, sort by global x, group near-identical
    # spots. The radius is TIGHT (0.25 gap): stitched sightings of one note
    # land within a few pixels, while a parenthesis or the second digit of
    # "11" sits about half a gap away and must never fuse in
    from collections import Counter
    merged = []
    for string in range(1, 7):
        row = sorted([o for o in obs if o["string"] == string], key=lambda o: o["gx"])
        i = 0
        while i < len(row):
            group = [row[i]]
            while i + 1 < len(row) and row[i + 1]["gx"] - row[i]["gx"] < 0.25 * gap:
                i += 1
                group.append(row[i])
            best_cluster = Counter(o["cluster"] for o in group).most_common(1)[0][0]
            rep = next(o for o in group if o["cluster"] == best_cluster)
            note = dict(rep)
            note["cx"] = float(np.mean([o["gx"] for o in group]))
            x, y, bw, bh = rep["bbox"]
            note["bbox"] = (int(x + rep["off"]), y, bw, bh)
            note["sightings"] = len(group)
            merged.append(note)
            i += 1
    merged.sort(key=lambda g: g["cx"])

    # merge bar-line sightings the same way; require 2+ sightings (a one-off
    # vertical artifact is not a bar)
    bar_obs = sorted(b + off for s, off in zip(sections, offsets)
                     for b in s["systems"][0]["bar_xs"]
                     if 0.03 * s["roi"].shape[1] < b < 0.97 * s["roi"].shape[1])
    bars = []
    i = 0
    while i < len(bar_obs):
        j = i
        while j + 1 < len(bar_obs) and bar_obs[j + 1] - bar_obs[j] < 0.5 * gap:
            j += 1
        if j - i + 1 >= 2:
            bars.append(int(np.mean(bar_obs[i:j + 1])))
        i = j + 1

    # panorama of all windows for visual verification
    total_w = int(max(offsets) + w) + 10
    pano = np.zeros((h, total_w), np.uint8)
    for r, off in zip(rois, offsets):
        x0 = int(off)
        pano[:, x0:x0 + w] = np.maximum(pano[:, x0:x0 + w], r[:h, :w])

    line_ys = sections[0]["systems"][0]["line_ys"]
    return {
        "ts": sections[0]["ts"], "roi": pano, "consistent": True,
        "n_windows": len(sections),
        "systems": [{"line_ys": line_ys, "bar_xs": bars,
                     "glyphs": merged, "gap": gap}],
    }


# ---------------------------------------------------------------- assemble measures

def join_two_digit_frets(glyphs, gap):
    """'13' is drawn as a 1 and a 3 almost touching on the same string —
    join such pairs into one note. Only 1 or 2 can lead (frets stop at 24),
    and the two shapes must be far closer than separately played notes."""
    out = []
    i = 0
    glyphs = sorted(glyphs, key=lambda g: (g["string"], g["cx"]))
    while i < len(glyphs):
        a = glyphs[i]
        b = glyphs[i + 1] if i + 1 < len(glyphs) else None
        if (b and a["string"] == b["string"]
                and isinstance(a["digit"], int) and isinstance(b["digit"], int)
                and a["digit"] in (1, 2)
                and b["cx"] - a["cx"] < 0.75 * gap
                and int(f"{a['digit']}{b['digit']}") <= 24):
            joined = dict(a)
            joined["digit"] = int(f"{a['digit']}{b['digit']}")
            joined["cx"] = (a["cx"] + b["cx"]) / 2
            out.append(joined)
            i += 2
        else:
            out.append(a)
            i += 1
    out.sort(key=lambda g: g["cx"])
    return out


def mark_ghosts(glyphs, gap):
    """A digit wrapped in parentheses is a ghost (optional) note. The parens
    are their own shapes, labeled "(" and ")". A note with "(" just to its
    left and ")" just to its right, on the same string, is marked ghost —
    and is rendered with its parentheses, e.g. (8)."""
    notes = [g for g in glyphs if isinstance(g["digit"], int)]
    opens = [g for g in glyphs if g["digit"] == "("]
    closes = [g for g in glyphs if g["digit"] == ")"]
    for n in notes:
        has_open = any(o["string"] == n["string"] and 0 < n["cx"] - o["cx"] < 0.9 * gap
                       for o in opens)
        has_close = any(c["string"] == n["string"] and 0 < c["cx"] - n["cx"] < 0.9 * gap
                        for c in closes)
        if has_open and has_close:
            n["ghost"] = True
    return glyphs


def attach_connectors(glyphs, gap):
    """Slur arcs and slide slashes sit between two notes on a string. Attach
    each to its neighbors and record how a guitarist writes it: h (hammer-on,
    pitch up) / p (pull-off, pitch down) for a slur; / or \\ for a slide.
    Returns notes only — connectors are consumed."""
    notes = [g for g in glyphs if isinstance(g["digit"], int)]

    def bracketing_pair(c, strings):
        """Nearest note pair (left, right) around the connector's x, searched
        on the given strings; the tightest, most centered pair wins."""
        best = None
        for s in strings:
            row = sorted((n for n in notes if n["string"] == s), key=lambda n: n["cx"])
            left = max((n for n in row if n["cx"] < c["cx"] + 0.3 * gap),
                       key=lambda n: n["cx"], default=None)
            right = min((n for n in row if left is not None and n["cx"] > left["cx"]),
                        key=lambda n: n["cx"], default=None)
            if left is None or right is None:
                continue
            if right["cx"] - left["cx"] > c["bbox"][2] + 2.5 * gap:
                continue  # pair far wider than the mark — not what it connects
            score = abs((left["cx"] + right["cx"]) / 2 - c["cx"]) \
                + 0.5 * gap * abs(s - c["string"])
            if best is None or score < best[0]:
                best = (score, left, right)
        return (best[1], best[2]) if best else (None, None)

    for c in (g for g in glyphs
              if g["digit"] == "arc" or str(g["digit"]).startswith("slide")):
        if c["digit"] == "arc":
            # an arc floats above its notes — its nearest line may be one off
            strings = [s for s in (c["string"], c["string"] + 1, c["string"] - 1)
                       if 1 <= s <= 6]
        else:
            strings = [c["string"]]
        left, right = bracketing_pair(c, strings)
        if left is not None and right is not None:
            up = right["digit"] > left["digit"]
            left["legato_next"] = ("h" if up else "p") if c["digit"] == "arc" \
                else ("/" if up else "\\")
            continue
        # a slide with no note after it (an 18\ sliding out to nothing):
        # the slash shape itself says which way it points
        if c["digit"] in ("slide/", "slide\\"):
            row = [n for n in notes if n["string"] == c["string"]]
            left = max((n for n in row if n["cx"] < c["cx"] + 0.3 * gap),
                       key=lambda n: n["cx"], default=None)
            if left is not None and c["cx"] - left["cx"] < 2.0 * gap:
                left["legato_next"] = c["digit"][-1]
    return notes


def build_measures(system, width):
    """Glyphs of one system -> ordered note events, split into measures at bar
    lines. Chord = glyphs at (nearly) the same x. Requires digits assigned."""
    gap = system["gap"]
    inner_bars = [b for b in system["bar_xs"] if 0.02 * width < b < 0.98 * width]
    boundaries = sorted(inner_bars) + [width + 1]

    measures = [{"notes": []} for _ in boundaries]
    i = 0
    glyphs = attach_connectors(mark_ghosts(join_two_digit_frets(system["glyphs"], gap), gap), gap)
    while i < len(glyphs):
        group = [glyphs[i]]
        while i + 1 < len(glyphs) and glyphs[i + 1]["cx"] - glyphs[i]["cx"] < 0.45 * gap:
            i += 1
            group.append(glyphs[i])
        mi = next(k for k, b in enumerate(boundaries) if group[0]["cx"] < b)
        notes = [{"string": g["string"], "fret": g.get("digit", -1),
                  **({"ghost": True} if g.get("ghost") else {}),
                  **({"legato_next": g["legato_next"]} if g.get("legato_next") else {})}
                 for g in group]
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

    print("[1/4] finding tab screens ...")
    sections_raw = find_sections(args.video)
    print(f"      {len(sections_raw)} sampled frames show a tab")

    print("[2/4] measuring geometry (every frame) ...")
    measured = []
    dropped = 0
    for ts, crop, pol in sections_raw:
        m = measure_section(crop, pol)
        if m and "error" not in m:
            m["ts"] = ts
            measured.append(m)
        else:
            dropped += 1
    print(f"      {len(measured)} frames measured"
          + (f", {dropped} dropped (blur/transition)" if dropped else ""))

    # group repeat sightings of the SAME page: verified by laying the note
    # ink of one screen over the other at (near-)zero shift. Tutorials often
    # show a page more than once — repeats are free redundancy, and two
    # measurements of one page must agree. Lookback 2 catches the common
    # A-B-A-B teaching pattern without ever merging distant real repeats.
    groups = []
    for m in measured:
        placed = False
        for g in groups[-2:]:
            score, dx = link_sections(g[0], m)
            gap = m["systems"][0]["gap"]
            if abs(dx) < 0.4 * gap and score > 0.45:
                g.append(m)
                placed = True
                break
        if not placed:
            groups.append([m])

    sections = []
    for gi, g in enumerate(groups):
        counts = [len(section_glyphs(x)) for x in g]
        agree = len(set(counts)) == 1
        # keep the modal-count observation; disagreement is flagged, not hidden
        modal = max(set(counts), key=counts.count)
        chosen = next(x for x in g if len(section_glyphs(x)) == modal)
        chosen["consistent"] = agree
        chosen["obs_counts"] = counts
        sections.append(chosen)
        flag = "" if agree else f"  <-- OBSERVATIONS DISAGREE {counts}: verify this page"
        print(f"      page {gi + 1} @ {chosen['ts']:5.1f}s: "
              f"{len(chosen['systems'])} system(s), {modal} glyphs, {len(g)} obs{flag}")

    print("[3/4] clustering glyphs across the song ...")
    all_glyphs = [g for s in sections for g in section_glyphs(s)]
    reps = cluster_glyphs(all_glyphs)
    print(f"      {len(all_glyphs)} glyphs -> {len(reps)} unique shapes")

    # chain neighboring sections that are the same tab shifted sideways
    # (a scrolling or jumping tab); unrelated pages stay separate because
    # their note ink does not line up at any shift
    if len(sections) > 1 and all(len(s["systems"]) == 1 for s in sections):
        links = [link_sections(a, b) for a, b in zip(sections, sections[1:])]
        # an app that scrolls in jumps uses the SAME jump size every time —
        # a weak link whose shift matches the established jump is still real
        # (its overlap region just happened to hold few notes)
        strong_dx = [dx for sc, dx in links if sc > 0.3 and abs(dx) > 100]
        med = float(np.median(strong_dx)) if strong_dx else None
        chains = [[(sections[0], 0.0)]]
        for (score, dx), cur_s in zip(links, sections[1:]):
            ok = score > 0.3
            if not ok and med is not None and score > 0.12 \
                    and abs(dx - med) < 0.12 * abs(med):
                ok = True
                print(f"      accepted a weak link (score {score:.2f}) — its "
                      f"shift {dx:.0f} matches the app's usual jump {med:.0f}")
            if ok:
                chains[-1].append((cur_s, chains[-1][-1][1] - dx))
            else:
                chains.append([(cur_s, 0.0)])
        if any(len(ch) > 1 for ch in chains):
            new_sections = []
            for ch in chains:
                if len(ch) == 1:
                    new_sections.append(ch[0][0])
                    continue
                secs = [s for s, _ in ch]
                offs = [o for _, o in ch]
                base = min(offs)
                st = stitch_scroll(secs, [o - base for o in offs])
                print(f"      chained {len(secs)} windows of one moving tab "
                      f"into a single page ({len(section_glyphs(st))} merged notes)")
                new_sections.append(st)
            sections = new_sections
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

    for s in sections:
        for g in section_glyphs(s):
            val = digits.get(g["cluster"], "-1")
            g["digit"] = int(val) if str(val).lstrip("-").isdigit() else str(val)
    # clusters labeled "x" are non-note symbols (rests, ornaments) — drop them
    for s in sections:
        for sys_ in s["systems"]:
            sys_["glyphs"] = [g for g in sys_["glyphs"] if g["digit"] != "x"]

    # now that clutter is gone and digits are named, spot duplicate pages
    sections = merge_duplicate_neighbors(sections)

    from m1_spike import render_ascii  # noqa: E402
    song, page_dump = [], []
    for i, s in enumerate(sections, 1):
        annotate(s, dbg / f"page_{i}_annotated.png")
        measures = []
        for sys_ in s["systems"]:  # top-to-bottom = song order within a screen
            measures.extend(build_measures(sys_, s["roi"].shape[1]))
        song.extend(measures)
        page_dump.append({
            "page": i, "ts": s["ts"], "measures": measures,
            "ascii": render_ascii(measures),
            "consistent": s.get("consistent", True),
            "obs_glyph_counts": s.get("obs_counts", []),
            "dup_counts": s.get("dup_counts", []),
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
