# Project status & next steps

Last updated: 2026-07-04. Read `PRD.md` for goals and decisions; this file is
where we track progress between sessions. Plain English, always.

## Where the project stands

**The extraction pipeline works on three very different video styles.**
One pipeline (`pipeline/extract_cv.py`) turns a screen-recorded guitar tutorial
into tab data:

| Video | Style | Result |
|---|---|---|
| Cannock Chase (IG Reel) | white tab strip, page flips, each page shown twice | 4 pages, 8 even measures (junk note + doubled bar fixed 2026-07-06) |
| Capo-6 song (tab app) | full-screen white app, scroll-jumps, clutter (clef, rests, time sig) | 2 pages, 4 measures — dense ones are real 16th-note picking, correct |
| Redbone (IG Reel) | white-on-black overlay, jump-scrolls sideways, legato notation | 1 stitched page, 8 measures (3 missed bars recovered 2026-07-06) — QA pending |

**How it works, in one paragraph:** sample the video ~2×/second; find the tab
on each frame by its six evenly spaced lines (any color scheme); measure every
digit's exact position with pixel math (no AI decides positions); group
identical shapes and have a human name each shape once from "flashcards";
merge repeat sightings of the same page (verified by overlaying note ink);
stitch sideways-moving tabs onto one long timeline (measured shifts, wrap-aware,
weak links accepted when they match the app's usual jump); every note is seen
several times and voted on.

**Features working:** digits; chords; measures; two-digit frets (11–24); ghost
notes rendered with parens `(8)`; slides `5/6`, `18\` (direction from the slash
shape when there's no landing note); slur arcs as `7h9` / `p` — including arcs
that cross a string line (fixed 2026-07-04: those came out fused with line
pixels, too wide to be recognized; a rescue step now strips the line rows and
keeps the arc's crown); playhead-line removal; junk rejection (clef letters,
rests, text, rhythm marks).

**Hard-won lessons (see PRD §4 for details):**
- Vision-LLM reading of tabs confabulates — positions must be measured, not
  guessed. AI is only OK at naming isolated glyphs, and even that is verified.
- Never pre-select "interesting" frames — keep everything, group by measurement.
- Cluster label numbers shuffle between runs — re-check flashcards after any
  pipeline change (bit us 3×).

## Working label sets (so we don't re-derive them)

- Video 1 `ScreenRecording_07-03-2026 17-10-24_1.MP4` (re-labeled
  2026-07-06: the border fix dropped a background junk glyph that was a
  cluster of its own, so indices shifted — old set is stale):
  `0=0 1=5 2=5 3=0 4=4 5=3 6=0 7=x 8=0`
- Video 2 `ScreenRecording_07-03-2026 18-15-36_1.MP4`:
  `0=x 1=0 2=8 3=7 4=x 5=5 6=3 7=1 8=2 9=x 10=x 11=4`
- Video 3 `ScreenRecording_07-03-2026 23-12-48_1.MP4` (re-labeled 2026-07-04
  after the arc fix added a cluster and shifted indices — old sets are stale):
  `0=5 '1=slide/' 2=6 3=9 4=7 5=8 6=arc '7=(' '8=)' 9=x 10=x '11=slide/' 12=1 13=3 14=4 '15=slide\' 16=6 17=arc`

Run: `.venv/bin/python pipeline/extract_cv.py <video> --debug-dir <dir> --label ...`
(Labels are only valid for the pipeline version they were made on — re-check
flashcards if the code changed.)

## QA pages (claude.ai artifacts)

- Cannock Chase: https://claude.ai/code/artifact/be584106-b6be-4dcf-96fe-ca9d29e5587a
- Capo-6 song: https://claude.ai/code/artifact/bed73042-3189-4dd0-b1ce-4076928e9831
- Redbone: https://claude.ai/code/artifact/7a9aab48-4352-4e90-83d8-94dd2c29448b
- Page-builder scripts now live in `pipeline/qa/` (moved 2026-07-04). The
  Redbone one takes the debug dir as an argument:
  `pipeline/qa/build_qa_video3.py <debug-dir> -o page.html`

## Done 2026-07-04

- **Songs saved to `data/songs/`** (`cannock-chase`, `capo-6-song`, `redbone`)
  plus `index.json` for the future website. New script `pipeline/save_song.py`
  turns any run's `extraction.json` into a song file. All marked `qa: draft`
  ("Capo 6 Song" is a placeholder title — ask user for the real one).
- **Missing-arc bug found and fixed.** User confirmed the arc over the 6-8
  pair in Redbone measure 1 was absent. Cause: that arc crosses a string
  line; line-pixel restore fused it into a blob 4.2 gaps wide — too wide for
  both the digit and the arc test, so it was silently dropped. Fix: a rescue
  step strips line rows from wide hollow rejects and keeps the arc crown.
  Redbone now shows `6h8` in measures 1 and 4 (matches the video's "H"
  marks); videos 1 and 2 re-ran byte-identical; QA page updated.

## Done 2026-07-06 (evening) — "Piece C": consistent measures + metadata

- **Bar-line sanity pass** (`sanitize_bars`): measures in one video are
  drawn near-uniform in width, so width outliers reveal bar mistakes.
  Stitched bars seen only once are kept if they fit the width grid; a
  bar carving a sliver is removed; clean-multiple spans get bars added
  in note-free gaps. All repairs flagged (measure `suspect`/`boundary`),
  printed, and drawn in color on overlays. `flag_repeats` marks measure
  runs duplicating earlier ones (`repeat_of`) — flagged, never deleted.
- **Border fix:** a bar is a border when the string lines stop beyond it
  (was: only near frame edge) — kills background-scene junk glyphs.
- **Results (verified by eye + note-for-note):** Cannock 9→8 even
  measures (one junk note gone, labels shifted, see above); Redbone 5→8
  measures with repeat pass flagged; Capo-6 untouched — its 16-event
  measures are genuine 16th-note picking. NOTE: a time signature was
  NOT needed for any of this; events ≠ beats without rhythm data.
- **App:** ⚠ check / repeat? markers on flagged measures; measure sheet
  gains Merge-with-next, Split (tap where the bar belongs), Looks right
  (clears flags); Song info dialog (title/artist/capo/tuning/time sig)
  replaces Rename. All click-tested against the mock API.
- **`pipeline/read_metadata.py`:** one Gemini call reads on-screen text
  (title/artist/capo/tuning/time-sig) and prints save_song flags for
  human confirmation; `save_song.py --time-sig` added. Tested: found
  "Capo 6" on video 2 and "Redbone / Childish Gambino" on video 3.

## Next steps, in priority order

1. **User QA of Redbone** (waiting on user) — the 6-8 arc is now in; check
   the rest of the arcs and any wrong/missing notes.
2. **M3 v1 BUILT (2026-07-06) — `web/` practice app.** Static, no build
   step: song list; tab view with big fret numbers, REAL drawn arcs with
   h/p riding the curve (user requirement), slanted slide strokes, ghost
   parens; font size stepper; edit mode (tap a note → fret/string/mark/
   ghost, add/delete note); rename, delete + restore. Edits save as local
   drafts in the phone browser (localStorage) overlaying the committed
   JSON; "Download JSON" exports a corrected file to commit. Verified:
   all three songs rendered at phone width; edit/rename/revert/delete/
   restore click-tested (Playwright + system Chrome).
   Run locally: `python3 -m http.server` from repo root → open `/web/`.
   **2026-07-06 later: Pieces A + B of the approved plan are BUILT:**
   - A — immediate saves: Settings takes owner/repo/fine-grained token;
     edits auto-commit through the GitHub Contents API ~4 s after you
     stop editing (index.json kept in sync); topbar chip shows saving/
     saved/offline-will-retry; drafts flush on app start and when back
     online; delete = restorable `archived` flag. Verified end-to-end
     against a local mock of the Contents API.
   - B — add notes anywhere: in edit mode every empty spot shows a faint
     `+` (empty strings of an event = chord-building; gaps between
     events, measure ends, empty measures = insert). Bar-line tap opens
     measure ops (add measure after / delete measure). Emptied measures
     survive. All flows click-tested; data round-trips byte-identical.
   **LIVE (2026-07-06):** user authorized the push; the site is at
   https://apramz74.github.io/guitar-tabs/web/ (public repo
   apramz74/guitar-tabs, Pages from main root). Real-repo saving
   verified end-to-end from the live site (edit → commit → revert).
   Remaining user setup: create a fine-grained PAT (Contents RW on just
   this repo) and paste it into the app's Settings on the phone.
   - Video intake ("submit video for analysis"): still not built —
     next major piece, as a Mac-local import app wrapping the pipeline.
3. **Label-by-shape** (kills the fragile cluster-index labels): store labeled
   glyph images per video; match new clusters to stored shapes by the same
   distance metric. Removes relabel-after-every-change pain.
4. **Capo / tuning capture** (user deferred): "Capo 2", "Capo 6", "Standard
   Tuning" are on screen; read them into song metadata. Vision AI on a text
   crop is acceptable here (it's text, and human-verifiable).
5. **Small opens:** the 5/6 pair has both a slide and an arc in the
   video but we keep only the slide mark. (The video-1 9-vs-8 split was
   fixed 2026-07-06 by the bar sanity pass.)

## Deferred / not started

- IG-link fetching (PRD M2) — user currently screen-records manually; fine.
- Timing/rhythm, chord names (PRD non-goals for now).
- Correction UI (PRD M4) — flashcards + QA pages cover this for now.

## Working agreements

- Plain English in all explanations and reports (user is a PM).
- Human QA against source frames is the only ground truth — AI grading of
  extraction quality has been wrong before.
- Verify every pipeline change visually (annotated overlays) and rerun all
  three videos before calling it done.
- Commit at each verified milestone.
