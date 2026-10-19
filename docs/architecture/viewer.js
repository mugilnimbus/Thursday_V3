// Draws window.ARCH_MODEL as a layered diagram: each level deeper opens the boxes one step
// further. Every box is drawn at the same readable size and the lines are routed once per level.
// Nothing here is project-specific.
(() => {
  'use strict';
  const M = window.ARCH_MODEL;

  // Sizes in pixels at 100%.
  const BOX_W = 214, BOX_H = 88;                 // a part, or a closed box of parts
  const GAP_X = 96, GAP_Y = 30, ROW_GAP = 96;    // between parts along the flow, stacked parts, and side bands
  const PAD = 42, HEAD = 34;                     // inside an open box: clear space around its parts, and its title strip

  const C = {
    fill: ['#0d0d13', '#12121a', '#181822', '#1e1e2a', '#242432'],
    border: '#2e2e3d', text: '#ececf4', muted: '#9a9ab0', accent: '#9b7bff', warn: '#e0a53a',
    font: 'Inter, "Segoe UI", system-ui, sans-serif'
  };
  const KIND = { actor: 'External', service: 'Service', interface: 'Interface', queue: 'Queue', policy: 'Rule',
    pool: 'Pool', ui: 'UI', hardware: 'Hardware', batcher: 'Batcher', database: 'Database', component: 'Component' };
  // Every connection belongs to exactly one category. The category sets the colour; a hand-off
  // that does not wait for an answer (async: true) is drawn dashed in whatever colour it has.
  const LINK = {
    data: { label: 'Data flow', hint: 'The thing being processed moves along it', color: '#6ea8ff', dash: [] },
    control: { label: 'Control flow', hint: 'A signal with no payload: a trigger, a check, an acknowledgement', color: '#b79bff', dash: [] },
    result: { label: 'Result', hint: 'The answer on its way back', color: '#4fd1a5', dash: [] },
    error: { label: 'Error or refusal', hint: 'What happens when it does not go through', color: '#ff7a6b', dash: [3, 4] },
    store: { label: 'Storage', hint: 'Written to or read from something that persists', color: '#f08fd0', dash: [] },
    monitor: { label: 'Monitoring', hint: 'Metrics and logs', color: '#8f94a8', dash: [1.5, 5] },
    ui: { label: 'Shown in the UI', hint: 'Data a person sees', color: '#8fe07a', dash: [] },
    config: { label: 'Configuration', hint: 'A setting a person can change', color: '#f2d04a', dash: [] }
  };
  const FORWARD = new Set(['data', 'control', 'store']); // categories that set the left-to-right order
  const STATUS = { accepted: 'Accepted', open: 'Open', revisit: 'Needs revisit' };
  const hidden = new Set();

  // ---------- model ----------
  const nodes = new Map(), order = [], problems = [];
  const root = { id: '', name: M.name, children: [], parent: null, depth: 0, card: {}, lane: 'main' };
  (function build(specs, parent) {
    for (const s of specs) {
      const n = { id: parent.id ? parent.id + '.' + s.id : s.id, parent, depth: parent.depth + 1, kind: s.kind || 'component',
        name: s.name, headline: s.headline || '', lane: s.lane || 'main', card: s.card || {}, children: [] };
      if (nodes.has(n.id)) problems.push(`Two parts share the id ${n.id}; only the last one is reachable.`);
      if (s.kind && !KIND[s.kind]) problems.push(`${n.id}: unknown kind "${s.kind}".`);
      if (s.lane && !['main', 'top', 'bottom', 'left', 'right'].includes(s.lane)) { problems.push(`${n.id}: unknown lane "${s.lane}"; drawn on the main line.`); n.lane = 'main'; }
      nodes.set(n.id, n); order.push(n); parent.children.push(n);
      build(s.children || [], n);
    }
  })(M.elements, root);

  const edges = [];
  M.edges.forEach((e, i) => {
    const a = nodes.get(e.from), b = nodes.get(e.to);
    if (!a || !b) { problems.push(`Connection ${e.from} → ${e.to} names a part that does not exist, so it is not drawn.`); return; }
    if (e.kind && !LINK[e.kind]) problems.push(`Connection ${e.from} → ${e.to}: unknown category "${e.kind}"; drawn as data flow.`);
    edges.push({ ...e, kind: LINK[e.kind] ? e.kind : 'data', i, a, b });
  });
  M.flows.forEach(f => { const ok = f.steps.filter(s => nodes.has(s.at)); if (ok.length !== f.steps.length) problems.push(`Flow "${f.name}" names a part that does not exist; that step is skipped.`); f.steps = ok; });
  M.flows = M.flows.filter(f => f.steps.length);

  const isLeaf = n => n.children.length === 0;
  const isGap = n => n.card.status === 'open' || n.card.status === 'revisit' || (isLeaf(n) && n.kind !== 'actor' && !(n.card.rules || []).length);
  (function count(n) { n.gaps = (n !== root && isGap(n) ? 1 : 0) + n.children.reduce((s, c) => s + count(c), 0); return n.gaps; })(root);
  const within = (n, anc) => { for (let p = n; p; p = p.parent) if (p === anc) return true; return false; };
  const childOf = (c, n) => { for (let p = n; p; p = p.parent) if (p.parent === c) return p; return null; };
  const pathOf = n => { const out = []; for (let p = n; p && p !== root; p = p.parent) out.unshift(p); return out; };
  const maxLevel = 1 + Math.max(0, ...order.filter(n => !isLeaf(n)).map(n => n.depth));

  // ---------- which boxes are open ----------
  const expanded = new Set();
  const isOpen = n => n === root || expanded.has(n);
  const setLevel = lv => { expanded.clear(); order.forEach(n => { if (!isLeaf(n) && n.depth < lv) expanded.add(n); }); };
  const level = () => 1 + Math.max(0, ...[...expanded].map(n => n.depth));
  const atExactLevel = () => { const lv = level(); return order.every(n => isLeaf(n) || expanded.has(n) === (n.depth < lv)); };
  const close = n => { order.forEach(k => { if (within(k, n)) expanded.delete(k); }); };
  const show = n => { let changed = false; for (const p of pathOf(n)) if (p !== n && !expanded.has(p)) { expanded.add(p); changed = true; } return changed; };
  // The box that stands for a part right now: itself, or the first closed box around it.
  const rep = n => { for (const p of pathOf(n)) { if (p === n) break; if (!expanded.has(p)) return p; } return n; };

  // ---------- layout: positions for everything visible at the current level ----------
  function computeLayout() {
    const size = c => {
      if (!isOpen(c)) { c.w = BOX_W; c.h = BOX_H; return; }
      // Parts on the main line are ranked along the data flow. A part can instead be put on a side
      // (lane: 'top' | 'bottom' | 'left' | 'right') so that what surrounds the system stays around it.
      const kids = c.children.filter(k => k.lane === 'main');
      kids.forEach(size);
      const idx = new Map(kids.map((k, i) => [k, i]));
      // The order along the line follows what moves forward (data, control, storage). Results,
      // errors and the rest only decide it where nothing else connects the parts.
      const out = kids.map(() => new Set());
      const link = all => { for (const e of edges) {
        if (!all && !FORWARD.has(e.kind)) continue;
        const a = childOf(c, e.a), b = childOf(c, e.b);
        if (a && b && a !== b && idx.has(a) && idx.has(b)) out[idx.get(a)].add(idx.get(b));
      } };
      link(false);
      if (out.every(s => s.size === 0)) link(true);
      // Ignore connections that close a loop, then rank by longest path so data reads left to right.
      const state = kids.map(() => 0), preds = kids.map(() => []);
      const dfs = u => { state[u] = 1; for (const v of out[u]) { if (state[v] === 1) continue; preds[v].push(u); if (!state[v]) dfs(v); } state[u] = 2; };
      kids.forEach((_, i) => { if (!state[i]) dfs(i); });
      const rank = kids.map(() => -1);
      const rk = v => rank[v] >= 0 ? rank[v] : (rank[v] = preds[v].length ? Math.max(...preds[v].map(rk)) + 1 : 0);
      kids.forEach((_, i) => rk(i));
      // Parts with no connections between them have no order to show, so they sit side by side.
      if (kids.length > 1 && out.every(s => s.size === 0)) kids.forEach((_, i) => { rank[i] = i; });
      const cols = [];
      kids.forEach((k, i) => (cols[rank[i]] = cols[rank[i]] || []).push(i));
      const pos = kids.map(() => 0);
      const bary = v => preds[v].length ? preds[v].reduce((s, u) => s + pos[u], 0) / preds[v].length : 1e3;
      cols.forEach((col, ci) => { if (ci) col.sort((p, q) => bary(p) - bary(q) || p - q); col.forEach((v, j) => { pos[v] = j; }); });
      const colH = cols.map(col => col.reduce((s, v) => s + kids[v].h, 0) + GAP_Y * (col.length - 1));
      let inH = Math.max(0, ...colH), x = 0;
      cols.forEach((col, ci) => {
        const cw = Math.max(...col.map(v => kids[v].w)); let y = (inH - colH[ci]) / 2;
        for (const v of col) { kids[v].x = x + (cw - kids[v].w) / 2; kids[v].y = y; y += kids[v].h + GAP_Y; }
        x += cw + GAP_X;
      });
      let inW = Math.max(0, x - GAP_X);

      const on = s => c.children.filter(k => k.lane === s);
      const row = list => list.length ? (list.forEach(size), { list, w: list.reduce((s, k) => s + k.w, 0) + GAP_X * (list.length - 1), h: Math.max(...list.map(k => k.h)) }) : null;
      const column = list => list.length ? (list.forEach(size), { list, w: Math.max(...list.map(k => k.w)), h: list.reduce((s, k) => s + k.h, 0) + GAP_Y * (list.length - 1) }) : null;
      const T = row(on('top')), B = row(on('bottom')), L = column(on('left')), R = column(on('right'));
      if (T || B || L || R) {
        const midW = Math.max(inW, T ? T.w : 0, B ? B.w : 0), midH = Math.max(inH, L ? L.h : 0, R ? R.h : 0);
        const lx = L ? L.w + GAP_X : 0, ty = T ? T.h + ROW_GAP : 0;
        kids.forEach(k => { k.x += lx + (midW - inW) / 2; k.y += ty + (midH - inH) / 2; });
        const putRow = (r, y) => { let bx = lx + (midW - r.w) / 2; for (const k of r.list) { k.x = bx; k.y = y + (r.h - k.h) / 2; bx += k.w + GAP_X; } };
        const putCol = (r, x0) => { let by = ty + (midH - r.h) / 2; for (const k of r.list) { k.x = x0 + (r.w - k.w) / 2; k.y = by; by += k.h + GAP_Y; } };
        if (T) putRow(T, 0);
        if (B) putRow(B, ty + midH + ROW_GAP);
        if (L) putCol(L, 0);
        if (R) putCol(R, lx + midW + GAP_X);
        inW = lx + midW + (R ? GAP_X + R.w : 0); inH = ty + midH + (B ? ROW_GAP + B.h : 0);
      }
      if (c === root) { c.w = inW; c.h = inH; c.ox = 0; c.oy = 0; return; }
      c.w = Math.max(inW + PAD * 2, 280); c.h = inH + HEAD + PAD * 2;
      c.ox = (c.w - inW) / 2; c.oy = HEAD + PAD;
    };
    size(root);
    const R = new Map();
    const place = (c, ax, ay) => { R.set(c, { x: ax, y: ay, w: c.w, h: c.h, open: isOpen(c) }); if (isOpen(c)) for (const k of c.children) place(k, ax + c.ox + k.x, ay + c.oy + k.y); };
    place(root, 0, 0);
    return R;
  }

  // ---------- routing: straight segments with right-angle bends, worked out once per level ----------
  function route(L) {
    const groups = new Map();
    for (const e of edges) {
      const a = rep(e.a), b = rep(e.b);
      if (a === b || within(a, b) || within(b, a) || hidden.has(e.kind)) continue;
      const key = a.id + '>' + b.id + '>' + e.kind + (e.async ? '>async' : '');
      if (!groups.has(key)) groups.set(key, { key, a, b, kind: e.kind, async: !!e.async, list: [] });
      groups.get(key).list.push(e);
    }
    // Boxes a line between a and b could run into: the neighbours of each end and of each box around it.
    const obstacles = (a, b) => {
      const seen = new Set(), out = [];
      for (const end of [a, b]) for (let q = end.parent; q; q = q.parent) for (const k of q.children) {
        if (seen.has(k) || within(a, k) || within(b, k)) continue;
        seen.add(k); out.push(L.get(k));
      }
      return out;
    };
    const ends = new Map(); let lane = 0;
    const side = (n, s, g, end, other) => { const k = n.id + '|' + s; if (!ends.has(k)) ends.set(k, { n, s, list: [] }); ends.get(k).list.push({ g, end, other }); };
    for (const g of groups.values()) {
      const ra = L.get(g.a), rb = L.get(g.b), obs = obstacles(g.a, g.b);
      const gapX = Math.max(rb.x - (ra.x + ra.w), ra.x - (rb.x + rb.w)), gapY = Math.max(rb.y - (ra.y + ra.h), ra.y - (rb.y + rb.h));
      g.pts = null; g.block = [];
      // Leave by the top or bottom when the other box is clearly above or below, otherwise by the sides.
      if (gapY > 0 && (gapX <= 0 || gapY >= gapX * 0.5)) {
        g.mode = rb.y > ra.y ? 'tb' : 'bt';
        const lo = g.mode === 'tb' ? ra.y + ra.h : rb.y + rb.h, hi = g.mode === 'tb' ? rb.y : ra.y;
        g.block = obs.filter(r => r.y < hi - 1 && r.y + r.h > lo + 1);
      } else {
        g.mode = rb.x + rb.w / 2 >= ra.x + ra.w / 2 ? 'lr' : 'rl';
        // A box standing between the two ends would be crossed by a direct line, so the line
        // goes over the row (forward) or under it (backward) instead.
        const lo = Math.min(ra.x + ra.w, rb.x + rb.w), hi = Math.max(ra.x, rb.x);
        const y0 = Math.min(ra.y, rb.y), y1 = Math.max(ra.y + ra.h, rb.y + rb.h);
        const between = obs.filter(r => r.x < hi - 1 && r.x + r.w > lo + 1 && r.y < y1 && r.y + r.h > y0);
        if (between.length) {
          const fwd = g.mode === 'lr', k = lane++ % 4, off = 10 + k * 6;
          const all = [ra, rb, ...between];
          const cy = fwd ? Math.min(...all.map(r => r.y)) - off : Math.max(...all.map(r => r.y + r.h)) + off;
          const f = 0.62 + k * 0.08, xs = fwd ? ra.x + ra.w * f : ra.x + ra.w * (1 - f), xt = fwd ? rb.x + rb.w * (1 - f) : rb.x + rb.w * f;
          g.mode = 'around';
          g.pts = [[xs, fwd ? ra.y : ra.y + ra.h], [xs, cy], [xt, cy], [xt, fwd ? rb.y : rb.y + rb.h]];
          continue;
        }
      }
      const [sa, sb] = { lr: ['R', 'L'], rl: ['L', 'R'], tb: ['B', 'T'], bt: ['T', 'B'] }[g.mode];
      const horiz = g.mode === 'lr' || g.mode === 'rl';
      side(g.a, sa, g, 'p1', horiz ? rb.y + rb.h / 2 : rb.x + rb.w / 2);
      side(g.b, sb, g, 'p2', horiz ? ra.y + ra.h / 2 : ra.x + ra.w / 2);
    }
    for (const { n, s, list } of ends.values()) {
      const r = L.get(n);
      list.sort((p, q) => p.other - q.other);
      list.forEach((it, i) => {
        // Spread the lines along the side, but never further apart than they need to be.
        const span = (s === 'L' || s === 'R' ? r.h : r.w), step = Math.min(span * 0.76 / (list.length + 1), 22);
        const at = span / 2 + (i - (list.length - 1) / 2) * step;
        it.g[it.end] = s === 'L' ? [r.x, r.y + at] : s === 'R' ? [r.x + r.w, r.y + at] : s === 'T' ? [r.x + at, r.y] : [r.x + at, r.y + r.h];
        // Each line turns at its own distance from the box, so parallel lines do not share a channel.
        if (it.end === 'p1') it.g.turn = 0.3 + 0.4 * (i + 1) / (list.length + 1);
      });
    }
    const out = [];
    for (const g of groups.values()) {
      if (!g.pts) {
        const [x1, y1] = g.p1, [x2, y2] = g.p2;
        if (g.mode === 'lr' || g.mode === 'rl') {
          const mx = x1 + (x2 - x1) * g.turn;
          g.pts = Math.abs(y2 - y1) < 1.5 ? [[x1, y1], [x2, y1]] : [[x1, y1], [mx, y1], [mx, y2], [x2, y2]];
        } else if (!g.block.length) {
          const my = y1 + (y2 - y1) * g.turn;
          g.pts = Math.abs(x2 - x1) < 1.5 ? [[x1, y1], [x1, y2]] : [[x1, y1], [x1, my], [x2, my], [x2, y2]];
        } else {
          // Something stands between the two rows: turn beside whichever end has a clear run,
          // or cross through the nearest gap between the boxes in the way.
          const hits = x => g.block.some(r => x > r.x - 4 && x < r.x + r.w + 4);
          const dir = Math.sign(y2 - y1), d = 12 + (lane++ % 4) * 6, m1 = y1 + dir * d, m2 = y2 - dir * d;
          if (!hits(x1)) g.pts = [[x1, y1], [x1, m2], [x2, m2], [x2, y2]];
          else if (!hits(x2)) g.pts = [[x1, y1], [x1, m1], [x2, m1], [x2, y2]];
          else {
            const spans = g.block.map(r => [r.x, r.x + r.w]).sort((p, q) => p[0] - q[0]), merged = [];
            for (const s of spans) { const last = merged[merged.length - 1]; if (last && s[0] <= last[1] + 10) last[1] = Math.max(last[1], s[1]); else merged.push([...s]); }
            const cand = [merged[0][0] - 16, merged[merged.length - 1][1] + 16];
            for (let i = 0; i + 1 < merged.length; i++) cand.push((merged[i][1] + merged[i + 1][0]) / 2);
            const xg = cand.reduce((best, c) => Math.abs(x1 - c) + Math.abs(x2 - c) < Math.abs(x1 - best) + Math.abs(x2 - best) ? c : best);
            g.pts = [[x1, y1], [x1, m1], [xg, m1], [xg, m2], [x2, m2], [x2, y2]];
          }
        }
      }
      out.push(g);
    }
    // Labels: on the longest segment that is free of boxes and of labels already placed.
    ctx.font = `500 10.5px ${C.font}`;
    const boxes = [...L.entries()].filter(([n, r]) => n !== root && !r.open).map(([, r]) => r), placed = [];
    for (const g of out) {
      g.text = g.list.length === 1 ? (g.list[0].label || '') : `${g.list.length} connections`;
      const tw = ctx.measureText(g.text).width + 14, ra = L.get(g.a), rb = L.get(g.b);
      const segs = g.pts.slice(0, -1).map((p, i) => ({ p, q: g.pts[i + 1], len: Math.hypot(g.pts[i + 1][0] - p[0], g.pts[i + 1][1] - p[1]) })).sort((s, t) => t.len - s.len);
      g.lab = { x: (segs[0].p[0] + segs[0].q[0]) / 2, y: (segs[0].p[1] + segs[0].q[1]) / 2, w: tw, show: false };
      if (!g.text) continue;
      for (const s of segs) {
        const flat = Math.abs(s.p[1] - s.q[1]) < 1;
        if (flat ? tw > s.len * 0.94 : s.len < 30) continue;
        const x = (s.p[0] + s.q[0]) / 2, y = (s.p[1] + s.q[1]) / 2;
        const hit = r => x + tw / 2 > r.x - 2 && x - tw / 2 < r.x + r.w + 2 && y + 10 > r.y - 2 && y - 10 < r.y + r.h + 2;
        if (boxes.some(r => r !== ra && r !== rb && hit(r)) || placed.some(hit)) continue;
        g.lab = { x, y, w: tw, show: true }; placed.push({ x: x - tw / 2, y: y - 9, w: tw, h: 18 });
        break;
      }
    }
    return out;
  }

  // ---------- view state ----------
  const canvas = document.getElementById('canvas'), ctx = canvas.getContext('2d'), wrap = document.getElementById('wrap');
  const panel = document.getElementById('panel'), legend = document.getElementById('legend'), fitBtn = document.getElementById('fit');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches || /[?&]still(&|$)/.test(location.search);
  let W = 0, H = 0, dpr = 1, legendH = 40;
  const cam = { x: 0, y: 0, z: 1 };
  let L = computeLayout(), E = [], tw = null, fitMode = true, started = false, queued = false;
  let selected = null, selEdge = null, hoverEdge = null, flow = null, stepI = 0;

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const lerp = (a, b, k) => a + (b - a) * k;
  const usable = () => ({ top: legendH + 6, bottom: 72 });

  // Draw on the next frame. The timer is a fallback for when the browser is not delivering frames.
  function redraw() {
    if (queued) return;
    queued = true;
    let ran = false;
    const go = () => { if (ran) return; ran = true; queued = false; paint(); if (tw) redraw(); };
    requestAnimationFrame(go); setTimeout(go, 90);
  }

  function fitCam(layout) {
    const r = layout.get(root), u = usable();
    const z = clamp(Math.min((W - 48) / r.w, (H - u.top - u.bottom - 24) / r.h), 0.22, 1.05);
    return { z, x: r.w / 2 - W / 2 / z, y: r.h / 2 - (u.top + (H - u.top - u.bottom) / 2) / z };
  }
  const centreOn = (r, z) => { const u = usable(); return { z, x: r.x + r.w / 2 - W / 2 / z, y: r.y + r.h / 2 - (u.top + (H - u.top - u.bottom) / 2) / z }; };
  const nearest = (layout, n) => { for (let p = n; p; p = p.parent) if (layout.has(p)) return p; return root; };

  // Re-lay the diagram after boxes opened or closed, keeping `anchor` where it was on screen
  // (or bringing it to the middle when `centre` is set).
  function relayout(anchor, centre) {
    const from = L, camFrom = { ...cam };
    L = computeLayout(); E = route(L);
    let camTo = { ...cam };
    if (centre && anchor) { fitMode = false; camTo = centreOn(L.get(nearest(L, anchor)), Math.max(cam.z, 0.85)); }
    else {
      // Fit the whole level only while it stays readable; past that, show it at full size and let it scroll.
      const f = fitCam(L);
      if (fitMode && (f.z >= 0.5 || expanded.size === 0)) camTo = f;
      else {
        fitMode = false;
        const z = cam.z < 0.6 ? 1 : cam.z, u = usable();
        if (anchor) {
          const a = nearest(L, anchor), ro = from.get(nearest(from, a)), rn = L.get(a);
          const sx = (ro.x + ro.w / 2 - cam.x) * cam.z, sy = (ro.y + ro.h / 2 - cam.y) * cam.z;
          camTo = { z, x: rn.x + rn.w / 2 - sx / z, y: rn.y + rn.h / 2 - sy / z };
        } else {
          // With nothing to hold on to, start where the data starts: the left end of the main line.
          const r = L.get(root);
          camTo = { z, x: -28 / z, y: r.h / 2 - (u.top + (H - u.top - u.bottom) / 2) / z };
        }
      }
    }
    fitBtn.textContent = fitMode ? 'Actual size' : 'Fit all';
    levelButtons();
    if (reduce || !started) { Object.assign(cam, camTo); tw = null; } else tw = { t0: performance.now(), from, camFrom, camTo };
    redraw();
  }
  function panTo(camTo) {
    if (reduce) { Object.assign(cam, camTo); tw = null; } else tw = { t0: performance.now(), from: L, camFrom: { ...cam }, camTo };
    redraw();
  }
  function setFit(on) {
    fitMode = on; fitBtn.textContent = on ? 'Actual size' : 'Fit all';
    const mid = { x: cam.x + W / 2 / cam.z, y: cam.y + H / 2 / cam.z };
    panTo(on ? fitCam(L) : { z: 1, x: mid.x - W / 2, y: mid.y - H / 2 });
  }

  // ---------- drawing ----------
  function rr(x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2)); ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else { ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
  }
  function fitText(s, maxW) {
    if (maxW <= 0) return '';
    if (ctx.measureText(s).width <= maxW) return s;
    let lo = 0, hi = s.length;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ctx.measureText(s.slice(0, m) + '…').width <= maxW) lo = m; else hi = m - 1; }
    return lo > 1 ? s.slice(0, lo) + '…' : '';
  }
  const font = (w, px) => { ctx.font = `${w} ${px}px ${C.font}`; };
  const caps = (text, x, y, color) => { font(600, 9.5); ctx.fillStyle = color; ctx.letterSpacing = '0.08em'; ctx.fillText(text, x, y); ctx.letterSpacing = '0px'; };

  function drawNode(n, r, alpha, st) {
    const { x, y, w, h } = r, own = n.card.status === 'open' || n.card.status === 'revisit';
    const dim = st.related && !st.related.has(n) ? 0.45 : 1;
    ctx.globalAlpha = alpha * dim;
    rr(x, y, w, h, r.open ? 16 : n.kind === 'actor' ? h / 2 : 12);
    ctx.fillStyle = C.fill[Math.min(n.depth - 1, C.fill.length - 1)]; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = own ? C.warn : C.border;
    ctx.setLineDash(own ? [5, 4] : []); ctx.stroke(); ctx.setLineDash([]);
    if (st.done.has(n) || n === st.now || n === selected) {
      const strong = n === st.now || n === selected;
      ctx.globalAlpha = alpha * (strong ? 1 : 0.55);
      ctx.lineWidth = strong ? 2.25 : 1.25; ctx.strokeStyle = C.accent; ctx.stroke();
      if (n === st.now && !r.open) { ctx.globalAlpha = alpha * 0.1; ctx.fillStyle = C.accent; ctx.fill(); }
      ctx.globalAlpha = alpha * dim;
    }
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    if (r.open) {
      // The title stays in view while the box is wider than the screen.
      const hx = clamp(cam.x + 16 / cam.z, x + 16, Math.max(x + 16, x + w - 260));
      font(650, 14); ctx.fillStyle = C.text; ctx.fillText(n.name, hx, y + 23);
      const nw = ctx.measureText(n.name).width;
      caps((KIND[n.kind] || n.kind).toUpperCase() + (n.gaps ? `   ${n.gaps} OPEN` : ''), hx + nw + 12, y + 22.5, n.gaps ? C.warn : C.muted);
      return;
    }
    const pad = n.kind === 'actor' ? 26 : 15, maxW = w - pad * 2, box = !isLeaf(n);
    let inside = '';
    if (box) {
      // A closed box says how much is inside it.
      inside = `${n.children.length} inside`; font(600, 10.5);
      const iw = ctx.measureText(inside).width;
      ctx.fillStyle = C.accent; ctx.fillText(inside, x + w - pad - iw, y + 23);
      if (n.gaps) { const gw = ctx.measureText(`${n.gaps} open  `).width; ctx.fillStyle = C.warn; ctx.fillText(`${n.gaps} open`, x + w - pad - iw - gw, y + 23); inside = `${n.gaps} open  ` + inside; }
    }
    font(600, 10.5); const used = inside ? ctx.measureText(inside).width + 10 : 0;
    font(600, 9.5); ctx.letterSpacing = '0.08em';
    const kind = fitText((KIND[n.kind] || n.kind).toUpperCase(), maxW - used); ctx.letterSpacing = '0px';
    caps(kind, x + pad, y + 23, C.muted);
    font(600, 14.5); ctx.fillStyle = C.text; ctx.fillText(fitText(n.name, maxW), x + pad, y + 46);
    font(400, 12); ctx.fillStyle = C.muted; ctx.fillText(fitText(n.headline, maxW), x + pad, y + 66);
    if (own) { ctx.fillStyle = C.warn; ctx.beginPath(); ctx.arc(x + w - 14, y + h - 14, 3.5, 0, 7); ctx.fill(); }
  }

  function drawEdges(st) {
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
    const pass = hot => {
      for (const g of E) {
        const inFlow = flow && flow.steps.slice(1, stepI + 1).some((s, i) => g.list.some(e => e.from === flow.steps[i].at && e.to === s.at));
        const touch = selected && g.list.some(e => within(e.a, selected) || within(e.b, selected));
        const isHot = inFlow || touch || (selEdge && selEdge.key === g.key) || hoverEdge === g.key;
        if (isHot !== hot) continue;
        const style = LINK[g.kind];
        ctx.globalAlpha = hot ? 1 : (selected || selEdge || flow) ? 0.2 : 0.9;
        ctx.strokeStyle = ctx.fillStyle = style.color;
        ctx.lineWidth = hot ? 2.6 : 1.6; ctx.setLineDash(g.async ? [9, 5] : style.dash);
        ctx.beginPath(); g.pts.forEach(([px, py], i) => i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)); ctx.stroke(); ctx.setLineDash([]);
        const last = g.pts[g.pts.length - 1]; let prev = g.pts[g.pts.length - 2];
        for (let i = g.pts.length - 2; i >= 0; i--) { prev = g.pts[i]; if (Math.hypot(last[0] - prev[0], last[1] - prev[1]) > 0.5) break; }
        const ang = Math.atan2(last[1] - prev[1], last[0] - prev[0]), s = hot ? 9 : 7.5;
        ctx.beginPath(); ctx.moveTo(last[0], last[1]);
        ctx.lineTo(last[0] - s * Math.cos(ang - 0.4), last[1] - s * Math.sin(ang - 0.4)); ctx.lineTo(last[0] - s * Math.cos(ang + 0.4), last[1] - s * Math.sin(ang + 0.4)); ctx.closePath(); ctx.fill();
        if (g.text && (g.lab.show || hot)) {
          font(500, 10.5);
          ctx.fillStyle = '#000'; rr(g.lab.x - g.lab.w / 2, g.lab.y - 9, g.lab.w, 18, 9); ctx.fill();
          ctx.fillStyle = style.color; ctx.fillText(g.text, g.lab.x, g.lab.y + 0.5);
        }
      }
    };
    pass(false); pass(true); // highlighted lines and their labels go on top
    ctx.globalAlpha = 1;
  }

  function paint(solid) {
    let layout = L, k = 1;
    if (tw) {
      k = clamp((performance.now() - tw.t0) / 360, 0, 1);
      const e = 1 - Math.pow(1 - k, 3);
      cam.z = tw.camFrom.z * Math.pow(tw.camTo.z / tw.camFrom.z, e);
      const fc = { x: tw.camFrom.x + W / 2 / tw.camFrom.z, y: tw.camFrom.y + H / 2 / tw.camFrom.z }, tc = { x: tw.camTo.x + W / 2 / tw.camTo.z, y: tw.camTo.y + H / 2 / tw.camTo.z };
      cam.x = lerp(fc.x, tc.x, e) - W / 2 / cam.z; cam.y = lerp(fc.y, tc.y, e) - H / 2 / cam.z;
      if (tw.from !== L && k < 1) {
        // Boxes that appear grow out of the box they were inside; boxes that vanish shrink back into it.
        layout = new Map();
        for (const n of [root, ...order]) {
          const a = tw.from.get(n), b = L.get(n);
          if (!a && !b) continue;
          const ra = a || tw.from.get(nearest(tw.from, n)), rb = b || L.get(nearest(L, n));
          layout.set(n, { x: lerp(ra.x, rb.x, e), y: lerp(ra.y, rb.y, e), w: lerp(ra.w, rb.w, e), h: lerp(ra.h, rb.h, e), open: (b || a).open, alpha: lerp(a ? 1 : 0, b ? 1 : 0, e) });
        }
      }
      if (k >= 1) tw = null;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
    if (solid) { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H); }
    ctx.setTransform(dpr * cam.z, 0, 0, dpr * cam.z, -cam.x * cam.z * dpr, -cam.y * cam.z * dpr);
    const st = { done: new Set(flow ? flow.steps.slice(0, stepI).map(s => rep(nodes.get(s.at))) : []), now: flow ? rep(nodes.get(flow.steps[stepI].at)) : null, related: null };
    if (selected) {
      st.related = new Set(pathOf(selected));
      order.forEach(n => { if (within(n, selected)) st.related.add(n); });
      for (const e of edges) { if (within(e.a, selected)) pathOf(e.b).forEach(p => st.related.add(p)); if (within(e.b, selected)) pathOf(e.a).forEach(p => st.related.add(p)); }
    }
    for (const n of order) { const r = layout.get(n); if (r) drawNode(n, r, r.alpha === undefined ? 1 : r.alpha, st); }
    if (layout === L) drawEdges(st);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1;
  }

  // ---------- panel ----------
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const list = a => a && a.length ? `<ul>${a.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  const sec = (title, body) => body ? `<h3>${title}</h3>${body}` : '';
  const para = s => s ? `<p>${esc(s)}</p>` : '';
  const longName = n => pathOf(n).map(p => p.name).join(' › ');
  const dot = kind => `<i class="dot" style="background:${LINK[kind].color}"></i>`;

  function levelButtons() {
    const lv = level(), exact = atExactLevel();
    document.getElementById('crumbs').innerHTML = '<span class="lvl-label">Level</span>' + Array.from({ length: maxLevel }, (_, i) =>
      `<button data-level="${i + 1}" aria-pressed="${exact && lv === i + 1}" title="Open every box down to level ${i + 1}">${i + 1}</button>`).join('');
  }
  function outline(n, q) {
    const kids = n.children.map(k => {
      const sub = outline(k, q), hit = !q || k.name.toLowerCase().includes(q);
      if (!hit && !sub) return '';
      return `<li><button data-sel="${esc(k.id)}" class="${isGap(k) ? 'gap' : ''}">${esc(k.name)}</button>${sub}</li>`;
    }).join('');
    return kids ? `<ul>${kids}</ul>` : '';
  }
  function showOverview(q) {
    const gaps = order.filter(isGap);
    panel.innerHTML = `<div class="kind">System</div><h2>${esc(M.name)}</h2>
      <p class="muted">${esc(M.note || '')}</p>
      ${problems.length ? `<h3>Problems in the model (${problems.length})</h3><div class="question"><ul>${problems.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
      ${sec(`Still undecided (${gaps.length})`, gaps.length ? `<ul class="links">${gaps.map(g => `<li><button data-sel="${esc(g.id)}"><span>${esc(g.name)}</span><small>${esc(g.parent === root ? '' : g.parent.name)}</small></button></li>`).join('')}</ul>` : '<p class="muted">Nothing open.</p>')}
      ${q ? '' : `<h3>Connections by category (${edges.length})</h3><ul class="links">${Object.entries(LINK).map(([k, v]) => { const c = edges.filter(e => e.kind === k).length; return c ? `<li><button data-cat="${k}" title="${esc(v.hint)}"><span>${dot(k)}${esc(v.label)}</span><small>${c}</small></button></li>` : ''; }).join('')}</ul>`}
      <h3>${q ? 'Matches' : 'Every part'}</h3><div class="outline">${outline(root, q) || '<p class="muted">No part has that name.</p>'}</div>`;
  }
  function showNode(n) {
    const c = n.card, st = c.status || 'open';
    const ins = edges.filter(e => within(e.b, n) && !within(e.a, n)), outs = edges.filter(e => within(e.a, n) && !within(e.b, n));
    const link = (e, other) => `<li><button data-sel="${esc(other.id)}"><span>${dot(e.kind)}${esc(longName(other))}</span><small>${esc(e.label || '')}</small></button></li>`;
    const trail = pathOf(n).slice(0, -1);
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      ${trail.length ? `<div class="trail">${trail.map(p => `<button data-sel="${esc(p.id)}">${esc(p.name)}</button>`).join('<span>›</span>')}</div>` : ''}
      <div class="kind">${esc(KIND[n.kind] || n.kind)}<span class="tag ${st}">${STATUS[st] || st}</span></div>
      <h2>${esc(n.name)}</h2><div class="path">${esc(n.id)}</div>
      ${c.question ? sec('Open question', `<div class="question">${esc(c.question)}</div>`) : ''}
      ${sec('Does', para(c.does))}
      ${sec('Rules and numbers', list(c.rules))}
      ${sec('Decision', para(c.decision) + (c.why ? `<p class="muted">${esc(c.why)}</p>` : ''))}
      ${sec('Rejected', list(c.rejected))}
      ${sec('If it fails', para(c.failure))}
      ${sec('Exposes', para(c.exposes))}
      ${sec(`Inside (${n.children.length})`, n.children.length ? `<ul class="links">${n.children.map(k => `<li><button data-sel="${esc(k.id)}"><span>${esc(k.name)}</span><small>${esc(k.headline)}</small></button></li>`).join('')}</ul>` : '')}
      ${sec(`Receives from (${ins.length})`, ins.length ? `<ul class="links">${ins.map(e => link(e, e.a)).join('')}</ul>` : '')}
      ${sec(`Sends to (${outs.length})`, outs.length ? `<ul class="links">${outs.map(e => link(e, e.b)).join('')}</ul>` : '')}`;
    panel.scrollTop = 0;
  }
  // All connections of one category, and only that category on the diagram.
  function showCategory(k) {
    const all = edges.filter(e => e.kind === k);
    only(k);
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      <div class="kind">${dot(k)}Category</div><h2>${esc(LINK[k].label)}</h2><p class="muted">${esc(LINK[k].hint)}. The diagram now shows only these ${all.length}.</p>
      <p><button class="btn" data-all>Show every category again</button></p>
      <ul class="links">${all.map(e => `<li><button data-sel="${esc(e.a.id)}"><span>${esc(longName(e.a))} → ${esc(longName(e.b))}</span><small>${e.async ? 'no wait · ' : ''}${esc(e.label || '')}</small></button></li>`).join('')}</ul>`;
    panel.scrollTop = 0;
  }
  function syncLegend() { legend.querySelectorAll('[data-kind]').forEach(b => b.setAttribute('aria-pressed', String(!hidden.has(b.dataset.kind)))); selEdge = null; E = route(L); redraw(); }
  function only(k) { hidden.clear(); if (k) Object.keys(LINK).forEach(x => { if (x !== k) hidden.add(x); }); syncLegend(); }
  function showEdge(g) {
    panel.innerHTML = `<button class="back" data-sel="">‹ Every part</button>
      <div class="kind">${dot(g.kind)}${esc(LINK[g.kind].label)}${g.async ? '<span class="tag">Does not wait</span>' : ''}</div><h2>${esc(g.a.name)} → ${esc(g.b.name)}</h2>
      ${g.list.map(e => `<h3>${esc(e.label || 'Connection')}</h3>
        <ul class="links"><li><button data-sel="${esc(e.a.id)}"><span>${esc(longName(e.a))}</span><small>from</small></button></li>
        <li><button data-sel="${esc(e.b.id)}"><span>${esc(longName(e.b))}</span><small>to</small></button></li></ul>
        ${e.card ? `<ul>${['carries', 'mode', 'timeout', 'retry'].filter(k => e.card[k]).map(k => `<li><span class="muted">${k[0].toUpperCase() + k.slice(1)}:</span> ${esc(e.card[k])}</li>`).join('')}</ul>` : '<p class="muted">No contract recorded for this connection yet.</p>'}`).join('')}`;
    panel.scrollTop = 0;
  }
  // Selecting from a list brings the part into view, opening the boxes around it if needed.
  function goTo(n) {
    const changed = show(n);
    const r = L.get(n), u = usable();
    const seen = r && !changed && (r.x - cam.x) * cam.z > 20 && (r.x + r.w - cam.x) * cam.z < W - 20 && (r.y - cam.y) * cam.z > u.top && (r.y + r.h - cam.y) * cam.z < H - u.bottom;
    if (changed) relayout(n, true);
    else if (!seen) { fitMode = false; fitBtn.textContent = 'Fit all'; panTo(centreOn(L.get(n), Math.max(cam.z, 0.85))); }
  }
  function select(n, move) {
    selected = n || null; selEdge = null;
    if (selected) { showNode(selected); if (move) goTo(selected); history.replaceState(null, '', '#' + selected.id); }
    else { showOverview(''); history.replaceState(null, '', location.pathname + location.search); }
    redraw();
  }
  panel.addEventListener('click', e => {
    const c = e.target.closest('[data-cat]'); if (c) return showCategory(c.dataset.cat);
    if (e.target.closest('[data-all]')) { only(null); return select(null); }
    const b = e.target.closest('[data-sel]'); if (b) select(nodes.get(b.dataset.sel), true);
  });
  document.getElementById('crumbs').addEventListener('click', e => { const b = e.target.closest('[data-level]'); if (b) toLevel(+b.dataset.level, null); });

  // ---------- levels ----------
  function toLevel(lv, anchor) {
    lv = clamp(lv, 1, maxLevel);
    if (atExactLevel() && lv === level()) return;
    setLevel(lv); relayout(anchor || selected, false);
  }
  function toggle(n) {
    if (isLeaf(n)) return;
    if (expanded.has(n)) close(n); else expanded.add(n);
    relayout(n, false);
  }

  // ---------- flow walk ----------
  const flowSel = document.getElementById('flow'), stepEl = document.getElementById('step');
  flowSel.innerHTML = '<option value="">None</option>' + M.flows.map(f => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join('');
  function showStep() {
    document.getElementById('prev').disabled = !flow || stepI === 0;
    document.getElementById('next').disabled = !flow || stepI === flow.steps.length - 1;
    if (!flow) { stepEl.textContent = 'Pick a flow to follow one request through the system.'; redraw(); return; }
    const s = flow.steps[stepI], n = nodes.get(s.at);
    stepEl.innerHTML = `<b>${stepI + 1} / ${flow.steps.length}</b>${esc(n.name)}: ${esc(s.note)}`;
    selected = null; selEdge = null; showNode(n); goTo(n); redraw();
  }
  flowSel.addEventListener('change', () => { flow = M.flows.find(f => f.id === flowSel.value) || null; stepI = 0; if (!flow) showOverview(''); showStep(); });
  const stepBy = d => { if (!flow) return; stepI = clamp(stepI + d, 0, flow.steps.length - 1); showStep(); };
  document.getElementById('prev').addEventListener('click', () => stepBy(-1));
  document.getElementById('next').addEventListener('click', () => stepBy(1));

  // ---------- input ----------
  const world = e => { const r = canvas.getBoundingClientRect(); return [cam.x + (e.clientX - r.left) / cam.z, cam.y + (e.clientY - r.top) / cam.z]; };
  function hitNode(wx, wy) {
    let best = null;
    for (const n of order) { const r = L.get(n); if (r && wx >= r.x && wx <= r.x + r.w && wy >= r.y && wy <= r.y + r.h) best = n; }
    return best;
  }
  function hitEdge(wx, wy) {
    const tol = 6 / cam.z;
    for (const g of E) for (let i = 0; i + 1 < g.pts.length; i++) {
      const [ax, ay] = g.pts[i], [bx, by] = g.pts[i + 1], dx = bx - ax, dy = by - ay;
      const k = clamp(((wx - ax) * dx + (wy - ay) * dy) / (dx * dx + dy * dy || 1), 0, 1);
      if (Math.hypot(ax + k * dx - wx, ay + k * dy - wy) < tol) return g;
    }
    return null;
  }
  const hideHint = () => document.getElementById('hint').classList.add('gone');
  let wheelAcc = 0, wheelAt = 0;
  canvas.addEventListener('wheel', e => {
    e.preventDefault(); hideHint();
    if (e.shiftKey || (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(e.deltaY))) { fitMode = false; fitBtn.textContent = 'Fit all'; cam.x += (e.shiftKey ? (e.deltaY || e.deltaX) : e.deltaX) / cam.z; tw = null; redraw(); return; }
    // One step of the wheel is one level, not a little more magnification.
    const now = performance.now();
    if (now - wheelAt > 400) wheelAcc = 0;
    wheelAcc += e.deltaY;
    if (Math.abs(wheelAcc) < 50 || now - wheelAt < 260) return;
    const dir = wheelAcc < 0 ? 1 : -1; wheelAcc = 0; wheelAt = now;
    const [wx, wy] = world(e);
    toLevel((atExactLevel() ? level() : dir > 0 ? level() - 1 : level()) + dir, hitNode(wx, wy));
  }, { passive: false });
  let drag = null;
  canvas.addEventListener('pointerdown', e => { canvas.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y, moved: false }; });
  canvas.addEventListener('pointermove', e => {
    if (!drag) {
      const [wx, wy] = world(e), g = hitEdge(wx, wy);
      canvas.style.cursor = g || hitNode(wx, wy) ? 'pointer' : '';
      if ((g ? g.key : null) !== hoverEdge) { hoverEdge = g ? g.key : null; redraw(); }
      return;
    }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true; canvas.classList.add('dragging'); hideHint(); tw = null;
    if (fitMode) { fitMode = false; fitBtn.textContent = 'Fit all'; }
    cam.x = drag.cx - dx / cam.z; cam.y = drag.cy - dy / cam.z; redraw();
  });
  canvas.addEventListener('pointerleave', () => { if (hoverEdge) { hoverEdge = null; redraw(); } });
  canvas.addEventListener('pointerup', e => {
    const d = drag; drag = null; canvas.classList.remove('dragging');
    if (!d || d.moved) return;
    const [wx, wy] = world(e), g = hitEdge(wx, wy);
    if (g) { selected = null; selEdge = g; showEdge(g); redraw(); return; }
    select(hitNode(wx, wy), false);
  });
  canvas.addEventListener('dblclick', e => { const [wx, wy] = world(e), n = hitNode(wx, wy); if (n) { hideHint(); toggle(n); } });
  const search = document.getElementById('search');
  document.addEventListener('keydown', e => {
    const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); search.focus(); return; }
    if (typing) { if (e.key === 'Escape') document.activeElement.blur(); return; }
    const step = 90 / cam.z;
    if (e.key === 'ArrowLeft') cam.x -= step; else if (e.key === 'ArrowRight') cam.x += step;
    else if (e.key === 'ArrowUp') cam.y -= step; else if (e.key === 'ArrowDown') cam.y += step;
    else if (e.key === '+' || e.key === '=') return toLevel(level() + 1, selected);
    else if (e.key === '-') return toLevel(atExactLevel() ? level() - 1 : level() - 1, selected);
    else if (e.key === '0') return setFit(true);
    else if (e.key === 'Enter' && selected) return toggle(selected);
    else if (e.key === ']') return stepBy(1); else if (e.key === '[') return stepBy(-1);
    else if (e.key === 'Escape') return select(null);
    else return;
    e.preventDefault(); tw = null; fitMode = false; fitBtn.textContent = 'Fit all'; redraw();
  });
  search.addEventListener('input', () => { selected = null; selEdge = null; showOverview(search.value.trim().toLowerCase()); redraw(); });
  search.addEventListener('keydown', e => { if (e.key === 'Enter') { const b = panel.querySelector('.outline [data-sel]'); if (b) { b.click(); search.blur(); } } });
  fitBtn.addEventListener('click', () => setFit(!fitMode));
  // Save the level that is open, whole and at full size, as a picture for documents that cannot run the viewer.
  document.getElementById('shot').addEventListener('click', () => {
    const r = L.get(root), m = 40, keep = { ...cam }, kw = W, kh = H, kd = dpr;
    tw = null; W = r.w + m * 2; H = r.h + m * 2; dpr = Math.min(2, 12000 / W, 12000 / H);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    Object.assign(cam, { x: -m, y: -m, z: 1 });
    paint(true);
    const a = document.createElement('a');
    a.download = `${M.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}-level-${level()}.png`;
    a.href = canvas.toDataURL('image/png'); a.click();
    W = kw; H = kh; dpr = kd; Object.assign(cam, keep); measure();
  });
  document.getElementById('zin').addEventListener('click', () => toLevel(level() + 1, selected));
  document.getElementById('zout').addEventListener('click', () => toLevel(level() - 1, selected));

  legend.innerHTML = Object.entries(LINK).filter(([k]) => edges.some(e => e.kind === k)).map(([k, v]) =>
    `<button type="button" data-kind="${k}" aria-pressed="true" title="${esc(v.hint)}. Click to hide or show; double-click to show only this."><svg width="26" height="8" aria-hidden="true"><line x1="1" y1="4" x2="25" y2="4" stroke="${v.color}" stroke-width="2" stroke-dasharray="${v.dash.join(' ')}"/></svg>${esc(v.label)}</button>`).join('')
    + '<span class="key"><svg width="26" height="8" aria-hidden="true"><line x1="1" y1="4" x2="25" y2="4" stroke="#9a9ab0" stroke-width="2" stroke-dasharray="9 5"/></svg>dashed: does not wait</span>';
  legend.addEventListener('click', e => {
    const b = e.target.closest('[data-kind]'); if (!b) return;
    const k = b.dataset.kind; hidden.has(k) ? hidden.delete(k) : hidden.add(k); syncLegend();
  });
  legend.addEventListener('dblclick', e => {
    const b = e.target.closest('[data-kind]'); if (!b) return;
    const k = b.dataset.kind, alone = !hidden.has(k) && Object.keys(LINK).every(x => x === k || hidden.has(x));
    only(alone ? null : k);
  });
  const gapBtn = document.getElementById('gaps');
  gapBtn.textContent = (problems.length ? `${problems.length} problems · ` : '') + (root.gaps ? `${root.gaps} undecided` : 'Fully decided'); gapBtn.classList.toggle('warn', root.gaps > 0 || problems.length > 0);
  gapBtn.addEventListener('click', () => select(null));

  // ---------- start ----------
  const measure = () => {
    dpr = window.devicePixelRatio || 1; W = wrap.clientWidth; H = wrap.clientHeight; legendH = legend.offsetHeight + 16;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    if (!W || !H) return;
    if (!started) {
      const n = nodes.get(decodeURIComponent(location.hash.slice(1)));
      if (n) { show(n); selected = n; showNode(n); relayout(n, true); } else relayout(null, false);
      started = true;
    } else if (fitMode) Object.assign(cam, fitCam(L));
    redraw();
  };
  document.getElementById('title').textContent = M.name; document.title = M.name + ' · architecture';
  levelButtons(); showOverview(''); showStep();
  new ResizeObserver(measure).observe(wrap);
  addEventListener('resize', measure);
  measure();
})();
