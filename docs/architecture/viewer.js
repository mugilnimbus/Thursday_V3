// Draws the model (model.js, read by load.js) in three views:
//   Structure  the system opened level by level (System, Containers, Components, Detail). Scroll opens one
//              level deeper at the pointer; double-click steps inside a box.
//   Journeys   one journey, data flow, or trace, drawn alone as a flow diagram (flow.js).
//   Data       every data item as a table (flow.js).
// The shared lists (kinds, levels, categories, palettes) come from schema.js; the rules from checks.js.
// Nothing here is project-specific: projects edit model.js, never this file.
(() => {
  'use strict';

  const A = window.ARCH;
  const S = A.S, M = A.M;

  // ------------------------------------------------------------------ sizes, in pixels at 100%

  const BOX_MIN_W = 214;   // a closed box is never narrower than this...
  const BOX_MAX_W = 300;   // ...or wider; a longer headline wraps to a second line instead
  const BOX_H = 88;        // a closed box with a one-line headline
  const DIAMOND_H = 112;   // a decision is drawn as a diamond, so it needs more height for the same text
  const LINE_H = 16;       // added for a second headline line
  const GAP_X = 96;        // between parts along the flow
  const GAP_Y = 48;        // between parts stacked in one column
  const ROW_GAP = 96;      // between the main line and a side band
  const PAD = 42;          // clear space inside an open box
  const HEAD = 38;         // the title band of an open box
  const PORT_H = 44;       // a stub that stands for something outside the box you stepped into
  const BAND_PAD = 26;     // clear space around the parts in a side band
  const FONT = 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif';
  // What each side band holds at the top of the system; a model can rename them with `lanes: { ... }`.
  const LANE_NAMES = { top: 'People and UI', left: 'Callers', right: 'Outside services', bottom: 'Monitoring' };

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const lerp = (a, b, k) => a + (b - a) * k;
  const kindLabel = k => (S.kinds[k] || { label: k }).label;

  // ------------------------------------------------------------------ preferences (per browser, optional)

  const readPref = key => { try { return localStorage.getItem('arch-model.' + key); } catch { return null; } };
  const writePref = (key, value) => {
    try {
      if (value === null) localStorage.removeItem('arch-model.' + key);
      else localStorage.setItem('arch-model.' + key, value);
    } catch { /* storage unavailable: keep the choice for this visit only */ }
  };

  // ------------------------------------------------------------------ the model, as load.js read it

  const nodes = A.parts, order = A.order, root = A.root;
  const edges = A.links;
  const report = window.ARCH_CHECK(A, null);   // the same rules as check.mjs, without the "code" path check

  const isLeaf = n => n.children.length === 0;
  const isOwnGap = n => n.status === 'open' || n.status === 'revisit';
  const isGap = isOwnGap;
  (function countGaps(n) {
    n.gaps = (n !== root && isGap(n) ? 1 : 0) + n.children.reduce((sum, c) => sum + countGaps(c), 0);
    return n.gaps;
  })(root);

  const within = (n, ancestor) => { for (let p = n; p; p = p.parent) if (p === ancestor) return true; return false; };
  const childOf = (box, n) => { for (let p = n; p; p = p.parent) if (p.parent === box) return p; return null; };
  const pathOf = n => { const out = []; for (let p = n; p && p !== root; p = p.parent) out.unshift(p); return out; };
  const longName = n => pathOf(n).map(p => p.name).join(' › ');

  // ------------------------------------------------------------------ theme: palette and light or dark

  const canvas = document.getElementById('canvas');
  const realCtx = canvas.getContext('2d');
  let ctx = realCtx;   // swapped for an SVG writer while a picture is saved
  const themeBtn = document.getElementById('theme');
  const prefersDark = matchMedia('(prefers-color-scheme: dark)');
  let themeChoice = readPref('theme') || 'auto';   // 'auto' follows the system
  let C = {};                                      // the colours in use

  const hexToRgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const mix = (fg, bg, k) => {
    const f = hexToRgb(fg), b = hexToRgb(bg);
    return '#' + f.map((v, i) => Math.round(v * k + b[i] * (1 - k)).toString(16).padStart(2, '0')).join('');
  };

  function applyTheme() {
    const mode = themeChoice === 'auto' ? (prefersDark.matches ? 'dark' : 'light') : themeChoice;
    const p = (S.palettes[M.palette] || S.palettes.violet)[mode];
    const base = mode === 'dark' ? p.bg : p.surface;
    // Boxes get a little more ink each level deeper, so nesting reads at a glance.
    const fills = (mode === 'dark' ? [0.04, 0.065, 0.09, 0.115, 0.14] : [0, 0.03, 0.055, 0.08, 0.105]).map(k => mix(p.text, base, k));
    C = { mode, ...p, fills, links: {} };
    for (const [k, v] of Object.entries(S.links)) C.links[k] = v.color[mode];
    const html = document.documentElement;
    html.dataset.theme = mode;
    for (const k of ['bg', 'surface', 'raised', 'border', 'text', 'muted', 'accent', 'warn']) html.style.setProperty('--' + k, p[k]);
    themeBtn.textContent = { auto: 'Theme: auto', light: 'Theme: light', dark: 'Theme: dark' }[themeChoice];
  }

  // ------------------------------------------------------------------ which box is in focus, and which are open

  // The diagram shows one box at a time: the whole system, or the box the reader stepped into.
  // Levels count from that box: level 1 shows its parts closed, level 2 opens them, and so on.
  let focus = null;                       // null: the whole system
  const base = () => focus || root;
  const inBase = n => n !== base() && within(n, base());
  const baseDepth = () => base().depth;
  const expanded = new Set();
  const isOpen = n => n === root || n === focus || expanded.has(n);
  const setLevel = lv => {
    expanded.clear();
    order.forEach(n => { if (!isLeaf(n) && inBase(n) && n.depth < baseDepth() + lv) expanded.add(n); });
  };
  const level = () => 1 + Math.max(0, ...[...expanded].filter(inBase).map(n => n.depth - baseDepth()));
  const maxLevel = () => 1 + Math.max(0, ...order.filter(n => !isLeaf(n) && inBase(n)).map(n => n.depth - baseDepth()));
  const atExactLevel = () => {
    const lv = level();
    return order.every(n => isLeaf(n) || !inBase(n) || expanded.has(n) === (n.depth - baseDepth() < lv));
  };
  const close = n => { order.forEach(k => { if (within(k, n)) expanded.delete(k); }); };
  const reveal = n => {
    let changed = false;
    for (const p of pathOf(n)) if (p !== n && inBase(p) && !expanded.has(p)) { expanded.add(p); changed = true; }
    return changed;
  };
  // The box that stands for a part right now: the part itself, or the first closed box around it.
  const rep = n => {
    for (const p of pathOf(n)) {
      if (p === n) break;
      if (within(base(), p)) continue;   // the focused box and everything around it count as open
      if (!expanded.has(p)) return p;
    }
    return n;
  };
  // Seen from inside the focused box, the outside part that `n` belongs to: the one beside the box or one of
  // its ancestors. Lines to anything outside end at a stub named after it.
  const neighbour = n => { let p = n; while (p.parent && !within(base(), p.parent)) p = p.parent; return p; };

  // The front-end contract (lines into and out of the UI) is always shown, so every screen stays
  // connected to what feeds it. The reader can hide it for a moment when a level gets crowded.
  let contractChoice = true;
  const contractShown = () => contractChoice;

  // ------------------------------------------------------------------ box sizes

  const font = (weight, px) => { ctx.font = `${weight} ${px}px ${FONT}`; };

  function fitText(text, maxW) {
    if (maxW <= 0) return '';
    if (ctx.measureText(text).width <= maxW) return text;
    let lo = 0, hi = text.length;
    while (lo < hi) {
      const m = (lo + hi + 1) >> 1;
      if (ctx.measureText(text.slice(0, m) + '…').width <= maxW) lo = m; else hi = m - 1;
    }
    return lo > 1 ? text.slice(0, lo) + '…' : '';
  }

  // Splits text into at most `maxLines` lines that fit `maxW`; the last line is shortened with … if needed.
  function wrapText(text, maxW, maxLines) {
    const words = text.split(/\s+/).filter(Boolean), lines = [];
    let line = '';
    for (let i = 0; i < words.length; i++) {
      const next = line ? line + ' ' + words[i] : words[i];
      if (ctx.measureText(next).width <= maxW || !line) { line = next; continue; }
      if (lines.length === maxLines - 1) { line = words.slice(i - line.split(' ').length).join(' '); break; }
      lines.push(fitText(line, maxW));
      line = words[i];
    }
    if (line) lines.push(fitText(line, maxW));
    return lines.slice(0, maxLines);
  }

  // A closed box is as wide as its name and headline need, between the two limits.
  // A decision is a diamond: the text sits in its middle half, so the box is wider and taller.
  function measureBox(n) {
    font(600, 14.5); const nameW = ctx.measureText(n.name).width;
    font(400, 12); const headW = ctx.measureText(n.headline).width;
    if (n.kind === 'decision' && isLeaf(n)) {
      const w = clamp(Math.ceil(Math.max(nameW, headW) * 1.9 + 24), 250, 360), textW = w * 0.52;
      const lines = wrapText(n.headline, textW, 2);
      n.box = { w, h: DIAMOND_H + (lines.length > 1 ? LINE_H : 0), lines, pad: (w - textW) / 2 };
      return;
    }
    const pad = n.kind === 'external' ? 26 : n.kind === 'event' && isLeaf(n) ? 30 : 15, extra = n.kind === 'queue' && isLeaf(n) ? 34 : 0;
    const w = clamp(Math.ceil(Math.max(nameW, headW) + pad * 2 + extra), BOX_MIN_W, BOX_MAX_W);
    const lines = wrapText(n.headline, w - pad * 2 - extra, 2);
    n.box = { w, h: BOX_H + (lines.length > 1 ? LINE_H : 0) + (n.kind === 'ui' && isLeaf(n) ? 8 : 0), lines, pad };
  }

  // ------------------------------------------------------------------ layout: positions for this level

  function computeLayout() {
    const forward = new Set(S.forward);

    const size = c => {
      if (!isOpen(c)) { c.w = c.box.w; c.h = c.box.h; return; }

      // Parts on the main line are ranked along the data flow. A part can instead sit on a side
      // (lane: 'top' | 'bottom' | 'left' | 'right'), so that what surrounds the system stays around it.
      const kids = c.children.filter(k => k.lane === 'main');
      kids.forEach(size);
      const idx = new Map(kids.map((k, i) => [k, i]));

      // The order along the line follows what moves forward (data, control, storage). Results,
      // errors and the rest decide it only where nothing else connects the parts.
      const out = kids.map(() => new Set());
      const link = all => {
        for (const e of edges) {
          if (!all && !forward.has(e.kind)) continue;
          const a = childOf(c, e.a), b = childOf(c, e.b);
          if (a && b && a !== b && idx.has(a) && idx.has(b)) out[idx.get(a)].add(idx.get(b));
        }
      };
      link(false);
      if (out.every(s => s.size === 0)) link(true);

      // Ignore connections that close a loop, then rank by longest path so the data reads left to right.
      const state = kids.map(() => 0), preds = kids.map(() => []);
      const dfs = u => {
        state[u] = 1;
        for (const v of out[u]) {
          if (state[v] === 1) continue;
          preds[v].push(u);
          if (!state[v]) dfs(v);
        }
        state[u] = 2;
      };
      kids.forEach((_, i) => { if (!state[i]) dfs(i); });
      const rank = kids.map(() => -1);
      const rankOf = v => rank[v] >= 0 ? rank[v] : (rank[v] = preds[v].length ? Math.max(...preds[v].map(rankOf)) + 1 : 0);
      kids.forEach((_, i) => rankOf(i));
      // Parts with no connections between them have no order to show, so they sit side by side.
      if (kids.length > 1 && out.every(s => s.size === 0)) kids.forEach((_, i) => { rank[i] = i; });

      // Columns by rank; inside a column, order by the average position of what feeds each part.
      const cols = [];
      kids.forEach((k, i) => (cols[rank[i]] = cols[rank[i]] || []).push(i));
      const pos = kids.map(() => 0);
      const bary = v => preds[v].length ? preds[v].reduce((s, u) => s + pos[u], 0) / preds[v].length : 1e3;
      cols.forEach((col, ci) => {
        if (ci) col.sort((p, q) => bary(p) - bary(q) || p - q);
        col.forEach((v, j) => { pos[v] = j; });
      });
      const colH = cols.map(col => col.reduce((s, v) => s + kids[v].h, 0) + GAP_Y * (col.length - 1));
      let inH = Math.max(0, ...colH), x = 0;
      cols.forEach((col, ci) => {
        const cw = Math.max(...col.map(v => kids[v].w));
        let y = (inH - colH[ci]) / 2;
        for (const v of col) { kids[v].x = x + (cw - kids[v].w) / 2; kids[v].y = y; y += kids[v].h + GAP_Y; }
        x += cw + GAP_X;
      });
      let inW = Math.max(0, x - GAP_X);

      // Side bands around the main line.
      const on = side => c.children.filter(k => k.lane === side);
      const row = list => {
        if (!list.length) return null;
        list.forEach(size);
        return { list, w: list.reduce((s, k) => s + k.w, 0) + GAP_X * (list.length - 1), h: Math.max(...list.map(k => k.h)) };
      };
      const column = list => {
        if (!list.length) return null;
        list.forEach(size);
        return { list, w: Math.max(...list.map(k => k.w)), h: list.reduce((s, k) => s + k.h, 0) + GAP_Y * (list.length - 1) };
      };
      const T = row(on('top')), B = row(on('bottom')), Lf = column(on('left')), Rt = column(on('right'));
      c.bands = [];
      if (T || B || Lf || Rt) {
        const midW = Math.max(inW, T ? T.w : 0, B ? B.w : 0);
        const midH = Math.max(inH, Lf ? Lf.h : 0, Rt ? Rt.h : 0);
        const lx = Lf ? Lf.w + GAP_X : 0, ty = T ? T.h + ROW_GAP : 0;
        kids.forEach(k => { k.x += lx + (midW - inW) / 2; k.y += ty + (midH - inH) / 2; });
        const putRow = (r, y) => {
          let bx = lx + (midW - r.w) / 2;
          for (const k of r.list) { k.x = bx; k.y = y + (r.h - k.h) / 2; bx += k.w + GAP_X; }
        };
        const putColumn = (r, x0) => {
          let by = ty + (midH - r.h) / 2;
          for (const k of r.list) { k.x = x0 + (r.w - k.w) / 2; k.y = by; by += k.h + GAP_Y; }
        };
        if (T) putRow(T, 0);
        if (B) putRow(B, ty + midH + ROW_GAP);
        if (Lf) putColumn(Lf, 0);
        if (Rt) putColumn(Rt, lx + midW + GAP_X);
        // A faint band behind each side, so the shape of the system reads at a glance.
        const b = BAND_PAD;
        if (T) c.bands.push({ side: 'top', x: lx - b, y: -b, w: midW + 2 * b, h: T.h + 2 * b });
        if (B) c.bands.push({ side: 'bottom', x: lx - b, y: ty + midH + ROW_GAP - b, w: midW + 2 * b, h: B.h + 2 * b });
        if (Lf) c.bands.push({ side: 'left', x: -b, y: ty + (midH - Lf.h) / 2 - b, w: Lf.w + 2 * b, h: Lf.h + 2 * b });
        if (Rt) c.bands.push({ side: 'right', x: lx + midW + GAP_X - b, y: ty + (midH - Rt.h) / 2 - b, w: Rt.w + 2 * b, h: Rt.h + 2 * b });
        inW = lx + midW + (Rt ? GAP_X + Rt.w : 0);
        inH = ty + midH + (B ? ROW_GAP + B.h : 0);
      }

      if (c === root) { c.w = inW; c.h = inH; c.ox = 0; c.oy = 0; return; }
      c.w = Math.max(inW + PAD * 2, 280);
      c.h = inH + HEAD + PAD * 2;
      c.ox = (c.w - inW) / 2;
      c.oy = HEAD + PAD;
    };

    const top = base();
    size(top);
    const R = new Map();
    const place = (c, ax, ay) => {
      R.set(c, { x: ax, y: ay, w: c.w, h: c.h, open: isOpen(c) });
      if (isOpen(c)) for (const k of c.children) place(k, ax + c.ox + k.x, ay + c.oy + k.y);
    };
    place(top, 0, 0);
    // Side bands are drawn only for the whole system, where the lanes mean what their names say.
    R.bands = top === root ? (top.bands || []).map(b => ({ ...b, x: b.x + top.ox, y: b.y + top.oy, label: (M.lanes || {})[b.side] || LANE_NAMES[b.side] })) : [];

    // Inside a focused box, everything outside it becomes a stub: incoming on the left, outgoing on the right.
    R.ports = [];
    if (focus) {
      const byKey = new Map();
      for (const e of edges) {
        const inA = within(e.a, focus), inB = within(e.b, focus);
        if (inA === inB) continue;
        const dir = inA ? 'out' : 'in', target = neighbour(inA ? e.b : e.a), key = dir + ':' + target.id;
        if (!byKey.has(key)) byKey.set(key, { id: 'port:' + key, port: true, dir, target, name: target.name, kind: target.kind, children: [], spec: {}, status: 'accepted', depth: 0 });
      }
      font(600, 13);
      for (const p of byKey.values()) { p.w = clamp(Math.ceil(ctx.measureText(p.name).width) + 70, 150, BOX_MAX_W); p.h = PORT_H; }
      const side = (list, x0, alignRight) => {
        const total = list.reduce((s, p) => s + p.h, 0) + GAP_Y * 0.5 * (list.length - 1);
        let y = (top.h - total) / 2;
        for (const p of list) {
          R.set(p, { x: alignRight ? x0 - p.w : x0, y, w: p.w, h: p.h, open: false, port: true });
          y += p.h + GAP_Y * 0.5;
        }
      };
      const ins = [...byKey.values()].filter(p => p.dir === 'in'), outs = [...byKey.values()].filter(p => p.dir === 'out');
      side(ins, -GAP_X, true);
      side(outs, top.w + GAP_X, false);
      R.ports = [...ins, ...outs];
      R.portFor = (dir, n) => byKey.get(dir + ':' + neighbour(n).id);
    }

    // The area everything takes up, for fitting it on screen, routing, and saving pictures.
    const rects = [...R.values(), ...R.bands];
    const x0 = Math.min(...rects.map(r => r.x)), y0 = Math.min(...rects.map(r => r.y));
    R.bounds = { x: x0, y: y0, w: Math.max(...rects.map(r => r.x + r.w)) - x0, h: Math.max(...rects.map(r => r.y + r.h)) - y0 };
    return R;
  }

  // ------------------------------------------------------------------ routing: right-angle lines around boxes

  // Every line is routed on a grid around the boxes, so no line runs through a box it does not belong
  // to. A line pays for each bend and for sharing a lane with a line already placed, which keeps lines
  // straight and side by side instead of on top of each other.
  function route(layout) {
    const hiddenNow = k => hidden.has(k) || (S.contract.includes(k) && !contractShown());
    const groups = new Map();
    for (const e of edges) {
      if (hiddenNow(e.kind)) continue;
      let a = rep(e.a), b = rep(e.b);
      if (focus) {
        // Inside a focused box, a line to anything outside ends at that thing's stub.
        const inA = within(e.a, focus), inB = within(e.b, focus);
        if (!inA && !inB) continue;
        if (!inA) a = layout.portFor('in', e.a);
        if (!inB) b = layout.portFor('out', e.b);
      }
      if (a === b || (!a.port && !b.port && (within(a, b) || within(b, a)))) continue;
      const key = a.id + '>' + b.id + '>' + e.kind + (e.async ? '>async' : '');
      if (!groups.has(key)) groups.set(key, { key, a, b, kind: e.kind, async: !!e.async, list: [] });
      groups.get(key).list.push(e);
    }

    const whole = layout.bounds, MARGIN = 72, CLEAR = 8, BEND = 6, SHARE = 5, CROSS = 1.2;
    let G = 12;
    while (((whole.w + MARGIN * 2) / G) * ((whole.h + MARGIN * 2) / G) > 420000) G += 4;
    const cols = Math.ceil((whole.w + MARGIN * 2) / G) + 1, rows = Math.ceil((whole.h + MARGIN * 2) / G) + 1, N = cols * rows;
    const OX = whole.x - MARGIN, OY = whole.y - MARGIN;   // where the grid starts
    const px = c => OX + c * G, py = r => OY + r * G;
    const col = x => Math.round((x - OX) / G), row = y => Math.round((y - OY) / G);

    // Cells covered by a closed box or a stub (plus a little clearance) cannot be crossed.
    const solid = [...layout.entries()].filter(([n, r]) => n !== root && !r.open);
    const owner = new Int32Array(N).fill(-1);
    solid.forEach(([, r], k) => {
      const c0 = Math.max(0, Math.ceil((r.x - CLEAR - OX) / G)), c1 = Math.min(cols - 1, Math.floor((r.x + r.w + CLEAR - OX) / G));
      const r0 = Math.max(0, Math.ceil((r.y - CLEAR - OY) / G)), r1 = Math.min(rows - 1, Math.floor((r.y + r.h + CLEAR - OY) / G));
      for (let y = r0; y <= r1; y++) for (let x = c0; x <= c1; x++) owner[y * cols + x] = k;
    });
    const usedH = new Uint8Array(N), usedV = new Uint8Array(N), portUse = new Uint8Array(N);
    const best = new Float32Array(N * 4), stamp = new Int32Array(N * 4), from = new Int32Array(N * 4);
    const DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];

    // Cells just outside a box, one step clear of it, where a line may leave or arrive.
    // A line ends on the part's own outline, not on its bounding box: the last straight run is
    // carried on until it meets the diamond, the cylinder's curve, or the pill's round end.
    // dir: 0 right, 1 bottom, 2 left, 3 top.
    const touch = (shape, r, dir, ax, ay) => {
      const cx = r.x + r.w / 2, cy = r.y + r.h / 2, hw = r.w / 2, hh = r.h / 2, vertical = dir % 2 === 1;
      if (shape === 'decision') {
        if (vertical) { const d = hh * (1 - Math.min(1, Math.abs(ax - cx) / hw)); return [ax, dir === 3 ? cy - d : cy + d]; }
        const d = hw * (1 - Math.min(1, Math.abs(ay - cy) / hh)); return [dir === 2 ? cx - d : cx + d, ay];
      }
      if (shape === 'store' && vertical) {
        const t = (ax - cx) / hw, k = Math.sqrt(Math.max(0, 1 - t * t));
        return [ax, dir === 3 ? r.y + STORE_RY - STORE_RY * k : r.y + r.h - STORE_RY + STORE_RY * k];
      }
      if (shape === 'event') {
        const R = Math.min(hh, hw);
        if (vertical) {
          const dx = Math.max(0, r.x + R - ax, ax - (r.x + r.w - R)), d = Math.sqrt(Math.max(0, R * R - dx * dx));
          return [ax, dir === 3 ? cy - d : cy + d];
        }
        const d = R - Math.sqrt(Math.max(0, R * R - (ay - cy) * (ay - cy)));
        return [dir === 2 ? r.x + d : r.x + r.w - d, ay];
      }
      return [ax, ay];
    };
    const ports = (r, n) => {
      const out = [];
      const shape = n.port ? 'event' : shapeOf(n, r);
      // A diamond's edges slope away from the box, so lines meet it only near the middle of each side.
      // A pill's top and bottom are flat only between its round ends.
      const mx = shape === 'decision' ? r.w * 0.3 : shape === 'event' ? Math.min(r.h / 2, r.w * 0.3) : Math.min(18, r.w * 0.2);
      const my = shape === 'decision' ? r.h * 0.3 : Math.min(14, r.h * 0.2);
      const c0 = col(r.x + mx), c1 = col(r.x + r.w - mx);
      const r0 = row(r.y + my), r1 = row(r.y + r.h - my);
      const top = Math.ceil((r.y - CLEAR - OY) / G) - 1, bot = Math.floor((r.y + r.h + CLEAR - OY) / G) + 1;
      const lef = Math.ceil((r.x - CLEAR - OX) / G) - 1, rig = Math.floor((r.x + r.w + CLEAR - OX) / G) + 1;
      const add = (c, w, dir, ax, ay) => {
        if (c >= 0 && c < cols && w >= 0 && w < rows && owner[w * cols + c] < 0) {
          const [tx, ty] = touch(shape, r, dir, ax, ay);
          out.push({ cell: w * cols + c, dir, ax: tx, ay: ty });
        }
      };
      for (let c = c0; c <= c1; c++) { add(c, top, 3, px(c), r.y); add(c, bot, 1, px(c), r.y + r.h); }
      for (let w = r0; w <= r1; w++) { add(lef, w, 2, r.x, py(w)); add(rig, w, 0, r.x + r.w, py(w)); }
      return out;
    };

    // A small binary heap for the search.
    const heap = [];
    const push = (f, s) => {
      heap.push([f, s]);
      let k = heap.length - 1;
      while (k > 0) {
        const q = (k - 1) >> 1;
        if (heap[q][0] <= heap[k][0]) break;
        [heap[q], heap[k]] = [heap[k], heap[q]];
        k = q;
      }
    };
    const pop = () => {
      const top = heap[0], last = heap.pop();
      if (heap.length) {
        heap[0] = last;
        let k = 0;
        for (;;) {
          let m = k;
          const l = k * 2 + 1, r2 = l + 1;
          if (l < heap.length && heap[l][0] < heap[m][0]) m = l;
          if (r2 < heap.length && heap[r2][0] < heap[m][0]) m = r2;
          if (m === k) break;
          [heap[m], heap[k]] = [heap[k], heap[m]];
          k = m;
        }
      }
      return top;
    };

    const centre = r => [r.x + r.w / 2, r.y + r.h / 2];
    // Short lines first: they have the fewest ways round.
    const queue = [...groups.values()].map(g => {
      const a = centre(layout.get(g.a)), b = centre(layout.get(g.b));
      g.span = Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]);
      return g;
    }).sort((p, q) => p.span - q.span);

    let run = 0;
    const out = [];
    for (const g of queue) {
      const ra = layout.get(g.a), rb = layout.get(g.b);
      const starts = ports(ra, g.a), goals = new Map(ports(rb, g.b).map(q => [q.cell, q]));
      run++;
      heap.length = 0;
      // Distance still to go, measured to the box the line is heading for.
      const h = cell => {
        const x = px(cell % cols), y = py((cell / cols) | 0);
        return (Math.max(rb.x - x, 0, x - rb.x - rb.w) + Math.max(rb.y - y, 0, y - rb.y - rb.h)) / G;
      };
      for (const s of starts) {
        const st = s.cell * 4 + s.dir, c = 1 + portUse[s.cell] * SHARE;
        if (stamp[st] !== run || c < best[st]) {
          stamp[st] = run; best[st] = c; from[st] = -1 - starts.indexOf(s);
          push(c + h(s.cell), st);
        }
      }
      let end = -1, endPort = null, budget = 90000;
      while (heap.length && budget-- > 0) {
        const [f, st] = pop(), cell = st >> 2, dir = st & 3;
        if (f - h(cell) > best[st] + 1e-3) continue;
        const goal = goals.get(cell);
        if (goal) { end = st; endPort = goal; break; }
        const cx = cell % cols, cy = (cell / cols) | 0;
        for (let d = 0; d < 4; d++) {
          if (d === (dir + 2) % 4) continue;
          const nx = cx + DX[d], ny = cy + DY[d];
          if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
          const nc = ny * cols + nx;
          if (owner[nc] >= 0) continue;
          const horiz = d % 2 === 0;
          let c = best[st] + 1 + (d !== dir ? BEND : 0)
            + (horiz ? usedH[nc] : usedV[nc]) * SHARE
            + (horiz ? usedV[nc] : usedH[nc]) * CROSS;
          const g2 = goals.get(nc);
          if (g2) c += portUse[nc] * SHARE + (d !== (g2.dir + 2) % 4 ? BEND : 0);
          const ns = nc * 4 + d;
          if (stamp[ns] === run && best[ns] <= c) continue;
          stamp[ns] = run; best[ns] = c; from[ns] = st;
          push(c + h(nc), ns);
        }
      }

      if (end < 0) {
        // No way round (the boxes touch, or the search ran out): fall back to a plain elbow.
        const a = centre(ra), b = centre(rb);
        g.pts = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]]];
      } else {
        const cells = [];
        let s = end;
        while (s >= 0) { cells.push(s); s = from[s]; }
        const start = starts[-1 - s];
        cells.reverse();
        const pts = [[start.ax, start.ay]];
        cells.forEach((st, k) => {
          const cell = st >> 2, d = st & 3, lanes = d % 2 === 0 ? usedH : usedV;
          pts.push([px(cell % cols), py((cell / cols) | 0)]);
          if (k) lanes[cell] = Math.min(250, lanes[cell] + 1);
        });
        const first = cells[0] >> 2;
        (start.dir % 2 === 0 ? usedH : usedV)[first]++;
        portUse[first]++;
        portUse[endPort.cell]++;
        pts.push([endPort.ax, endPort.ay]);
        // Drop the points that lie on a straight run.
        g.pts = pts.filter((q, k) => k === 0 || k === pts.length - 1
          || !((pts[k - 1][0] === q[0] && q[0] === pts[k + 1][0]) || (pts[k - 1][1] === q[1] && q[1] === pts[k + 1][1])));
      }
      out.push(g);
    }

    // Labels go on the longest segment that is free of boxes and of labels already placed.
    font(500, 10.5);
    const boxes = [...layout.entries()].filter(([n, r]) => n !== root && !r.open).map(([, r]) => r), placed = [];
    const seen = new Map();
    for (const g of out) for (const e of g.list) seen.set(e.text || e.label, (seen.get(e.text || e.label) || 0) + 1);
    for (const g of out) {
      g.text = g.list.length === 1 ? (g.list[0].text || g.list[0].label || '') : `${g.list.length} connections`;
      const tw = ctx.measureText(g.text).width + 14, ra = layout.get(g.a), rb = layout.get(g.b);
      const segs = g.pts.slice(0, -1)
        .map((p, i) => ({ p, q: g.pts[i + 1], len: Math.hypot(g.pts[i + 1][0] - p[0], g.pts[i + 1][1] - p[1]) }))
        .sort((s, t) => t.len - s.len);
      g.lab = { x: (segs[0].p[0] + segs[0].q[0]) / 2, y: (segs[0].p[1] + segs[0].q[1]) / 2, w: tw, show: false };
      if (!g.text || (g.list.length === 1 && seen.get(g.text) > 3)) continue;
      for (const s of segs) {
        const flat = Math.abs(s.p[1] - s.q[1]) < 1;
        if (flat ? tw > s.len * 0.94 : s.len < 30) continue;
        const x = (s.p[0] + s.q[0]) / 2, y = (s.p[1] + s.q[1]) / 2;
        const hit = r => x + tw / 2 > r.x - 2 && x - tw / 2 < r.x + r.w + 2 && y + 10 > r.y - 2 && y - 10 < r.y + r.h + 2;
        if (boxes.some(r => r !== ra && r !== rb && hit(r)) || placed.some(hit)) continue;
        g.lab = { x, y, w: tw, show: true };
        placed.push({ x: x - tw / 2, y: y - 9, w: tw, h: 18 });
        break;
      }
    }
    return out;
  }

  // ------------------------------------------------------------------ view state and camera

  const wrap = document.getElementById('wrap'), panel = document.getElementById('panel');
  const legend = document.getElementById('legend'), fitBtn = document.getElementById('fit');
  const contractBtn = document.getElementById('contract');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches || /[?&]still(&|$)/.test(location.search);
  const hidden = new Set();   // connection categories the reader has hidden
  let W = 0, H = 0, dpr = 1, legendH = 40;
  const cam = { x: 0, y: 0, z: 1 };
  let L = new Map(), E = [], tween = null, fitMode = true, started = false, queued = false;
  let selected = null, selEdge = null, hoverEdge = null, hoverNode = null, hoverPort = null, flow = null, stepI = 0;

  const usable = () => ({ top: legendH + 6, bottom: 72 });
  const setFitLabel = () => { fitBtn.textContent = mode !== 'structure' || !fitMode ? 'Fit all' : 'Actual size'; };

  // Draw on the next frame. The timer is a fallback for when the browser is not delivering frames.
  function redraw() {
    if (queued) return;
    queued = true;
    let ran = false;
    const go = () => { if (ran) return; ran = true; queued = false; paint(); if (tween) redraw(); };
    requestAnimationFrame(go);
    setTimeout(go, 90);
  }

  function fitCam(layout) {
    const r = layout.bounds, u = usable();
    const z = clamp(Math.min((W - 48) / r.w, (H - u.top - u.bottom - 24) / r.h), 0.22, 1.05);
    return { z, x: r.x + r.w / 2 - W / 2 / z, y: r.y + r.h / 2 - (u.top + (H - u.top - u.bottom) / 2) / z };
  }
  const centreOn = (r, z) => {
    const u = usable();
    return { z, x: r.x + r.w / 2 - W / 2 / z, y: r.y + r.h / 2 - (u.top + (H - u.top - u.bottom) / 2) / z };
  };
  const nearest = (layout, n) => { for (let p = n; p; p = p.parent) if (layout.has(p)) return p; return base(); };

  // Re-lay the diagram after boxes opened or closed, keeping `anchor` where it was on screen
  // (or bringing it to the middle when `centre` is set).
  function relayout(anchor, centre, pointer) {
    const before = L, camFrom = { ...cam };
    L = computeLayout();
    E = route(L);
    let camTo = { ...cam };
    if (centre && anchor) {
      fitMode = false;
      camTo = centreOn(L.get(nearest(L, anchor)), Math.max(cam.z, 0.85));
    } else {
      // Fit the whole level only while it stays readable; past that, show it at full size and let it scroll.
      const f = fitCam(L);
      if (fitMode && (f.z >= 0.5 || expanded.size === 0)) camTo = f;
      else {
        fitMode = false;
        const z = cam.z < 0.6 ? 1 : cam.z, u = usable();
        if (anchor && before.size && pointer) {
          // Scrolling: the spot under the pointer stays under the pointer, inside the box that opened.
          const rn = L.get(nearest(L, anchor));
          camTo = { z, x: rn.x + pointer.fx * rn.w - pointer.sx / z, y: rn.y + pointer.fy * rn.h - pointer.sy / z };
        } else if (anchor && before.size) {
          const a = nearest(L, anchor), ro = before.get(nearest(before, a)), rn = L.get(a);
          const sx = (ro.x + ro.w / 2 - cam.x) * cam.z, sy = (ro.y + ro.h / 2 - cam.y) * cam.z;
          camTo = { z, x: rn.x + rn.w / 2 - sx / z, y: rn.y + rn.h / 2 - sy / z };
        } else {
          // With nothing to hold on to, start where the data starts: the left end of the main line.
          const r = L.bounds;
          camTo = { z, x: r.x - 28 / z, y: r.y + r.h / 2 - (u.top + (H - u.top - u.bottom) / 2) / z };
        }
      }
    }
    setFitLabel();
    levelButtons();
    syncContract();
    if (reduceMotion || !started || !before.size) { Object.assign(cam, camTo); tween = null; }
    else tween = { t0: performance.now(), from: before, camFrom, camTo };
    redraw();
  }
  function panTo(camTo) {
    if (reduceMotion) { Object.assign(cam, camTo); tween = null; }
    else tween = { t0: performance.now(), from: L, camFrom: { ...cam }, camTo };
    redraw();
  }
  function setFit(on) {
    fitMode = on;
    setFitLabel();
    const mid = { x: cam.x + W / 2 / cam.z, y: cam.y + H / 2 / cam.z };
    panTo(on ? fitCam(L) : { z: 1, x: mid.x - W / 2, y: mid.y - H / 2 });
  }

  // ------------------------------------------------------------------ drawing

  function roundRect(x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  // A rectangle with only its top corners rounded: the title band of an open box.
  function topRoundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x, y + h);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h);
    ctx.closePath();
  }

  // The faint bands behind the sides of the whole system, each with its name.
  function drawBands(bands) {
    for (const b of bands) {
      ctx.globalAlpha = 1;
      roundRect(b.x, b.y, b.w, b.h, 20);
      ctx.fillStyle = mix(C.text, C.bg, C.mode === 'dark' ? 0.035 : 0.04);
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = mix(C.text, C.bg, 0.1);
      ctx.setLineDash([3, 5]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      caps(b.label.toUpperCase(), b.x + 16, b.y + 17, C.muted);
    }
  }

  // A stub for something outside the focused box. Clicking it steps over to that part.
  function drawPort(p, r) {
    const { x, y, w, h } = r, hot = hoverPort === p;
    ctx.globalAlpha = 1;
    roundRect(x, y, w, h, h / 2);
    ctx.fillStyle = mix(C.text, C.bg, C.mode === 'dark' ? 0.05 : 0.03);
    ctx.fill();
    ctx.lineWidth = hot ? 1.6 : 1;
    ctx.strokeStyle = hot ? C.accent : C.border;
    ctx.setLineDash([4, 3]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    caps(p.dir === 'in' ? 'FROM' : 'TO', x + 20, y + 17, C.muted);
    drawIcon(p.kind, x + w - 32, y + 16, C.muted);
    font(600, 13);
    ctx.fillStyle = C.text;
    ctx.fillText(fitText(p.name, w - 64), x + 20, y + 34);
  }

  const caps = (text, x, y, color) => {
    font(600, 9.5);
    ctx.fillStyle = color;
    ctx.letterSpacing = '0.08em';
    ctx.fillText(text, x, y);
    ctx.letterSpacing = '0px';
  };

  // A small line icon for each kind of part, 12 px square, drawn at (x, y) = top left.
  function drawIcon(kind, x, y, color) {
    const line = (pts, closed) => {
      ctx.beginPath();
      pts.forEach(([a, b], i) => (i ? ctx.lineTo(x + a, y + b) : ctx.moveTo(x + a, y + b)));
      if (closed) ctx.closePath();
      ctx.stroke();
    };
    const circle = (cx, cy, r, filled) => {
      ctx.beginPath();
      ctx.arc(x + cx, y + cy, r, 0, Math.PI * 2);
      filled ? ctx.fill() : ctx.stroke();
    };
    ctx.save();
    ctx.strokeStyle = ctx.fillStyle = color;
    ctx.lineWidth = 1.3;
    ctx.setLineDash([]);
    switch (kind) {
      case 'external': line([[0.5, 1.5], [11.5, 1.5], [11.5, 10.5], [0.5, 10.5]], true); line([[3, 1.5], [3, 10.5]]); line([[9, 1.5], [9, 10.5]]); break;
      case 'group': line([[1, 1], [5, 1], [5, 5], [1, 5]], true); line([[7, 1], [11, 1], [11, 5], [7, 5]], true);
        line([[1, 7], [5, 7], [5, 11], [1, 11]], true); line([[7, 7], [11, 7], [11, 11], [7, 11]], true); break;
      case 'step': line([[0.5, 2.5], [11.5, 2.5], [11.5, 9.5], [0.5, 9.5]], true); break;
      case 'decision': line([[6, 0.5], [11.5, 6], [6, 11.5], [0.5, 6]], true); break;
      case 'store': line([[1, 2.5], [1, 9.5]]); line([[11, 2.5], [11, 9.5]]);
        ctx.beginPath(); ctx.ellipse(x + 6, y + 2.5, 5, 2, 0, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.ellipse(x + 6, y + 9.5, 5, 2, 0, 0, Math.PI); ctx.stroke(); break;
      case 'queue': line([[0.5, 2], [11.5, 2], [11.5, 10], [0.5, 10]], true); line([[4, 2], [4, 10]]); line([[8, 2], [8, 10]]); break;
      case 'event': circle(6, 6, 5); circle(6, 6, 2, true); break;
      case 'ui': line([[0.5, 1.5], [11.5, 1.5], [11.5, 10.5], [0.5, 10.5]], true); line([[0.5, 4], [11.5, 4]]); break;
      default: line([[1.5, 1.5], [10.5, 1.5], [10.5, 10.5], [1.5, 10.5]], true);
    }
    ctx.restore();
  }

  // The outline of a part. A part with nothing inside is drawn in its kind's shape; a box that holds
  // parts is always a rounded box, so "this opens" reads at a glance.
  const STORE_RY = 9;
  const shapeOf = (n, r) => (r.open || !isLeaf(n) ? 'box' : n.kind);
  function shapePath(n, r) {
    const { x, y, w, h } = r;
    switch (shapeOf(n, r)) {
      case 'decision':
        ctx.beginPath(); ctx.moveTo(x + w / 2, y); ctx.lineTo(x + w, y + h / 2); ctx.lineTo(x + w / 2, y + h); ctx.lineTo(x, y + h / 2); ctx.closePath(); break;
      case 'store':
        ctx.beginPath(); ctx.moveTo(x, y + STORE_RY); ctx.lineTo(x, y + h - STORE_RY);
        ctx.ellipse(x + w / 2, y + h - STORE_RY, w / 2, STORE_RY, 0, Math.PI, 0, true);
        ctx.lineTo(x + w, y + STORE_RY);
        ctx.ellipse(x + w / 2, y + STORE_RY, w / 2, STORE_RY, 0, 0, Math.PI, true);
        ctx.closePath(); break;
      case 'event': roundRect(x, y, w, h, h / 2); break;
      case 'step': case 'queue': roundRect(x, y, w, h, 5); break;
      case 'external': roundRect(x, y, w, h, 4); break;
      case 'ui': roundRect(x, y, w, h, 8); break;
      default: roundRect(x, y, w, h, r.open ? 16 : 12);
    }
  }
  // The extra lines that finish a shape: the cylinder's rim, the queue's bars, the double sides, the screen's bar.
  function decorate(n, r) {
    const { x, y, w, h } = r, seg = (x1, y1, x2, y2) => { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); };
    switch (shapeOf(n, r)) {
      case 'store': ctx.beginPath(); ctx.ellipse(x + w / 2, y + STORE_RY, w / 2, STORE_RY, 0, 0, Math.PI); ctx.stroke(); break;
      case 'queue': for (const o of [12, 21, 30]) seg(x + w - o, y + 1, x + w - o, y + h - 1); break;
      case 'external': seg(x + 9, y, x + 9, y + h); seg(x + w - 9, y, x + w - 9, y + h); break;
      case 'ui':
        seg(x, y + 15, x + w, y + 15);
        for (const o of [10, 17, 24]) { ctx.beginPath(); ctx.arc(x + o, y + 7.5, 1.7, 0, Math.PI * 2); ctx.fillStyle = ctx.strokeStyle; ctx.fill(); }
        break;
    }
  }

  function drawNode(n, r, alpha, st) {
    const { x, y, w, h } = r, own = isOwnGap(n);
    const dim = st.related && !st.related.has(n) ? 0.45 : 1;
    ctx.globalAlpha = alpha * dim;
    const radius = r.open ? 16 : 12;
    const fill = C.fills[Math.min(Math.max(n.depth - 1, 0), C.fills.length - 1)];
    shapePath(n, r);
    ctx.fillStyle = fill;
    ctx.fill();
    if (r.open) {
      // An open box is a clear frame: a tinted title band across the top and a firmer border.
      topRoundRect(x, y, w, HEAD, radius);
      ctx.fillStyle = mix(C.accent, fill, C.mode === 'dark' ? 0.13 : 0.09);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(x, y + HEAD);
      ctx.lineTo(x + w, y + HEAD);
      ctx.lineWidth = 1;
      ctx.strokeStyle = C.border;
      ctx.stroke();
      roundRect(x, y, w, h, radius);
    }
    ctx.lineWidth = r.open ? 1.6 : 1.4;
    ctx.strokeStyle = own ? C.warn : r.open ? mix(C.text, fill, 0.42) : mix(C.text, fill, 0.5);
    ctx.setLineDash(own ? [5, 4] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    decorate(n, r);
    shapePath(n, r);
    if (st.done.has(n) || n === st.now || n === selected) {
      const strong = n === st.now || n === selected;
      ctx.globalAlpha = alpha * (strong ? 1 : 0.55);
      ctx.lineWidth = strong ? 2.25 : 1.25;
      ctx.strokeStyle = C.accent;
      ctx.stroke();
      if (n === st.now && !r.open) { ctx.globalAlpha = alpha * 0.1; ctx.fillStyle = C.accent; ctx.fill(); }
      ctx.globalAlpha = alpha * dim;
    }
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';

    if (r.open) {
      // An open box shows its title at the top; the title stays in view while the box is wider than the screen.
      const hx = clamp(cam.x + 16 / cam.z, x + 16, Math.max(x + 16, x + w - 260));
      drawIcon(n.kind, hx, y + 13, C.text);
      font(650, 15);
      ctx.fillStyle = C.text;
      ctx.fillText(n.name, hx + 19, y + 25);
      const nw = ctx.measureText(n.name).width;
      caps(kindLabel(n.kind).toUpperCase() + `   ${A.levelName(n.depth).toUpperCase()}` + (n.gaps ? `   ${n.gaps} OPEN` : ''), hx + 19 + nw + 12, y + 24.5, n.gaps ? C.warn : C.muted);
      return;
    }

    if (shapeOf(n, r) === 'decision') {
      // A diamond: everything centred, the kind above the name, the test below it.
      const cy = y + h / 2, dl = n.box.lines;
      ctx.textAlign = 'center';
      caps('DECISION', x + w / 2, cy - (dl.length > 1 ? 30 : 22), C.muted);
      font(600, 14);
      ctx.fillStyle = C.text;
      ctx.fillText(fitText(n.name, w * 0.6), x + w / 2, cy - (dl.length > 1 ? 10 : 2));
      font(400, 12);
      ctx.fillStyle = C.muted;
      dl.forEach((text, i) => ctx.fillText(text, x + w / 2, cy + (dl.length > 1 ? 8 : 17) + i * 15));
      ctx.textAlign = 'left';
      if (own) { ctx.fillStyle = C.warn; ctx.beginPath(); ctx.arc(x + w / 2, y + h - 14, 3.5, 0, Math.PI * 2); ctx.fill(); }
      return;
    }
    const top = shapeOf(n, r) === 'ui' ? 8 : 0;

    const { pad, lines } = n.box, maxW = w - pad * 2;
    // Top row: icon and kind on the left; on a closed box, how much is inside on the right.
    let inside = '';
    if (!isLeaf(n)) {
      inside = `${n.children.length} inside`;
      font(600, 10.5);
      const iw = ctx.measureText(inside).width;
      ctx.fillStyle = C.accent;
      ctx.fillText(inside, x + w - pad - iw, y + 23 + top);
      if (n.gaps) {
        const label = `${n.gaps} open`, gw = ctx.measureText(label + '  ').width;
        ctx.fillStyle = C.warn;
        ctx.fillText(label, x + w - pad - iw - gw, y + 23 + top);
        inside = label + '  ' + inside;
      }
    }
    font(600, 10.5);
    const used = inside ? ctx.measureText(inside).width + 10 : 0;
    const textMax = maxW - (shapeOf(n, r) === 'queue' ? 34 : 0);
    drawIcon(n.kind, x + pad, y + 13 + top, C.muted);
    font(600, 9.5);
    ctx.letterSpacing = '0.08em';
    const kind = fitText(kindLabel(n.kind).toUpperCase(), maxW - used - 18);
    ctx.letterSpacing = '0px';
    caps(kind, x + pad + 18, y + 23 + top, C.muted);
    // Name, then the headline on up to two lines.
    font(600, 14.5);
    ctx.fillStyle = C.text;
    ctx.fillText(fitText(n.name, textMax), x + pad, y + 46 + top);
    font(400, 12);
    ctx.fillStyle = C.muted;
    lines.forEach((text, i) => ctx.fillText(text, x + pad, y + 66 + top + i * LINE_H));
    if (own) {
      ctx.fillStyle = C.warn;
      ctx.beginPath();
      ctx.arc(x + w - 14, y + h - 14, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // The arrowhead says the category at a glance: filled for things moving forward, open for a result
  // coming back, a bar for a refusal, a dot for monitoring.
  function drawHead(head, tip, angle, size) {
    const [tx, ty] = tip, cos = Math.cos, sin = Math.sin;
    ctx.setLineDash([]);
    if (head === 'dot') {
      ctx.beginPath(); ctx.arc(tx - size * 0.45 * cos(angle), ty - size * 0.45 * sin(angle), size * 0.42, 0, Math.PI * 2); ctx.fill();
      return;
    }
    if (head === 'bar') {
      const bx = tx - 2 * cos(angle), by = ty - 2 * sin(angle), half = size * 0.75;
      ctx.beginPath();
      ctx.moveTo(bx + half * cos(angle + Math.PI / 2), by + half * sin(angle + Math.PI / 2));
      ctx.lineTo(bx - half * cos(angle + Math.PI / 2), by - half * sin(angle + Math.PI / 2));
      ctx.lineWidth += 0.6;
      ctx.stroke();
      ctx.lineWidth -= 0.6;
      return;
    }
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - size * cos(angle - 0.4), ty - size * sin(angle - 0.4));
    ctx.lineTo(tx - size * cos(angle + 0.4), ty - size * sin(angle + 0.4));
    ctx.closePath();
    if (head === 'open') {
      const keep = ctx.fillStyle;
      ctx.fillStyle = C.bg; ctx.fill(); ctx.fillStyle = keep;
      ctx.stroke();
    } else ctx.fill();
  }

  function drawEdges() {
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    const dense = E.length > 40;
    const pass = hot => {
      for (const g of E) {
        const inFlow = flow && g.list.some(e => flow.links.includes(e) && flow.idx.get(e.from) <= stepI && flow.idx.get(e.to) <= stepI);
        const touch = selected && g.list.some(e => within(e.a, selected) || within(e.b, selected));
        const near = hoverNode && g.list.some(e => within(e.a, hoverNode) || within(e.b, hoverNode));
        const isHot = inFlow || touch || near || (selEdge && selEdge.key === g.key) || hoverEdge === g.key;
        if (isHot !== hot) continue;
        const color = C.links[g.kind];
        const quiet = selected || selEdge || flow || hoverNode;
        ctx.globalAlpha = hot ? 1 : quiet ? (dense ? 0.12 : 0.2) : dense ? 0.5 : 0.9;
        ctx.strokeStyle = ctx.fillStyle = color;
        ctx.lineWidth = hot ? 1.8 : 1.1;
        // Dotted: the sender waits for an answer. Solid: the sender hands off and does not wait.
        ctx.lineCap = 'round';
        ctx.setLineDash(g.async ? [] : [2, 4]);
        ctx.beginPath();
        g.pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
        ctx.stroke();
        const tip = g.pts[g.pts.length - 1];
        let prev = g.pts[g.pts.length - 2];
        for (let i = g.pts.length - 2; i >= 0; i--) { prev = g.pts[i]; if (Math.hypot(tip[0] - prev[0], tip[1] - prev[1]) > 0.5) break; }
        ctx.lineCap = 'butt';
        drawHead(S.links[g.kind].head, tip, Math.atan2(tip[1] - prev[1], tip[0] - prev[0]), hot ? 8.5 : 7);
        if (g.text && (g.lab.show || hot)) {
          font(500, 10.5);
          ctx.fillStyle = C.bg;
          roundRect(g.lab.x - g.lab.w / 2, g.lab.y - 9, g.lab.w, 18, 9);
          ctx.fill();
          ctx.fillStyle = color;
          ctx.fillText(g.text, g.lab.x, g.lab.y + 0.5);
        }
      }
    };
    pass(false);
    pass(true);   // highlighted lines and their labels go on top
    ctx.globalAlpha = 1;
  }

  function paint(solidBackground) {
    let layout = L, k = 1;
    if (tween) {
      k = clamp((performance.now() - tween.t0) / 360, 0, 1);
      const e = 1 - Math.pow(1 - k, 3);
      cam.z = tween.camFrom.z * Math.pow(tween.camTo.z / tween.camFrom.z, e);
      const fc = { x: tween.camFrom.x + W / 2 / tween.camFrom.z, y: tween.camFrom.y + H / 2 / tween.camFrom.z };
      const tc = { x: tween.camTo.x + W / 2 / tween.camTo.z, y: tween.camTo.y + H / 2 / tween.camTo.z };
      cam.x = lerp(fc.x, tc.x, e) - W / 2 / cam.z;
      cam.y = lerp(fc.y, tc.y, e) - H / 2 / cam.z;
      if (tween.from !== L && k < 1) {
        // Boxes that appear grow out of the box they were inside; boxes that vanish shrink back into it.
        layout = new Map();
        for (const n of [root, ...order]) {
          const a = tween.from.get(n), b = L.get(n);
          if (!a && !b) continue;
          const ra = a || tween.from.get(nearest(tween.from, n)), rb = b || L.get(nearest(L, n));
          layout.set(n, {
            x: lerp(ra.x, rb.x, e), y: lerp(ra.y, rb.y, e), w: lerp(ra.w, rb.w, e), h: lerp(ra.h, rb.h, e),
            open: (b || a).open, alpha: lerp(a ? 1 : 0, b ? 1 : 0, e)
          });
        }
      }
      if (k >= 1) tween = null;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, W, H);
    if (solidBackground) { ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H); }
    ctx.setTransform(dpr * cam.z, 0, 0, dpr * cam.z, -cam.x * cam.z * dpr, -cam.y * cam.z * dpr);
    const st = {
      done: new Set(flow ? flow.steps.slice(0, stepI).map(s => rep(nodes.get(s.id))) : []),
      now: flow ? rep(nodes.get(flow.steps[stepI].id)) : null,
      related: null
    };
    if (selected) {
      st.related = new Set(pathOf(selected));
      order.forEach(n => { if (within(n, selected)) st.related.add(n); });
      for (const e of edges) {
        if (within(e.a, selected)) pathOf(e.b).forEach(p => st.related.add(p));
        if (within(e.b, selected)) pathOf(e.a).forEach(p => st.related.add(p));
      }
    }
    drawBands(L.bands || []);
    for (const n of order) {
      const r = layout.get(n);
      if (r) drawNode(n, r, r.alpha === undefined ? 1 : r.alpha, st);
    }
    if (layout === L) {
      for (const p of L.ports || []) drawPort(p, L.get(p));
      drawEdges();
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
  }

  // ------------------------------------------------------------------ saving a picture

  // A stand-in for the canvas that writes SVG instead of pixels. It supports exactly the calls paint()
  // makes, so the picture matches the screen. Text stays text, so the SVG is sharp at any size.
  function svgContext(width, height) {
    const parts = [], st = { fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1, font: '10px sans-serif',
      textAlign: 'left', textBaseline: 'alphabetic', letterSpacing: '0px', lineJoin: 'round' };
    const stack = [];
    let dash = [], path = '', T = [1, 0, 0, 1, 0, 0], cur = [0, 0];   // cur: the pen, in drawing units
    const num = v => +v.toFixed(2);
    const pt = (x, y) => `${num(T[0] * x + T[4])} ${num(T[3] * y + T[5])}`;
    const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const opacity = () => (st.globalAlpha < 1 ? ` opacity="${num(st.globalAlpha)}"` : '');
    const api = {
      save() { stack.push({ ...st, dash: [...dash] }); },
      restore() { const s = stack.pop(); if (s) { dash = s.dash; delete s.dash; Object.assign(st, s); } },
      setTransform(a, b, c, d, e, f) { T = [a, b, c, d, e, f]; },
      clearRect() {},
      fillRect(x, y, w, h) { parts.push(`<rect x="${num(T[0] * x + T[4])}" y="${num(T[3] * y + T[5])}" width="${num(w * T[0])}" height="${num(h * T[3])}" fill="${st.fillStyle}"/>`); },
      beginPath() { path = ''; },
      moveTo(x, y) { path += `M${pt(x, y)}`; cur = [x, y]; },
      lineTo(x, y) { path += `L${pt(x, y)}`; cur = [x, y]; },
      closePath() { path += 'Z'; },
      // Rounded corners, as the canvas draws them: a straight line to where the corner starts, then a
      // quarter circle of radius r that turns towards (x2, y2).
      arcTo(x1, y1, x2, y2, r) {
        const unit = (dx, dy) => { const len = Math.hypot(dx, dy) || 1; return [dx / len, dy / len]; };
        const [ax, ay] = unit(x1 - cur[0], y1 - cur[1]), [bx, by] = unit(x2 - x1, y2 - y1);
        const sx = x1 - ax * r, sy = y1 - ay * r, ex = x1 + bx * r, ey = y1 + by * r;
        const sweep = ax * by - ay * bx > 0 ? 1 : 0, R = r * T[0];
        path += `L${pt(sx, sy)}${R > 0 ? `A${num(R)} ${num(R)} 0 0 ${sweep} ${pt(ex, ey)}` : ''}`;
        cur = [ex, ey];
      },
      arc(x, y, r, a0, a1) {
        const R = r * T[0];
        if (Math.abs(a1 - a0) >= Math.PI * 2 - 1e-6) {
          path += `M${pt(x - r, y)}a${num(R)} ${num(R)} 0 1 0 ${num(2 * R)} 0a${num(R)} ${num(R)} 0 1 0 ${num(-2 * R)} 0`;
        } else {
          const sx = x + r * Math.cos(a0), sy = y + r * Math.sin(a0), ex = x + r * Math.cos(a1), ey = y + r * Math.sin(a1);
          path += `${path ? 'L' : 'M'}${pt(sx, sy)}A${num(R)} ${num(R)} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${pt(ex, ey)}`;
        }
      },
      ellipse(x, y, rx, ry, rot, a0, a1, ccw) {
        const RX = rx * T[0], RY = ry * T[3];
        if (Math.abs(a1 - a0) >= Math.PI * 2 - 1e-6) {
          path += `M${pt(x - rx, y)}a${num(RX)} ${num(RY)} 0 1 0 ${num(2 * RX)} 0a${num(RX)} ${num(RY)} 0 1 0 ${num(-2 * RX)} 0`;
        } else {
          let span = ccw ? a0 - a1 : a1 - a0;
          while (span <= 0) span += Math.PI * 2;
          const ex = x + rx * Math.cos(a1), ey = y + ry * Math.sin(a1);
          path += `${path ? 'L' : 'M'}${pt(x + rx * Math.cos(a0), y + ry * Math.sin(a0))}A${num(RX)} ${num(RY)} 0 ${span > Math.PI + 1e-6 ? 1 : 0} ${ccw ? 0 : 1} ${pt(ex, ey)}`;
          cur = [ex, ey];
        }
      },
      fill() { parts.push(`<path d="${path}" fill="${st.fillStyle}"${opacity()}/>`); },
      stroke() {
        const d = dash.length ? ` stroke-dasharray="${dash.map(v => num(v * T[0])).join(' ')}"` : '';
        parts.push(`<path d="${path}" fill="none" stroke="${st.strokeStyle}" stroke-width="${num(st.lineWidth * T[0])}" stroke-linejoin="round" stroke-linecap="round"${d}${opacity()}/>`);
      },
      fillText(text, x, y) {
        const anchor = { left: 'start', center: 'middle', right: 'end' }[st.textAlign] || 'start';
        const base = st.textBaseline === 'middle' ? ' dominant-baseline="central"' : '';
        const spacing = st.letterSpacing && st.letterSpacing !== '0px' ? ` letter-spacing="${st.letterSpacing}"` : '';
        parts.push(`<text x="${num(T[0] * x + T[4])}" y="${num(T[3] * y + T[5])}" style="font:${esc(st.font)}" fill="${st.fillStyle}" text-anchor="${anchor}"${base}${spacing}${opacity()}>${esc(text)}</text>`);
      },
      measureText(text) { realCtx.font = st.font; realCtx.letterSpacing = st.letterSpacing; return realCtx.measureText(text); },
      setLineDash(d) { dash = [...d]; },
      toSVG() {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${num(width)}" height="${num(height)}" viewBox="0 0 ${num(width)} ${num(height)}">`
          + parts.join('') + '</svg>\n';
      }
    };
    for (const k of Object.keys(st)) Object.defineProperty(api, k, { get: () => st[k], set: v => { st[k] = v; } });
    return api;
  }

  // Draws the open level, whole and at full size, with `drawWith` standing in for the screen.
  function renderWhole(makeContext) {
    const r = L.bounds, m = 40, keep = { cam: { ...cam }, W, H, dpr, selected, selEdge, hoverEdge, hoverNode, flow };
    tween = null; selected = selEdge = hoverEdge = hoverNode = flow = null;
    W = r.w + m * 2; H = r.h + m * 2;
    Object.assign(cam, { x: r.x - m, y: r.y - m, z: 1 });
    const result = makeContext(W, H);
    ({ selected, selEdge, hoverEdge, hoverNode, flow } = keep);
    W = keep.W; H = keep.H; dpr = keep.dpr; Object.assign(cam, keep.cam);
    ctx = realCtx;
    measure();
    return result;
  }
  const pictureName = ext => `architecture${focus ? '-' + focus.id.replace(/\./g, '-') : ''}${level() > 1 ? '-level-' + level() : ''}${C.mode === 'dark' ? '-dark' : ''}.${ext}`;
  function download(name, href) {
    const a = document.createElement('a');
    a.download = name;
    a.href = href;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  function buildSVG() {
    return renderWhole((w, h) => {
      dpr = 1;
      ctx = svgContext(w, h);
      paint(true);
      return ctx.toSVG();
    });
  }
  function savePNG() {
    const url = renderWhole((w, h) => {
      dpr = Math.min(2, 12000 / w, 12000 / h);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      paint(true);
      return canvas.toDataURL('image/png');
    });
    download(pictureName('png'), url);
  }
  function saveSVG() {
    const url = URL.createObjectURL(new Blob([buildSVG()], { type: 'image/svg+xml' }));
    download(pictureName('svg'), url);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // ------------------------------------------------------------------ side panel

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const list = a => (a && a.length ? `<ul>${a.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '');
  const section = (title, body) => (body ? `<h3>${title}</h3>${body}` : '');
  const para = s => (s ? `<p>${esc(s)}</p>` : '');
  const dot = kind => `<i class="dot" style="background:${C.links[kind]}"></i>`;

  // Where you are (Whole system › Box › Box) and how far the boxes in view are opened.
  function levelButtons() {
    const lv = level(), exact = atExactLevel(), trail = [root, ...(focus ? pathOf(focus) : [])];
    const where = trail.map((n, i) => {
      const name = esc(n === root ? 'Whole system' : n.name);
      return i < trail.length - 1
        ? `<button class="crumb" data-focus="${esc(n.id)}" title="Step out to ${name}">${name}</button><span class="sep">›</span>`
        : `<b class="here">${name}</b>`;
    }).join('');
    const levels = Array.from({ length: maxLevel() }, (_, i) =>
      `<button data-level="${i + 1}" aria-pressed="${exact && lv === i + 1}" title="Open every box in view down to level ${baseDepth() + i + 1}: ${A.levelName(baseDepth() + i + 1)}">${baseDepth() + i + 1}</button>`).join('');
    document.getElementById('crumbs').innerHTML = `<span class="where">${where}</span><span class="lvl-label">Level</span>${levels}<span class="lvl-name">${esc(A.levelName(baseDepth() + lv))}</span>`;
  }

  function outline(n, query) {
    const kids = n.children.map(k => {
      const sub = outline(k, query), hit = !query || k.name.toLowerCase().includes(query);
      if (!hit && !sub) return '';
      return `<li><button data-sel="${esc(k.id)}" class="${isGap(k) ? 'gap' : ''}">${esc(k.name)}</button>${sub}</li>`;
    }).join('');
    return kids ? `<ul>${kids}</ul>` : '';
  }

  const partBtn = id => { const n = nodes.get(id); return n ? `<button class="chip" data-sel="${esc(id)}" title="${esc(longName(n))}">${esc(n.name)}</button>` : esc(id); };
  const dataBtn = id => (A.data.has(id) ? `<button class="chip data" data-dataitem="${esc(id)}">${esc(A.dataName(id))}</button>` : `<span class="muted">${esc(id)}</span>`);
  const chips = ids => A.asList(ids).map(dataBtn).join(' ');
  const journeyList = list => (list.length ? `<ul class="links">${list.map(j => `<li><button data-journey="${esc(j.id)}"><span>${esc(j.name)}</span><small>${esc(j.type || '')}</small></button></li>`).join('')}</ul>` : '');
  const details = (title, items, cls) => (items.length ? `<details${cls ? ` class="${cls}"` : ''}><summary>${title} (${items.length})</summary><ul>${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : '');

  // A small picture of each kind's shape, for the key in the panel.
  function shapeIcon(k) {
    const c = C.muted, a = `fill="none" stroke="${c}" stroke-width="1.2"`;
    const body = {
      external: `<rect x="1" y="2" width="26" height="14" rx="1.5" ${a}/><path d="M4 2V16M24 2V16" ${a}/>`,
      group: `<rect x="1" y="1" width="26" height="16" rx="4" ${a}/><path d="M1 6H27" ${a}/>`,
      step: `<rect x="1" y="3" width="26" height="12" rx="2" ${a}/>`,
      decision: `<path d="M14 1L27 9L14 17L1 9Z" ${a}/>`,
      store: `<path d="M3 4V14A11 3 0 0 0 25 14V4A11 3 0 0 0 3 4ZM3 4A11 3 0 0 0 25 4" ${a}/>`,
      queue: `<rect x="1" y="3" width="26" height="12" rx="2" ${a}/><path d="M17 3V15M20.5 3V15M24 3V15" ${a}/>`,
      event: `<rect x="1" y="3" width="26" height="12" rx="6" ${a}/><circle cx="7" cy="9" r="2" fill="${C.accent}"/>`,
      ui: `<rect x="1" y="1" width="26" height="16" rx="3" ${a}/><path d="M1 5H27" ${a}/>`
    }[k] || '';
    return `<svg width="28" height="18" aria-hidden="true">${body}</svg>`;
  }

  function showOverview(query) {
    const gaps = order.filter(isGap);
    const byCategory = Object.entries(S.links).map(([k, v]) => {
      const count = edges.filter(e => e.kind === k).length;
      return count ? `<li><button data-cat="${k}" title="${esc(v.hint)}"><span>${dot(k)}${esc(v.label)}</span><small>${count}</small></button></li>` : '';
    }).join('');
    panel.innerHTML = `<div class="kind">System</div><h2>${esc(M.name)}</h2>
      <p class="muted">${esc(M.note || '')}</p>
      ${query ? '' : `<h3>Checks</h3>
      <p class="muted">${A.journeys.length} journeys cover ${report.covered} of ${edges.length} lines.</p>
      ${report.errors.length ? `<div class="question"><b>Must fix (${report.errors.length})</b><ul>${report.errors.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
      ${details('Worth a look', report.warnings, 'warn')}
      ${!report.errors.length && !report.warnings.length ? '<p class="muted">No problems found.</p>' : ''}
      ${section(`Still undecided (${gaps.length})`, gaps.length
        ? `<ul class="links">${gaps.map(g => `<li><button data-sel="${esc(g.id)}"><span>${esc(g.name)}</span><small>${esc(g.parent === root ? '' : g.parent.name)}</small></button></li>`).join('')}</ul>`
        : '<p class="muted">Nothing open.</p>')}
      ${section(`Journeys (${A.journeys.length})`, journeyList(A.journeys))}
      ${section(`Data (${A.data.size})`, `<p>${[...A.data.keys()].map(dataBtn).join(' ')}</p>`)}
      ${section('Shapes', `<div class="shapes">${Object.entries(S.kinds).map(([k, v]) => `<span title="${esc(v.hint)}">${shapeIcon(k)}${esc(v.label)}</span>`).join('')}</div>`)}
      <h3>Lines by category (${edges.length})</h3><ul class="links">${byCategory}</ul>`}
      <h3>${query ? 'Matches' : 'Every part'}</h3><div class="outline">${outline(root, query) || '<p class="muted">No part has that name.</p>'}</div>`;
  }

  function showNode(n) {
    const s = n.spec, status = n.status;
    const ins = edges.filter(e => within(e.b, n) && !within(e.a, n));
    const outs = edges.filter(e => within(e.a, n) && !within(e.b, n));
    const linkRow = (e, other) => `<li><button data-sel="${esc(other.id)}"><span>${dot(e.kind)}${esc(longName(other))}</span><small>${esc(e.text || e.label || '')}</small></button></li>`;
    const trail = pathOf(n).slice(0, -1);
    const code = A.asList(s.code);
    const through = A.journeys.filter(j => j.paths.some(path => path.some(id => within(nodes.get(id), n))));
    const branches = edges.filter(e => e.a === n && e.branch);
    let own = '';
    if (n.kind === 'step' && isLeaf(n)) own = section('Takes in', `<p>${chips(s.in)}</p>`) + section('Sends out', `<p>${chips(s.out)}</p>`);
    if (n.kind === 'decision') own = section('Tests', para(s.test)) + section('Branches', `<ul class="links">${branches.map(e => `<li><button data-sel="${esc(e.b.id)}"><span>${dot(e.kind)}${esc(e.branch)}</span><small>→ ${esc(e.b.name)}</small></button></li>`).join('')}</ul>`);
    if (n.kind === 'store') own = section('Keeps', `<p>${chips(s.keeps)}</p>`);
    if (n.kind === 'queue') own = section('Holds', `<ul><li>Capacity: ${esc(s.capacity ?? '')}</li><li>When full: ${esc(s.when_full || '')}</li></ul>`);
    if (n.kind === 'event') own = section('Starts when', para(s.trigger));
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      ${trail.length ? `<div class="trail">${trail.map(p => `<button data-sel="${esc(p.id)}">${esc(p.name)}</button>`).join('<span>›</span>')}</div>` : ''}
      <div class="kind">${esc(kindLabel(n.kind))} · level ${n.depth}, ${esc(A.levelName(n.depth).toLowerCase())}<span class="tag ${status}">${S.statuses[status] || status}</span></div>
      <h2>${esc(n.name)}</h2><div class="path">${esc(n.id)}</div>
      <div class="actions">${!isLeaf(n) && n !== focus ? `<button class="btn" data-focus="${esc(n.id)}">Step inside</button>${inBase(n)
        ? `<button class="btn" data-open="${esc(n.id)}">${expanded.has(n) ? 'Close here' : 'Open here'}</button>` : ''}` : ''}
        <button class="btn" data-trace="${esc(n.id)}:fwd" title="Draw everything this part reaches, to the end">Trace forward</button>
        <button class="btn" data-trace="${esc(n.id)}:back" title="Draw everything that reaches this part, back to the start">Trace back</button></div>
      ${s.question ? section('Open question', `<div class="question">${esc(s.question)}</div>`) : ''}
      ${section('Does', para(s.does))}
      ${own}
      ${section('Rules and numbers', list(A.asList(s.rules)))}
      ${section('Choice', para(s.choice) + (s.why ? `<p class="muted">${esc(s.why)}</p>` : ''))}
      ${section('Rejected', list(A.asList(s.rejected)))}
      ${section('If it fails', para(s.failure))}
      ${section('A journey may stop here', para(s.stops))}
      ${section('Exposes', para(s.exposes))}
      ${section('Built in', code.length ? `<ul class="code">${code.map(c => `<li><code>${esc(c)}</code></li>`).join('')}</ul>` : '')}
      ${section(`Inside (${n.children.length})`, n.children.length
        ? `<ul class="links">${n.children.map(k => `<li><button data-sel="${esc(k.id)}"><span>${esc(k.name)}</span><small>${esc(kindLabel(k.kind))}</small></button></li>`).join('')}</ul>` : '')}
      ${section(`Journeys through it (${through.length})`, journeyList(through))}
      ${section(`Receives from (${ins.length})`, ins.length ? `<ul class="links">${ins.map(e => linkRow(e, e.a)).join('')}</ul>` : '')}
      ${section(`Sends to (${outs.length})`, outs.length ? `<ul class="links">${outs.map(e => linkRow(e, e.b)).join('')}</ul>` : '')}`;
    panel.scrollTop = 0;
  }

  function showData(id) {
    const d = A.data.get(id);
    if (!d) return showOverview('');
    const makes = order.filter(n => A.asList(n.spec.out).includes(id)), takes = order.filter(n => A.asList(n.spec.in).includes(id));
    const kept = order.filter(n => n.kind === 'store' && A.asList(n.spec.keeps).includes(id));
    const carried = edges.filter(e => e.carries === id);
    const used = A.journeys.filter(j => j.links.some(e => e.carries === id));
    const parts = list => (list.length ? `<p>${list.map(n => partBtn(n.id)).join(' ')}</p>` : '');
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      <div class="kind">Data</div><h2>${esc(d.name)}</h2><div class="path">${esc(id)}</div>
      ${carried.length ? `<div class="actions"><button class="btn" data-dataflow="${esc(id)}">Show its flow</button></div>` : ''}
      ${d.note ? para(d.note) : ''}
      <h3>Fields</h3><table class="fields">${Object.entries(d.fields).map(([f, t]) => `<tr><td><code>${esc(f)}</code></td><td>${A.data.has(String(t).replace(/\[\]$/, '')) ? dataBtn(String(t).replace(/\[\]$/, '')) + (/\[\]$/.test(t) ? ' list' : '') : `<span class="muted">${esc(t)}</span>`}</td></tr>`).join('')}</table>
      ${section(`Made by (${makes.length})`, parts(makes))}
      ${section(`Used by (${takes.length})`, parts(takes))}
      ${section(`Kept in (${kept.length})`, parts(kept))}
      ${section(`Carried on (${carried.length})`, carried.length ? `<ul class="links">${carried.map(e => `<li><button data-sel="${esc(e.a.id)}"><span>${dot(e.kind)}${esc(e.a.name)} → ${esc(e.b.name)}</span></button></li>`).join('')}</ul>` : '')}
      ${section(`Journeys (${used.length})`, journeyList(used))}`;
    panel.scrollTop = 0;
  }

  function showJourney(id) {
    const J = A.journeys.find(j => j.id === id);
    if (!J) return showOverview('');
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      <div class="kind">Journey · ${esc(S.journeyTypes[J.type] || J.type || '')}</div><h2>${esc(J.name)}</h2>
      <div class="actions"><button class="btn" data-journey="${esc(id)}">Draw it alone</button><button class="btn" data-walk="${esc(id)}">Light it up on Structure</button></div>
      <h3>Steps (${J.steps.length})</h3><ol class="steps">${J.steps.map(st => `<li><button data-sel="${esc(st.id)}"><span>${esc(nodes.get(st.id).name)}</span><small>${esc(kindLabel(nodes.get(st.id).kind))}</small></button>${J.notes[st.id] ? `<p class="muted">${esc(J.notes[st.id])}</p>` : ''}</li>`).join('')}</ol>
      ${J.missing.length ? `<div class="question">Missing lines: ${esc(J.missing.join(', '))}</div>` : ''}`;
    panel.scrollTop = 0;
  }

  // All connections of one category, and only that category on the diagram.
  function showCategory(k) {
    const all = edges.filter(e => e.kind === k);
    onlyCategory(k);
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      <div class="kind">${dot(k)}Category</div><h2>${esc(S.links[k].label)}</h2>
      <p class="muted">${esc(S.links[k].hint)}. The diagram now shows only these ${all.length}.</p>
      <p><button class="btn" data-all>Show every category again</button></p>
      <ul class="links">${all.map(e => `<li><button data-sel="${esc(e.a.id)}"><span>${esc(longName(e.a))} → ${esc(longName(e.b))}</span><small>${e.async ? 'no wait · ' : ''}${esc(e.text || e.label || '')}</small></button></li>`).join('')}</ul>`;
    panel.scrollTop = 0;
  }

  function showEdge(g) {
    const contract = e => (e.contract
      ? `<ul>${['mode', 'timeout', 'retry'].filter(k => e.contract[k]).map(k => `<li><span class="muted">${k[0].toUpperCase() + k.slice(1)}:</span> ${esc(e.contract[k])}</li>`).join('')}</ul>`
      : '') + (e.carries ? `<p>Carries ${dataBtn(e.carries)}</p>` : '') + (e.branch ? `<p class="muted">The "${esc(e.branch)}" branch of a decision.</p>` : '')
      + journeyList(A.journeys.filter(j => j.links.includes(e)));
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      <div class="kind">${dot(g.kind)}${esc(S.links[g.kind].label)}${g.async ? '<span class="tag">Does not wait</span>' : ''}</div>
      <h2>${esc(g.a.name)} → ${esc(g.b.name)}</h2>
      ${g.list.map(e => `<h3>${esc(e.text || e.label || 'Connection')}</h3>
        <ul class="links"><li><button data-sel="${esc(e.a.id)}"><span>${esc(longName(e.a))}</span><small>from</small></button></li>
        <li><button data-sel="${esc(e.b.id)}"><span>${esc(longName(e.b))}</span><small>to</small></button></li></ul>${contract(e)}`).join('')}`;
    panel.scrollTop = 0;
  }

  // Selecting from a list brings the part into view, opening the boxes around it if needed.
  function goTo(n) {
    let refocused = false;
    if (focus && !within(n, focus)) {
      // The part is outside the box in view: step over to the box that holds it.
      focus = n.parent === root ? null : n.parent;
      expanded.clear();
      L = new Map();
      refocused = true;
    }
    const changed = reveal(n) || refocused;
    const r = L.get(n), u = usable();
    const inView = r && !changed && (r.x - cam.x) * cam.z > 20 && (r.x + r.w - cam.x) * cam.z < W - 20
      && (r.y - cam.y) * cam.z > u.top && (r.y + r.h - cam.y) * cam.z < H - u.bottom;
    if (changed) relayout(n, true);
    else if (!inView) { fitMode = false; setFitLabel(); panTo(centreOn(L.get(n), Math.max(cam.z, 0.85))); }
  }
  function select(n, move) {
    selected = n || null;
    selEdge = null;
    if (selected) {
      showNode(selected);
      if (move) goTo(selected);
      history.replaceState(null, '', '#' + selected.id);
    } else {
      showOverview('');
      history.replaceState(null, '', location.pathname + location.search);
    }
    redraw();
  }
  panel.addEventListener('click', e => {
    const jb = e.target.closest('[data-journey]');
    if (jb) { setMode('journeys'); return flowView.openJourney(jb.dataset.journey); }
    const wb = e.target.closest('[data-walk]');
    if (wb) { setMode('structure'); return walk(wb.dataset.walk); }
    const tb = e.target.closest('[data-trace]');
    if (tb) { const [id, dir] = tb.dataset.trace.split(':'); setMode('journeys'); return flowView.openTrace(id, dir); }
    const df = e.target.closest('[data-dataflow]');
    if (df) { setMode('journeys'); return flowView.openDataFlow(df.dataset.dataflow); }
    const di = e.target.closest('[data-dataitem]');
    if (di) { if (mode !== 'data') setMode('data'); flowView.openData(di.dataset.dataitem); return showData(di.dataset.dataitem); }
    if (mode !== 'structure') {
      const sb = e.target.closest('[data-sel]'), fb = e.target.closest('[data-focus]');
      if (fb) { setMode('structure'); return setFocus(nodes.get(fb.dataset.focus) || null); }
      if (sb) { const n = nodes.get(sb.dataset.sel); if (n) { showNode(n); flowView.pick(n.id); } else { showOverview(''); flowView.pick(null); } }
      return;
    }
    const into = e.target.closest('[data-focus]');
    if (into) return setFocus(nodes.get(into.dataset.focus) || null);
    const here = e.target.closest('[data-open]');
    if (here) { const n = nodes.get(here.dataset.open); toggle(n); return showNode(n); }
    const cat = e.target.closest('[data-cat]');
    if (cat) return showCategory(cat.dataset.cat);
    if (e.target.closest('[data-all]')) { onlyCategory(null); return select(null); }
    const b = e.target.closest('[data-sel]');
    if (b) select(nodes.get(b.dataset.sel), true);
  });
  document.getElementById('crumbs').addEventListener('click', e => {
    const b = e.target.closest('[data-level]');
    if (b) return toLevel(+b.dataset.level, null);
    const c = e.target.closest('[data-focus]');
    if (c) { const was = focus; setFocus(nodes.get(c.dataset.focus) || null); if (was) select(was, false); }
  });

  // ------------------------------------------------------------------ stepping into and out of a box

  // Step into a box: it fills the screen, its parts are shown, and everything outside it becomes a stub.
  function setFocus(n) {
    focus = n && n !== root && !isLeaf(n) ? n : null;
    expanded.clear();
    L = new Map();   // a different view: no animation from the old one
    fitMode = true;
    selected = null;
    selEdge = null;
    relayout(null, false);
    if (focus) showNode(focus); else showOverview('');
    history.replaceState(null, '', focus ? '#in:' + focus.id : location.pathname + location.search);
  }
  function stepOut() {
    if (!focus) return;
    const was = focus;
    setFocus(focus.parent === root ? null : focus.parent);
    select(was, false);
  }
  // Clicking a stub steps over to the part it names: into it if it has parts, otherwise to the box around it.
  function stepOver(port) {
    const t = port.target;
    if (!isLeaf(t)) return setFocus(t);
    setFocus(t.parent === root ? null : t.parent);
    select(t, false);
  }
  const hitPort = (wx, wy) => (L.ports || []).find(p => {
    const r = L.get(p);
    return wx >= r.x && wx <= r.x + r.w && wy >= r.y && wy <= r.y + r.h;
  }) || null;

  // ------------------------------------------------------------------ levels

  function toLevel(lv, anchor, pointer) {
    lv = clamp(lv, 1, maxLevel());
    if (atExactLevel() && lv === level()) return;
    setLevel(lv);
    relayout(anchor || selected, false, pointer);
  }
  function toggle(n) {
    if (isLeaf(n)) return;
    if (expanded.has(n)) close(n); else expanded.add(n);
    relayout(n, false);
  }

  // ------------------------------------------------------------------ lighting up a journey on this view

  const flowSel = document.getElementById('flow'), stepEl = document.getElementById('step');
  flowSel.innerHTML = '<option value="">None</option>' + A.journeys.map(j => `<option value="${esc(j.id)}">${esc(j.name)}</option>`).join('');
  function showStep() {
    document.getElementById('prev').disabled = !flow || stepI === 0;
    document.getElementById('next').disabled = !flow || stepI === flow.steps.length - 1;
    if (!flow) { stepEl.textContent = 'Pick a journey to light it up here, part by part. The Journeys tab draws it on its own.'; redraw(); return; }
    const id = flow.steps[stepI].id, n = nodes.get(id);
    stepEl.innerHTML = `<b>${stepI + 1} / ${flow.steps.length}</b>${esc(n.name)}${flow.notes[id] ? ': ' + esc(flow.notes[id]) : ''}`;
    selected = null;
    selEdge = null;
    showNode(n);
    goTo(n);
    redraw();
  }
  function walk(id) {
    const J = A.journeys.find(j => j.id === id);
    flow = J ? { ...J, idx: new Map(J.steps.map((s, i) => [s.id, i])) } : null;
    flowSel.value = flow ? id : '';
    stepI = 0;
    if (!flow) showOverview('');
    showStep();
  }
  flowSel.addEventListener('change', () => walk(flowSel.value));
  const stepBy = d => { if (!flow) return; stepI = clamp(stepI + d, 0, flow.steps.length - 1); showStep(); };
  document.getElementById('prev').addEventListener('click', () => stepBy(-1));
  document.getElementById('next').addEventListener('click', () => stepBy(1));

  // ------------------------------------------------------------------ pointer and keyboard

  const world = e => {
    const r = canvas.getBoundingClientRect();
    return [cam.x + (e.clientX - r.left) / cam.z, cam.y + (e.clientY - r.top) / cam.z];
  };
  function hitNode(wx, wy) {
    let hit = null;
    for (const n of order) {
      const r = L.get(n);
      if (r && wx >= r.x && wx <= r.x + r.w && wy >= r.y && wy <= r.y + r.h) hit = n;   // the innermost wins
    }
    return hit;
  }
  // The closed box nearest to a point, for zooming when the pointer is between boxes.
  function nearestBox(wx, wy) {
    let best = null, d = Infinity;
    for (const [n, r] of L) {
      if (n === root || r.open || r.port) continue;
      const dx = Math.max(r.x - wx, 0, wx - r.x - r.w), dy = Math.max(r.y - wy, 0, wy - r.y - r.h), k = dx * dx + dy * dy;
      if (k < d) { d = k; best = n; }
    }
    return best;
  }
  function hitEdge(wx, wy) {
    const tolerance = 6 / cam.z;
    for (const g of E) {
      for (let i = 0; i + 1 < g.pts.length; i++) {
        const [ax, ay] = g.pts[i], [bx, by] = g.pts[i + 1], dx = bx - ax, dy = by - ay;
        const k = clamp(((wx - ax) * dx + (wy - ay) * dy) / (dx * dx + dy * dy || 1), 0, 1);
        if (Math.hypot(ax + k * dx - wx, ay + k * dy - wy) < tolerance) return g;
      }
    }
    return null;
  }
  const hideHint = () => document.getElementById('hint').classList.add('gone');
  const leaveFit = () => { if (fitMode) { fitMode = false; setFitLabel(); } };

  let wheelSum = 0, wheelAt = 0;
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    hideHint();
    if (e.shiftKey || (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(e.deltaY))) {
      leaveFit();
      cam.x += (e.shiftKey ? (e.deltaY || e.deltaX) : e.deltaX) / cam.z;
      tween = null;
      redraw();
      return;
    }
    // One step of the wheel is one level, not a little more magnification.
    const now = performance.now();
    if (now - wheelAt > 400) wheelSum = 0;
    wheelSum += e.deltaY;
    if (Math.abs(wheelSum) < 50 || now - wheelAt < 260) return;
    const dir = wheelSum < 0 ? 1 : -1;
    wheelSum = 0;
    wheelAt = now;
    const [wx, wy] = world(e), rect = canvas.getBoundingClientRect();
    const under = hitNode(wx, wy) || nearestBox(wx, wy);
    const b = under && L.get(under);
    const pointer = b ? { sx: e.clientX - rect.left, sy: e.clientY - rect.top, fx: (wx - b.x) / b.w, fy: (wy - b.y) / b.h } : null;
    leaveFit();
    toLevel((atExactLevel() ? level() : dir > 0 ? level() - 1 : level()) + dir, under, pointer);
  }, { passive: false });

  let drag = null;
  canvas.addEventListener('pointerdown', e => {
    canvas.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y, moved: false };
  });
  canvas.addEventListener('pointermove', e => {
    if (!drag) {
      const [wx, wy] = world(e), g = hitEdge(wx, wy), port = g ? null : hitPort(wx, wy);
      const over = g || port ? null : hitNode(wx, wy), box = over && !L.get(over).open ? over : null;
      canvas.style.cursor = g || over || port ? 'pointer' : '';
      if ((g ? g.key : null) !== hoverEdge || box !== hoverNode || port !== hoverPort) {
        hoverEdge = g ? g.key : null; hoverNode = box; hoverPort = port; redraw();
      }
      return;
    }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    canvas.classList.add('dragging');
    hideHint();
    tween = null;
    leaveFit();
    cam.x = drag.cx - dx / cam.z;
    cam.y = drag.cy - dy / cam.z;
    redraw();
  });
  canvas.addEventListener('pointerleave', () => { if (hoverEdge || hoverNode || hoverPort) { hoverEdge = hoverNode = hoverPort = null; redraw(); } });
  canvas.addEventListener('pointerup', e => {
    const d = drag;
    drag = null;
    canvas.classList.remove('dragging');
    if (!d || d.moved) return;
    const [wx, wy] = world(e), g = hitEdge(wx, wy);
    if (g) { selected = null; selEdge = g; showEdge(g); redraw(); return; }
    const port = hitPort(wx, wy);
    if (port) return stepOver(port);
    select(hitNode(wx, wy), false);
  });
  // Double-click a box to step inside it.
  canvas.addEventListener('dblclick', e => {
    const [wx, wy] = world(e), n = hitPort(wx, wy) ? null : hitNode(wx, wy);
    if (n && !isLeaf(n) && n !== focus) { hideHint(); setFocus(n); }
  });

  const search = document.getElementById('search');
  document.addEventListener('keydown', e => {
    const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); search.focus(); return; }
    if (typing) { if (e.key === 'Escape') document.activeElement.blur(); return; }
    if (mode !== 'structure') return;
    const step = 90 / cam.z;
    if (e.key === 'ArrowLeft') cam.x -= step;
    else if (e.key === 'ArrowRight') cam.x += step;
    else if (e.key === 'ArrowUp') cam.y -= step;
    else if (e.key === 'ArrowDown') cam.y += step;
    else if (e.key === '+' || e.key === '=') return toLevel(level() + 1, selected);
    else if (e.key === '-') return toLevel(level() - 1, selected);
    else if (e.key === '0') return setFit(true);
    else if (e.key === 'Enter' && selected && !isLeaf(selected)) return setFocus(selected);
    else if (e.key === 'Backspace') return stepOut();
    else if (e.key === ']') return stepBy(1);
    else if (e.key === '[') return stepBy(-1);
    else if (e.key === 'Escape') return select(null);
    else return;
    e.preventDefault();
    tween = null;
    leaveFit();
    redraw();
  });
  search.addEventListener('input', () => { selected = null; selEdge = null; if (mode !== 'structure') setMode('structure'); showOverview(search.value.trim().toLowerCase()); redraw(); });
  search.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const b = panel.querySelector('.outline [data-sel]');
    if (b) { b.click(); search.blur(); }
  });

  // ------------------------------------------------------------------ toolbar and legend

  fitBtn.addEventListener('click', () => (mode === 'structure' ? setFit(!fitMode) : flowView.fit(true)));
  document.getElementById('svg').addEventListener('click', () => {
    if (mode === 'structure') return saveSVG();
    const url = URL.createObjectURL(new Blob([flowView.svg()], { type: 'image/svg+xml' }));
    download(flowView.pictureName('svg'), url);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  });
  document.getElementById('shot').addEventListener('click', () => {
    if (mode === 'structure') return savePNG();
    const url = URL.createObjectURL(new Blob([flowView.svg()], { type: 'image/svg+xml' })), img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas'), k = Math.min(2, 12000 / img.width, 12000 / img.height);
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const g = c.getContext('2d'); g.scale(k, k); g.drawImage(img, 0, 0);
      download(flowView.pictureName('png'), c.toDataURL('image/png'));
      URL.revokeObjectURL(url);
    };
    img.src = url;
  });
  document.getElementById('zin').addEventListener('click', () => toLevel(level() + 1, selected));
  document.getElementById('zout').addEventListener('click', () => toLevel(level() - 1, selected));
  themeBtn.addEventListener('click', () => {
    themeChoice = { auto: 'light', light: 'dark', dark: 'auto' }[themeChoice];
    writePref('theme', themeChoice === 'auto' ? null : themeChoice);
    applyTheme();
    buildLegend();
    redraw();
    flowView.render();
  });
  prefersDark.addEventListener('change', () => { if (themeChoice === 'auto') { applyTheme(); buildLegend(); redraw(); flowView.render(); } });

  function syncContract() {
    const shown = contractShown(), any = edges.some(e => S.contract.includes(e.kind));
    contractBtn.hidden = !any;
    contractBtn.setAttribute('aria-pressed', String(shown));
    contractBtn.textContent = shown ? 'Front-end contract: shown' : 'Front-end contract: hidden';
    legend.querySelectorAll('[data-kind]').forEach(b => {
      const k = b.dataset.kind;
      b.setAttribute('aria-pressed', String(!hidden.has(k) && (!S.contract.includes(k) || shown)));
    });
  }
  contractBtn.addEventListener('click', () => {
    contractChoice = !contractShown();
    E = route(L);
    syncContract();
    redraw();
  });

  const legendSwatch = k => {
    const color = C.links[k], head = S.links[k].head;
    const tip = head === 'filled' ? `<path d="M21 1 L27 4 L21 7 Z" fill="${color}"/>`
      : head === 'open' ? `<path d="M21 1 L27 4 L21 7 Z" fill="none" stroke="${color}" stroke-width="1.3"/>`
      : head === 'bar' ? `<line x1="26" y1="0" x2="26" y2="8" stroke="${color}" stroke-width="2"/>`
      : `<circle cx="25" cy="4" r="2.6" fill="${color}"/>`;
    return `<svg width="30" height="8" aria-hidden="true"><line x1="1" y1="4" x2="23" y2="4" stroke="${color}" stroke-width="2"/>${tip}</svg>`;
  };
  function buildLegend() {
    legend.innerHTML = Object.entries(S.links).filter(([k]) => edges.some(e => e.kind === k)).map(([k, v]) =>
      `<button type="button" data-kind="${k}" aria-pressed="true" title="${esc(v.hint)}. Click to hide or show; double-click to show only this.">${legendSwatch(k)}${esc(v.label)}</button>`).join('')
      + `<span class="key"><svg width="30" height="8" aria-hidden="true"><line x1="2" y1="4" x2="28" y2="4" stroke="${C.muted}" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="2 4"/></svg>dotted: waits for an answer</span>`
      + `<span class="key"><svg width="30" height="8" aria-hidden="true"><line x1="1" y1="4" x2="29" y2="4" stroke="${C.muted}" stroke-width="1.6"/></svg>solid: does not wait</span>`;
    document.getElementById('flegend').innerHTML = Object.entries(S.links).filter(([k]) => edges.some(e => e.kind === k))
      .map(([k, v]) => `<span title="${esc(v.hint)}">${legendSwatch(k)}${esc(v.label)}</span>`).join('');
    syncContract();
    legendH = legend.offsetHeight + 16;
  }
  function syncLegend() { selEdge = null; E = route(L); syncContract(); redraw(); }
  function onlyCategory(k) {
    hidden.clear();
    if (k) {
      Object.keys(S.links).forEach(x => { if (x !== k) hidden.add(x); });
      if (S.contract.includes(k)) contractChoice = true;
    }
    syncLegend();
  }
  legend.addEventListener('click', e => {
    const b = e.target.closest('[data-kind]');
    if (!b) return;
    const k = b.dataset.kind;
    if (S.contract.includes(k) && !contractShown()) { contractChoice = true; hidden.delete(k); }
    else if (hidden.has(k)) hidden.delete(k);
    else hidden.add(k);
    syncLegend();
  });
  legend.addEventListener('dblclick', e => {
    const b = e.target.closest('[data-kind]');
    if (!b) return;
    const k = b.dataset.kind, alone = !hidden.has(k) && Object.keys(S.links).every(x => x === k || hidden.has(x));
    onlyCategory(alone ? null : k);
  });

  const gapBtn = document.getElementById('gaps');
  gapBtn.textContent = [report.errors.length ? `${report.errors.length} to fix` : '', report.warnings.length ? `${report.warnings.length} to check` : '',
    root.gaps ? `${root.gaps} undecided` : ''].filter(Boolean).join(' · ') || 'No problems';
  gapBtn.classList.toggle('warn', root.gaps > 0 || report.errors.length > 0 || report.warnings.length > 0);
  gapBtn.addEventListener('click', () => { if (mode === 'structure') select(null); else showOverview(''); });

  // ------------------------------------------------------------------ the three views

  const flowWrap = document.getElementById('flowview'), tabs = document.getElementById('tabs');
  let mode = 'structure';
  function setMode(m) {
    mode = m;
    tabs.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.mode === m)));
    wrap.hidden = m !== 'structure';
    flowWrap.hidden = m === 'structure';
    document.getElementById('crumbs').hidden = m !== 'structure';
    contractBtn.hidden = m !== 'structure' || !edges.some(e => S.contract.includes(e.kind));
    fitBtn.textContent = m === 'structure' ? (fitMode ? 'Actual size' : 'Fit all') : 'Fit all';
    if (m === 'structure') {
      measure();
      history.replaceState(null, '', focus ? '#in:' + focus.id : selected ? '#' + selected.id : location.pathname + location.search);
    }
  }
  tabs.addEventListener('click', e => {
    const b = e.target.closest('[data-mode]');
    if (!b) return;
    setMode(b.dataset.mode);
    if (b.dataset.mode === 'journeys') flowView.openFirst();
    if (b.dataset.mode === 'data') { flowView.openData(); showOverview(''); }
  });

  // ------------------------------------------------------------------ start

  function measure() {
    dpr = window.devicePixelRatio || 1;
    W = wrap.clientWidth;
    H = wrap.clientHeight;
    legendH = legend.offsetHeight + 16;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    if (!W || !H) return;
    if (!started) {
      const hash = decodeURIComponent(location.hash.slice(1));
      const inside = hash.startsWith('in:') ? nodes.get(hash.slice(3)) : null, n = inside ? null : nodes.get(hash);
      if (inside && !isLeaf(inside)) { focus = inside; L = new Map(); relayout(null, false); showNode(inside); }
      else if (n) { reveal(n); selected = n; showNode(n); relayout(n, true); }
      else relayout(null, false);
      started = true;
    } else if (fitMode) Object.assign(cam, fitCam(L));
    redraw();
  }

  const flowView = window.ARCH_FLOW({
    A, S, esc, FONT, mix, colors: () => C,
    showPart: id => showNode(nodes.get(id)),
    showLinks: list => { if (list.length) showEdge({ a: list[0].a, b: list[0].b, kind: list[0].kind, async: list.every(l => l.async), list }); },
    showData, showJourney,
    showList: () => showOverview(''),
    setHash: h => history.replaceState(null, '', '#' + h)
  });

  applyTheme();
  order.forEach(measureBox);
  L = computeLayout();
  E = route(L);
  document.getElementById('title').textContent = M.name;
  document.title = M.name + ' · architecture';
  buildLegend();
  levelButtons();
  showOverview('');
  showStep();
  new ResizeObserver(measure).observe(wrap);
  addEventListener('resize', measure);
  measure();
  {
    const hash = decodeURIComponent(location.hash.slice(1)), [k, a, b] = hash.split(':');
    if (k === 'journey') { setMode('journeys'); flowView.openJourney(a); }
    else if (k === 'dataflow') { setMode('journeys'); flowView.openDataFlow(a); }
    else if (k === 'trace') { setMode('journeys'); flowView.openTrace(a, b); }
    else if (k === 'journeys') { setMode('journeys'); flowView.openFirst(); }
    else if (k === 'data') { setMode('data'); flowView.openData(a); if (a) showData(a); }
  }

  // For scripts and tests.
  window.ARCH_VIEWER = {
    svg: () => (mode === 'structure' ? buildSVG() : flowView.svg()), level, toLevel: lv => toLevel(lv, null),
    focus: id => setFocus(id ? nodes.get(id) : null),
    ports: () => (L.ports || []).map(p => p.dir + ':' + p.name),
    mode: m => { if (m) { setMode(m); if (m === 'journeys') flowView.openFirst(); if (m === 'data') flowView.openData(); } return mode; },
    journey: id => { setMode('journeys'); flowView.openJourney(id); },
    trace: (id, dir) => { setMode('journeys'); flowView.openTrace(id, dir || 'fwd'); },
    report
  };
})();
