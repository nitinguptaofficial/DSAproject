"use strict";

/*
 * FloodGuard dashboard.
 *
 * Rendering is kept light so a 50x50 city (2,500 nodes, 4,900 roads) stays
 * fast:
 *   - terrain + water are ONE raster image (one pixel per intersection,
 *     smoothly scaled up by the browser);
 *   - all roads of one severity are ONE <path>; all nodes are ONE <path>;
 *   - hover and click use a single listener on the <svg>: the pointer
 *     position is converted to grid coordinates to find the node/road;
 *   - selecting nodes or drawing routes only redraws a small overlay.
 */

const state = {
  network: null,
  nodes: {}, // id -> node
  edges: new Map(), // "u|v" (sorted) -> edge
  dangerous: [], // top flooded roads
  history: [], // per-hour stats from the server
  routes: null, // { safest, shortest }
  selFrom: null,
  selTo: null,
  selectsFor: null, // grid size the dropdowns were built for
  playing: false,
  show: { terrain: true, water: true, roads: true, storm: true },
};

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const SEVERITIES = ["safe", "caution", "warning", "danger"];

const GRID_SPACING = 30; // px between grid nodes in the SVG coordinate space
const TICK_HOURS = 1; // simulated hours per step
const PLAY_DELAY_MS = 350; // pause between hours while playing
const MIN_TIMELINE_HOURS = 12; // the timeline always spans at least this long

// Colour ramps for the raster (keep in sync with .water-scale / .swatch-terrain)
const TERRAIN_LOW = [16, 30, 34]; // valley floor
const TERRAIN_HIGH = [58, 70, 56]; // hill tops
const WATER_SHALLOW = [30, 86, 160];
const WATER_DEEP = [150, 215, 255];
const WATER_FULL_M = 0.75; // depth that reaches the brightest blue

// SVG layers, created once per grid size
const layers = {};

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (res.status === 404 && path.startsWith("/api/")) {
    // the page is newer than the running server (static files are read from
    // disk on every request, but Python code only loads at startup)
    throw new Error(
      "The server is running an older version. Stop it (Ctrl+C) and run " +
        "py -3 run_server.py again, then refresh this page.",
    );
  }
  if (!res.ok || data.error) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function createEl(tag, attrs, parent) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const lerp = (a, b, t) => a + (b - a) * t;

// ------------------------------------------------------------------ //
// Geometry
// ------------------------------------------------------------------ //
function gridDims() {
  return state.network.dims;
}

function viewBox() {
  const { rows, cols } = gridDims();
  const W = (cols - 1) * GRID_SPACING;
  const H = (rows - 1) * GRID_SPACING;
  const pad = GRID_SPACING * 1.1;
  const stepX = (W - 2 * pad) / Math.max(1, cols - 1);
  const stepY = (H - 2 * pad) / Math.max(1, rows - 1);
  return { W, H, pad, stepX, stepY };
}

function gridToXY(row, col) {
  const { pad, stepX, stepY } = viewBox();
  return { x: pad + col * stepX, y: pad + row * stepY };
}

function nodeXY(id) {
  const n = state.nodes[id];
  return gridToXY(n.row, n.col);
}

const edgeKey = (u, v) => (u < v ? `${u}|${v}` : `${v}|${u}`);
const nodeId = (r, c) => `n${r}_${c}`;

function isDense() {
  const { rows, cols } = gridDims();
  return rows * cols > 150;
}

/** SVG path data for a small circle (two arcs), for batching many dots. */
function circlePath(x, y, r) {
  return `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
}

// ------------------------------------------------------------------ //
// Map layers
// ------------------------------------------------------------------ //
function buildLayers() {
  const svg = $("map");
  const { W, H } = viewBox();
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";

  const defs = createEl("defs", {}, svg);
  // diagonal rain streaks used to fill the storm cell
  const rain = createEl(
    "pattern",
    { id: "rainStreaks", width: 14, height: 14, patternUnits: "userSpaceOnUse", patternTransform: "rotate(20)" },
    defs,
  );
  createEl("line", { x1: 4, y1: 0, x2: 4, y2: 8, class: "rain-streak" }, rain);
  createEl("line", { x1: 11, y1: 6, x2: 11, y2: 14, class: "rain-streak" }, rain);

  createEl("rect", { x: 0, y: 0, width: W, height: H, class: "map-bg" }, svg);

  layers.raster = createEl("image", { preserveAspectRatio: "none" }, svg);
  layers.edgeGroup = createEl("g", { class: "edge-layer" }, svg);
  layers.edges = {};
  for (const sev of SEVERITIES) {
    layers.edges[sev] = createEl("path", { class: `edges ${sev}` }, layers.edgeGroup);
  }
  layers.nodes = createEl("path", { class: "nodes" }, svg);
  layers.storm = createEl("g", { class: "storm" }, svg);
  layers.overlay = createEl("g", { class: "overlay" }, svg);
  layers.hover = createEl("g", { class: "hover" }, svg);

  layers.builtFor = `${gridDims().rows}x${gridDims().cols}`;
}

/** Redraw everything that depends on flood state (once per data refresh). */
function renderMap() {
  const dims = `${gridDims().rows}x${gridDims().cols}`;
  if (layers.builtFor !== dims) buildLayers();

  renderRaster();

  const paths = { safe: [], caution: [], warning: [], danger: [] };
  for (const e of state.network.edges) {
    const a = nodeXY(e.u);
    const b = nodeXY(e.v);
    (paths[e.severity] || paths.safe).push(`M${a.x} ${a.y}L${b.x} ${b.y}`);
  }
  for (const sev of SEVERITIES) {
    layers.edges[sev].setAttribute("d", paths[sev].join(""));
  }

  const r = isDense() ? 1.8 : 5;
  layers.nodes.setAttribute(
    "d",
    state.network.nodes
      .map((n) => {
        const { x, y } = gridToXY(n.row, n.col);
        return circlePath(x, y, r);
      })
      .join(""),
  );

  renderStorm();
  applyLayerVisibility();
  renderOverlay();
}

/** Terrain + water as one small image: one pixel per intersection. */
function renderRaster() {
  const { rows, cols } = gridDims();
  const { pad, stepX, stepY } = viewBox();
  const canvas = document.createElement("canvas");
  canvas.width = cols;
  canvas.height = rows;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(cols, rows);
  const px = img.data;

  for (const n of state.network.nodes) {
    const i = (n.row * cols + n.col) * 4;
    let rgb = [0, 0, 0];
    let alpha = 0;
    if (state.show.terrain) {
      rgb = TERRAIN_LOW.map((lo, k) => lerp(lo, TERRAIN_HIGH[k], n.elevation));
      alpha = 1;
    }
    if (state.show.water && n.water >= 0.01) {
      const t = Math.min(1, n.water / WATER_FULL_M);
      const w = WATER_SHALLOW.map((lo, k) => lerp(lo, WATER_DEEP[k], t));
      const a = 0.45 + 0.55 * t; // deeper water is more opaque
      rgb = rgb.map((c, k) => lerp(c, w[k], a));
      alpha = Math.max(alpha, a);
    }
    px[i] = rgb[0];
    px[i + 1] = rgb[1];
    px[i + 2] = rgb[2];
    px[i + 3] = Math.round(alpha * 255);
  }
  ctx.putImageData(img, 0, 0);

  const el = layers.raster;
  el.setAttribute("href", canvas.toDataURL());
  el.setAttribute("x", pad - stepX / 2);
  el.setAttribute("y", pad - stepY / 2);
  el.setAttribute("width", cols * stepX);
  el.setAttribute("height", rows * stepY);
}

/** Draw every active storm: tinted disc + rain streaks + a heading label. */
function renderStorm() {
  const g = layers.storm;
  g.innerHTML = "";
  const { stepX } = viewBox();
  for (const s of state.network.storms || []) {
    if (s.intensity <= 0) continue;
    const c = gridToXY(s.row, s.col);
    const r = s.radius * stepX;
    const strength = Math.min(1, s.intensity);
    createEl(
      "circle",
      { cx: c.x, cy: c.y, r, class: "storm-cell", "fill-opacity": 0.06 + 0.12 * strength },
      g,
    );
    createEl(
      "circle",
      { cx: c.x, cy: c.y, r, class: "storm-rain", opacity: 0.25 + 0.6 * strength },
      g,
    );
    createEl("text", { x: c.x, y: c.y - r - 8, class: "storm-label" }, g).textContent =
      `${s.intensity >= 1.1 ? "extreme storm" : "storm"} · rain ${s.intensity.toFixed(2)} · moving ${s.heading}`;
  }
}

function applyLayerVisibility() {
  layers.edgeGroup.style.display = state.show.roads ? "" : "none";
  layers.storm.style.display = state.show.storm ? "" : "none";
}

/** Redraw routes + selected endpoints only (cheap; runs on every click). */
function renderOverlay() {
  const g = layers.overlay;
  if (!g) return;
  g.innerHTML = "";
  const routes = state.routes;
  layers.edgeGroup.classList.toggle("dimmed", !!routes);
  const dense = isDense();
  const r = dense ? 3 : 6;
  const lineD = (route) =>
    route.path
      .map(nodeXY)
      .map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`)
      .join("");

  if (routes) {
    // shortest first (dashed, underneath), then the safest on top
    createEl("path", { d: lineD(routes.shortest), class: "route-shortest" }, g);
    const safeD = lineD(routes.safest);
    createEl("path", { d: safeD, class: "route-glow" }, g);
    createEl("path", { d: safeD, class: "route-line" }, g);
  }

  for (const [id, kind] of [
    [state.selFrom, "from"],
    [state.selTo, "to"],
  ]) {
    if (!id || !state.nodes[id]) continue;
    const { x, y } = nodeXY(id);
    createEl("circle", { cx: x, cy: y, r: r + 7, class: `halo ${kind}` }, g);
    createEl("circle", { cx: x, cy: y, r: r + 1.5, class: `endpoint ${kind}` }, g);
    createEl(
      "text",
      { x, y: y + (dense ? 16 : 20), class: "node-label" },
      g,
    ).textContent = (kind === "from" ? "Start " : "End ") + id;
  }
}

// ------------------------------------------------------------------ //
// Map pointer: one listener for the whole map
// ------------------------------------------------------------------ //
function pointerToGrid(ev) {
  const svg = $("map");
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  const { pad, stepX, stepY } = viewBox();
  return { row: (p.y - pad) / stepY, col: (p.x - pad) / stepX };
}

/** Return the node or road under the pointer, or null. */
function hitTest(ev) {
  if (!state.network) return null;
  const { rows, cols } = gridDims();
  const { row, col } = pointerToGrid(ev);
  const r = Math.round(row);
  const c = Math.round(col);
  if (r < 0 || c < 0 || r >= rows || c >= cols) return null;
  const dr = Math.abs(row - r);
  const dc = Math.abs(col - c);
  if (Math.hypot(dr, dc) < 0.3) return { type: "node", id: nodeId(r, c) };
  if (dr > 0.25 && dc > 0.25) return null; // inside a city block
  // nearer a horizontal road (same row) or a vertical road (same column)?
  let u;
  let v;
  if (dr <= dc) {
    const c0 = Math.floor(col);
    u = nodeId(r, c0);
    v = nodeId(r, c0 + 1);
  } else {
    const r0 = Math.floor(row);
    u = nodeId(r0, c);
    v = nodeId(r0 + 1, c);
  }
  const edge = state.edges.get(edgeKey(u, v));
  return edge ? { type: "edge", edge } : null;
}

function terrainWord(elev) {
  if (elev < 0.35) return "low ground (water collects here)";
  if (elev < 0.55) return "gentle slope";
  return "high ground (drains quickly)";
}

function nodeTip(id) {
  const n = state.nodes[id];
  return (
    `<div class="tt-title">Intersection ${n.id}</div>` +
    `<div class="tt-row"><span class="tt-muted">water</span><span>${(n.water * 100).toFixed(0)} cm</span></div>` +
    `<div class="tt-row"><span class="tt-muted">terrain</span><span>${terrainWord(n.elevation)}</span></div>` +
    `<div class="tt-hint">Click to set as start / end</div>`
  );
}

function edgeTip(e) {
  const factor = 1 + 6 * e.depth;
  return (
    `<div class="tt-title">Road ${e.u} ↔ ${e.v}</div>` +
    `<div class="tt-row"><span class="tt-muted">water</span><span>${(e.depth * 100).toFixed(0)} cm</span></div>` +
    `<div class="tt-row"><span class="tt-muted">level</span><span class="sev ${e.severity}">${e.severity}</span></div>` +
    `<div class="tt-row"><span class="tt-muted">route cost</span><span>×${factor.toFixed(1)}</span></div>`
  );
}

function showHover(hit) {
  const g = layers.hover;
  if (!g) return; // map not built yet
  g.innerHTML = "";
  if (!hit) return;
  if (hit.type === "node") {
    const { x, y } = nodeXY(hit.id);
    createEl("circle", { cx: x, cy: y, r: isDense() ? 6 : 10, class: "hover-ring" }, g);
  } else {
    const a = nodeXY(hit.edge.u);
    const b = nodeXY(hit.edge.v);
    createEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "hover-road" }, g);
  }
}

let pendingMove = null;
function onMapPointerMove(ev) {
  // coalesce mouse moves to at most one update per animation frame
  if (pendingMove === null) {
    requestAnimationFrame(() => {
      const e = pendingMove;
      pendingMove = null;
      if (!e) return;
      const hit = hitTest(e);
      showHover(hit);
      if (!hit) return hideTip();
      showTip(
        hit.type === "node" ? nodeTip(hit.id) : edgeTip(hit.edge),
        e.clientX,
        e.clientY,
      );
    });
  }
  pendingMove = ev;
}

function onMapPointerLeave() {
  pendingMove = null;
  if (layers.hover) layers.hover.innerHTML = "";
  hideTip();
}

function onMapClick(ev) {
  if (!state.network) return;
  const { rows, cols } = gridDims();
  const { row, col } = pointerToGrid(ev);
  const r = Math.round(row);
  const c = Math.round(col);
  if (r < 0 || c < 0 || r >= rows || c >= cols) return;
  if (Math.hypot(row - r, col - c) > 0.45) return;
  handleNodeClick(nodeId(r, c));
}

// ------------------------------------------------------------------ //
// "What is happening" caption
// ------------------------------------------------------------------ //
/** "north-west", "south", "centre" ... for a grid position. */
function placeWord(row, col) {
  const { rows, cols } = gridDims();
  const ns = row < rows / 3 ? "north" : row > (2 * rows) / 3 ? "south" : "";
  const ew = col < cols / 3 ? "west" : col > (2 * cols) / 3 ? "east" : "";
  return ns && ew ? `${ns}-${ew}` : ns || ew || "centre";
}

/** One or two sentences about the weather right now. */
function describeWeather(net) {
  const { rows, cols } = gridDims();
  const storms = (net.storms || [])
    .filter((s) => s.intensity > 0)
    .sort((a, b) => b.intensity - a.intensity);
  if (!storms.length) {
    const wait = Math.max(1, Math.round(net.next_storm_in || 0));
    return `No rain right now. The next storm arrives in about ${wait} hour${wait === 1 ? "" : "s"}.`;
  }
  const s = storms[0];
  const extreme = s.intensity >= 1.1;
  let stage;
  if (s.progress < 0.3) stage = extreme ? "An extreme storm is building" : "A storm is building";
  else if (s.progress < 0.7) stage = extreme ? "An extreme storm is at its strongest" : "The storm is at its strongest";
  else stage = "The storm is passing and the rain is easing";
  const outside = s.row < 0 || s.col < 0 || s.row >= rows || s.col >= cols;
  const where = outside
    ? `just outside the city to the ${placeWord(s.row, s.col)}`
    : placeWord(s.row, s.col) === "centre"
      ? "over the city centre"
      : `over the ${placeWord(s.row, s.col)} of the city`;
  const others = storms.length > 1 ? ` ${storms.length} storms are raining at once.` : "";
  return `${stage}, ${where}, moving ${s.heading}.${others}`;
}

function renderStory(stats) {
  const net = state.network;
  const c = stats.severity_counts;
  if (net.time === 0) {
    const wait = Math.max(1, Math.round(net.next_storm_in || 1));
    $("story").innerHTML =
      `<b>City #${net.seed}.</b> The city is dry; a storm is on its way (about ${wait} hour${wait === 1 ? "" : "s"}). ` +
      "Press <b>▶ Play</b> to start and watch the water spread.";
    return;
  }
  let text = `<b>Hour ${Math.round(net.time)}.</b> ${describeWeather(net)} `;

  if (c.danger + c.warning + c.caution === 0) {
    text += "All roads are still safe to drive.";
  } else {
    const parts = [];
    if (c.danger) parts.push(`<i class="dot danger"></i> <b>${c.danger}</b> roads are impassable`);
    if (c.warning) parts.push(`<i class="dot warning"></i> <b>${c.warning}</b> are only passable for tall vehicles`);
    if (c.caution) parts.push(`<i class="dot caution"></i> <b>${c.caution}</b> need caution`);
    text += parts.join(", ") + ".";
  }

  // trend vs. the previous hour
  const h = state.history;
  if (h.length >= 2) {
    const now = h[h.length - 1];
    const before = h[h.length - 2];
    const bad = (x) => x.danger + x.warning;
    const diff = bad(now) - bad(before);
    if (diff > 0) text += ` Flooding is <b>rising</b> (+${diff} serious roads this hour).`;
    else if (diff < 0) text += ` Flooding is <b>receding</b> (${diff} serious roads this hour).`;
  }

  const deepest = state.dangerous[0];
  if (deepest && deepest.depth >= 0.05) {
    text += ` Deepest water: <b>${(deepest.depth * 100).toFixed(0)} cm</b> on ${deepest.u} ↔ ${deepest.v}.`;
  }
  $("story").innerHTML = text;
}

// ------------------------------------------------------------------ //
// Timeline: flooded roads (stacked) and rain (separate panel, own axis)
// ------------------------------------------------------------------ //
const TL_SERIES = [
  // bottom of the stack first: the most serious level sits on the baseline
  { key: "danger", label: "danger" },
  { key: "warning", label: "warning" },
  { key: "caution", label: "caution" },
];

function niceMax(v) {
  if (v <= 10) return 10;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

function renderTimeline() {
  const box = $("timeline");
  const h = state.history;
  const W = Math.max(320, box.clientWidth || 600);
  const M = { l: 44, r: 64, t: 10 };
  const topH = 150;
  const gap = 26;
  const rainH = 56;
  const H = M.t + topH + gap + rainH + 24;
  const iw = W - M.l - M.r;

  const t0 = h.length ? h[0].time : 0;
  const t1 = Math.max(h.length ? h[h.length - 1].time : 0, t0 + MIN_TIMELINE_HOURS);
  const x = (t) => M.l + ((t - t0) / (t1 - t0)) * iw;
  const totals = h.map((d) => d.danger + d.warning + d.caution);
  const yMax = niceMax(Math.max(10, ...totals));
  const y = (v) => M.t + topH - (v / yMax) * topH;
  const rainTop = M.t + topH + gap;
  // extreme storms rain harder than 1.0: stretch the axis in 0.5 steps
  const rainMax = Math.max(1, Math.ceil(Math.max(0, ...h.map((d) => d.intensity)) * 2) / 2);
  const yr = (v) => rainTop + rainH - (v / rainMax) * rainH;

  const legend =
    `<div class="tl-legend">` +
    TL_SERIES.map((s) => `<span><i class="dot ${s.key}"></i>${s.label}</span>`).join("") +
    `<span><i class="swatch-line rain"></i>rain intensity</span></div>`;
  let svg = `${legend}<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="Flooded roads and rain per hour">`;

  // recessive grid + y labels
  for (const v of [0, yMax / 2, yMax]) {
    svg += `<line class="tl-grid" x1="${M.l}" x2="${M.l + iw}" y1="${y(v)}" y2="${y(v)}"/>`;
    svg += `<text class="tl-axis" x="${M.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  svg += `<text class="tl-axis" x="${M.l}" y="${M.t - 1}">flooded roads</text>`;
  for (const v of rainMax > 1 ? [0, 1, rainMax] : [0, 1]) {
    svg += `<line class="tl-grid" x1="${M.l}" x2="${M.l + iw}" y1="${yr(v)}" y2="${yr(v)}"/>`;
    svg += `<text class="tl-axis" x="${M.l - 6}" y="${yr(v) + 4}" text-anchor="end">${v}</text>`;
  }
  svg += `<text class="tl-axis" x="${M.l}" y="${rainTop - 6}">rain intensity</text>`;

  // x ticks every 6 hours
  for (let t = Math.ceil(t0 / 6) * 6; t <= t1; t += 6) {
    svg += `<text class="tl-axis" x="${x(t)}" y="${H - 6}" text-anchor="middle">${t}h</text>`;
  }

  if (h.length >= 2) {
    // stacked areas
    let base = h.map(() => 0);
    for (const s of TL_SERIES) {
      const top = h.map((d, i) => base[i] + d[s.key]);
      const upper = h.map((d, i) => `${x(d.time)},${y(top[i])}`);
      const lower = h.map((d, i) => `${x(d.time)},${y(base[i])}`).reverse();
      svg += `<polygon class="tl-area ${s.key}" points="${upper.concat(lower).join(" ")}"/>`;
      // direct label at the right end when the band is tall enough
      const last = h.length - 1;
      const bandPx = y(base[last]) - y(top[last]);
      if (bandPx >= 12) {
        const mid = (y(base[last]) + y(top[last])) / 2;
        svg += `<text class="tl-label" x="${M.l + iw + 6}" y="${mid + 4}">${s.label}</text>`;
      }
      base = top;
    }
    // rain line
    const rainPts = h.map((d) => `${x(d.time)},${yr(d.intensity)}`).join(" ");
    svg += `<polyline class="tl-rain" points="${rainPts}"/>`;
  } else {
    svg += `<text class="tl-empty" x="${M.l + iw / 2}" y="${M.t + topH / 2}" text-anchor="middle">Press ▶ Play to start recording</text>`;
  }

  svg += `<line id="tl-cross" class="tl-cross" x1="0" x2="0" y1="${M.t}" y2="${yr(0)}" visibility="hidden"/>`;
  svg += `<rect class="tl-hit" x="${M.l}" y="${M.t}" width="${iw}" height="${yr(0) - M.t}"/>`;
  svg += "</svg>";
  box.innerHTML = svg;

  // crosshair + tooltip listing every series at the hovered hour
  const hit = box.querySelector(".tl-hit");
  const cross = box.querySelector("#tl-cross");
  hit.addEventListener("mousemove", (ev) => {
    if (h.length < 2) return;
    const svgEl = box.querySelector("svg");
    const pt = svgEl.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const p = pt.matrixTransform(svgEl.getScreenCTM().inverse());
    const t = t0 + ((p.x - M.l) / iw) * (t1 - t0);
    let best = 0;
    for (let i = 1; i < h.length; i++) {
      if (Math.abs(h[i].time - t) < Math.abs(h[best].time - t)) best = i;
    }
    const d = h[best];
    cross.setAttribute("x1", x(d.time));
    cross.setAttribute("x2", x(d.time));
    cross.setAttribute("visibility", "visible");
    showTip(
      `<div class="tt-title">Hour ${Math.round(d.time)}</div>` +
        `<div class="tt-row"><span><i class="dot danger"></i> danger</span><span>${d.danger}</span></div>` +
        `<div class="tt-row"><span><i class="dot warning"></i> warning</span><span>${d.warning}</span></div>` +
        `<div class="tt-row"><span><i class="dot caution"></i> caution</span><span>${d.caution}</span></div>` +
        `<div class="tt-row"><span class="tt-muted">rain</span><span>${d.intensity.toFixed(2)}</span></div>`,
      ev.clientX,
      ev.clientY,
    );
  });
  hit.addEventListener("mouseleave", () => {
    cross.setAttribute("visibility", "hidden");
    hideTip();
  });
}

// ------------------------------------------------------------------ //
// Data
// ------------------------------------------------------------------ //
async function refreshAll() {
  const [net, stats, dangerous, history] = await Promise.all([
    api("/api/network"),
    api("/api/stats"),
    api("/api/dangerous?limit=8"),
    // optional: the map still works if the timeline can't load
    api("/api/history").catch((err) => {
      if (!state.historyWarned) toast(err.message);
      state.historyWarned = true;
      return { history: [] };
    }),
  ]);
  state.network = net;
  state.nodes = Object.fromEntries(net.nodes.map((n) => [n.id, n]));
  state.edges = new Map(net.edges.map((e) => [edgeKey(e.u, e.v), e]));
  state.dangerous = dangerous.roads;
  state.history = history.history;
  renderMap();
  populateSelects();
  renderStats(stats);
  renderAlerts(dangerous.roads);
  renderStory(stats);
  renderTimeline();
  updateSimChips(net);
  // keep a planned trip up to date as the water moves
  if (state.routes) await compareRoutes({ quiet: true });
}

function populateSelects() {
  // node ids never change for a given grid, so build the options only once
  const dims = `${gridDims().rows}x${gridDims().cols}`;
  if (state.selectsFor === dims) return;
  state.selectsFor = dims;
  const ids = state.network.nodes.map((n) => n.id);
  const options = ids.map((id) => `<option value="${id}">${id}</option>`).join("");
  $("from-select").innerHTML = options;
  $("to-select").innerHTML = options;
  $("from-select").value = ids[0];
  $("to-select").value = ids[ids.length - 1];
}

function renderStats(s) {
  const c = s.severity_counts || {};
  $("stats").innerHTML = `
    <div class="stat ${c.danger ? "danger" : ""}"><div class="num">${c.danger || 0}</div><div class="lbl">danger roads</div></div>
    <div class="stat warning"><div class="num">${c.warning || 0}</div><div class="lbl">warning</div></div>
    <div class="stat caution"><div class="num">${c.caution || 0}</div><div class="lbl">caution</div></div>
    <div class="stat safe"><div class="num">${c.safe || 0}</div><div class="lbl">safe</div></div>
    <div class="stat"><div class="num">${s.flooded_roads}</div><div class="lbl">flooded</div></div>
    <div class="stat"><div class="num">${s.total_roads}</div><div class="lbl">total roads</div></div>`;
}

function renderAlerts(roads) {
  const ul = $("alerts");
  const real = roads.filter((r) => r.depth >= 0.05);
  if (!real.length) {
    ul.innerHTML = "<li class='caution'>No significant flooding right now.</li>";
    return;
  }
  ul.innerHTML = real
    .map(
      (r) => `
    <li class="${r.severity}">
      <span class="road">${r.u} ↔ ${r.v}</span>
      <div class="depth">${(r.depth * 100).toFixed(0)} cm · ${r.severity}</div>
    </li>`,
    )
    .join("");
}

function updateSimChips(net) {
  $("city-chip").textContent = `City #${net.seed}`;
  $("time-chip").textContent = "t = " + Math.round(net.time) + "h";
  $("rain-chip").textContent = "Rain: " + net.intensity.toFixed(2);
}

// ------------------------------------------------------------------ //
// Simulation controls
// ------------------------------------------------------------------ //
async function stepOnce() {
  await api(`/api/tick?hours=${TICK_HOURS}`, { method: "POST" });
  await refreshAll();
}

async function onStep() {
  $("tick-btn").disabled = true;
  try {
    await stepOnce();
  } catch (err) {
    toast(err.message);
  } finally {
    $("tick-btn").disabled = state.playing;
  }
}

function updatePlayButtons() {
  $("play-btn").textContent = state.playing ? "⏸ Pause" : "▶ Play";
  $("tick-btn").disabled = state.playing;
}

/** Start or stop playing. Stopping resolves once the current hour is done. */
async function togglePlay() {
  if (state.playing) {
    state.playing = false;
    updatePlayButtons();
    await state.playLoop;
    return;
  }
  state.playing = true;
  updatePlayButtons();
  state.playLoop = (async () => {
    while (state.playing) {
      try {
        await stepOnce();
      } catch (err) {
        toast(err.message);
        state.playing = false;
        updatePlayButtons();
        break;
      }
      await sleep(PLAY_DELAY_MS);
    }
  })();
}

/** Start over: a brand-new random city, or replay `seed` from hour 0. */
async function startCity(seed) {
  if (state.playing) await togglePlay(); // let the running hour finish first
  try {
    const query = seed ? `?seed=${encodeURIComponent(seed)}` : "";
    await api(`/api/reset${query}`, { method: "POST" });
    state.routes = null;
    $("route-result").innerHTML = "";
    await refreshAll();
    toast(seed ? `Replaying city #${state.network.seed}` : `New random city #${state.network.seed}`);
  } catch (err) {
    toast(err.message);
  }
}

// ------------------------------------------------------------------ //
// Routing: always compare the safest and the shortest route
// ------------------------------------------------------------------ //
function handleNodeClick(id) {
  // Click-to-select: first click sets start, second sets end, third resets.
  if (state.selFrom === null) {
    state.selFrom = id;
  } else if (state.selTo === null) {
    if (id === state.selFrom) {
      state.selFrom = null; // click same node again clears selection
      renderOverlay();
      return;
    }
    state.selTo = id;
  } else {
    // both set: start over with this node as the new start
    state.selFrom = id;
    state.selTo = null;
    state.routes = null;
    $("route-result").innerHTML = "";
  }

  // keep the dropdowns in sync
  if (state.selFrom) $("from-select").value = state.selFrom;
  if (state.selTo) $("to-select").value = state.selTo;

  renderOverlay();

  // compare routes once both endpoints are chosen
  if (state.selFrom && state.selTo) {
    compareRoutes();
  }
}

async function compareRoutes({ quiet = false } = {}) {
  // dropdowns are kept in sync with map clicks, so they are the source of truth
  const from = $("from-select").value;
  const to = $("to-select").value;
  state.selFrom = from;
  state.selTo = to;
  const algo = $("algo-select").value;
  const url = (strategy) =>
    `/api/route?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&strategy=${strategy}&algo=${algo}`;
  $("route-btn").disabled = true;
  try {
    const [safest, shortest] = await Promise.all([api(url("safest")), api(url("shortest"))]);
    state.routes = { safest, shortest };
    renderRouteComparison(safest, shortest);
  } catch (err) {
    if (!quiet) toast(err.message);
    state.routes = null;
  } finally {
    renderOverlay();
    $("route-btn").disabled = false;
  }
}

function summarize(route) {
  const counts = { safe: 0, caution: 0, warning: 0, danger: 0 };
  let deepest = 0;
  for (const h of route.hops) {
    counts[h.severity] += 1;
    deepest = Math.max(deepest, h.depth);
  }
  return { blocks: route.hops.length, counts, deepest };
}

function profileStrip(route) {
  // one coloured cell per road along the route: a quick picture of the trip
  return `<div class="profile" title="Each block is one road along the route">${route.hops
    .map((h) => `<i class="${h.severity}"></i>`)
    .join("")}</div>`;
}

function routeCard(kind, route, s) {
  const flooded = [];
  for (const sev of ["danger", "warning", "caution"]) {
    if (s.counts[sev]) flooded.push(`<span class="sev ${sev}">${s.counts[sev]} ${sev}</span>`);
  }
  return `
    <div class="route-card ${kind}">
      <div class="route-card-head">
        <i class="swatch-line ${kind}"></i>
        <b>${kind === "safest" ? "Safest route" : "Shortest route"}</b>
        <span class="muted">${s.blocks} blocks</span>
      </div>
      ${profileStrip(route)}
      <div class="route-card-meta">
        ${flooded.length ? flooded.join(" ") : '<span class="sev safe">all roads safe</span>'}
        <span class="muted">deepest water ${(s.deepest * 100).toFixed(0)} cm</span>
      </div>
    </div>`;
}

function renderRouteComparison(safest, shortest) {
  const a = summarize(safest);
  const b = summarize(shortest);
  const same = safest.path.join() === shortest.path.join();
  let verdict;
  if (same) {
    verdict =
      a.counts.danger + a.counts.warning === 0
        ? "Both routes are the same: there is no deep water in the way."
        : `There is no way around: the only route crosses ${a.counts.danger} impassable and ${a.counts.warning} warning roads. Better not to travel now.`;
  } else {
    const extra = a.blocks - b.blocks;
    const avoided = [];
    const dd = b.counts.danger - a.counts.danger;
    const dw = b.counts.warning - a.counts.warning;
    if (dd > 0) avoided.push(`${dd} impassable`);
    if (dw > 0) avoided.push(`${dw} warning`);
    verdict =
      `The safest route is <b>${extra > 0 ? `${extra} blocks longer` : "just as long"}</b>` +
      (avoided.length ? ` but avoids <b>${avoided.join(" and ")}</b> roads.` : " and keeps you in shallower water.");
    if (a.counts.danger > 0) {
      verdict += ` Even so, it still crosses ${a.counts.danger} impassable roads.`;
    }
  }
  $("route-result").innerHTML = `
    <div class="verdict">${verdict}</div>
    ${routeCard("safest", safest, a)}
    ${routeCard("shortest", shortest, b)}
    <div class="muted small">Found with ${safest.algo === "astar" ? "A*" : "Dijkstra"} on the road graph.</div>`;
}

// ------------------------------------------------------------------ //
// Help dialog, tooltip, toast
// ------------------------------------------------------------------ //
function openHelp() {
  $("help").classList.remove("hidden");
  $("help-close").focus();
}

function closeHelp() {
  $("help").classList.add("hidden");
  try {
    localStorage.setItem("floodguard-help-seen", "1");
  } catch (e) {
    /* storage unavailable: the guide simply shows again next time */
  }
}

function helpSeen() {
  try {
    return localStorage.getItem("floodguard-help-seen") === "1";
  } catch (e) {
    return false;
  }
}

function showTip(html, x, y) {
  const tip = $("tooltip");
  tip.innerHTML = html;
  // keep the tooltip on screen near the right/bottom edges
  const w = tip.offsetWidth || 200;
  const h = tip.offsetHeight || 80;
  const left = x + 16 + w > window.innerWidth ? x - w - 12 : x + 16;
  const top = y + 16 + h > window.innerHeight ? y - h - 12 : y + 16;
  tip.style.left = left + "px";
  tip.style.top = top + "px";
  tip.classList.add("show");
}
function hideTip() {
  $("tooltip").classList.remove("show");
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3200);
}

// ------------------------------------------------------------------ //
// Wiring
// ------------------------------------------------------------------ //
const tipDiv = document.createElement("div");
tipDiv.id = "tooltip";
document.body.appendChild(tipDiv);

$("map").addEventListener("mousemove", onMapPointerMove);
$("map").addEventListener("mouseleave", onMapPointerLeave);
$("map").addEventListener("click", onMapClick);
$("route-btn").addEventListener("click", () => compareRoutes());
$("play-btn").addEventListener("click", togglePlay);
$("tick-btn").addEventListener("click", onStep);
$("reset-btn").addEventListener("click", () => startCity());
$("replay-btn").addEventListener("click", () => state.network && startCity(state.network.seed));
$("help-btn").addEventListener("click", openHelp);
$("help-close").addEventListener("click", closeHelp);
$("help").addEventListener("click", (ev) => {
  if (ev.target === $("help")) closeHelp(); // click on the backdrop
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("help").classList.contains("hidden")) closeHelp();
});
for (const box of document.querySelectorAll(".layer-toggles input")) {
  box.addEventListener("change", () => {
    state.show[box.dataset.layer] = box.checked;
    if (!state.network) return;
    renderRaster();
    applyLayerVisibility();
  });
}
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => state.network && renderTimeline(), 150);
});

refreshAll()
  .catch((err) => toast(err.message))
  .finally(() => $("map-msg").classList.add("hidden"));
if (!helpSeen()) openHelp();
