# PRD: guitar-tabs

*Turn guitar tutorial videos into a phone-first, practice-ready tab library.*

## 1. Problem

Practicing a song from an Instagram Reel tutorial means scrubbing back and forth
and pausing at every key frame to read the tab. That's tedious and kills practice
flow. This tool extracts the tab notation once, so you can pull up a clean tab on
your phone and practice — instead of re-watching the video every time.

## 2. North star

**Open the song on your phone → start practicing in seconds → barely touch the
device for the rest of the session.**

The user is happy to invest a *small* amount of setup time per song (importing,
and correcting extraction errors) in exchange for a frictionless practice
experience forever after. Optimize the practice moment ruthlessly; setup can be a
little manual.

## 3. Users & scope

- **User:** Just you. No accounts, no sharing, no multi-user concerns.
- **Non-goals (out for now):** public product, other people's libraries,
  timing/rhythm extraction, chord detection, video-synced playback, native
  mobile app.

## 4. Core flow

```
IG link (or local file) → get video → sample frames → crop tab strip → diff CROPS → CV geometry → glyph digit ID → song JSON → viewer
                          [swappable]   [~2 fps]      [row-projection,  [change detect  [lines, blobs,  [template match      (data/)
                                                       every frame]      in crop space]  order, bars]    + verified AI]
```

Change detection runs on the cropped tab strip, not the full frame (PM
feedback, 2026-07-03): full-frame diffing both over-fires on background motion
and — worse — can silently *miss* a section when a small tab change is drowned
out by a calm frame. In crop space, every compared pixel is tab.

**M1 learnings (static-tab case, 2026-07-03).**
1. **Crop before reading** (holds). The tab strip is ~10% of a phone frame;
   row-projection (band of rows dominated by one long white run) finds it
   reliably; nothing reads the full frame well.
2. **Batch, never per-frame** (holds for any AI usage). Free-tier 429s
   regularly lost whole sections in per-frame calls; one request per song is
   the only quota-viable shape.
3. **Vision LLMs cannot be trusted with tab GEOMETRY** (the pivot). User QA
   found substantive errors in all 4 sections of the best run — including
   confabulated-but-plausible patterns where the model composed a fingerpicking
   pattern instead of reading the frame. Root cause: VLMs are weak at fine
   spatial binding (digit→line, digit→order) and fill ambiguity from language
   priors. Digits themselves are detected reliably. Therefore: **OpenCV owns
   all geometry deterministically** (string lines, digit-blob x/y, ordering,
   measure boundaries); a model or template matcher only answers "which digit
   is this glyph?" — hallucinated positions become structurally impossible.
4. **"Glyph ID is reliable" is a hypothesis, not a fact.** It gets a dedicated
   test (flashcard-read every glyph, human-verify against the crops) before
   anything depends on it. Fallback that removes AI entirely: within one video
   the tab font is uniform, so cluster identical glyphs and resolve each
   cluster once (template match, or ~5 human taps per song). Standing
   principle after M1: **nothing enters the tab file that wasn't measured
   deterministically or verified by human eyes.**

## 5. Key decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| **Input** | IG link, with **manual file fallback** | Convenience, but a broken scraper must never block practice. IG download is ToS-violating + fragile; personal use keeps legal risk low. |
| **Extraction** | Vision model on deduplicated key frames | Fastest path to feasibility; handles varied tab styles without training. |
| **Vision backend** | **Gemini API free tier (confirmed default).** Backend kept pluggable so Claude or a local model can be swapped in for accuracy comparison | Genuinely free at personal scale, strong vision. Pluggability preserves the option to trade cents for accuracy later. |
| **Output (v1)** | Fret + string numbers only, **as structured note events** (see §6) | Timing/chords deferred. Structure (not a text blob) lets the phone viewer re-flow the tab to screen width. |
| **Viewer** | **Phone-first**, plain scrollable tab | Matches the north star. Big readable text, one-handed, minimal interaction during practice. |
| **Accuracy (v1)** | Draft quality, accepted for now | Prove raw extraction first. Per-song correction is *welcomed* by the user, so a review step (M4) aligns with the core value prop rather than fighting it. |
| **Hosting** | GitHub Pages (static viewer reads committed JSON) | Free, simple. Pipeline runs locally; you commit the resulting tabs. |
| **Pipeline stack** | Python (ffmpeg, opencv, `google-genai` SDK) | Best video/vision ecosystem. |

## 6. Data model (v1)

One JSON file per song in `data/songs/`. Sketch:

```json
{
  "title": "Song Name",
  "source": "https://instagram.com/reel/...",
  "tuning": "EADGBE",
  "capo": 0,
  "measures": [
    { "notes": [ { "string": 6, "fret": 3 }, { "string": 5, "fret": 2 } ] }
  ]
}
```

- Notes are **ordered events**, grouped into measures when the source shows bar
  lines (a single measure if it doesn't). Simultaneous notes (chords) share an
  event: `{ "strings": [{...},{...}] }` — exact shape to be settled in M2.
- The viewer renders classic ASCII-style tab from this structure, re-flowed to
  the phone's screen width. A text blob can't do that; structure can.

## 7. Vision backend cost note

- **Gemini API (default):** genuinely **free tier** with generous daily limits;
  strong vision. Key from Google AI Studio, stored in `.env` (gitignored).
- **Claude / OpenAI vision:** paid per call — cents per song at this scale, best
  accuracy. Optional swap if Gemini's accuracy disappoints.
- **Local model** (Qwen2-VL / Llama vision via Ollama): free, private, zero
  marginal cost; weaker on messy OCR-style reading. Fallback if rate limits bite.
- `detect_tabs` treats the backend as pluggable; comparisons run on identical
  frames so accuracy differences are attributable to the model.

## 8. Milestones

1. **M1 — Feasibility spike (do first):** local video file → key frames → Gemini
   reads → print raw tab. Test on **3–5 real tutorials spanning styles**
   (static tab, scrolling tab, fretboard diagram).
   **Success criteria:** on at least one static-tab and one scrolling-tab video,
   the printed tab is recognizable as the song — right notes in the right order
   for a clear majority of measures, with duplicated measures from overlapping
   frames mostly merged. If no style meets that bar, stop and rethink before
   building anything else. No UI, no polish.
   **Status: vision-LLM-only reading FAILED** (2026-07-03, "Cannock Chase" by
   jmu.sikk): user QA found real errors in all 4 sections, including
   confabulated patterns. Pipeline mechanics (key frames, crop, dedupe,
   batching) validated; reading accuracy did not meet the bar. Per this
   milestone's stop rule, extraction pivots to hybrid CV-geometry + glyph ID
   (see §4) before any further building. Also caution: AI-graded QA understated
   the errors — human QA against source frames is the only ground truth.
   **Still open: hybrid extractor on this video; scrolling-tab and other styles.**
2. **M2 — Pipeline + JSON:** harden M1 into scripts that write
   `data/songs/*.json` per §6. Add IG-link fetcher with file fallback.
3. **M3 — Phone-first viewer:** library index + big scrollable tab, re-flowed to
   screen width, optimized for one-handed use. Deploy to GitHub Pages.
4. **M4 (deferred, but aligned) — Reliability & low-touch practice:** per-song
   review/correction screen; practice-time conveniences (auto-scroll or
   tap-to-advance) that reduce device interaction. Prioritized after M1 reveals
   real output quality.

## 9. Known risks

- **Extraction quality is the whole gamble.** M1 exists to de-risk this before
  building anything else — including the stitch step, which is where naive
  approaches usually fall apart. Better to learn in an afternoon than after
  building a UI.
- **Scrolling/animated tabs stress everything:** frame-differencing fires on
  every frame of a scroll, and overlap between frames is near-total. Expect the
  key-frame heuristic and stitcher to need per-style tuning.
- **IG scraping breaks / violates ToS.** Mitigated by the manual-file fallback;
  never on the critical path.
- **Gemini free-tier rate limits.** Fine for a few songs a day; if usage grows,
  swap to a local model or paid backend via the pluggable interface.
