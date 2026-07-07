"use strict";

let runId = null;
let state = null;
let padFor = null;       // cluster index the pad is editing
let localLabels = {};    // cluster -> label, edited client-side until Build

const $ = id => document.getElementById(id);
const PANELS = ["start", "busy", "notab", "label", "chords", "check", "publish", "done", "error"];
let localChords = null;   // [{name, fr}] per diagram, edited client-side
const PAD_KEYS = ["0","1","2","3","4","5","6","7","8","9","x","arc","slide/","slide\\","(",")","h","p"];

function show(name) {
  PANELS.forEach(p => $("panel-" + p).classList.toggle("hidden", p !== name));
  const stepOf = { start: 1, busy: 2, notab: 2, label: 3, chords: 3, check: 4, publish: 5, done: 5, error: 1 };
  document.querySelectorAll("#rail li").forEach(li => {
    const n = +li.dataset.step;
    li.classList.toggle("on", n === stepOf[name]);
    li.classList.toggle("past", n < stepOf[name]);
  });
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

/* ---------------- start: link or file ---------------- */

$("link-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const link = $("link").value.trim();
  if (!link) return;
  const r = await api("/api/runs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ link }),
  });
  startPolling(r.id);
});

$("file").addEventListener("change", () => sendFile($("file").files[0]));
const drop = $("drop");
drop.addEventListener("dragover", ev => { ev.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", ev => {
  ev.preventDefault(); drop.classList.remove("over");
  if (ev.dataTransfer.files[0]) sendFile(ev.dataTransfer.files[0]);
});
async function sendFile(f) {
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  show("busy"); $("busy-title").textContent = "Uploading…";
  const r = await api("/api/runs", { method: "POST", body: fd });
  startPolling(r.id);
}

/* ---------------- polling ---------------- */

function startPolling(id) {
  runId = id;
  show("busy");
  poll();
  setInterval(poll, 1000);
}

async function poll() {
  if (!runId) return;
  state = await api(`/api/runs/${runId}`);
  render();
}

let lastStep = null;
function render() {
  const s = state.step;
  $("log").textContent = state.log.join("\n");
  $("log").scrollTop = $("log").scrollHeight;

  if (s === "download" || s === "extract" || s === "build" || s === "publishing" || s === "starting") {
    $("busy-title").textContent = {
      download: "Downloading the video…", extract: "Reading the video…",
      build: "Building the tab…", publishing: "Publishing…", starting: "Starting…",
    }[s];
    show("busy");
  } else if (s === "notab") {
    $("notab-msg").textContent = state.error;
    $("notab-frames").src = `/api/runs/${runId}/file/frames.png`;
    show("notab");
  } else if (s === "error") {
    $("error-msg").textContent = state.error || "Unknown error";
    $("error-log").textContent = state.log.slice(-15).join("\n");
    show("error");
  } else if (s === "label") {
    if (lastStep !== "label") {
      localLabels = { ...state.labels };
      renderCards();
    }
    if (state.suggestions && lastStep === "label" && !renderCards.suggested) {
      renderCards.suggested = true;
      for (const [k, v] of Object.entries(state.suggestions)) {
        if (!localLabels[k]) { localLabels[k] = v; markSuggested(k); }
      }
      renderCards(true);
    }
    show("label");
  } else if (s === "chords") {
    if (lastStep !== "chords") {
      localChords = state.diagrams.map(() => ({ name: "", fr: "" }));
      renderChordCards();
    }
    if (state.chord_suggestions && !renderChordCards.suggested) {
      renderChordCards.suggested = true;
      state.chord_suggestions.forEach((sug, i) => {
        if (sug && localChords[i] && !localChords[i].name && !localChords[i].fr) {
          localChords[i] = { name: sug.name || "", fr: sug.fr ?? "" };
        }
      });
      renderChordCards();
    }
    show("chords");
  } else if (s === "check") {
    if (lastStep !== "check") renderCheck();
    show("check");
  } else if (s === "done") {
    const a = $("done-link");
    if (state.published?.local) {
      $("done-msg").textContent = "Saved to data/songs/ (not committed — push was off).";
      a.textContent = "Open it in the local practice app"; a.href = "http://localhost:8000/web/";
    } else {
      $("done-msg").textContent = "Committed and pushed. The site updates in about a minute.";
      a.textContent = state.published.url; a.href = state.published.url;
    }
    show("done");
  }
  lastStep = s;
}

/* ---------------- labeling ---------------- */

const suggested = new Set();
function markSuggested(k) { suggested.add(String(k)); }

function renderCards() {
  const wrap = $("cards");
  wrap.innerHTML = "";
  let missing = 0;
  for (let i = 0; i < state.clusters; i++) {
    const k = String(i);
    const label = localLabels[k];
    if (!label) missing++;
    const card = document.createElement("div");
    card.className = "fcard " + (label ? (state.prefill[k] === label ? "known" : "") : "needs");
    card.dataset.cluster = k;
    card.innerHTML = `
      <img src="/api/runs/${runId}/file/debug/glyph_cluster_${i}.png" alt="shape ${i}">
      <div class="lab">${label ? escapeHtml(label) : "?"}</div>
      <div class="src">${label ? (state.prefill[k] === label ? "from library" : (suggested.has(k) ? "AI — confirm" : "you")) : "needs a name"}</div>`;
    card.onclick = () => openPad(k, card);
    wrap.append(card);
  }
  $("label-progress").textContent = missing ? `${missing} still need names` : "all named";
}

function openPad(k, card) {
  padFor = k;
  const pad = $("pad");
  pad.innerHTML = "";
  for (const key of PAD_KEYS) {
    const b = document.createElement("button");
    b.textContent = key;
    b.onclick = () => { localLabels[k] = key; pad.classList.add("hidden"); renderCards(); };
    pad.append(b);
  }
  const clear = document.createElement("button");
  clear.textContent = "clear"; clear.className = "wide2";
  clear.onclick = () => { delete localLabels[k]; pad.classList.add("hidden"); renderCards(); };
  pad.append(clear);
  const close = document.createElement("button");
  close.textContent = "close"; close.className = "wide2";
  close.onclick = () => pad.classList.add("hidden");
  pad.append(close);
  pad.classList.remove("hidden");
  card.scrollIntoView({ block: "center", behavior: "smooth" });
}

$("ask-ai").onclick = async () => {
  renderCards.suggested = false;
  $("ask-ai").textContent = "Asking…";
  await api(`/api/runs/${runId}/suggest`, { method: "POST" });
};

$("build").onclick = async () => {
  const missing = [];
  for (let i = 0; i < state.clusters; i++) if (!localLabels[String(i)]) missing.push(i);
  if (missing.length && !confirm(`${missing.length} shape(s) have no name yet — they'll be treated as unknown ("?" in the tab). Continue?`)) return;
  await api(`/api/runs/${runId}/labels`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ labels: localLabels }),
  });
  show("busy");
};

/* ---------------- chord mode ---------------- */

// mirror of diagram_chord in extract_cv.py, for the live preview only —
// the authoritative build happens in Python when you hit Build
function previewFrets(d, fr, flip) {
  const away = d.marks_side === "right";
  const marks = Object.fromEntries(d.marks);
  const out = ["x", "x", "x", "x", "x", "x"];   // physical strings, low E first
  for (let si = 0; si < 6; si++) {
    const phys = flip ? 5 - si : si;
    const cols = d.dots.filter(([s]) => s === si).map(([, c]) => c);
    if (cols.length) {
      const col = away ? Math.max(...cols) : Math.min(...cols);
      out[phys] = String(fr + (away ? d.ncols - 1 - col : col));
    } else if (marks[si] === "o") {
      out[phys] = "0";
    }
  }
  return out.join(" ");
}

function renderChordCards() {
  const wrap = $("chord-cards");
  wrap.innerHTML = "";
  const flip = $("flip-strings").checked;
  let missing = 0;
  state.diagrams.forEach((d, i) => {
    const cur = localChords[i];
    if (!cur.fr) missing++;
    const card = document.createElement("div");
    card.className = "ccard";
    const frVal = parseInt(cur.fr, 10);
    card.innerHTML = `
      <img src="/api/runs/${runId}/file/debug/${d.crop}" alt="chord diagram ${i + 1}">
      <div class="frets ${cur.fr ? "" : "bad"}">${cur.fr ? escapeHtml(previewFrets(d, frVal, flip)) : "Fr needed → ?"}</div>
      <label>Name <input class="c-name" value="${escapeHtml(cur.name)}" placeholder="e.g. Bm7"></label>
      <label>Fr (base fret) <input class="c-fr" type="number" min="1" max="24" value="${escapeHtml(String(cur.fr))}"></label>
      <div class="sight">seen ${d.sightings}× at ${d.ts}s</div>`;
    card.querySelector(".c-name").addEventListener("input", ev => { cur.name = ev.target.value; });
    card.querySelector(".c-fr").addEventListener("input", ev => {
      cur.fr = ev.target.value;
      const v = parseInt(cur.fr, 10);
      const el2 = card.querySelector(".frets");
      el2.textContent = v >= 1 ? previewFrets(d, v, $("flip-strings").checked) : "Fr needed → ?";
      el2.classList.toggle("bad", !(v >= 1));
      $("chords-progress").textContent = progressText();
    });
    wrap.append(card);
  });
  $("chords-progress").textContent = progressText();
  function progressText() {
    const m = localChords.filter(c => !(parseInt(c.fr, 10) >= 1)).length;
    return m ? `${m} still need a fret` : "all confirmed";
  }
}

$("flip-strings").addEventListener("change", () => renderChordCards());

$("chords-ai").onclick = async () => {
  renderChordCards.suggested = false;
  $("chords-ai").textContent = "Asking…";
  await api(`/api/runs/${runId}/suggest`, { method: "POST" });
};

$("chords-build").onclick = async () => {
  const bad = localChords.filter(c => !(parseInt(c.fr, 10) >= 1)).length;
  if (bad) { alert(`${bad} diagram(s) still need their Fr number.`); return; }
  await api(`/api/runs/${runId}/chords`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      frets: localChords.map(c => parseInt(c.fr, 10)),
      names: localChords.map(c => c.name.trim()),
      flip: $("flip-strings").checked,
    }),
  });
  show("busy");
};

/* ---------------- check + publish ---------------- */

function renderCheck() {
  $("video").src = `/api/runs/${runId}/file/${state.video}`;
  const pages = $("pages");
  pages.innerHTML = "";
  state.pages.forEach((p, i) => {
    const pre = document.createElement("pre");
    pre.textContent = p.ascii;
    const img = document.createElement("img");
    img.src = `/api/runs/${runId}/file/debug/${p.annotated}`;
    img.alt = `page ${i + 1} with detected notes boxed`;
    img.loading = "lazy";
    pages.append(pre, img);
  });
  const fl = $("flags");
  if (state.flags.length) {
    fl.innerHTML = "<b>Worth a look:</b> " + state.flags.map(f => {
      const bits = [];
      if (f.boundary) bits.push(`bar ${f.boundary} by the pipeline`);
      else if (f.suspect) bits.push("unusual width");
      if (f.repeat_of) bits.push(`looks like a repeat of measure ${f.repeat_of}`);
      return `measure ${f.measure} (${bits.join("; ")})`;
    }).join(" · ");
  } else fl.textContent = "No warnings from the pipeline.";
}

$("relabel").onclick = async () => {
  const back = state.mode === "chords" ? "back-to-chords" : "back-to-labels";
  await api(`/api/runs/${runId}/${back}`, { method: "POST" });
  lastStep = null;
};

$("to-publish").onclick = () => {
  const m = state.meta || {};
  if (m.title) $("m-title").value = m.title;
  if (m.artist) $("m-artist").value = String(m.artist).replace(/\s*\.\.\.$/, "");
  if (m.capo) $("m-capo").value = m.capo;
  if (m.tuning && !/standard/i.test(m.tuning)) $("m-tuning").value = m.tuning;
  if (m.time_signature) $("m-tsig").value = m.time_signature;
  show("publish");
};

$("publish").onclick = async () => {
  const title = $("m-title").value.trim();
  if (!title) { $("m-title").focus(); return; }
  await api(`/api/runs/${runId}/publish`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      push: $("m-push").checked,
      meta: {
        title, artist: $("m-artist").value.trim(),
        capo: parseInt($("m-capo").value, 10) || 0,
        tuning: $("m-tuning").value.trim().toUpperCase() || "EADGBE",
        time_signature: $("m-tsig").value.trim(),
      },
    }),
  });
  show("busy");
};

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

show("start");
