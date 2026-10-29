// The Journeys view and the Data view. viewer.js calls ARCH_FLOW(api) once and switches to these views.
//   Journeys: one journey, one data item's flow, or a trace, drawn alone as a flat flow diagram. Each
//             top-level part is a band, decisions are diamonds, and each branch shows its condition.
//   Data:     every data item as a table, with the steps that turn one item into another.
// Scroll zooms at the pointer, drag moves, and "Fit all" shows everything.
window.ARCH_FLOW = api => {
  'use strict';
  const { A, S, esc } = api;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.getElementById('flowsvg');
  const sel = document.getElementById('fsel'), stepEl = document.getElementById('fstep');
  const prevB = document.getElementById('fprev'), nextB = document.getElementById('fnext');
  const walkBar = document.getElementById('fwalk');

  const NODE_W = 200, NODE_H = 76, COL_GAP = 92, ROW_GAP = 30, BAND_TOP = 40, BAND_BOTTOM = 22, BAND_GAP = 18, LEFT = 28;
  const TABLE_W = 236, ROW = 20, TABLE_HEAD = 46, TCOL_GAP = 120, TROW_GAP = 30;

  const mctx = document.createElement('canvas').getContext('2d');
  const textW = (t, weight, px) => { mctx.font = `${weight} ${px}px ${api.FONT}`; return mctx.measureText(t).width; };
  function wrap(text, maxW, weight, px, maxLines) {
    const words = String(text || '').split(/\s+/).filter(Boolean), lines = [];
    let line = '';
    for (const w of words) {
      const next = line ? line + ' ' + w : w;
      if (textW(next, weight, px) <= maxW || !line) { line = next; continue; }
      lines.push(line);
      line = w;
    }
    if (line) lines.push(line);
    if (lines.length > maxLines) {
      lines.length = maxLines;
      let last = lines[maxLines - 1];
      while (last.length > 1 && textW(last + '…', weight, px) > maxW) last = last.slice(0, -1);
      lines[maxLines - 1] = last + '…';
    }
    return lines.map(l => { while (l.length > 1 && textW(l, weight, px) > maxW) l = l.slice(0, -2) + '…'; return l; });
  }
  const top = n => { let p = n; while (p.parent && p.parent.depth) p = p.parent; return p; };
  const kindLabel = k => (S.kinds[k] || { label: k }).label;
  const leavesOf = n => (A.isLeaf(n) ? [n] : n.children.flatMap(leavesOf));

  // ------------------------------------------------------------------ what to draw

  // Ranks by the longest path from the start, ignoring lines that loop back.
  function ranks(ids, edges) {
    const out = new Map(ids.map(x => [x, new Set()]));
    for (const l of edges) if (out.has(l.from) && out.has(l.to)) out.get(l.from).add(l.to);
    const state = new Map(), preds = new Map(ids.map(x => [x, []]));
    const dfs = u => { state.set(u, 1); for (const v of out.get(u)) { if (state.get(v) === 1) continue; preds.get(v).push(u); if (!state.get(v)) dfs(v); } state.set(u, 2); };
    ids.forEach(x => { if (!state.get(x)) dfs(x); });
    const rank = new Map();
    const rankOf = v => { if (rank.has(v)) return rank.get(v); rank.set(v, 0); const r = preds.get(v).length ? Math.max(...preds.get(v).map(rankOf)) + 1 : 0; rank.set(v, r); return r; };
    ids.forEach(rankOf);
    return rank;
  }
  const graph = (kind, id, title, sub, ids, edges, notes) => {
    const rank = ranks(ids, edges);
    const steps = ids.map((x, k) => ({ x, k })).sort((p, q) => rank.get(p.x) - rank.get(q.x) || p.k - q.k).map(s => s.x);
    return { kind, id, title, sub, ids: steps, rank, edges, notes: notes || {} };
  };
  function journeyGraph(J) {
    return graph('journey', J.id, J.name, S.journeyTypes[J.type] || '', J.steps.map(s => s.id), J.links, J.notes);
  }
  // A data item's flow: every line that carries it, plus the branches of each decision it passes through.
  function dataGraph(id) {
    const E = new Set(A.links.filter(l => l.carries === id));
    for (let grew = true; grew;) {
      grew = false;
      for (const l of [...E]) if (l.b.kind === 'decision') for (const m of A.links) if (m.a === l.b && m.branch && !E.has(m)) { E.add(m); grew = true; }
    }
    const edges = [...E], ids = [...new Set(edges.flatMap(l => [l.from, l.to]))];
    return graph('data', id, `Flow of ${A.dataName(id)}`, 'Every line that carries it, and every branch it takes', ids, edges);
  }
  // Everything a part reaches (forward) or everything that reaches it (back), across every level.
  function traceGraph(id, dir) {
    const start = A.parts.get(id), seen = new Set(), edges = new Set(), queue = leavesOf(start).map(n => n.id);
    queue.forEach(x => seen.add(x));
    while (queue.length && edges.size < 600) {
      const at = queue.shift();
      for (const l of A.links) {
        if (S.offJourney.includes(l.kind) || (dir === 'fwd' ? l.from !== at : l.to !== at)) continue;
        edges.add(l);
        const next = dir === 'fwd' ? l.to : l.from;
        if (!seen.has(next)) { seen.add(next); queue.push(next); }
      }
    }
    const list = [...edges], ids = [...new Set([...leavesOf(start).map(n => n.id), ...list.flatMap(l => [l.from, l.to])])];
    return graph('trace', `${id}:${dir}`, dir === 'fwd' ? `Everything ${start.name} reaches` : `Everything that reaches ${start.name}`,
      dir === 'fwd' ? 'Follows every line out of it, and out of what it reaches, to the end' : 'Follows every line into it back to where it starts', ids, list);
  }

  // ------------------------------------------------------------------ layout

  function layoutFlow(G) {
    const pos = new Map(), bandMap = new Map();
    for (const id of G.ids) {
      const t = top(A.parts.get(id));
      if (!bandMap.has(t.id)) bandMap.set(t.id, { t, ids: [] });
      bandMap.get(t.id).ids.push(id);
    }
    const bands = [...bandMap.values()];
    const maxRank = Math.max(0, ...G.ids.map(x => G.rank.get(x)));
    const W = LEFT * 2 + (maxRank + 1) * (NODE_W + COL_GAP) - COL_GAP;
    let y = 0;
    for (const b of bands) {
      const cols = new Map();
      for (const id of b.ids) { const r = G.rank.get(id); if (!cols.has(r)) cols.set(r, []); cols.get(r).push(id); }
      const rows = Math.max(...[...cols.values()].map(c => c.length));
      Object.assign(b, { x: 0, y, w: W, h: BAND_TOP + rows * NODE_H + (rows - 1) * ROW_GAP + BAND_BOTTOM });
      for (const [r, ids] of cols) ids.forEach((id, k) => pos.set(id, { x: LEFT + r * (NODE_W + COL_GAP), y: y + BAND_TOP + k * (NODE_H + ROW_GAP), w: NODE_W, h: NODE_H, n: A.parts.get(id) }));
      y += b.h + BAND_GAP;
    }
    // Lines between the same two parts are drawn once, with their labels joined.
    const pairs = new Map();
    for (const l of G.edges) {
      const key = `${l.from}>${l.to}`;
      if (!pairs.has(key)) pairs.set(key, []);
      pairs.get(key).push(l);
    }
    const edges = [...pairs.values()].map(list => {
      const a = pos.get(list[0].from), b = pos.get(list[0].to);
      return { list, from: list[0].from, to: list[0].to, ...curve(a, b), text: list.map(l => l.text || l.label).filter(Boolean).join(' · ') };
    });
    return { pos, bands, edges, bounds: { x: 0, y: 0, w: W, h: Math.max(y - BAND_GAP, 1) } };
  }

  // A smooth line from one box to another, with the point halfway along for its label.
  function curve(a, b) {
    const bz = (p0, p1, p2, p3, t) => { const u = 1 - t; return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3; };
    let P;
    if (b.x > a.x + a.w - 1) {
      const sx = a.x + a.w, sy = a.y + a.h / 2, ex = b.x, ey = b.y + b.h / 2, dx = Math.max(36, (ex - sx) / 2);
      P = [sx, sy, sx + dx, sy, ex - dx, ey, ex, ey];
    } else if (b.x === a.x) {
      const sx = a.x + a.w, sy = a.y + a.h / 2, ex = b.x + b.w, ey = b.y + b.h / 2, bulge = 46 + Math.abs(ey - sy) * 0.12;
      P = [sx, sy, sx + bulge, sy, ex + bulge, ey, ex, ey];
    } else {
      const sx = a.x + a.w / 2, sy = a.y + a.h, ex = b.x + b.w / 2, ey = b.y + b.h, drop = 34 + Math.abs(sx - ex) * 0.08;
      P = [sx, sy, sx, sy + drop, ex, ey + drop, ex, ey];
    }
    const lx = bz(P[0], P[2], P[4], P[6], 0.5), ly = bz(P[1], P[3], P[5], P[7], 0.5);
    return { d: `M${P[0]} ${P[1]} C${P[2]} ${P[3]} ${P[4]} ${P[5]} ${P[6]} ${P[7]}`, lx, ly };
  }

  function layoutData() {
    const items = [...A.data.values()];
    const lineage = new Map();
    for (const n of A.order) {
      if (n.kind !== 'step') continue;
      for (const a of A.asList(n.spec.in)) for (const b of A.asList(n.spec.out)) {
        if (a === b || !A.data.has(a) || !A.data.has(b)) continue;
        const key = `${a}>${b}`;
        if (!lineage.has(key)) lineage.set(key, { from: a, to: b, steps: [] });
        lineage.get(key).steps.push(n);
      }
    }
    const L = [...lineage.values()], rank = ranks(items.map(d => d.id), L);
    const cols = new Map();
    for (const d of items) { const r = rank.get(d.id); if (!cols.has(r)) cols.set(r, []); cols.get(r).push(d); }
    const pos = new Map();
    let maxH = 0;
    for (const [r, list] of cols) {
      let y = 0;
      for (const d of list) {
        const fields = Object.entries(d.fields), kept = A.order.filter(n => n.kind === 'store' && A.asList(n.spec.keeps).includes(d.id));
        const h = TABLE_HEAD + (kept.length ? 16 : 0) + fields.length * ROW + 10;
        pos.set(d.id, { x: LEFT + r * (TABLE_W + TCOL_GAP), y, w: TABLE_W, h, d, fields, kept });
        y += h + TROW_GAP;
      }
      maxH = Math.max(maxH, y - TROW_GAP);
    }
    const edges = L.map(l => {
      const a = pos.get(l.from), b = pos.get(l.to);
      const names = l.steps.map(s => s.name);
      return { ...l, ...curve({ ...a, h: TABLE_HEAD * 2 - 6 }, { ...b, h: TABLE_HEAD * 2 - 6 }), text: names.length > 2 ? `${names[0]} +${names.length - 1}` : names.join(' · ') };
    });
    // A field whose type names another data item is a reference to it.
    const refs = [];
    for (const p of pos.values()) {
      p.fields.forEach(([f, t], k) => {
        const target = String(t).replace(/\[\]$/, '');
        if (!A.data.has(target) || target === p.d.id) return;
        const q = pos.get(target), fy = p.y + TABLE_HEAD + (p.kept.length ? 16 : 0) + k * ROW + ROW / 2;
        const sx = p.x + p.w, ex = q.x <= p.x ? q.x + q.w : q.x, ey = q.y + 20;
        const dx = q.x <= p.x ? 60 : Math.max(36, (ex - sx) / 2);
        refs.push({ from: p.d.id, to: target, many: /\[\]$/.test(t), d: `M${sx} ${fy} C${sx + dx} ${fy} ${q.x <= p.x ? ex + 60 : ex - dx} ${ey} ${ex} ${ey}` });
      });
    }
    const maxRank = Math.max(0, ...rank.values());
    return { pos, edges, refs, bounds: { x: 0, y: 0, w: LEFT * 2 + (maxRank + 1) * (TABLE_W + TCOL_GAP) - TCOL_GAP, h: Math.max(maxH, 1) } };
  }

  // ------------------------------------------------------------------ drawing

  let view = 'journeys', G = null, L = null, stepI = -1, picked = null, hover = null;
  const cam = { x: 0, y: 0, z: 1 };

  const markers = C => Object.entries(S.links).map(([k, v]) => {
    const c = C.links[k];
    const shape = v.head === 'open' ? `<path d="M1 1 L9 5 L1 9 Z" fill="${C.bg}" stroke="${c}" stroke-width="1.3"/>`
      : v.head === 'bar' ? `<path d="M8 0 L8 10" stroke="${c}" stroke-width="2.2"/>`
      : v.head === 'dot' ? `<circle cx="5" cy="5" r="3.4" fill="${c}"/>`
      : `<path d="M0 0 L10 5 L0 10 Z" fill="${c}"/>`;
    return `<marker id="h-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">${shape}</marker>`;
  }).join('') + `<marker id="h-ref" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0 L10 5 L0 10" fill="none" stroke="${C.muted}" stroke-width="1.4"/></marker>`;

  // The outline of each kind of part, drawn in the box (x, y, w, h).
  function shape(kind, x, y, w, h, fill, stroke, sw, dash) {
    const st = `fill="${fill}" stroke="${stroke}" stroke-width="${sw}"${dash ? ` stroke-dasharray="${dash}"` : ''}`;
    const line = d => `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="1"/>`;
    switch (kind) {
      case 'decision': return `<path d="M${x + w / 2} ${y} L${x + w} ${y + h / 2} L${x + w / 2} ${y + h} L${x} ${y + h / 2} Z" ${st}/>`;
      case 'store': {
        const ry = 7;
        return `<path d="M${x} ${y + ry} L${x} ${y + h - ry} A${w / 2} ${ry} 0 0 0 ${x + w} ${y + h - ry} L${x + w} ${y + ry} A${w / 2} ${ry} 0 0 0 ${x} ${y + ry} Z" ${st}/>`
          + `<path d="M${x} ${y + ry} A${w / 2} ${ry} 0 0 0 ${x + w} ${y + ry}" fill="none" stroke="${stroke}" stroke-width="${sw}"/>`;
      }
      case 'queue': return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" ${st}/>` + [16, 26, 36].map(o => line(`M${x + w - o} ${y + 1} L${x + w - o} ${y + h - 1}`)).join('');
      case 'event': return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${h / 2}" ${st}/>`;
      case 'external': return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" ${st}/>` + line(`M${x + 8} ${y} L${x + 8} ${y + h}`) + line(`M${x + w - 8} ${y} L${x + w - 8} ${y + h}`);
      case 'ui': return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" ${st}/>` + line(`M${x} ${y + 12} L${x + w} ${y + 12}`)
        + [8, 14, 20].map(o => `<circle cx="${x + o}" cy="${y + 6}" r="1.6" fill="${stroke}"/>`).join('');
      case 'group': return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" ${st}/>`;
      default: return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" ${st}/>`;
    }
  }

  function nodeSVG(p, C, st) {
    const { x, y, w, h, n } = p, open = n.status !== 'accepted';
    const hot = st.now === n.id || picked === n.id;
    const stroke = hot ? C.accent : open ? C.warn : api.mix(C.text, C.surface, 0.5);
    const fill = st.now === n.id ? api.mix(C.accent, C.surface, 0.14) : C.surface;
    const parent = n.parent && n.parent.depth && n.parent !== top(n) ? n.parent.name : '';
    let out = `<g data-node="${esc(n.id)}" opacity="${st.dim ? 0.28 : 1}" style="cursor:pointer">`;
    out += shape(n.kind, x, y, w, h, fill, stroke, hot ? 2.2 : 1.4, open && !hot ? '5 4' : '');
    const center = n.kind === 'decision';
    const maxW = center ? w * 0.56 : n.kind === 'queue' ? w - 64 : w - 28;
    const cx = center ? x + w / 2 : x + (n.kind === 'external' ? 18 : n.kind === 'event' ? 22 : 14);
    const anchor = center ? 'middle' : 'start';
    const lines = wrap(n.name, maxW, 600, 13, 2);
    const kindY = center ? y + h / 2 - (lines.length > 1 ? 21 : 13) : y + (n.kind === 'ui' ? 27 : 20);
    if (n.kind === 'event') out += `<circle cx="${x + 13}" cy="${y + h / 2}" r="3.5" fill="${C.accent}"/>`;
    out += `<text x="${cx}" y="${kindY}" text-anchor="${anchor}" fill="${C.muted}" style="font:600 9px ${api.FONT};letter-spacing:.08em">${esc(kindLabel(n.kind).toUpperCase())}</text>`;
    lines.forEach((t, i) => { out += `<text x="${cx}" y="${kindY + 17 + i * 16}" text-anchor="${anchor}" fill="${C.text}" style="font:600 13px ${api.FONT}">${esc(t)}</text>`; });
    if (parent && !center) out += `<text x="${cx}" y="${y + h - 10}" fill="${C.muted}" style="font:400 10.5px ${api.FONT}">${esc(wrap(parent, maxW, 400, 10.5, 1)[0] || '')}</text>`;
    if (st.num) {
      const bx = x + w - (center ? w / 2 - 4 : 2), by = y + (center ? 4 : 2);
      out += `<circle cx="${bx}" cy="${by}" r="10" fill="${hot ? C.accent : C.raised}" stroke="${C.border}"/><text x="${bx}" y="${by + 3.6}" text-anchor="middle" fill="${hot ? C.bg : C.text}" style="font:600 10px ${api.FONT}">${st.num}</text>`;
    }
    return out + '</g>';
  }

  function flowSVG(C) {
    const visited = new Set(stepI >= 0 ? G.ids.slice(0, stepI + 1) : G.ids);
    const now = stepI >= 0 ? G.ids[stepI] : null;
    let out = '';
    L.bands.forEach((b, i) => {
      out += `<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="14" fill="${api.mix(C.text, C.bg, i % 2 ? 0.025 : 0.045)}" stroke="${api.mix(C.text, C.bg, 0.3)}" stroke-width="1.2"/>`;
      out += `<text x="${b.x + 16}" y="${b.y + 22}" fill="${C.muted}" style="font:600 10px ${api.FONT};letter-spacing:.08em">${esc(b.t.name.toUpperCase())}  ·  ${esc(kindLabel(b.t.kind).toUpperCase())}</text>`;
    });
    const touch = id => hover === id || picked === id;
    for (const pass of [false, true]) {
      for (const e of L.edges) {
        const kind = e.list[0].kind, async = e.list.every(l => l.async);
        const lit = visited.has(e.from) && visited.has(e.to);
        const hot = !!(touch(e.from) || touch(e.to) || (now && e.to === now && lit));
        if (hot !== pass) continue;
        const color = C.links[kind];
        const op = !lit ? 0.18 : (hover || picked) && !hot ? 0.35 : 1;
        out += `<g data-edge="${esc(e.from)}>${esc(e.to)}" opacity="${op}" style="cursor:pointer">`;
        out += `<path d="${e.d}" fill="none" stroke="transparent" stroke-width="12"/>`;
        out += `<path d="${e.d}" fill="none" stroke="${color}" stroke-width="${hot ? 1.8 : 1.1}" stroke-linecap="round"${async ? '' : ' stroke-dasharray="2 4"'} marker-end="url(#h-${kind})"/>`;
        if (e.text) {
          const tw = textW(e.text, 500, 10.5) + 14;
          out += `<rect x="${e.lx - tw / 2}" y="${e.ly - 9}" width="${tw}" height="18" rx="9" fill="${C.bg}" stroke="${api.mix(color, C.bg, 0.35)}"/>`;
          out += `<text x="${e.lx}" y="${e.ly + 3.8}" text-anchor="middle" fill="${color}" style="font:500 10.5px ${api.FONT}">${esc(e.text)}</text>`;
        }
        out += '</g>';
      }
    }
    G.ids.forEach((id, k) => { out += nodeSVG(L.pos.get(id), C, { dim: !visited.has(id), now, num: G.kind === 'journey' ? k + 1 : 0 }); });
    return out;
  }

  function dataSVG(C) {
    const rel = picked && A.data.has(picked) ? new Set([picked, ...L.edges.filter(e => e.from === picked || e.to === picked).flatMap(e => [e.from, e.to]),
      ...L.refs.filter(r => r.from === picked || r.to === picked).flatMap(r => [r.from, r.to])]) : null;
    let out = '';
    for (const r of L.refs) {
      const on = !rel || r.from === picked || r.to === picked;
      out += `<path d="${r.d}" fill="none" stroke="${C.muted}" stroke-width="1.1" stroke-dasharray="6 4" marker-end="url(#h-ref)" opacity="${on ? 0.9 : 0.15}"/>`;
    }
    for (const e of L.edges) {
      const on = !rel || e.from === picked || e.to === picked, color = C.links.data;
      out += `<g opacity="${on ? 1 : 0.15}"><path d="${e.d}" fill="none" stroke="${color}" stroke-width="1.2" marker-end="url(#h-data)"/>`;
      if (e.text) {
        const tw = textW(e.text, 500, 10.5) + 14;
        out += `<rect x="${e.lx - tw / 2}" y="${e.ly - 9}" width="${tw}" height="18" rx="9" fill="${C.bg}" stroke="${api.mix(color, C.bg, 0.35)}"/><text x="${e.lx}" y="${e.ly + 3.8}" text-anchor="middle" fill="${color}" style="font:500 10.5px ${api.FONT}">${esc(e.text)}</text>`;
      }
      out += '</g>';
    }
    for (const p of L.pos.values()) {
      const { x, y, w, h, d, fields, kept } = p, on = !rel || rel.has(d.id), hot = picked === d.id;
      out += `<g data-data="${esc(d.id)}" opacity="${on ? 1 : 0.3}" style="cursor:pointer">`;
      out += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${C.surface}" stroke="${hot ? C.accent : api.mix(C.text, C.surface, 0.5)}" stroke-width="${hot ? 2.2 : 1.4}"/>`;
      out += `<path d="M${x} ${y + TABLE_HEAD + (kept.length ? 16 : 0) - 6} L${x + w} ${y + TABLE_HEAD + (kept.length ? 16 : 0) - 6}" stroke="${C.border}"/>`;
      out += `<text x="${x + 14}" y="${y + 19}" fill="${C.muted}" style="font:600 9px ${api.FONT};letter-spacing:.08em">DATA</text>`;
      out += `<text x="${x + 14}" y="${y + 35}" fill="${C.text}" style="font:600 13.5px ${api.FONT}">${esc(wrap(d.name, w - 28, 600, 13.5, 1)[0])}</text>`;
      if (kept.length) out += `<text x="${x + 14}" y="${y + 51}" fill="${C.links.store}" style="font:500 10.5px ${api.FONT}">${esc(wrap('Kept in ' + kept.map(s => s.name).join(', '), w - 28, 500, 10.5, 1)[0])}</text>`;
      fields.forEach(([f, t], k) => {
        const ry = y + TABLE_HEAD + (kept.length ? 16 : 0) + k * ROW + 14, ref = A.data.has(String(t).replace(/\[\]$/, ''));
        out += `<text x="${x + 14}" y="${ry}" fill="${C.text}" style="font:500 12px ui-monospace, Consolas, monospace">${esc(f)}</text>`;
        out += `<text x="${x + w - 14}" y="${ry}" text-anchor="end" fill="${ref ? C.accent : C.muted}" style="font:400 11.5px ui-monospace, Consolas, monospace">${esc(t)}</text>`;
      });
      out += '</g>';
    }
    return out;
  }

  function render() {
    const C = api.colors();
    if (!L) { svg.innerHTML = ''; return; }
    const body = view === 'data' ? dataSVG(C) : flowSVG(C);
    svg.innerHTML = `<defs>${markers(C)}</defs><g id="fcam">${body}</g>`;
    applyCam();
  }
  const applyCam = () => { const g = svg.querySelector('#fcam'); if (g) g.setAttribute('transform', `translate(${-cam.x * cam.z} ${-cam.y * cam.z}) scale(${cam.z})`); };

  // ------------------------------------------------------------------ camera: scroll zooms at the pointer

  const box = () => svg.getBoundingClientRect();
  // Fit everything while it stays readable; past that, show the start at a readable size and let the
  // reader scroll and drag along it. `all` always fits everything.
  function fit(all) {
    if (!L) return;
    const r = box(), b = L.bounds, m = 36, bottomBar = 70, topBar = (document.getElementById('flegend').offsetHeight || 40) + 22;
    const z = Math.min(1.1, (r.width - m * 2) / b.w, (r.height - topBar - bottomBar - m) / b.h);
    if (all || z >= 0.55) {
      cam.z = Math.max(0.1, z);
      cam.x = b.x + b.w / 2 - r.width / 2 / cam.z;
      cam.y = b.y + b.h / 2 - (topBar + (r.height - topBar - bottomBar) / 2) / cam.z;
    } else {
      cam.z = Math.max(0.55, Math.min(0.85, (r.height - topBar - bottomBar - m) / b.h));
      cam.x = b.x - m / cam.z;
      cam.y = b.y - topBar / cam.z;
    }
    applyCam();
  }
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const r = box(), px = e.clientX - r.left, py = e.clientY - r.top;
    if (e.shiftKey) { cam.x += (e.deltaY || e.deltaX) / cam.z; return applyCam(); }
    const wx = cam.x + px / cam.z, wy = cam.y + py / cam.z;
    cam.z = Math.max(0.12, Math.min(3, cam.z * Math.exp(-e.deltaY * 0.0015)));
    cam.x = wx - px / cam.z;
    cam.y = wy - py / cam.z;
    applyCam();
  }, { passive: false });
  let drag = null;
  svg.addEventListener('pointerdown', e => { svg.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y, moved: false }; });
  svg.addEventListener('pointermove', e => {
    if (!drag) {
      const n = e.target.closest('[data-node]'), id = n ? n.dataset.node : null;
      if (id !== hover && view === 'journeys') { hover = id; render(); }
      return;
    }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    cam.x = drag.cx - dx / cam.z;
    cam.y = drag.cy - dy / cam.z;
    applyCam();
  });
  svg.addEventListener('pointerup', e => {
    const d = drag;
    drag = null;
    if (!d || d.moved) return;
    const t = document.elementFromPoint(e.clientX, e.clientY) || e.target;
    const n = t.closest('[data-node]'), ed = t.closest('[data-edge]'), dt = t.closest('[data-data]');
    if (n) { picked = n.dataset.node; api.showPart(picked); }
    else if (ed) { const [f, to] = ed.dataset.edge.split('>'); api.showLinks(G.edges.filter(l => l.from === f && l.to === to)); picked = null; }
    else if (dt) { picked = dt.dataset.data; api.showData(picked); }
    else { picked = null; api.showList(); }
    render();
  });
  svg.addEventListener('pointerleave', () => { if (hover) { hover = null; render(); } });

  // ------------------------------------------------------------------ choosing what to show, and walking it

  function fillPicker() {
    const opt = (v, t) => `<option value="${esc(v)}"${G && v === pickValue() ? ' selected' : ''}>${esc(t)}</option>`;
    const types = Object.keys(S.journeyTypes);
    const byType = types.map(t => {
      const js = A.journeys.filter(j => j.type === t);
      return js.length ? `<optgroup label="Journeys: ${esc(S.journeyTypes[t])}">${js.map(j => opt('j:' + j.id, j.name)).join('')}</optgroup>` : '';
    }).join('');
    const loose = A.journeys.filter(j => !types.includes(j.type));
    const data = [...A.data.values()].filter(d => A.links.some(l => l.carries === d.id));
    sel.innerHTML = byType + (loose.length ? `<optgroup label="Journeys">${loose.map(j => opt('j:' + j.id, j.name)).join('')}</optgroup>` : '')
      + (data.length ? `<optgroup label="Data flows">${data.map(d => opt('d:' + d.id, d.name)).join('')}</optgroup>` : '')
      + (G && G.kind === 'trace' ? `<optgroup label="Trace">${opt('t:' + G.id, G.title)}</optgroup>` : '');
  }
  const pickValue = () => (G ? { journey: 'j:', data: 'd:', trace: 't:' }[G.kind] + G.id : '');

  function showStep() {
    prevB.disabled = !G || stepI < 0;
    nextB.disabled = !G || stepI >= G.ids.length - 1;
    if (!G) { stepEl.textContent = ''; return; }
    if (stepI < 0) {
      stepEl.innerHTML = `<b>${G.ids.length} parts</b>${esc(G.sub)}. Press Next to walk it step by step.`;
    } else {
      const id = G.ids[stepI], n = A.parts.get(id);
      stepEl.innerHTML = `<b>${stepI + 1} / ${G.ids.length}</b>${esc(n.name)}${G.notes[id] ? ': ' + esc(G.notes[id]) : ''}`;
      picked = id;
      api.showPart(id);
      const p = L.pos.get(id), r = box();
      const sx = (p.x - cam.x) * cam.z, sy = (p.y - cam.y) * cam.z;
      if (sx < 20 || sx + p.w * cam.z > r.width - 20 || sy < 20 || sy + p.h * cam.z > r.height - 80) {
        cam.x = p.x + p.w / 2 - r.width / 2 / cam.z;
        cam.y = p.y + p.h / 2 - (r.height - 60) / 2 / cam.z;
      }
    }
    render();
  }
  prevB.addEventListener('click', () => { if (G && stepI >= 0) { stepI--; if (stepI < 0) picked = null; showStep(); } });
  nextB.addEventListener('click', () => { if (G && stepI < G.ids.length - 1) { stepI++; showStep(); } });
  sel.addEventListener('change', () => open(sel.value));

  function open(value) {
    const [k, id, dir] = String(value).split(':');
    if (k === 'j') { const J = A.journeys.find(j => j.id === id); G = J ? journeyGraph(J) : null; }
    else if (k === 'd' && A.data.has(id)) G = dataGraph(id);
    else if (k === 't' && A.parts.has(id)) G = traceGraph(id, dir === 'back' ? 'back' : 'fwd');
    else G = null;
    view = 'journeys';
    walkBar.hidden = false;
    document.getElementById('flegend').hidden = false;
    stepI = -1;
    picked = null;
    L = G ? layoutFlow(G) : null;
    fillPicker();
    showStep();
    fit();
    render();
    api.setHash(G ? (k === 'j' ? 'journey:' + id : k === 'd' ? 'dataflow:' + id : `trace:${id}:${dir === 'back' ? 'back' : 'fwd'}`) : 'journeys');
    if (G && k === 'j') api.showJourney(id);
  }

  function openData(id) {
    view = 'data';
    walkBar.hidden = true;
    document.getElementById('flegend').hidden = true;
    G = null;
    picked = id && A.data.has(id) ? id : null;
    L = layoutData();
    render();
    fit();
    api.setHash(picked ? 'data:' + picked : 'data');
  }

  // ------------------------------------------------------------------ saving a picture

  function buildSVG() {
    if (!L) return '';
    const C = api.colors(), b = L.bounds, m = 32, keep = { ...cam }, keepHover = hover;
    hover = null;
    const body = view === 'data' ? dataSVG(C) : flowSVG(C);
    hover = keepHover;
    Object.assign(cam, keep);
    const w = b.w + m * 2, h = b.h + m * 2 + 40;
    const title = view === 'data' ? 'Data' : G ? G.title : '';
    return `<svg xmlns="${NS}" width="${w}" height="${h}" viewBox="${b.x - m} ${b.y - m - 40} ${w} ${h}"><rect x="${b.x - m}" y="${b.y - m - 40}" width="${w}" height="${h}" fill="${C.bg}"/>`
      + `<defs>${markers(C)}</defs><text x="${b.x}" y="${b.y - 22}" fill="${C.text}" style="font:650 16px ${api.FONT}">${esc(title)}</text>${body}</svg>\n`;
  }
  const pictureName = ext => `${view === 'data' ? 'data' : G ? G.kind + '-' + G.id.replace(/[:.]/g, '-') : 'journey'}${api.colors().mode === 'dark' ? '-dark' : ''}.${ext}`;

  return {
    openJourney: id => open('j:' + id),
    openDataFlow: id => open('d:' + id),
    openTrace: (id, dir) => open(`t:${id}:${dir}`),
    openFirst: () => (G && view === 'journeys' ? (render(), fit()) : open(A.journeys.length ? 'j:' + A.journeys[0].id : '')),
    openData,
    render,
    fit,
    resize: () => { if (L) fit(); },
    view: () => view,
    pick: id => { picked = id; render(); },
    svg: buildSVG,
    pictureName
  };
};
