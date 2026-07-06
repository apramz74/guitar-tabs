/* Tabs — phone-first practice viewer for data/songs/*.json.
   No build step. Edits are saved as local drafts (localStorage) that overlay
   the committed JSON; "Download JSON" exports a corrected song file to commit
   back into the repo. A future remote save path can slot into saveDraft(). */

"use strict";

const DATA_DIR = "../data/songs/";
const FONT_SIZES = [17, 21, 25];
const SVG_NS = "http://www.w3.org/2000/svg";

const store = {
  drafts: read("gt.drafts", {}),   // file -> song object, or {deleted:true,title}
  settings: read("gt.settings", { fontIdx: 1 }),
};
function read(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}
function persist() {
  localStorage.setItem("gt.drafts", JSON.stringify(store.drafts));
  localStorage.setItem("gt.settings", JSON.stringify(store.settings));
}

const state = {
  index: null,        // parsed index.json
  songs: {},          // file -> fetched base song
  file: null,         // current song file
  editMode: false,
  sel: null,          // {m, e, n} measure/event/note indices
  menuOpen: false,
  renameOpen: false,
};

const app = document.getElementById("app");

/* ---------------------------------------------------------------- data */

async function fetchJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function effectiveSong(file) {
  const d = store.drafts[file];
  if (d && !d.deleted) return d;
  return state.songs[file];
}
function isDraft(file) { return !!store.drafts[file] && !store.drafts[file].deleted; }
function isDeleted(file) { return !!store.drafts[file]?.deleted; }

function draftFor(file) {
  // first edit copies the base song into a draft; later edits mutate it
  if (!isDraft(file)) store.drafts[file] = JSON.parse(JSON.stringify(state.songs[file]));
  return store.drafts[file];
}

function notesOf(event) { return event.chord ? event.chord : [event]; }

/* ---------------------------------------------------------------- routing */

window.addEventListener("hashchange", route);
window.addEventListener("resize", debounce(() => { if (state.file) render(); }, 150));

async function route() {
  state.menuOpen = false; state.renameOpen = false; state.sel = null; state.editMode = false;
  const m = location.hash.match(/^#\/s\/(.+)$/);
  state.file = m ? decodeURIComponent(m[1]) : null;
  try {
    if (!state.index) state.index = await fetchJSON(DATA_DIR + "index.json");
    if (state.file && !state.songs[state.file] && !isDeleted(state.file)) {
      state.songs[state.file] = await fetchJSON(DATA_DIR + state.file);
    }
  } catch (err) {
    app.innerHTML = "";
    app.append(el("div", { class: "empty" },
      "Couldn't load songs. Serve the repo root over HTTP — e.g.  python3 -m http.server  — then open /web/."));
    console.error(err);
    return;
  }
  render();
}

/* ---------------------------------------------------------------- render */

function render() {
  app.innerHTML = "";
  if (!state.file || isDeleted(state.file)) renderShelf();
  else renderSong();
}

function renderShelf() {
  document.title = "Tabs";
  const wrap = el("div", { class: "shelf" });
  wrap.append(
    el("header", { class: "shelf-head" },
      el("h1", {}, "Tabs"),
      el("p", {}, "Your practice library")),
  );
  const list = el("ul", { class: "songs" });
  let shown = 0;
  for (const entry of state.index) {
    if (isDeleted(entry.file)) continue;
    shown++;
    const draft = isDraft(entry.file) ? store.drafts[entry.file] : null;
    const title = draft?.title ?? entry.title;
    const artist = draft?.artist ?? entry.artist;
    const measures = draft ? draft.measures.length : entry.measures;
    const row = el("button", { class: "song-row", onclick: () => { location.hash = "#/s/" + encodeURIComponent(entry.file); } },
      el("h2", {}, title),
      el("div", { class: "song-meta" },
        artist ? el("span", { class: "chip" }, artist) : null,
        entry.capo ? el("span", { class: "chip" }, `capo ${entry.capo}`) : null,
        el("span", { class: "chip" }, `${measures} measures`),
        el("span", { class: "chip qa-" + entry.qa }, entry.qa),
        draft ? el("span", { class: "chip edited" }, "edited") : null,
      ));
    list.append(el("li", {}, row));
  }
  wrap.append(list);
  if (!shown) wrap.append(el("div", { class: "empty" }, "No songs yet. Extract one with the pipeline, then save it with save_song.py."));

  const tombs = Object.keys(store.drafts).filter(isDeleted);
  if (tombs.length) {
    wrap.append(el("div", { class: "restore-row" },
      el("button", {
        onclick: () => {
          tombs.forEach(f => delete store.drafts[f]);
          persist(); render(); toast("Restored");
        },
      }, `Restore ${tombs.length} deleted song${tombs.length > 1 ? "s" : ""}`)));
  }
  app.append(wrap);
}

function renderSong() {
  const song = effectiveSong(state.file);
  document.title = song.title;
  const view = el("div", { class: "songview" });

  const sub = [song.tuning || "EADGBE", song.capo ? `capo ${song.capo}` : null, isDraft(state.file) ? "edited" : null]
    .filter(Boolean).join(" · ");
  view.append(el("div", { class: "topbar" },
    el("button", { class: "icon-btn", "aria-label": "Back to library", onclick: () => { location.hash = ""; } }, "‹"),
    el("div", { class: "t-title" }, song.title, el("span", { class: "t-sub" }, sub)),
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

  // thumb bar / edit sheet
  if (state.editMode && state.sel) app.append(renderEditSheet(song));
  else {
    app.append(el("div", { class: "thumbbar" },
      el("button", { class: "tb-btn", "aria-label": "Smaller text", onclick: () => bumpFont(-1) }, "A−"),
      el("button", { class: "tb-btn", "aria-label": "Bigger text", onclick: () => bumpFont(1) }, "A+"),
      el("button", {
        class: "tb-btn", "aria-pressed": String(state.editMode),
        onclick: () => {
          state.editMode = !state.editMode; state.sel = null; render();
          if (state.editMode) toast("Tap a note to edit it");
        },
      }, state.editMode ? "Done" : "Edit"),
    ));
  }

  if (state.menuOpen) app.append(renderMenu(song));
  if (state.renameOpen) app.append(renderRename(song));
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

// flatten song into drawable columns
function songColumns(song) {
  const cols = [];
  song.measures.forEach((measure, m) => {
    measure.notes.forEach((event, e) => cols.push({ type: "event", m, e, notes: notesOf(event) }));
    cols.push({ type: "bar" });
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

  const cols = songColumns(song);
  for (const c of cols) {
    if (c.type === "bar") { c.w = 2 + colGap; continue; }
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
        continue;
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
    persist(); render();
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
    measure.notes.splice(sel.e, 1);
    if (!measure.notes.length) song.measures.splice(sel.m, 1);
  }
  state.sel = null;
}

function addNoteAfter(song, n, sel) {
  const fresh = { string: n.string, fret: n.fret };
  song.measures[sel.m].notes.splice(sel.e + 1, 0, fresh);
  state.sel = { m: sel.m, e: sel.e + 1, n: 0 };
}

/* ---------------------------------------------------------------- menu, rename, delete */

function renderMenu(song) {
  const close = () => { state.menuOpen = false; render(); };
  const frag = document.createDocumentFragment();
  frag.append(el("div", { class: "scrim", onclick: close }));
  frag.append(el("div", { class: "menu", role: "menu" },
    el("button", { onclick: () => { state.menuOpen = false; state.editMode = true; render(); toast("Tap a note to edit it"); } }, "Edit tab"),
    el("button", { onclick: () => { state.menuOpen = false; state.renameOpen = true; render(); } }, "Rename…"),
    el("button", { onclick: () => { downloadSong(song); close(); } }, "Download JSON"),
    isDraft(state.file) ? el("button", {
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
        if (confirm(`Delete “${song.title}”? (Removable from the library now; restore from the list page.)`)) {
          store.drafts[state.file] = { deleted: true, title: song.title };
          persist(); location.hash = "";
        } else close();
      },
    }, "Delete song"),
  ));
  return frag;
}

function renderRename(song) {
  const close = () => { state.renameOpen = false; render(); };
  const input = el("input", { value: song.title, "aria-label": "Song title" });
  const form = el("form", {},
    el("h3", {}, "Rename song"),
    input,
    el("div", { class: "actions" },
      el("button", { type: "button", onclick: close }, "Cancel"),
      el("button", { type: "submit", class: "primary" }, "Rename")));
  form.addEventListener("submit", ev => {
    ev.preventDefault();
    const t = input.value.trim();
    if (t) { draftFor(state.file).title = t; persist(); }
    close();
  });
  const dlg = el("div", { class: "dialog" }, form);
  dlg.addEventListener("click", ev => { if (ev.target === dlg) close(); });
  queueMicrotask(() => input.select());
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
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "class") { if (v) node.setAttribute("class", v); }
    else node.setAttribute(k, v);
  }
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

route();
