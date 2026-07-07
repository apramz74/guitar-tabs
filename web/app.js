/* Tabs — phone-first practice viewer for data/songs/*.json.
   No build step.

   Saving: every edit lands in a local draft instantly (works offline),
   then a debounced sync commits the changed files to GitHub through the
   Contents API when a token is configured in Settings. Without a token,
   drafts stay local and "Download JSON" exports a file to commit by hand.
   Delete = an `archived` flag saved into the song file (restorable);
   nothing is ever hard-deleted from the app. */

"use strict";

const DATA_DIR = "../data/songs/";
const FONT_SIZES = [17, 21, 25];
const SVG_NS = "http://www.w3.org/2000/svg";
const SYNC_DEBOUNCE_MS = 4000;

const store = {
  drafts: read("gt.drafts", {}),     // file -> full song object (may carry archived:true)
  settings: read("gt.settings", { fontIdx: 1, owner: "", repo: "", token: "", apiBase: "" }),
};
// migrate away pre-sync tombstones ({deleted:true} placeholders, no song data)
for (const [f, d] of Object.entries(store.drafts)) if (d && d.deleted) delete store.drafts[f];

function read(key, fallback) {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key)) }; }
  catch { return fallback; }
}
function persist() {
  localStorage.setItem("gt.drafts", JSON.stringify(store.drafts));
  localStorage.setItem("gt.settings", JSON.stringify(store.settings));
}

const state = {
  index: null,        // parsed index.json
  songs: {},          // file -> base song (as saved in the repo)
  file: null,         // current song file
  editMode: false,
  sel: null,          // {m, e, n} measure/event/note indices
  barSel: null,       // measure index whose bar was tapped (measure ops)
  splitFrom: null,    // measure index being split (tap a slot to place the bar)
  menuOpen: false,
  infoOpen: false,
  settingsOpen: false,
};

const app = document.getElementById("app");

/* ---------------------------------------------------------------- GitHub sync */

function ghCfg() {
  const { owner, repo, token, apiBase } = store.settings;
  if (!owner || !repo || !token) return null;
  return { owner, repo, token, base: apiBase || "https://api.github.com" };
}

async function ghReq(path, opts = {}) {
  const cfg = ghCfg();
  const r = await fetch(cfg.base + path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      Accept: "application/vnd.github+json",
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (r.status === 404) return null;
  if (!r.ok) { const e = new Error(`GitHub ${r.status} on ${path}`); e.status = r.status; throw e; }
  return r.json();
}

function contentsPath(file) {
  const cfg = ghCfg();
  return `/repos/${cfg.owner}/${cfg.repo}/contents/data/songs/${encodeURIComponent(file)}`;
}
async function ghGetJSON(file) {
  const res = await ghReq(contentsPath(file));
  if (!res) return null;
  return { obj: JSON.parse(b64decode(res.content)), sha: res.sha };
}
async function ghPutJSON(file, obj, sha, message) {
  const body = { message, content: b64encode(JSON.stringify(obj, null, 2) + "\n") };
  if (sha) body.sha = sha;
  return ghReq(contentsPath(file), { method: "PUT", body: JSON.stringify(body) });
}

const sync = { timer: null, running: false, status: "idle" };  // idle | saving | offline | error

function scheduleSync() {
  if (!ghCfg()) { setSyncStatus("idle"); return; }
  clearTimeout(sync.timer);
  sync.timer = setTimeout(flushSync, SYNC_DEBOUNCE_MS);
  setSyncStatus("idle");
}

async function flushSync() {
  if (!ghCfg() || sync.running) return;
  const files = Object.keys(store.drafts);
  if (!files.length) { setSyncStatus("idle"); return; }
  sync.running = true;
  setSyncStatus("saving");
  try {
    for (const file of files) await pushSong(file);
    await pushIndex();
    setSyncStatus("idle");
    toast("Saved to GitHub");
  } catch (err) {
    console.error("sync:", err);
    setSyncStatus(navigator.onLine === false || err instanceof TypeError ? "offline" : "error");
  } finally {
    sync.running = false;
  }
}

async function pushSong(file) {
  const draft = store.drafts[file];
  if (!draft) return;
  const put = async () => {
    const cur = await ghGetJSON(file);
    await ghPutJSON(file, draft, cur?.sha, `app: update ${draft.title}`);
  };
  try { await put(); }
  catch (err) {
    if (err.status === 409 || err.status === 422) await put();  // sha raced; refetch once
    else throw err;
  }
  state.songs[file] = draft;
  delete store.drafts[file];
  persist();
}

async function pushIndex() {
  const cur = await ghGetJSON("index.json");
  const idx = cur?.obj ?? state.index ?? [];
  for (const entry of idx) {
    const s = effectiveSong(entry.file);
    if (!s) continue;
    entry.title = s.title;
    entry.artist = s.artist || "";
    entry.capo = s.capo || 0;
    entry.measures = s.measures.length;
    entry.qa = s.qa || "draft";
    if (s.archived) entry.archived = true; else delete entry.archived;
  }
  await ghPutJSON("index.json", idx, cur?.sha, "app: update song index");
  state.index = idx;
}

function setSyncStatus(s) {
  if (sync.status === s) return;
  sync.status = s;
  render();
}

function syncChip() {
  if (!ghCfg()) {
    return Object.keys(store.drafts).length
      ? el("span", { class: "chip sync warn" }, "edits on this device only")
      : null;
  }
  const pending = Object.keys(store.drafts).length;
  const label = sync.status === "saving" ? "saving…"
    : sync.status === "offline" ? "offline — will retry"
    : sync.status === "error" ? "save failed — will retry"
    : pending ? "unsaved changes" : "saved";
  const cls = sync.status === "saving" ? "busy" : (pending || sync.status !== "idle") ? "warn" : "ok";
  return el("span", { class: "chip sync " + cls }, label);
}

window.addEventListener("online", flushSync);

/* ---------------------------------------------------------------- data */

async function fetchStatic(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// read through the API when configured (fresh after saves; also works on a
// private repo), else the static files GitHub Pages / http.server serves
async function loadData(file) {
  if (ghCfg()) {
    const res = await ghGetJSON(file);
    if (res) return res.obj;
  }
  return fetchStatic(DATA_DIR + file);
}

function effectiveSong(file) { return store.drafts[file] ?? state.songs[file]; }
function isDraft(file) { return !!store.drafts[file]; }
function isArchived(file) {
  const s = effectiveSong(file);
  if (s) return !!s.archived;
  return !!state.index?.find(e => e.file === file)?.archived;
}

function draftFor(file) {
  // first edit copies the base song into a draft; later edits mutate it
  if (!store.drafts[file]) store.drafts[file] = JSON.parse(JSON.stringify(state.songs[file]));
  return store.drafts[file];
}

function notesOf(event) { return event.chord ? event.chord : [event]; }

/* ---------------------------------------------------------------- routing */

window.addEventListener("hashchange", route);
window.addEventListener("resize", debounce(() => { if (state.file) render(); }, 150));

async function route() {
  state.menuOpen = false; state.infoOpen = false; state.settingsOpen = false;
  state.sel = null; state.barSel = null; state.splitFrom = null; state.editMode = false;
  const m = location.hash.match(/^#\/s\/(.+)$/);
  state.file = m ? decodeURIComponent(m[1]) : null;
  try {
    if (!state.index) state.index = await loadData("index.json");
    if (state.file && !state.songs[state.file] && !store.drafts[state.file]) {
      state.songs[state.file] = await loadData(state.file);
    }
  } catch (err) {
    app.innerHTML = "";
    app.append(el("div", { class: "empty" },
      "Couldn't load songs. Serve the repo root over HTTP — e.g.  python3 -m http.server  — then open /web/."));
    console.error(err);
    return;
  }
  render();
  flushSync();   // pick up drafts left over from an offline session
}

/* ---------------------------------------------------------------- render */

function render() {
  app.innerHTML = "";
  if (!state.file || isArchived(state.file)) renderShelf();
  else renderSong();
}

function renderShelf() {
  document.title = "Tabs";
  const wrap = el("div", { class: "shelf" });
  wrap.append(
    el("header", { class: "shelf-head" },
      el("div", { class: "shelf-top" },
        el("h1", {}, "Tabs"),
        el("button", { class: "icon-btn", "aria-label": "Settings", onclick: () => { state.settingsOpen = true; render(); } }, "⚙")),
      el("p", {}, "Your practice library"),
      el("div", { class: "song-meta" }, syncChip())),
  );
  const list = el("ul", { class: "songs" });
  let shown = 0;
  for (const entry of state.index) {
    if (isArchived(entry.file)) continue;
    shown++;
    const song = effectiveSong(entry.file);
    const title = song?.title ?? entry.title;
    const artist = song?.artist ?? entry.artist;
    const measures = song ? song.measures.length : entry.measures;
    const row = el("button", { class: "song-row", onclick: () => { location.hash = "#/s/" + encodeURIComponent(entry.file); } },
      el("h2", {}, title),
      el("div", { class: "song-meta" },
        artist ? el("span", { class: "chip" }, artist) : null,
        entry.capo ? el("span", { class: "chip" }, `capo ${entry.capo}`) : null,
        el("span", { class: "chip" }, `${measures} measures`),
        el("span", { class: "chip qa-" + entry.qa }, entry.qa),
        isDraft(entry.file) ? el("span", { class: "chip edited" }, ghCfg() ? "syncing" : "edited") : null,
      ));
    list.append(el("li", {}, row));
  }
  wrap.append(list);
  if (!shown) wrap.append(el("div", { class: "empty" }, "No songs yet. Extract one with the pipeline, then save it with save_song.py."));

  const archived = state.index.filter(e => isArchived(e.file));
  if (archived.length) {
    wrap.append(el("div", { class: "restore-row" },
      ...archived.map(e => el("button", { onclick: () => restoreSong(e.file) }, `Restore “${e.title}”`))));
  }
  app.append(wrap);
  if (state.settingsOpen) app.append(renderSettings());
}

async function restoreSong(file) {
  if (!state.songs[file] && !store.drafts[file]) {
    try { state.songs[file] = await loadData(file); }
    catch { toast("Couldn't load that song"); return; }
  }
  const draft = draftFor(file);
  delete draft.archived;
  persist(); scheduleSync(); render(); toast("Restored");
}

function renderSong() {
  const song = effectiveSong(state.file);
  document.title = song.title;
  const view = el("div", { class: "songview" });

  const sub = [song.tuning || "EADGBE", song.capo ? `capo ${song.capo}` : null,
    song.time_signature || null].filter(Boolean).join(" · ");
  view.append(el("div", { class: "topbar" },
    el("button", { class: "icon-btn", "aria-label": "Back to library", onclick: () => { location.hash = ""; } }, "‹"),
    el("div", { class: "t-title" }, song.title, el("span", { class: "t-sub" }, sub)),
    syncChip(),
    el("button", { class: "icon-btn", "aria-label": "Song menu", onclick: () => { state.menuOpen = true; render(); } }, "⋯"),
  ));

  const tabwrap = el("div", { class: "tabwrap" });
  view.append(tabwrap);
  if (song.qa === "draft") {
    view.append(el("p", { class: "song-note" },
      "Draft extraction — not fully QA’d against the video yet."));
  }
  app.append(view);
  drawTab(tabwrap, song);          // needs layout width, so after DOM insert

  // thumb bar / edit sheet / measure sheet
  if (state.editMode && state.sel) app.append(renderEditSheet(song));
  else if (state.editMode && state.barSel !== null) app.append(renderMeasureSheet(song));
  else {
    app.append(el("div", { class: "thumbbar" },
      el("button", { class: "tb-btn", "aria-label": "Smaller text", onclick: () => bumpFont(-1) }, "A−"),
      el("button", { class: "tb-btn", "aria-label": "Bigger text", onclick: () => bumpFont(1) }, "A+"),
      el("button", {
        class: "tb-btn", "aria-pressed": String(state.editMode),
        onclick: () => {
          state.editMode = !state.editMode; state.sel = null; state.barSel = null; state.splitFrom = null; render();
          if (state.editMode) toast("Tap a note to edit, a + to add");
        },
      }, state.editMode ? "Done" : "Edit"),
    ));
  }

  if (state.menuOpen) app.append(renderMenu(song));
  if (state.infoOpen) app.append(renderSongInfo(song));
}

function bumpFont(d) {
  store.settings.fontIdx = Math.max(0, Math.min(FONT_SIZES.length - 1, store.settings.fontIdx + d));
  persist(); render();
}

/* ---------------------------------------------------------------- tab drawing */

let measureCtx;
function textWidth(s, fs) {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  measureCtx.font = `500 ${fs}px "IBM Plex Mono", ui-monospace, Menlo, monospace`;
  return measureCtx.measureText(s).width;
}

function noteLabel(n) {
  const f = n.fret === -1 || n.fret === undefined ? "?" : String(n.fret);
  return n.ghost ? `(${f})` : f;
}

// flatten song into drawable columns; in edit mode, weave an insertion
// slot before every event and at each measure's end (so empty measures
// stay tappable too)
function songColumns(song, withSlots) {
  const cols = [];
  song.measures.forEach((measure, m) => {
    measure.notes.forEach((event, e) => {
      if (withSlots) cols.push({ type: "slot", m, at: e });
      cols.push({ type: "event", m, e, notes: notesOf(event) });
    });
    if (withSlots) cols.push({ type: "slot", m, at: measure.notes.length });
    cols.push({ type: "bar", m });
  });
  return cols;
}

function drawTab(container, song) {
  const fs = FONT_SIZES[store.settings.fontIdx];
  const gapY = 1.5 * fs;
  const padTop = 1.5 * fs;
  const labelCol = 1.5 * fs;
  const colGap = 0.62 * fs;
  const H = padTop + 5 * gapY + 0.9 * fs;
  const W = Math.max(280, container.clientWidth - 8);
  const yOf = s => padTop + (s - 1) * gapY;

  const cols = songColumns(song, state.editMode);
  for (const c of cols) {
    if (c.type === "bar") { c.w = 2 + colGap; continue; }
    if (c.type === "slot") { c.w = 0.95 * fs; continue; }
    c.w = Math.max(...c.notes.map(n => textWidth(noteLabel(n), fs))) + colGap;
    // a slide to the next note needs shoulder room for the slanted stroke
    if (c.notes.some(n => n.legato_next === "/" || n.legato_next === "\\")) c.w += 0.8 * fs;
  }

  // greedy flow into lines, preferring to break after a bar
  const lines = [];
  let cur = [], x = labelCol;
  for (const c of cols) {
    if (x + c.w > W - 4 && cur.length) {
      let cut = cur.length;
      for (let i = cur.length - 1; i > 0; i--) if (cur[i].type === "bar") { cut = i + 1; break; }
      lines.push(cur.slice(0, cut));
      cur = cur.slice(cut);
      x = labelCol + cur.reduce((a, b) => a + b.w, 0);
    }
    cur.push(c); x += c.w;
  }
  if (cur.some(c => c.type === "event")) lines.push(cur);

  const tuning = (song.tuning || "EADGBE").split("").reverse();
  if (tuning.length === 6) tuning[0] = tuning[0].toLowerCase();

  container.innerHTML = "";
  const markedMeasures = new Set();
  lines.forEach(lineCols => {
    const svg = elNS("svg", { class: "tabline", viewBox: `0 0 ${W} ${H}` });
    for (let s = 1; s <= 6; s++) {
      svg.append(elNS("line", { x1: labelCol - 0.3 * fs, y1: yOf(s), x2: W - 2, y2: yOf(s), stroke: "var(--stringline)", "stroke-width": 1 }));
      svg.append(elNS("text", { x: 2, y: yOf(s), class: "string-label", "font-size": 0.62 * fs, "dominant-baseline": "central" }, tuning[s - 1] ?? ""));
    }
    // position columns
    let cx = labelCol;
    for (const c of lineCols) { c.x = cx; c.cx = cx + c.w / 2; cx += c.w; }

    for (const [ci, c] of lineCols.entries()) {
      if (c.type === "bar") {
        svg.append(elNS("line", { x1: c.cx, y1: yOf(1), x2: c.cx, y2: yOf(6), stroke: "var(--line)", "stroke-width": 2 }));
        if (state.editMode) {
          svg.append(elNS("rect", {
            x: c.x, y: yOf(1) - 0.5 * fs, width: c.w, height: 5 * gapY + fs, class: "hit bar-hit",
            onclick: () => { state.barSel = c.m; state.sel = null; render(); },
          }));
        }
        continue;
      }
      if (c.type === "slot") {           // edit mode only: insert a note here
        for (let s = 1; s <= 6; s++) {
          svg.append(elNS("text", { x: c.cx, y: yOf(s), "text-anchor": "middle", "dominant-baseline": "central", "font-size": 0.62 * fs, class: "plus" }, "+"));
          svg.append(elNS("rect", {
            x: c.x, y: yOf(s) - 0.7 * fs, width: c.w, height: 1.4 * fs, class: "hit slot-hit",
            "data-m": c.m, "data-at": c.at, "data-s": s,
            onclick: () => {
              if (state.splitFrom !== null) {       // split mode: place the bar here
                if (state.splitFrom === c.m && c.at > 0 && c.at < song.measures[c.m].notes.length) {
                  editSong(song2 => splitMeasure(song2, c.m, c.at));
                } else {
                  toast(`Tap between two notes of measure ${state.splitFrom + 1}`);
                }
                return;
              }
              editSong(song2 => insertNoteAt(song2, c.m, c.at, s));
            },
          }));
        }
        continue;
      }
      if (!markedMeasures.has(c.m)) {    // flag markers above a measure's first notes
        const meas = song.measures[c.m];
        const flagged = meas && (meas.suspect || meas.boundary);
        const isRep = meas && "repeat_of" in meas;
        if (flagged || isRep) {
          markedMeasures.add(c.m);
          svg.append(elNS("text", {
            x: c.x + 2, y: 0.5 * fs, "font-size": 0.55 * fs,
            class: flagged ? "m-flag" : "m-flag rep",
          }, flagged ? "⚠ check" : "repeat?"));
          if (state.editMode) {
            svg.append(elNS("rect", {
              x: c.x - 4, y: 0, width: 3.2 * fs, height: fs, class: "hit flag-hit", "data-m": c.m,
              onclick: () => { state.barSel = c.m; state.sel = null; render(); },
            }));
          }
        }
      }
      const taken = new Set(c.notes.map(n => n.string));
      if (state.editMode) {              // chord-building: empty strings of an event
        for (let s = 1; s <= 6; s++) {
          if (taken.has(s)) continue;
          svg.append(elNS("text", { x: c.cx, y: yOf(s), "text-anchor": "middle", "dominant-baseline": "central", "font-size": 0.62 * fs, class: "plus dim" }, "+"));
          svg.append(elNS("rect", {
            x: c.x, y: yOf(s) - 0.7 * fs, width: c.w, height: 1.4 * fs, class: "hit chord-hit",
            "data-m": c.m, "data-e": c.e, "data-s": s,
            onclick: () => editSong((song2) => addChordNote(song2, c.m, c.e, s)),
          }));
        }
      }
      for (const [ni, n] of c.notes.entries()) {
        const y = yOf(n.string);
        const selected = state.sel && state.sel.m === c.m && state.sel.e === c.e && state.sel.n === ni;
        if (selected) {
          const w = textWidth(noteLabel(n), fs) + 10;
          svg.append(elNS("rect", { x: c.cx - w / 2, y: y - 0.75 * fs, width: w, height: 1.5 * fs, rx: 6, class: "sel-halo", "stroke-width": 1.5 }));
        }
        svg.append(elNS("text", {
          x: c.cx, y, "text-anchor": "middle", "dominant-baseline": "central",
          "font-size": fs, class: n.ghost ? "ghost-note" : "",
          style: "paint-order:stroke; stroke:var(--ground); stroke-width:6; stroke-linejoin:round",
        }, noteLabel(n)));

        // connection marks to the next note on the same string
        if (n.legato_next) {
          const next = findNext(lineCols, ci, n.string);
          const halfW = textWidth(noteLabel(n), fs) / 2;
          if (n.legato_next === "h" || n.legato_next === "p") {
            const x1 = c.cx, x2 = next ? next.cx : Math.min(c.cx + 2.4 * fs, W - 4);
            const y0 = y - 0.72 * fs, peak = y0 - 0.75 * fs;
            svg.append(elNS("path", { d: `M ${x1} ${y0} Q ${(x1 + x2) / 2} ${peak} ${x2} ${y0}`, class: "mark", "stroke-width": 1.6 }));
            svg.append(elNS("text", { x: (x1 + x2) / 2, y: peak + 0.1 * fs, "text-anchor": "middle", class: "mark-label", "font-size": 0.58 * fs }, n.legato_next));
          } else {  // slide / or \
            const x1 = c.cx + halfW + 0.15 * fs;
            const x2 = next ? next.cx - textWidth(noteLabel(next.note), fs) / 2 - 0.15 * fs : x1 + 0.8 * fs;
            const dy = 0.42 * fs, up = n.legato_next === "/";
            svg.append(elNS("line", {
              x1, y1: y + (up ? dy : -dy), x2: Math.max(x2, x1 + 0.5 * fs), y2: y + (up ? -dy : dy),
              class: "mark", "stroke-width": 1.8, "stroke-linecap": "round",
            }));
          }
        }
        if (state.editMode) {
          svg.append(elNS("rect", {
            x: c.x, y: y - 0.85 * fs, width: c.w, height: 1.7 * fs, class: "hit",
            onclick: () => { state.sel = { m: c.m, e: c.e, n: ni }; render(); },
          }));
        }
      }
    }
    container.append(svg);
  });
}

// next event column carrying a note on the given string (same line only)
function findNext(lineCols, fromIdx, string) {
  for (let i = fromIdx + 1; i < lineCols.length; i++) {
    const c = lineCols[i];
    if (c.type !== "event") continue;
    const note = c.notes.find(n => n.string === string);
    if (note) return { cx: c.cx, note };
  }
  return null;
}

/* ---------------------------------------------------------------- edit sheet */

function selNote(song) {
  const { m, e, n } = state.sel;
  const event = song.measures[m]?.notes[e];
  if (!event) return null;
  return notesOf(event)[n] ?? null;
}

function renderEditSheet(songRO) {
  const note = selNote(songRO);
  if (!note) { state.sel = null; return el("span"); }

  const edit = fn => {                       // every change goes through the draft
    const song = draftFor(state.file);
    fn(song, selNote(song), state.sel);
    persist(); scheduleSync(); render();
  };
  const LEGATO = [["—", undefined], ["h", "h"], ["p", "p"], ["/", "/"], ["\\", "\\"]];
  const STRINGS = ["e", "B", "G", "D", "A", "E"];

  return el("div", { class: "sheet", role: "dialog", "aria-label": "Edit note" },
    el("h3", {}, `String ${STRINGS[note.string - 1]} · fret ${note.fret}`),
    el("div", { class: "row" },
      el("span", { class: "row-label" }, "Fret"),
      el("div", { class: "stepper" },
        el("button", { "aria-label": "Fret down", onclick: () => edit((s, n) => { n.fret = Math.max(0, (n.fret || 0) - 1); }) }, "−"),
        el("span", { class: "val" }, noteLabel(note)),
        el("button", { "aria-label": "Fret up", onclick: () => edit((s, n) => { n.fret = Math.min(24, (n.fret || 0) + 1); }) }, "+"))),
    el("div", { class: "row" },
      el("span", { class: "row-label" }, "String"),
      el("div", { class: "seg" }, ...STRINGS.map((label, i) =>
        el("button", { "aria-pressed": String(note.string === i + 1), onclick: () => edit((s, n) => { n.string = i + 1; }) }, label)))),
    el("div", { class: "row" },
      el("span", { class: "row-label" }, "Mark"),
      el("div", { class: "seg" }, ...LEGATO.map(([label, v]) =>
        el("button", { "aria-pressed": String(note.legato_next === v), onclick: () => edit((s, n) => { if (v) n.legato_next = v; else delete n.legato_next; }) }, label))),
      el("div", { class: "seg", style: "flex:0 0 84px" },
        el("button", { "aria-pressed": String(!!note.ghost), onclick: () => edit((s, n) => { if (n.ghost) delete n.ghost; else n.ghost = true; }) }, "( )"))),
    el("div", { class: "actions" },
      el("button", { class: "danger", onclick: () => edit(deleteSelected) }, "Delete note"),
      el("button", { onclick: () => edit(addNoteAfter) }, "＋ Note after"),
      el("button", { class: "primary", onclick: () => { state.sel = null; render(); } }, "Done")),
  );
}

function deleteSelected(song, _n, sel) {
  const measure = song.measures[sel.m];
  const event = measure.notes[sel.e];
  if (event.chord) {
    event.chord.splice(sel.n, 1);
    if (event.chord.length === 1) measure.notes[sel.e] = event.chord[0];
  } else {
    // an emptied measure stays — its insertion slot keeps it editable
    measure.notes.splice(sel.e, 1);
  }
  state.sel = null;
}

function addNoteAfter(song, n, sel) {
  const fresh = { string: n.string, fret: n.fret };
  song.measures[sel.m].notes.splice(sel.e + 1, 0, fresh);
  state.sel = { m: sel.m, e: sel.e + 1, n: 0 };
}

// mutations behind the + targets; all go through the draft like the sheet
function editSong(fn) {
  const song = draftFor(state.file);
  fn(song);
  persist(); scheduleSync(); render();
}

function insertNoteAt(song, m, at, string) {
  song.measures[m].notes.splice(at, 0, { string, fret: 0 });
  state.sel = { m, e: at, n: 0 };
  state.barSel = null;
}

function addChordNote(song, m, e, string) {
  const event = song.measures[m].notes[e];
  if (event.chord) {
    event.chord.push({ string, fret: 0 });
    state.sel = { m, e, n: event.chord.length - 1 };
  } else {
    song.measures[m].notes[e] = { chord: [event, { string, fret: 0 }] };
    state.sel = { m, e, n: 1 };
  }
  state.barSel = null;
}

function renderMeasureSheet(song) {
  const m = state.barSel;
  const meas = song.measures[m];
  if (m === null || !meas) { state.barSel = null; return el("span"); }
  const flagged = meas.suspect || meas.boundary;
  const why = meas.boundary === "added" ? "The pipeline added a bar line at this measure — check it against the video."
    : meas.boundary === "removed" ? "The pipeline removed a bar line here — check it against the video."
    : meas.suspect ? "This measure's width looks unusual — check it against the video."
    : null;
  return el("div", { class: "sheet", role: "dialog", "aria-label": "Measure" },
    el("h3", {}, `Measure ${m + 1} of ${song.measures.length}`),
    why ? el("p", { class: "sheet-hint" }, why) : null,
    "repeat_of" in meas ? el("p", { class: "sheet-hint" },
      `Looks like a repeat of measure ${meas.repeat_of + 1} — tutorials often loop. Delete it if you only want one pass.`) : null,
    el("div", { class: "actions" },
      el("button", {
        onclick: () => editSong(s => mergeWithNext(s, m)),
        disabled: m + 1 >= song.measures.length,
      }, "Merge with next"),
      el("button", {
        onclick: () => {
          state.barSel = null; state.splitFrom = m; render();
          toast(`Tap the spot in measure ${m + 1} where the bar belongs`);
        },
      }, "Split…")),
    el("div", { class: "actions" },
      el("button", {
        class: "danger",
        onclick: () => {
          if (confirm(`Delete measure ${m + 1} and its ${meas.notes.length} event(s)?`)) {
            editSong(s => { s.measures.splice(m, 1); state.barSel = null; });
          }
        },
      }, "Delete measure"),
      el("button", { onclick: () => editSong(s => { s.measures.splice(m + 1, 0, { notes: [] }); state.barSel = m + 1; }) }, "＋ Measure after")),
    el("div", { class: "actions" },
      flagged || "repeat_of" in meas ? el("button", {
        onclick: () => editSong(s => {
          ["suspect", "boundary", "repeat_of"].forEach(k => delete s.measures[m][k]);
          state.barSel = null;
        }),
      }, "Looks right") : null,
      el("button", { class: "primary", onclick: () => { state.barSel = null; render(); } }, "Done")),
  );
}

function mergeWithNext(song, m) {
  const nx = song.measures[m + 1];
  if (!nx) return;
  song.measures[m].notes.push(...nx.notes);
  ["suspect", "boundary", "repeat_of"].forEach(k => delete song.measures[m][k]);
  song.measures.splice(m + 1, 1);
  state.barSel = null;
}

function splitMeasure(song, m, at) {
  const meas = song.measures[m];
  const right = meas.notes.splice(at);
  ["suspect", "boundary"].forEach(k => delete meas[k]);
  song.measures.splice(m + 1, 0, { notes: right });
  state.splitFrom = null;
}

/* ---------------------------------------------------------------- menu, rename, settings */

function renderMenu(song) {
  const close = () => { state.menuOpen = false; render(); };
  const frag = document.createDocumentFragment();
  frag.append(el("div", { class: "scrim", onclick: close }));
  frag.append(el("div", { class: "menu", role: "menu" },
    el("button", { onclick: () => { state.menuOpen = false; state.editMode = true; render(); toast("Tap a note to edit it"); } }, "Edit tab"),
    el("button", { onclick: () => { state.menuOpen = false; state.infoOpen = true; render(); } }, "Song info…"),
    el("button", { onclick: () => { downloadSong(song); close(); } }, "Download JSON"),
    isDraft(state.file) && !ghCfg() ? el("button", {
      onclick: () => {
        if (confirm("Discard your local edits and go back to the committed tab?")) {
          delete store.drafts[state.file]; persist();
        }
        close();
      },
    }, "Revert edits") : null,
    el("hr"),
    el("button", {
      class: "danger",
      onclick: () => {
        if (confirm(`Remove “${song.title}” from the library? You can restore it from the list page.`)) {
          draftFor(state.file).archived = true;
          persist(); scheduleSync(); location.hash = "";
        } else close();
      },
    }, "Delete song"),
  ));
  return frag;
}

function renderSongInfo(song) {
  const close = () => { state.infoOpen = false; render(); };
  const title = el("input", { value: song.title, "aria-label": "Song title" });
  const artist = el("input", { value: song.artist || "", "aria-label": "Artist" });
  const capo = el("input", { value: song.capo || 0, type: "number", min: 0, max: 12, "aria-label": "Capo" });
  const tuning = el("input", { value: song.tuning || "EADGBE", "aria-label": "Tuning", autocapitalize: "characters" });
  const tsig = el("input", { value: song.time_signature || "", placeholder: "e.g. 4/4 (optional)", "aria-label": "Time signature" });
  const form = el("form", {},
    el("h3", {}, "Song info"),
    el("label", {}, "Title", title),
    el("label", {}, "Artist", artist),
    el("label", {}, "Capo", capo),
    el("label", {}, "Tuning", tuning),
    el("label", {}, "Time signature", tsig),
    el("div", { class: "actions" },
      el("button", { type: "button", onclick: close }, "Cancel"),
      el("button", { type: "submit", class: "primary" }, "Save")));
  form.addEventListener("submit", ev => {
    ev.preventDefault();
    const d = draftFor(state.file);
    if (title.value.trim()) d.title = title.value.trim();
    d.artist = artist.value.trim();
    d.capo = Math.max(0, parseInt(capo.value, 10) || 0);
    d.tuning = (tuning.value.trim() || "EADGBE").toUpperCase();
    if (tsig.value.trim()) d.time_signature = tsig.value.trim();
    else delete d.time_signature;
    persist(); scheduleSync(); close();
  });
  const dlg = el("div", { class: "dialog" }, form);
  dlg.addEventListener("click", ev => { if (ev.target === dlg) close(); });
  queueMicrotask(() => title.select());
  return dlg;
}

function renderSettings() {
  const close = () => { state.settingsOpen = false; render(); };
  const s = store.settings;
  const owner = el("input", { value: s.owner, placeholder: "github username", "aria-label": "GitHub owner", autocapitalize: "none" });
  const repo = el("input", { value: s.repo, placeholder: "guitar-tabs", "aria-label": "Repository", autocapitalize: "none" });
  const token = el("input", { value: s.token, type: "password", placeholder: "fine-grained token", "aria-label": "Token" });
  const form = el("form", {},
    el("h3", {}, "Saving to GitHub"),
    el("p", { class: "hint" },
      "Edits save to your repo a few seconds after you stop editing. Create a fine-grained token with read/write access to Contents on just this repo."),
    el("label", {}, "Owner", owner),
    el("label", {}, "Repository", repo),
    el("label", {}, "Token", token),
    el("div", { class: "actions" },
      el("button", { type: "button", onclick: close }, "Cancel"),
      el("button", {
        type: "button", onclick: async () => {
          Object.assign(s, { owner: owner.value.trim(), repo: repo.value.trim(), token: token.value.trim() });
          persist();
          if (!ghCfg()) { toast("Fill in all three fields"); return; }
          try {
            const r = await ghReq(`/repos/${s.owner}/${s.repo}`);
            if (!r) throw new Error("not found");
            toast("Connected ✓");
          } catch { toast("Couldn't reach that repo"); }
        },
      }, "Test"),
      el("button", { type: "submit", class: "primary" }, "Save")));
  form.addEventListener("submit", ev => {
    ev.preventDefault();
    Object.assign(s, { owner: owner.value.trim(), repo: repo.value.trim(), token: token.value.trim() });
    persist(); close(); flushSync();
  });
  const dlg = el("div", { class: "dialog" }, form);
  dlg.addEventListener("click", ev => { if (ev.target === dlg) close(); });
  return dlg;
}

function downloadSong(song) {
  const blob = new Blob([JSON.stringify(song, null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: state.file });
  a.click();
  URL.revokeObjectURL(a.href);
  toast("Saved — commit it into data/songs/");
}

/* ---------------------------------------------------------------- utilities */

function b64encode(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(bin);
}
function b64decode(b64) {
  const bin = atob(b64.replace(/\s/g, ""));
  const bytes = Uint8Array.from(bin, ch => ch.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function toast(msg) {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const t = el("div", { class: "toast" }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), 2200);
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  applyAttrs(node, attrs);
  node.append(...children.filter(c => c !== null && c !== undefined));
  return node;
}
function elNS(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  applyAttrs(node, attrs);
  for (const c of children) node.append(typeof c === "string" ? document.createTextNode(c) : c);
  return node;
}
function applyAttrs(node, attrs) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "class") { if (v) node.setAttribute("class", v); }
    else node.setAttribute(k, v === true ? "" : v);
  }
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

route();
