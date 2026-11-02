/* eXtremeMan Nagyatád – finisherek
 * Statikus egyoldalas alkalmazás: adat Supabase-ből (vagy a beépített
 * data/finishers.json pillanatképből), nézetek hash alapú útválasztással:
 *   ./                          versenyzőlista (ABC, keresés, rendezés)
 *   versenyzo/<id>-<név>/       versenyző adatlap (?ev=<év>: a Körönként kártya éve)
 *   evek/  ev/<év>/             évek áttekintése, egy év eredménylistája
 *   rekordok/                   toplisták
 *   versenyek/  verseny/<kulcs>/ további eXtremeMan versenyek
 * Rendes (History API) címek; minden címhez van statikus oldal is (build_pages.py),
 * a régi hash-linkeket (#/...) az app átírja.
 */
(() => {
  'use strict';

  const CFG = window.FINISHERS_CONFIG || {};
  const $app = document.getElementById('app');
  const $tt = document.getElementById('tooltip');
  const $hero = document.getElementById('hero');

  /** Teljes szélességű fejlécfotó (főoldal, évek, rekordok, versenyek). Fotók: extrememan.hu
   *  A H1 a felirattal együtt kulcsszavas (pl. „eXtremeMan Nagyatád · teljes táv Finisherek”).
   *  A build_pages.py ugyanezt a jelölést a statikus HTML-be is beleírja; ha a fotó már ott van,
   *  csak a szöveges részt frissítjük – így betöltéskor nem ugrik el a tartalom (CLS). */
  function setHero({ img, pos = 'center 30%', eyebrow, title, lead, stats = [], compact = false }) {
    const inner = `
          <h1 class="hero-h1"><span class="hero-eyebrow">${eyebrow}</span> <span class="hero-title">${title}</span></h1>
          ${lead ? `<p class="hero-lead">${lead}</p>` : ''}
          ${stats.length ? `<div class="hero-stats">${stats.map(([v, l]) => `<div><b>${v}</b><span>${l}</span></div>`).join('')}</div>` : ''}`;
    const cur = $hero.querySelector('.hero');
    if (cur && cur.dataset.img === img) {
      cur.classList.toggle('compact', compact);
      cur.querySelector('.hero-in').innerHTML = inner;
      return;
    }
    $hero.innerHTML = `
      <section class="hero${compact ? ' compact' : ''}" data-img="${img}">
        <div class="hero-bg" style="background-image:url(${ROOT_PATH}images/${img});background-position:${pos}"></div>
        <div class="hero-in">${inner}
        </div>
        <div class="hero-credit">Fotó: <a href="https://www.extrememan.hu/" target="_blank" rel="noopener">extrememan.hu</a></div>
      </section>`;
  }
  const SVGNS = 'http://www.w3.org/2000/svg';

  // ------------------------------------------------------------------
  // Segédfüggvények
  // ------------------------------------------------------------------
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad2 = (n) => String(n).padStart(2, '0');
  const fmt = (s) => {
    if (s == null || !isFinite(s)) return '–';
    s = Math.round(s);
    return `${Math.floor(s / 3600)}:${pad2(Math.floor((s % 3600) / 60))}:${pad2(s % 60)}`;
  };
  const fmtHM = (s) => `${Math.floor(s / 3600)}:${pad2(Math.round((s % 3600) / 60) % 60)}`;
  const fmtDiff = (d) => (Math.round(d) === 0 ? '±0:00' : (d < 0 ? '−' : '+') + fmtShortDur(Math.abs(d)));
  const fmtShortDur = (s) => {
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return h ? `${h}:${pad2(m)}:${pad2(x)}` : `${m}:${pad2(x)}`;
  };
  const nf = new Intl.NumberFormat('hu-HU');
  const coll = new Intl.Collator('hu', { sensitivity: 'base' });
  const fold = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  // Az oldal gyökere (pl. /ExtremeManFinishers/) – az app.js helyéből
  const ROOT_PATH = new URL('.', document.currentScript.src).pathname;
  // ugyanaz, mint a build_pages.py slug()-ja
  const slugify = (x) => fold(String(x || '').normalize('NFKD')).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'versenyzo';
  const U = {
    home: () => ROOT_PATH,
    years: () => `${ROOT_PATH}evek/`,
    records: () => `${ROOT_PATH}rekordok/`,
    races: () => `${ROOT_PATH}versenyek/`,
    year: (y) => `${ROOT_PATH}ev/${y}/`,
    race: (k) => `${ROOT_PATH}verseny/${k}/`,
    athlete: (id, name, year) => `${ROOT_PATH}versenyzo/${id}-${slugify(name)}/${year ? `?ev=${year}` : ''}`,
  };
  const median = (arr) => {
    if (!arr.length) return null;
    const a = [...arr].sort((x, y) => x - y), m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  };
  const lowerBound = (sorted, v) => {
    let lo = 0, hi = sorted.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; }
    return lo;
  };
  const pct = (r) => (r.pos / r.y.n) * 100;
  const pctLabel = (p) => (p < 1 ? '<1%' : `${Math.round(p)}%`);
  const svgEl = (tag, attrs = {}) => {
    const e = document.createElementNS(SVGNS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ------------------------------------------------------------------
  // Adatok betöltése és feldolgozása
  // ------------------------------------------------------------------
  async function fetchData() {
    if (CFG.supabaseUrl && CFG.supabaseKey) {
      try {
        const headers = { 'Content-Type': 'application/json', apikey: CFG.supabaseKey };
        if (CFG.supabaseKey.startsWith('eyJ')) headers.Authorization = `Bearer ${CFG.supabaseKey}`;
        const res = await fetch(`${CFG.supabaseUrl.replace(/\/+$/, '')}/rest/v1/rpc/finisher_data`, {
          method: 'POST', headers, body: '{}',
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        if (!d || !Array.isArray(d.results) || !d.results.length) throw new Error('üres adat');
        return { d, source: 'supabase' };
      } catch (e) {
        console.warn('A Supabase nem elérhető, a beépített pillanatkép töltődik be.', e);
        const res = await fetch(`${ROOT_PATH}data/finishers.json`);
        return { d: await res.json(), source: 'fallback' };
      }
    }
    const res = await fetch(`${ROOT_PATH}data/finishers.json`);
    return { d: await res.json(), source: 'snapshot' };
  }

  const DISC = [
    { k: 'swim', label: 'Úszás', cls: 'sw', color: 'var(--s1)' },
    { k: 'bike', label: 'Kerékpár', cls: 'bk', color: 'var(--s2)' },
    { k: 'run', label: 'Futás', cls: 'rn', color: 'var(--s3)' },
    { k: 'tr', label: 'Depók', cls: 'tr', color: 'var(--s4)' },
  ];

  function buildModel(d) {
    const A = new Map();
    for (const [id, name, by, sex] of d.athletes) {
      A.set(id, { id, name, by, sex, res: [], key: fold(name) });
    }
    const Y = new Map();
    for (const [aid, year, pos, t, swim, t1, bike, t2, run, club] of d.results) {
      const a = A.get(aid);
      if (!a) continue;
      const tr = t1 != null || t2 != null ? (t1 || 0) + (t2 || 0) : null;
      const r = { a, year, pos, t, swim, t1, bike, t2, run, tr, club };
      a.res.push(r);
      if (!Y.has(year)) Y.set(year, { year, res: [] });
      Y.get(year).res.push(r);
    }
    for (const y of Y.values()) {
      y.res.sort((p, q) => p.t - q.t || (p.pos ?? 1e9) - (q.pos ?? 1e9));
      y.res.forEach((r, i) => { r.y = y; if (r.pos == null) r.pos = i + 1; });
      y.res.sort((p, q) => p.pos - q.pos);
      y.n = y.res.length;
      y.winner = y.res[0];
      y.median = median(y.res.map((r) => r.t));
      y.last = y.res[y.n - 1];
      y.hasSplits = y.res.some((r) => r.swim != null);
      if (y.hasSplits) {
        y.split = {};
        for (const dd of DISC) {
          const vals = y.res.map((r) => r[dd.k]).filter((v) => v != null).sort((p, q) => p - q);
          y.split[dd.k] = { sorted: vals, median: median(vals) };
        }
      }
    }
    const athletes = [];
    for (const a of A.values()) {
      if (!a.res.length) continue;
      a.res.sort((p, q) => p.year - q.year);
      a.res.forEach((r, i) => { r.nth = i + 1; });
      a.count = a.res.length;
      a.bestRes = a.res.reduce((b, r) => (r.t < b.t ? r : b));
      a.best = a.bestRes.t;
      a.first = a.res[0].year;
      a.last = a.res[a.count - 1].year;
      a.club = [...a.res].reverse().find((r) => r.club)?.club || null;
      const L = fold(a.name).replace(/[^a-z]/g, '').charAt(0).toUpperCase();
      a.letter = L || '#';
      // leghosszabb egymást követő évekből álló sorozat
      let streak = 1, best = 1, bestEnd = a.first;
      for (let i = 1; i < a.count; i++) {
        streak = a.res[i].year === a.res[i - 1].year + 1 ? streak + 1 : 1;
        if (streak > best) { best = streak; bestEnd = a.res[i].year; }
      }
      a.streak = best;
      a.streakEnd = bestEnd;
      athletes.push(a);
    }
    for (const y of Y.values()) y.rookies = y.res.filter((r) => r.a.first === y.year).length;
    const years = [...Y.values()].sort((p, q) => p.year - q.year);
    return { A, Y, athletes, years, results: d.results.length };
  }

  let M = null; // modell
  let source = '';

  // ------------------------------------------------------------------
  // Tooltip
  // ------------------------------------------------------------------
  function showTip(html, x, y) {
    $tt.innerHTML = html;
    $tt.hidden = false;
    const w = $tt.offsetWidth, h = $tt.offsetHeight;
    let left = x + 14, top = y - h - 12;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (left < 8) left = 8;
    if (top < 8) top = y + 16;
    $tt.style.left = `${left}px`;
    $tt.style.top = `${top}px`;
  }
  const hideTip = () => { $tt.hidden = true; };
  const ttRow = (label, value, color) =>
    `<div class="tt-row"><span class="tt-key">${color ? `<i class="key-line" style="background:${color}"></i>` : ''}${esc(label)}</span><b>${value}</b></div>`;

  // ------------------------------------------------------------------
  // Grafikonok (saját SVG)
  // ------------------------------------------------------------------
  function niceTimeStep(range, target = 5) {
    const steps = [60, 120, 300, 600, 900, 1200, 1800, 3600, 5400, 7200, 10800, 14400];
    return steps.find((s) => range / s <= target) || 14400;
  }
  function niceNumStep(range, target = 5) {
    const raw = range / target, p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
    return 10 * p;
  }

  /** Vonaldiagram, évek az x tengelyen.
   * opts: { series:[{name,color,points:[{x,y}],width?,endLabel?}], invert, kind:'time'|'pct',
   *         tip:(x)=>html|null, annotate:[{x,y,text}], ariaLabel, yDomain?,
   *         yFmt?, yStep?(span), minSpan?, xDomain?, xTicks?, xFmt?, bands?:[{x0,x1,label}] } */
  function lineChart(el, opts) {
    const draw = () => {
      el.innerHTML = '';
      const W = Math.max(240, el.clientWidth), H = opts.height || (W < 520 ? 240 : 300);
      const m = { t: 22, r: opts.series.some((s) => s.endLabel) ? 64 : 16, b: 28, l: 52 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const all = opts.series.flatMap((s) => s.points);
      const xs = [...new Set(all.map((p) => p.x))].sort((a, b) => a - b);
      let [x0, x1] = opts.xDomain || [xs[0], xs[xs.length - 1]];
      if (x0 === x1) { x0 -= 1; x1 += 1; }
      let y0, y1, step;
      if (opts.yDomain) {
        [y0, y1] = opts.yDomain;
        step = opts.kind === 'pct' ? 25 : niceTimeStep(y1 - y0);
      } else {
        const ys = all.map((p) => p.y);
        y0 = Math.min(...ys); y1 = Math.max(...ys);
        const span = Math.max(y1 - y0, opts.minSpan ?? (opts.kind === 'time' ? 1800 : 10));
        step = opts.yStep ? opts.yStep(span) : opts.kind === 'time' ? niceTimeStep(span) : niceNumStep(span);
        y0 = Math.floor((y0 - span * 0.06) / step) * step;
        y1 = Math.ceil((y1 + span * 0.06) / step) * step;
        if (opts.kind === 'pct') { y0 = Math.max(0, y0); y1 = Math.min(100, y1); }
      }
      const clamped = opts.yMin != null && y0 < opts.yMin;
      if (clamped) y0 = opts.yMin;
      const yTicks = clamped ? [y0] : [];
      for (let v = Math.ceil(y0 / step) * step; v <= y1 + 1e-6; v += step) {
        if (!clamped || v - y0 >= step * 0.75) yTicks.push(v);
      }
      const sx = (x) => m.l + ((x - x0) / (x1 - x0)) * iw;
      const sy = opts.invert
        ? (v) => m.t + ((v - y0) / (y1 - y0)) * ih
        : (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

      const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': opts.ariaLabel || '' });
      // háttérsávok (pl. úszás / kerékpár / futás szakaszok)
      for (const b of opts.bands || []) {
        const bx0 = Math.max(m.l, sx(b.x0)), bx1 = Math.min(W - m.r, sx(b.x1));
        svg.append(svgEl('rect', { x: bx0, y: m.t, width: Math.max(0, bx1 - bx0), height: ih, style: `fill:${b.fill || 'var(--surface-2)'}` }));
        if (b.label && bx1 - bx0 > 40) {
          const t = svgEl('text', { class: 'tick', x: (bx0 + bx1) / 2, y: m.t - 8, 'text-anchor': 'middle' });
          t.textContent = b.label;
          svg.append(t);
        }
      }
      // rácsvonalak + y címkék
      for (const v of yTicks) {
        const y = Math.round(sy(v)) + 0.5;
        svg.append(svgEl('line', { class: 'gridline', x1: m.l, x2: W - m.r, y1: y, y2: y }));
        const t = svgEl('text', { class: 'tick', x: m.l - 8, y: y + 4, 'text-anchor': 'end' });
        t.textContent = opts.yFmt ? opts.yFmt(v) : opts.kind === 'time' ? fmtHM(v) : `${Math.round(v)}%`;
        svg.append(t);
      }
      // x tengely
      const by = H - m.b + 0.5;
      svg.append(svgEl('line', { class: 'baseline', x1: m.l, x2: W - m.r, y1: by, y2: by }));
      const span = x1 - x0, maxLabels = Math.max(2, Math.floor(iw / 44));
      const xStep = [1, 2, 5, 10, 20, 25, 50, 100].find((s) => span / s <= maxLabels) || 100;
      const xt = opts.xTicks || [];
      if (!opts.xTicks) for (let x = Math.ceil(x0 / xStep) * xStep; x <= x1; x += xStep) xt.push(x);
      for (const x of xt) {
        const t = svgEl('text', { class: 'tick', x: sx(x), y: H - m.b + 17, 'text-anchor': 'middle' });
        t.textContent = opts.xFmt ? opts.xFmt(x) : x;
        svg.append(t);
      }
      // végfeliratok: ha kettő túl közel kerülne egymáshoz, egyiket sem írjuk ki
      // (ilyenkor a jelmagyarázat és a tooltip azonosít)
      const ends = opts.series.filter((s) => s.endLabel && s.points.length)
        .map((s) => sy(s.points[s.points.length - 1].y)).sort((p, q) => p - q);
      const labelsCollide = ends.some((y, i) => i > 0 && y - ends[i - 1] < 14);
      // sorozatok
      for (const s of opts.series) {
        if (s.points.length > 1) {
          const P = (p) => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`;
          let solid = '', gap = '';
          s.points.forEach((p, i) => {
            if (!i) { solid += `M${P(p)}`; return; }
            const prev = s.points[i - 1];
            if (s.gaps && p.x - prev.x > 1) { gap += `M${P(prev)}L${P(p)}`; solid += `M${P(p)}`; }
            else solid += `L${P(p)}`;
          });
          if (gap) svg.append(svgEl('path', { class: 'line gap', d: gap, style: `stroke:${s.color}` }));
          svg.append(svgEl('path', { class: 'line', d: solid, style: `stroke:${s.color}` }));
        }
        if (s.dots !== false) {
          for (const p of s.points) {
            svg.append(svgEl('circle', { cx: sx(p.x), cy: sy(p.y), r: W < 520 && s.points.length > 15 ? 3 : 4, style: `fill:${s.color};stroke:var(--surface);stroke-width:2` }));
          }
        }
        if (s.endLabel && s.points.length && !labelsCollide) {
          const p = s.points[s.points.length - 1];
          const t = svgEl('text', { class: 'dlabel', x: sx(p.x) + 8, y: sy(p.y) + 4 });
          t.textContent = s.endLabel;
          svg.append(t);
        }
      }
      // kiemelt pontok feliratai
      for (const a of opts.annotate || []) {
        const px = sx(a.x), py = sy(a.y);
        const above = py - m.t > 26;
        const anchor = px < m.l + 50 ? 'start' : px > W - m.r - 50 ? 'end' : 'middle';
        const t = svgEl('text', { class: 'dlabel', x: px, y: above ? py - 12 : py + 22, 'text-anchor': anchor });
        t.textContent = a.text;
        svg.append(t);
      }
      // hover réteg
      const cross = svgEl('line', { class: 'crosshair', y1: m.t, y2: H - m.b, visibility: 'hidden' });
      const halo = svgEl('circle', { r: 6, visibility: 'hidden', style: 'fill:none;stroke-width:2' });
      svg.append(cross, halo);
      const hit = svgEl('rect', { class: 'hit', x: m.l - 10, y: 0, width: iw + 20, height: H });
      svg.append(hit);
      const primary = opts.series[opts.primary ?? 0];
      const onMove = (ev) => {
        const rect = svg.getBoundingClientRect();
        const px = ((ev.clientX - rect.left) / rect.width) * W;
        let best = null, bd = Infinity;
        for (const x of xs) { const dd = Math.abs(sx(x) - px); if (dd < bd) { bd = dd; best = x; } }
        if (best == null) return;
        const html = opts.tip(best);
        if (!html) { hideTip(); return; }
        cross.setAttribute('x1', sx(best)); cross.setAttribute('x2', sx(best));
        cross.setAttribute('visibility', 'visible');
        const pp = primary.points.find((p) => p.x === best);
        if (pp) {
          halo.setAttribute('cx', sx(pp.x)); halo.setAttribute('cy', sy(pp.y));
          halo.setAttribute('style', `fill:none;stroke-width:2;stroke:${primary.color}`);
          halo.setAttribute('visibility', 'visible');
        } else halo.setAttribute('visibility', 'hidden');
        showTip(html, ev.clientX, ev.clientY);
      };
      const onLeave = () => { cross.setAttribute('visibility', 'hidden'); halo.setAttribute('visibility', 'hidden'); hideTip(); };
      hit.addEventListener('pointermove', onMove);
      hit.addEventListener('pointerdown', onMove);
      hit.addEventListener('pointerleave', onLeave);
      if (opts.onClick) hit.addEventListener('click', (ev) => {
        const rect = svg.getBoundingClientRect();
        const px = ((ev.clientX - rect.left) / rect.width) * W;
        let best = null, bd = Infinity;
        for (const x of xs) { const dd = Math.abs(sx(x) - px); if (dd < bd) { bd = dd; best = x; } }
        if (best != null) opts.onClick(best);
      });
      el.append(svg);
    };
    draw();
    observeResize(el, draw);
  }

  /** Oszlopdiagram. items: [{label, value, tip, onClick?}] */
  function columnChart(el, items, opts = {}) {
    const draw = () => {
      el.innerHTML = '';
      const W = Math.max(280, el.clientWidth), H = opts.height || (W < 520 ? 200 : 240);
      const m = { t: 20, r: 8, b: 28, l: 40 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const max = Math.max(...items.map((i) => i.value), 1);
      const step = niceNumStep(max, 4), top = Math.ceil(max / step) * step;
      const band = iw / items.length, bw = Math.min(24, Math.max(2, band - 2));
      const sy = (v) => m.t + ih - (v / top) * ih;
      const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': opts.ariaLabel || '' });
      for (let v = 0; v <= top; v += step) {
        const y = Math.round(sy(v)) + 0.5;
        svg.append(svgEl('line', { class: v === 0 ? 'baseline' : 'gridline', x1: m.l, x2: W - m.r, y1: y, y2: y }));
        const t = svgEl('text', { class: 'tick', x: m.l - 8, y: y + 4, 'text-anchor': 'end' });
        t.textContent = nf.format(v);
        svg.append(t);
      }
      const every = Math.max(1, Math.ceil(items.length / Math.floor(iw / 40)));
      const labelEvery = opts.labelEvery ? Math.max(every, opts.labelEvery) : every;
      const bars = [];
      items.forEach((it, i) => {
        const x = m.l + band * i + (band - bw) / 2, y = sy(it.value), h = m.t + ih - y;
        if (h > 0) {
          const r = Math.min(4, bw / 2, h);
          const d = `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${y + h}Z`;
          const cls = opts.highlight == null ? 'colbar' : i === opts.highlight ? 'colbar' : 'colbar other';
          const p = svgEl('path', { class: cls, d });
          svg.append(p);
          bars.push(p);
        } else bars.push(null);
        if (i % labelEvery === 0) {
          const t = svgEl('text', { class: 'tick', x: x + bw / 2, y: H - m.b + 17, 'text-anchor': 'middle' });
          t.textContent = it.label;
          svg.append(t);
        }
        if (it.valueLabel) {
          const t = svgEl('text', { class: 'dlabel', x: x + bw / 2, y: y - 6, 'text-anchor': 'middle' });
          t.textContent = it.valueLabel;
          svg.append(t);
        }
      });
      // hover: a teljes sáv a célterület
      items.forEach((it, i) => {
        const hit = svgEl('rect', { class: 'hit', x: m.l + band * i, y: m.t, width: band, height: ih, style: it.onClick ? 'cursor:pointer' : '' });
        hit.addEventListener('pointermove', (ev) => {
          bars.forEach((b, j) => b && b.classList.toggle('dim', j !== i));
          showTip(it.tip, ev.clientX, ev.clientY);
        });
        hit.addEventListener('pointerleave', () => { bars.forEach((b) => b && b.classList.remove('dim')); hideTip(); });
        if (it.onClick) hit.addEventListener('click', it.onClick);
        svg.append(hit);
      });
      el.append(svg);
    };
    draw();
    observeResize(el, draw);
  }

  /** Egy év célidői félórás sávokban. */
  function histBins(y) {
    const BIN = 1800;
    const lo = Math.floor(y.winner.t / BIN) * BIN, hi = Math.floor(y.last.t / BIN) * BIN;
    const bins = [];
    for (let s = lo; s <= hi; s += BIN) bins.push({ s, e: s + BIN, n: 0 });
    for (const r of y.res) bins[Math.floor((r.t - lo) / BIN)].n++;
    return bins;
  }
  const binIndex = (bins, t) => bins.findIndex((b) => t >= b.s && t < b.e);

  function sparkline(a) {
    const W = 110, H = 28, p = 4;
    if (a.count < 2) {
      return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><circle cx="${W / 2}" cy="${H / 2}" r="3" style="fill:var(--s1)"/></svg>`;
    }
    const x0 = a.first, x1 = a.last;
    const ts = a.res.map((r) => r.t), lo = Math.min(...ts), hi = Math.max(...ts), span = Math.max(hi - lo, 600);
    const sx = (x) => p + ((x - x0) / (x1 - x0)) * (W - 2 * p);
    const sy = (t) => p + ((t - lo) / span) * (H - 2 * p); // feljebb = gyorsabb
    const d = a.res.map((r, i) => `${i ? 'L' : 'M'}${sx(r.year).toFixed(1)},${sy(r.t).toFixed(1)}`).join('');
    const b = a.bestRes;
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><path d="${d}" style="fill:none;stroke:var(--ref);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round"/><circle cx="${sx(b.year).toFixed(1)}" cy="${sy(b.t).toFixed(1)}" r="3" style="fill:var(--s1)"/></svg>`;
  }

  // átméretezéskor újrarajzolás (nézetváltáskor a régi figyelők törlődnek)
  let observers = [];
  function observeResize(el, draw) {
    let w = el.clientWidth;
    const ro = new ResizeObserver(debounce(() => {
      if (Math.abs(el.clientWidth - w) > 4) { w = el.clientWidth; draw(); }
    }, 120));
    ro.observe(el);
    observers.push(ro);
  }
  function resetView() {
    observers.forEach((o) => o.disconnect());
    observers = [];
    hideTip();
  }

  // ------------------------------------------------------------------
  // Nézet: versenyzőlista
  // ------------------------------------------------------------------
  const listState = { q: '', letter: '', sort: 'name', scroll: 0 };
  const PAGE = 100;
  const SORTS = {
    name: { label: 'Név szerint (A–Z)', fn: (a, b) => coll.compare(a.name, b.name) },
    count: { label: 'Célba érések száma', fn: (a, b) => b.count - a.count || coll.compare(a.name, b.name) },
    best: { label: 'Legjobb idő', fn: (a, b) => a.best - b.best },
    last: { label: 'Legutóbbi célba érés', fn: (a, b) => b.last - a.last || coll.compare(a.name, b.name) },
  };

  function tile(label, value, sub) {
    return `<div class="tile"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
  }

  function renderList() {
    const { athletes, years } = M;
    const firstY = years[0].year, lastY = years[years.length - 1].year;
    const rec = years.reduce((b, y) => (y.winner.t < b.t ? y.winner : b), years[0].winner);
    const letters = [...new Set(athletes.map((a) => a.letter))].sort(coll.compare);
    setHero({
      img: 'hero-cel.jpg', pos: 'center 30%',
      eyebrow: 'eXtremeMan Nagyatád · teljes táv', title: 'Finisherek',
      lead: `3,8 km úszás · 180 km kerékpár · 42,2 km futás. Mindenki, aki ${firstY} óta célba ért Nagyatádon – kattints egy névre az eredményekért és a trendgrafikonokért.`,
      stats: [
        [nf.format(athletes.length), 'finisher'],
        [nf.format(M.results), 'célba érés'],
        [years.length, 'verseny'],
        [nf.format(years[years.length - 1].n), `célba érkező, ${lastY}`],
        [fmt(rec.t), `pályacsúcs · <a href="${U.athlete(rec.a.id, rec.a.name)}">${esc(rec.a.name)}</a>, ${rec.year}`],
      ],
    });
    $app.innerHTML = `
      <div class="controls">
        <label class="search">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>
          <span class="sr-only">Keresés névre</span>
          <input id="q" type="search" placeholder="Keresés névre…" autocomplete="off" value="${esc(listState.q)}">
        </label>
        <label><span class="sr-only">Rendezés</span>
          <select id="sort">${Object.entries(SORTS).map(([k, s]) => `<option value="${k}"${k === listState.sort ? ' selected' : ''}>${s.label}</option>`).join('')}</select>
        </label>
      </div>
      <div class="letters" role="group" aria-label="Kezdőbetű">
        <button type="button" data-l="" class="${listState.letter ? '' : 'active'}">Mind</button>
        ${letters.map((l) => `<button type="button" data-l="${l}" class="${l === listState.letter ? 'active' : ''}">${l}</button>`).join('')}
      </div>
      <p class="count-line" id="countLine"></p>
      <div class="list" id="list">
        <div class="list-head"><span>Versenyző</span><span class="c-spark">Idők alakulása</span><span class="r">Célba</span><span class="r">Legjobb</span></div>
        <div id="rows"></div>
      </div>
      <button class="btn show-more" id="more" type="button" hidden></button>`;

    const $q = document.getElementById('q');
    const $rows = document.getElementById('rows');
    const $count = document.getElementById('countLine');
    const $more = document.getElementById('more');
    let filtered = [], shown = 0;

    const rowHtml = (a) => `
      <a class="row" href="${U.athlete(a.id, a.name)}">
        <div><div class="name">${esc(a.name)}</div>
          <div class="meta">${a.by ? `${a.by} · ` : ''}${a.first === a.last ? a.first : `${a.first}–${a.last}`}</div></div>
        ${sparkline(a)}
        <div class="cnt num">${a.count}×</div>
        <div class="best num">${fmt(a.best)}<small>${a.bestRes.year}</small></div>
      </a>`;

    const more = () => {
      if (shown >= filtered.length) return;
      const next = filtered.slice(shown, shown + PAGE);
      $rows.insertAdjacentHTML('beforeend', next.map(rowHtml).join(''));
      shown += next.length;
      const left = filtered.length - shown;
      $more.hidden = left <= 0;
      $more.textContent = `Továbbiak betöltése (még ${nf.format(left)})`;
    };

    const apply = () => {
      const tokens = fold(listState.q.trim()).split(/\s+/).filter(Boolean);
      filtered = athletes.filter((a) =>
        (!listState.letter || a.letter === listState.letter) && tokens.every((t) => a.key.includes(t)));
      filtered.sort(SORTS[listState.sort].fn);
      $count.textContent = `${nf.format(filtered.length)} versenyző`;
      $rows.innerHTML = filtered.length ? '' : '<div class="empty">Nincs találat.</div>';
      shown = 0;
      $more.hidden = true;
      more();
      while (shown < Math.min(filtered.length, listState.restore || 0)) more();
      listState.restore = 0;
    };

    $q.addEventListener('input', debounce(() => { listState.q = $q.value; apply(); }, 120));
    document.getElementById('sort').addEventListener('change', (e) => { listState.sort = e.target.value; apply(); });
    document.querySelector('.letters').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      listState.letter = b.dataset.l;
      document.querySelectorAll('.letters button').forEach((x) => x.classList.toggle('active', x === b));
      apply();
    });
    $rows.addEventListener('click', () => {
      listState.scroll = window.scrollY;
      listState.restore = shown;
    });

    $more.addEventListener('click', more);
    apply();
  }

  // ------------------------------------------------------------------
  // Nézet: versenyző adatlap
  // ------------------------------------------------------------------
  function renderAthlete(id, focusYear = null) {
    const a = M.A.get(id);
    if (!a || !a.res.length) return renderSideAthlete(id);
    const lastR = a.res[a.count - 1];
    const bestPos = a.res.reduce((b, r) => (pct(r) < pct(b) ? r : b));
    const splitYears = a.res.filter((r) => r.swim != null);

    // első betöltéskor a statikus oldal (build_pages.py) már tartalmazza a chipeket
    const preChips = firstRoute ? (document.getElementById('otherSummary')?.innerHTML || '') : '';
    $app.innerHTML = `
      <div class="page-head">
        <div class="eyebrow"><a href="${U.home()}">← Finisherek</a></div>
        <h1>${esc(a.name)}</h1>
        <p class="lead">${[a.by ? `Született ${a.by}` : '', a.club ? esc(a.club) : '',
          `${a.count}× célba ért ${a.first === a.last ? a.first : `${a.first} és ${a.last} között`}`].filter(Boolean).join(' · ')}</p>
        <div class="chips" id="otherSummary">${preChips}</div>
      </div>
      <div class="tiles">
        ${tile('Célba érések', `${a.count}×`, a.streak > 1 ? `leghosszabb sorozat: ${a.streak} év` : '')}
        ${tile('Legjobb idő', fmt(a.best), `${a.bestRes.year} · ${a.bestRes.pos}. hely`)}
        ${tile('Legutóbbi', fmt(lastR.t), `${lastR.year}${a.count > 1 ? (lastR === a.bestRes ? ' · egyéni csúcs' : ` · ${fmtDiff(lastR.t - a.best)} a legjobbhoz`) : ''}`)}
        ${tile('Legjobb helyezés', `${bestPos.pos}.`, `${bestPos.year} · ${bestPos.y.n} célba érkezőből (${pctLabel(pct(bestPos))})`)}
      </div>
      ${a.count > 1 ? `<section class="card">
        <div class="card-head">
          <div><h2>Célidők évenként</h2><p id="trendNote"></p></div>
          <div class="seg" id="trendSeg" role="tablist">
            <button type="button" data-m="time" class="active">Célidő</button>
            <button type="button" data-m="pct">Helyezés a mezőnyben</button>
          </div>
        </div>
        <div class="legend" id="trendLegend"></div>
        <div class="chart" id="trend"></div>
      </section>` : `<section class="card">
        <div class="card-head"><div><h2>Helye a ${lastR.year}. évi mezőnyben</h2>
          <p>A célba érkezők idő szerinti eloszlása félórás sávokban. Ha több évben is célba ér, itt a trendgrafikonja jelenik meg.</p></div></div>
        ${legendHtml([{ name: `${a.name} sávja`, color: 'var(--s1)', dot: true }, { name: 'többi célba érkező', color: 'var(--ref)', dot: true }])}
        <div class="chart" id="trend"></div>
        <p class="chart-note">${lastR.pos}. hely ${lastR.y.n} célba érkezőből – a mezőny ${Math.round(100 - pct(lastR))}%-ánál gyorsabb.</p>
      </section>`}
      ${splitYears.length > 1 ? `<section class="card">
        <div class="card-head"><div><h2>Úszás, kerékpár, futás trendje</h2><p id="splitNote"></p></div>
          <div class="seg" id="splitSeg" role="tablist">
            <button type="button" data-m="time" class="active">Idő</button>
            <button type="button" data-m="pct">Helyezés a mezőnyben</button>
          </div>
        </div>
        <div class="legend" id="splitLegend"></div>
        <div id="splitTrend"></div>
      </section>` : ''}
      ${splitYears.length ? `<section class="card" id="lapCard">
        <div class="card-head"><div><h2>Körönként</h2><p>Köridők, tempó és helyezés a köztes mérőpontokon (EvoChip).</p></div>
          <div class="seg" id="lapSeg" role="tablist">${splitYears.slice().reverse().map((r, i) =>
            `<button type="button" data-y="${r.year}" class="${i ? '' : 'active'}">${r.year}</button>`).join('')}</div>
        </div>
        <div id="lapBody"><div class="loading" style="padding:40px 0"><span class="spinner"></span> Köridők betöltése…</div></div>
      </section>` : ''}
      ${splitYears.length ? `<section class="card"><div class="card-head"><div><h2>Részidők</h2><p>Úszás 3,8 km · kerékpár 180 km · futás 42,2 km.</p></div></div>
        <p class="chart-note split-explain"><span class="split-best-sample">1:19:33</span> piros = a versenyző saját legjobbja az adott szakaszon (a részidős évek közül).
          Az idő alatti kis szám a szakaszhelyezés a mezőnyben, pl. <span class="num">57. / 279</span>: 279 célba érkezőből az 57. leggyorsabb.</p>
        ${splitTable(splitYears)}</section>` : ''}
      <section class="card">
        <div class="card-head"><h2>Eredmények</h2></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Év</th><th class="r">Célidő</th><th class="r">Helyezés</th><th class="r">Mezőny</th><th class="r">A legjobbhoz</th><th class="r">A mediánhoz</th></tr></thead>
          <tbody>${a.res.slice().reverse().map((r) => `
            <tr class="${r === a.bestRes && a.count > 1 ? 'pb' : ''}">
              <td><a href="${U.year(r.year)}">${r.year}</a>${r === a.bestRes && a.count > 1 ? '<span class="pb-tag">legjobb</span>' : ''}</td>
              <td class="r">${fmt(r.t)}</td>
              <td class="r">${r.pos}. <span class="muted">/ ${r.y.n}</span></td>
              <td class="r">${pctLabel(pct(r))}</td>
              <td class="r">${r === a.bestRes ? '–' : fmtDiff(r.t - a.best)}</td>
              <td class="r ${r.t < r.y.median ? 'delta-good' : ''}">${fmtDiff(r.t - r.y.median)}</td>
            </tr>`).join('')}</tbody>
        </table></div>
      </section>
      <section class="card" id="otherCard" data-aid="${a.id}" hidden>
        <div class="card-head"><div><h2>További eXtremeMan versenyek</h2>
          <p>Nagyatád többi táva, Kaposvár, Gyékényes, Balatonszemes, Tab, Velence, Székesfehérvár … 2015-től (EvoChip).</p></div></div>
        <div id="otherBody"></div>
      </section>`;

    fillOther(a);
    const drawTrend = (mode) => {
      const el = document.getElementById('trend');
      observers.forEach((o) => o.unobserve(el));
      const pts = a.res.map((r) => ({ x: r.year, y: mode === 'time' ? r.t : pct(r), r }));
      const series = [];
      if (mode === 'time') {
        const x0 = a.first === a.last ? a.first - 1 : a.first, x1 = a.first === a.last ? a.last + 1 : a.last;
        const ref = M.years.filter((y) => y.year >= x0 && y.year <= x1).map((y) => ({ x: y.year, y: y.median }));
        series.push({ name: 'Mezőny mediánja', color: 'var(--ref)', points: ref, dots: false, endLabel: 'medián' });
      }
      series.push({ name: a.name, color: 'var(--s1)', points: pts, gaps: true });
      const hasGaps = a.res.some((r, i) => i && r.year - a.res[i - 1].year > 1);
      const gapKey = hasGaps ? [{ name: 'kimaradt év(ek)', color: 'var(--s1)', dash: true }] : [];
      document.getElementById('trendNote').textContent = mode === 'time'
        ? 'Feljebb = gyorsabb. A szürke vonal az adott év összes célba érkezőjének medián ideje.'
        : 'Hányadik százalékban ért célba a mezőnyön belül (feljebb = előrébb). Kiszűri az időjárás és a pálya évenkénti hatását.';
      document.getElementById('trendLegend').innerHTML = mode === 'time'
        ? legendInner([{ name: a.name, color: 'var(--s1)' }, ...gapKey, { name: 'Mezőny mediánja', color: 'var(--ref)' }])
        : legendInner(gapKey);
      const b = a.bestRes;
      const bestP = a.res.reduce((x, r) => (pct(r) < pct(x) ? r : x));
      lineChart(el, {
        series, primary: series.length - 1, invert: true, kind: mode,
        yDomain: mode === 'pct' ? [0, 100] : null,
        annotate: a.count > 1 ? [mode === 'time'
          ? { x: b.year, y: b.t, text: `legjobb ${fmt(b.t)}` }
          : { x: bestP.year, y: pct(bestP), text: `legjobb ${pctLabel(pct(bestP))}` }] : [],
        ariaLabel: `${a.name} célidői évenként`,
        tip: (x) => {
          const r = a.res.find((q) => q.year === x);
          const y = M.Y.get(x);
          if (!r) return y ? `<div class="tt-title">${x}</div>${ttRow('Nem indult / nem ért célba', '')}${ttRow('Mezőny mediánja', fmt(y.median), 'var(--ref)')}` : null;
          return `<div class="tt-title">${x}</div>
            ${ttRow('Célidő', fmt(r.t), 'var(--s1)')}
            ${ttRow('Helyezés', `${r.pos}. / ${r.y.n}`)}
            ${ttRow('Mezőny', pctLabel(pct(r)))}
            ${ttRow('Mezőny mediánja', fmt(r.y.median), 'var(--ref)')}
            ${a.count > 1 ? ttRow('A legjobbhoz', r === a.bestRes ? 'legjobb' : fmtDiff(r.t - a.best)) : ''}`;
        },
        onClick: (x) => { if (a.res.some((q) => q.year === x)) go(U.year(x)); },
      });
    };
    if (splitYears.length) {
      const drawLaps = (year) => renderLaps(document.getElementById('lapBody'), a, year);
      const startYear = splitYears.some((r) => r.year === focusYear) ? focusYear : splitYears[splitYears.length - 1].year;
      document.querySelectorAll('#lapSeg button').forEach((x) => x.classList.toggle('active', Number(x.dataset.y) === startYear));
      drawLaps(startYear);
      if (focusYear) setTimeout(() => document.getElementById('lapCard')?.scrollIntoView({ block: 'start' }), 60);
      document.getElementById('lapSeg').addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        document.querySelectorAll('#lapSeg button').forEach((x) => x.classList.toggle('active', x === btn));
        drawLaps(Number(btn.dataset.y));
      });
    }
    if (a.count === 1) {
      const bins = histBins(lastR.y), hi = binIndex(bins, lastR.t);
      columnChart(document.getElementById('trend'), bins.map((b, i) => ({
        label: fmtHM(b.s),
        value: b.n,
        tip: `<div class="tt-title">${fmtHM(b.s)} – ${fmtHM(b.e)}</div>${ttRow('Célba érkezők', b.n)}${i === hi ? ttRow(a.name, fmt(lastR.t), 'var(--s1)') : ''}`,
      })), { highlight: hi, labelEvery: 2, ariaLabel: `${lastR.year}. évi célidők eloszlása, kiemelve ${a.name} sávja` });
      return;
    }
    if (splitYears.length > 1) {
      const S3 = DISC.slice(0, 3);
      const discRank = (r, k) => lowerBound(r.y.split[k].sorted, r[k]) + 1;
      // a vízszintes tengely a teljes nagyatádi pályafutás; ahol nincs részidő, halvány sáv jelzi
      const splitFrom = M.years.find((y) => y.hasSplits).year;
      const xDom = [Math.min(a.first, splitYears[0].year), Math.max(a.last, splitYears[splitYears.length - 1].year)];
      const noData = a.first < splitFrom
        ? [{ x0: xDom[0] - 0.5, x1: splitFrom - 0.5, label: `nincs részidő-adat (${splitFrom} előtt)`, fill: 'var(--surface-2)' }] : [];
      const raceGaps = splitYears.some((r, i) => i && r.year - splitYears[i - 1].year > 1)
        || a.res.some((r) => r.year >= splitFrom && r.swim == null);
      const discPct = (r, k) => (discRank(r, k) / r.y.split[k].sorted.length) * 100;
      const drawSplits = (mode) => {
        const host = document.getElementById('splitTrend');
        observers.forEach((o) => host.querySelectorAll('.chart').forEach((c) => o.unobserve(c)));
        hideTip();
        if (mode === 'time') {
          document.getElementById('splitNote').textContent =
            'Szakaszidők évenként (feljebb = gyorsabb); a szürke vonal az adott év mezőnyének medián szakaszideje.';
          document.getElementById('splitLegend').innerHTML = legendInner([{ name: 'Mezőny mediánja', color: 'var(--ref)' },
            ...(raceGaps ? [{ name: 'kimaradt év(ek)', color: 'var(--ink-2)', dash: true }] : []),
            ...(noData.length ? [{ name: `${splitFrom} előtt nincs részidő-adat`, color: 'var(--surface-2)', dot: true }] : [])]);
          host.innerHTML = `<div class="split-multiples">${S3.map((d) =>
            `<div><h3><i class="key-dot" style="background:${d.color}"></i>${d.label}</h3><div class="chart" id="st-${d.k}"></div></div>`).join('')}</div>`;
          for (const d of S3) {
            const rs = splitYears.filter((r) => r[d.k] != null);
            const best = rs.reduce((b, r) => (r[d.k] < b[d.k] ? r : b), rs[0]);
            lineChart(document.getElementById(`st-${d.k}`), {
              kind: 'time', invert: true, height: 210, xDomain: xDom, bands: noData,
              series: [
                { name: 'Mezőny mediánja', color: 'var(--ref)', dots: false, points: rs.map((r) => ({ x: r.year, y: r.y.split[d.k].median })) },
                { name: d.label, color: d.color, points: rs.map((r) => ({ x: r.year, y: r[d.k] })), gaps: true },
              ],
              primary: 1,
              ariaLabel: `${a.name}: ${d.label.toLowerCase()} ideje évenként`,
              tip: (x) => {
                const r = rs.find((q) => q.year === x);
                if (!r) return null;
                const sp = r.y.split[d.k];
                return `<div class="tt-title">${d.label} · ${x}</div>
                  ${ttRow('Idő', fmt(r[d.k]), d.color)}
                  ${ttRow('Helyezés', `${discRank(r, d.k)}. / ${sp.sorted.length}`)}
                  ${ttRow('Mezőny mediánja', fmt(sp.median), 'var(--ref)')}
                  ${r === best ? '' : ttRow('A legjobbhoz', fmtDiff(r[d.k] - best[d.k]))}`;
              },
              onClick: (x) => { go(U.year(x)); },
            });
          }
        } else {
          document.getElementById('splitNote').textContent =
            'Hányadik százalékban végzett az egyes szakaszokon az adott év mezőnyében (feljebb = előrébb).';
          document.getElementById('splitLegend').innerHTML = legendInner([...S3.map((d) => ({ name: d.label, color: d.color })),
            ...(raceGaps ? [{ name: 'kimaradt év(ek)', color: 'var(--ink-2)', dash: true }] : []),
            ...(noData.length ? [{ name: `${splitFrom} előtt nincs részidő-adat`, color: 'var(--surface-2)', dot: true }] : [])]);
          host.innerHTML = '<div class="chart" id="st-pct"></div>';
          lineChart(document.getElementById('st-pct'), {
            kind: 'pct', invert: true, yDomain: [0, 100], xDomain: xDom, bands: noData,
            series: S3.map((d) => ({
              name: d.label, color: d.color, endLabel: d.label.toLowerCase(), gaps: true,
              points: splitYears.filter((r) => r[d.k] != null).map((r) => ({ x: r.year, y: discPct(r, d.k) })),
            })),
            ariaLabel: `${a.name}: helyezés szakaszonként a mezőnyben, évenként`,
            tip: (x) => {
              const r = splitYears.find((q) => q.year === x);
              if (!r) return null;
              return `<div class="tt-title">${x}</div>` + S3.map((d) =>
                ttRow(d.label, `${fmt(r[d.k])} · ${discRank(r, d.k)}. / ${r.y.split[d.k].sorted.length}`, d.color)).join('');
            },
            onClick: (x) => { go(U.year(x)); },
          });
        }
      };
      drawSplits('time');
      document.getElementById('splitSeg').addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        document.querySelectorAll('#splitSeg button').forEach((x) => x.classList.toggle('active', x === btn));
        drawSplits(btn.dataset.m);
      });
    }
    drawTrend('time');
    document.getElementById('trendSeg').addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      document.querySelectorAll('#trendSeg button').forEach((x) => x.classList.toggle('active', x === btn));
      drawTrend(btn.dataset.m);
    });
  }

  function legendInner(items) {
    return items.map((i) => (i.dash
      ? `<span><i class="key-dash" style="color:${i.color}"></i>${esc(i.name)}</span>`
      : `<span><i class="${i.dot ? 'key-dot' : 'key-line'}" style="background:${i.color}"></i>${esc(i.name)}</span>`)).join('');
  }
  const legendHtml = (items) => `<div class="legend">${legendInner(items)}</div>`;

  // ------------------------------------------------------------------
  // Körönkénti adatok (data/splits/<év>.json, igény szerint betöltve)
  // ------------------------------------------------------------------
  const lapCache = new Map();
  async function fetchLaps(year) {
    if (source === 'supabase') {
      try {
        const headers = { 'Content-Type': 'application/json', apikey: CFG.supabaseKey };
        if (CFG.supabaseKey.startsWith('eyJ')) headers.Authorization = `Bearer ${CFG.supabaseKey}`;
        const res = await fetch(`${CFG.supabaseUrl.replace(/\/+$/, '')}/rest/v1/rpc/lap_data`, {
          method: 'POST', headers, body: JSON.stringify({ p_year: year }),
        });
        if (res.ok) {
          const d = await res.json();
          if (d && d.points && d.points.length) return d;
        }
      } catch (e) { /* tartalék fájl */ }
    }
    const r = await fetch(`${ROOT_PATH}data/splits/${year}.json`);
    return r.ok ? r.json() : null;
  }
  /** Átalakítás: [[összidő, helyezés], ...] -> [[összidő, köridő, helyezés], ...] */
  function expandLaps(d) {
    if (!d) return null;
    for (const k in d.athletes) {
      d.athletes[k] = d.athletes[k].map((p, i, arr) => {
        const prev = i ? arr[i - 1][0] : 0;
        const lap = p[0] != null && (i === 0 || prev != null) ? p[0] - prev : null;
        return [p[0], lap, p[1]];
      });
    }
    return d;
  }
  function loadLaps(year) {
    if (!lapCache.has(year)) lapCache.set(year, fetchLaps(year).then(expandLaps).catch(() => null));
    return lapCache.get(year);
  }
  /** További verseny köridői (race_lap_data / data/splits_other/<kulcs>.json). */
  function loadRaceLaps(key) {
    const ck = `race:${key}`;
    if (!lapCache.has(ck)) {
      lapCache.set(ck, (async () => {
        if (source === 'supabase') {
          try {
            const res = await fetch(rpcUrl('race_lap_data'), { method: 'POST', headers: rpcHeaders(), body: JSON.stringify({ p_key: key }) });
            if (res.ok) {
              const d = await res.json();
              if (d && d.points && d.points.length) return expandLaps(d);
            }
          } catch (e) { /* tartalék fájl */ }
        }
        const r = await fetch(`${ROOT_PATH}data/splits_other/${key}.json`);
        return r.ok ? expandLaps(await r.json()) : null;
      })().catch(() => null));
    }
    return lapCache.get(ck);
  }
  const fmtPace = (s) => `${Math.floor(s / 60)}:${pad2(Math.round(s % 60))}`;
  const paceStep = (span) => [5, 10, 15, 20, 30, 60, 120, 300].find((st) => span / st <= 4) || 300;

  /** Körönkénti nézet. opts: { load: () => Promise<lap adat>, raceKey, people: Map } –
   *  alapból a nagyatádi teljes táv adott évi köztes ideje. */
  async function renderLaps(host, a, year, opts = {}) {
    const token = (host.dataset.token = String(Math.random()));
    const uid = `L${token.slice(2, 9)}`;
    hideTip();
    const d = await (opts.load ? opts.load() : loadLaps(year));
    if (host.dataset.token !== token || !host.isConnected) return; // időközben máshová kattintottak
    const mine = d && d.athletes[String(a.id)];
    if (!mine) {
      host.innerHTML = `<p class="muted">${opts.raceKey ? 'Ehhez a versenyhez' : 'Erre az évre'} nincsenek köztes mérőpont adatok.</p>`;
      return;
    }
    const P = d.points;
    const others = Object.values(d.athletes);
    const withMedian = others.length >= 20;
    // Szakaszok: a túl rövid mérőszakaszokat (fordító, gyógyfürdő, 1,5 km-es
    // kerékpáros pontok) összevonjuk a következővel, hogy a tempó ne ugráljon.
    const MIN_KM = { swim: 1, kayak: 1, bike: 8, run: 4 };
    const groups = (disc) => {
      const out = [];
      let acc = null;
      P.forEach((p, i) => {
        if (p.disc !== disc || !p.km) return;
        if (!acc) acc = { start: i, km: 0 };
        acc.km += p.km;
        acc.end = i;
        if (acc.km >= MIN_KM[disc] - 1e-6) { out.push(acc); acc = null; }
      });
      if (acc) {
        if (out.length) { const l = out[out.length - 1]; l.km += acc.km; l.end = acc.end; } else out.push(acc);
      }
      let km = 0;
      for (const g of out) { km += g.km; g.x = Math.round(km * 100) / 100; g.label = P[g.end].label; }
      return out;
    };
    const segTime = (pts, g) => {
      const endT = pts[g.end] && pts[g.end][0];
      const prevT = g.start === 0 ? 0 : pts[g.start - 1] && pts[g.start - 1][0];
      return endT != null && prevT != null && endT > prevT ? endT - prevT : null;
    };
    const metric = {
      swim: (t, km) => t / (km * 10),          // mp / 100 m
      bike: (t, km) => km / (t / 3600),        // km/h
      run: (t, km) => t / km,                  // mp / km
      kayak: (t, km) => t / km,                // mp / km
    };
    const personOfId = (id) => M.A.get(id) || (opts.people && opts.people.get(id)) || null;
    const sexWord = a.sex === 'F' ? 'a célba érkező nők között' : a.sex === 'M' ? 'a célba érkező férfiak között' : 'a célba érkezők között';

    // Helyezés és előzések ugyanabból az adatból: az azonos nemű célba érkezők köztes
    // idejéből (az EvoChip helyezése néha korosztályos, vagy a feladókat is számolja).
    // Ha valakinek hiányzik egy mérőpontja (kihagyta a szőnyeget), a két szomszédos
    // mért ideje közé becsüljük, a mezőny medián menetidejének arányában.
    const medT = P.map((_, i) => median(others.map((o) => o[i] && o[i][0]).filter((v) => v != null)));
    const filled = (o) => {
      const t = P.map((_, i) => (o[i] && o[i][0] != null ? o[i][0] : null));
      for (let i = 0; i < t.length; i++) {
        if (t[i] != null) continue;
        const j = i - 1;
        let k = i + 1;
        while (k < t.length && t[k] == null) k++;
        if (k >= t.length || (j >= 0 && t[j] == null)) continue;
        const t0 = j >= 0 ? t[j] : 0, m0 = j >= 0 ? medT[j] : 0;
        if (medT[i] == null || medT[k] == null || m0 == null || medT[k] <= m0) continue;
        t[i] = t0 + (t[k] - t0) * (medT[i] - m0) / (medT[k] - m0);
      }
      return t;
    };
    const rivals = Object.entries(d.athletes)
      .filter(([aid]) => Number(aid) !== a.id && (!a.sex || (personOfId(Number(aid)) || {}).sex === a.sex))
      .map(([aid, o]) => [Number(aid), filled(o)]);
    const myT = (i) => (mine[i] && mine[i][0] != null ? mine[i][0] : null);
    const rankAt = (i) => (myT(i) == null ? null : 1 + rivals.filter(([, t]) => t[i] != null && t[i] < myT(i)).length);

    // a versenyen előforduló szakaszok, az első előfordulás sorrendjében (duatlonnál
    // futás – kerékpár – futás, quadrathlonnál kajak is); a táv a mérőpontokból jön
    const SPEC = {
      swim: { title: 'Úszás', unit: 'perc/100 m', color: 'var(--s1)', invert: true, fmt: fmtPace, step: paceStep, minSpan: 20 },
      kayak: { title: 'Kajak', unit: 'perc/km', color: 'var(--s4)', invert: true, fmt: fmtPace, step: paceStep, minSpan: 30 },
      bike: { title: 'Kerékpár', unit: 'km/h', color: 'var(--s2)', invert: false, fmt: (v) => v.toFixed(1).replace('.', ','), minSpan: 4 },
      run: { title: 'Futás', unit: 'perc/km', color: 'var(--s3)', invert: true, fmt: fmtPace, step: paceStep, minSpan: 30 },
    };
    const specs = [...new Set(P.map((q) => q.disc).filter((x) => SPEC[x]))]
      .map((disc) => ({ disc, ...SPEC[disc], max: Math.round(P.filter((q) => q.disc === disc).reduce((t, q) => t + (q.km || 0), 0) * 10) / 10 }))
      .filter((sp) => sp.max > 0 && groups(sp.disc).length >= 2);  // egyetlen mérőpontból nincs mit rajzolni
    host.innerHTML = `
      ${legendHtml([{ name: a.name, color: 'var(--ink-2)' }, ...(withMedian ? [{ name: 'Mezőny mediánja', color: 'var(--ref)' }] : [])])}
      <div class="split-multiples">${specs.map((sp) => `<div><h3><i class="key-dot" style="background:${sp.color}"></i>${sp.title}
        <span class="muted" style="font-weight:400">· ${sp.unit}</span></h3><div class="chart" id="${uid}-${sp.disc}"></div></div>`).join('')}</div>
      <p class="chart-note">Vízszintesen a megtett táv (km); minden pont egy mérőszakasz átlaga.${withMedian ? '' : ' Ehhez az évhez nincs elég mezőny-adat a medián vonalhoz.'}</p>
      <h3 style="font-size:15px;margin:22px 0 2px">A verseny lefolyása</h3>
      <p class="chart-note" style="margin:0 0 6px">Helyezés ${sexWord} az egyes mérőpontokon, az eltelt idő függvényében (feljebb = előrébb).</p>
      <div class="chart" id="${uid}-race"></div>
      <div class="pass-panel" id="${uid}-pass"></div>`;

    for (const sp of specs) {
      const gs = groups(sp.disc);
      // a versenyző pontjai: ha egy köztes idő hiányzik (vagy hibás volt), a két
      // érvényes pont közötti szakaszt egyben, átlagtempóval mutatjuk
      const pts = [];
      {
        const s0 = P.findIndex((q) => q.disc === sp.disc);
        let prevT = s0 > 0 ? (mine[s0 - 1] && mine[s0 - 1][0]) : 0, acc = 0, first = null;
        for (const g of gs) {
          acc += g.km;
          if (first == null) first = g.start;
          const t1 = mine[g.end] && mine[g.end][0];
          if (t1 == null) continue;
          if (prevT != null && t1 > prevT) {
            const span = { ...g, km: acc, start: first, label: acc > g.km + 0.01 ? `${P[first].label} – ${g.label}` : g.label };
            pts.push({ x: g.x, y: metric[sp.disc](t1 - prevT, acc), g: span, t: t1 - prevT });
          }
          prevT = t1; acc = 0; first = null;
        }
      }
      const ref = withMedian ? gs.map((g) => {
        const v = median(others.map((o) => segTime(o, g)).filter(Boolean).map((t) => metric[sp.disc](t, g.km)));
        return v != null ? { x: g.x, y: v } : null;
      }).filter(Boolean) : [];
      lineChart(host.querySelector(`#${uid}-${sp.disc}`), {
        kind: 'num', invert: sp.invert, height: 210, yFmt: sp.fmt, yStep: sp.step, minSpan: sp.minSpan,
        xDomain: [0, sp.max], xFmt: (x) => `${x} km`,
        series: [
          ...(ref.length ? [{ name: 'Mezőny mediánja', color: 'var(--ref)', dots: false, points: ref }] : []),
          { name: sp.title, color: sp.color, points: pts },
        ],
        primary: ref.length ? 1 : 0,
        ariaLabel: `${a.name} ${year}: ${sp.title.toLowerCase()}, ${sp.unit} mérőszakaszonként`,
        tip: (x) => {
          const p = pts.find((q) => q.x === x);
          if (!p) return null;
          const r = ref.find((q) => q.x === x);
          const unit = sp.disc === 'bike' ? ' km/h' : sp.disc === 'swim' ? ' /100 m' : ' /km';  // futás, kajak: /km
          const rank = rankAt(p.g.end);
          return `<div class="tt-title">${esc(p.g.label)} <span class="muted">(${p.g.km.toFixed(2).replace('.', ',')} km)</span></div>
            ${ttRow('Szakaszidő', fmt(p.t), sp.color)}
            ${ttRow(sp.disc === 'bike' ? 'Sebesség' : 'Tempó', sp.fmt(p.y) + unit)}
            ${r ? ttRow('Mezőny mediánja', sp.fmt(r.y) + unit, 'var(--ref)') : ''}
            ${ttRow('Helyezés itt', rank ? `${rank}.` : '–')}`;
        },
      });
    }

    // a verseny lefolyása: helyezés az eltelt idő függvényében
    const race = P.map((p, i) => (myT(i) ? { x: myT(i) / 3600, y: rankAt(i), i } : null)).filter(Boolean);
    const end = race.length ? race[race.length - 1].x : 1;
    // háttérsávok: az egymást követő azonos szakaszú mérőpontok blokkjai
    const timeAt = (i) => (i < 0 ? 0 : mine[i] && mine[i][0] != null ? mine[i][0] / 3600 : null);
    const bands = [];
    P.forEach((q, i) => {
      if (!SPEC[q.disc]) return;
      const last = bands[bands.length - 1];
      if (last && last.disc === q.disc && last.end === i - 1) { last.end = i; return; }
      bands.push({ disc: q.disc, start: i, end: i });
    });
    for (const b of bands) {
      let s0 = b.start - 1;
      while (s0 >= 0 && timeAt(s0) == null) s0--;
      let e0 = b.end;
      while (e0 > b.start && timeAt(e0) == null) e0--;
      Object.assign(b, { x0: timeAt(s0) ?? 0, x1: timeAt(e0), label: SPEC[b.disc].title,
        fill: `color-mix(in srgb, ${SPEC[b.disc].color} 9%, transparent)` });
    }
    bands.splice(0, bands.length, ...bands.filter((b) => b.x1 != null && b.x1 > b.x0));
    const ranks = race.map((p) => p.y);
    // Előzések két egymást követő mérőpont között: az azonos nemű célba érkezők
    // közül ki volt előtted az előző ponton és mögötted ezen (megelőzted), ill. fordítva.
    // (Ugyanazokból az időkből, mint a helyezés, így a változás = megelőzted − megelőzött.)
    const passes = race.map((p, k) => {
      if (!k) return null;
      const ip = race[k - 1].i, i = p.i;
      const me0 = myT(ip), me1 = myT(i);
      const up = [], down = [];
      for (const [aid, t] of rivals) {
        const t0 = t[ip], t1 = t[i];
        const ahead0 = t0 != null && t0 < me0, ahead1 = t1 != null && t1 < me1;
        if (ahead0 && !ahead1) up.push({ aid, t: t1 ?? Infinity });
        else if (!ahead0 && ahead1) down.push({ aid, t: t1 });
      }
      up.sort((x, y) => x.t - y.t); down.sort((x, y) => x.t - y.t);
      return { from: P[ip].label, to: P[i].label, up, down };
    });
    const panel = host.querySelector(`#${uid}-pass`);
    const nameLink = (x) => {
      const o = personOfId(x.aid);
      return o ? `<a href="${U.athlete(o.id, o.name, opts.raceKey ? null : year)}">${esc(o.name)}</a>` : '';
    };
    const showPasses = (k) => {
      const ps = passes[k];
      if (!ps) { panel.innerHTML = '<p class="chart-note">Kattints a grafikon egy pontjára: megmutatom, kiket előztél meg az előző mérőpont óta, és kik előztek meg.</p>'; return; }
      panel.innerHTML = `<div class="pass-head"><b>${esc(ps.from)} → ${esc(ps.to)}</b>
          <span class="muted">${fmt(mine[race[k - 1].i][0])} → ${fmt(mine[race[k].i][0])} · helyezés ${race[k - 1].y}. → ${race[k].y}.</span></div>
        <p><span class="pass-up">▲ Megelőzted (${ps.up.length})</span>${ps.up.length ? ps.up.map(nameLink).join(', ') : '<span class="muted">senkit</span>'}</p>
        <p><span class="pass-down">▼ Megelőzött (${ps.down.length})</span>${ps.down.length ? ps.down.map(nameLink).join(', ') : '<span class="muted">senki</span>'}</p>
        <p class="chart-note">Az azonos nemű célba érkezők köztes ideje alapján (ha valakinek egy mérőpontja hiányzik, a szomszédos pontjai közé becsülve); a nevekre kattintva ${opts.raceKey ? 'az adatlapjuk' : `az ő ugyanezen évi (${year}) versenyük`} nyílik meg. Másik szakaszhoz kattints egy másik pontra.</p>`;
    };
    // kezdetben a legtöbb előzéssel járó szakasz látszik
    let startK = 0;
    passes.forEach((ps, k) => { if (ps && ps.up.length + ps.down.length > ((passes[startK] || { up: [], down: [] }).up.length + (passes[startK] || { up: [], down: [] }).down.length)) startK = k; });
    showPasses(startK);
    const hrs = [];
    for (let h = 0; h <= Math.ceil(end); h += end > 12 ? 3 : 2) hrs.push(h);
    lineChart(host.querySelector(`#${uid}-race`), {
      kind: 'num', invert: true, height: 260, yFmt: (v) => `${Math.round(v)}.`, minSpan: 10, yMin: 1,
      xDomain: [0, Math.max(end, 1)], xTicks: hrs, xFmt: (h) => `${h} ó`, bands,
      series: [{ name: a.name, color: 'var(--ink-2)', points: race }],
      annotate: race.length > 1 ? [
        { x: race[0].x, y: race[0].y, text: `${race[0].y}.` },
        { x: race[race.length - 1].x, y: race[race.length - 1].y, text: `cél: ${race[race.length - 1].y}.` },
      ] : [],
      ariaLabel: `${a.name} ${year}: helyezés a verseny során, ${ranks[0]}. helyről ${ranks[ranks.length - 1]}. helyre`,
      tip: (x) => {
        const k = race.findIndex((q) => q.x === x);
        if (k < 0) return null;
        const p = race[k], prev = race[k - 1];
        const diff = prev ? prev.y - p.y : 0;
        const ps = passes[k];
        return `<div class="tt-title">${esc(P[p.i].label)}</div>
          ${ttRow('Eltelt idő', fmt(mine[p.i][0]))}
          ${ttRow('Helyezés', `${p.y}.`)}
          ${prev ? ttRow('Változás', diff > 0 ? `+${diff} hely` : diff < 0 ? `−${-diff} hely` : '±0') : ''}
          ${ps ? ttRow('Megelőzted / megelőzött', `${ps.up.length} / ${ps.down.length}`) : ''}
          ${ps ? '<div class="tt-row"><span class="muted">kattints a nevekért</span></div>' : ''}`;
      },
      onClick: (x) => { const k = race.findIndex((q) => q.x === x); if (k >= 0) showPasses(k); },
    });
  }

  /** Részidők táblázat: soronként egy év, oszloponként egy szakasz. */
  function splitTable(rows) {
    const multi = rows.length > 1;
    const best = {};
    for (const d of DISC) {
      const vals = rows.map((r) => r[d.k]).filter((v) => v != null);
      best[d.k] = vals.length ? Math.min(...vals) : null;
    }
    const bestT = Math.min(...rows.map((r) => r.t));
    const bar = (r) => {
      const total = DISC.reduce((s, d) => s + (r[d.k] || 0), 0) || r.t;
      return `<div class="minibar" role="img" aria-label="${DISC.filter((d) => r[d.k]).map((d) => `${d.label} ${Math.round((r[d.k] / total) * 100)}%`).join(', ')}">${
        DISC.map((d) => (r[d.k] ? `<i style="flex:${r[d.k]} 1 0;background:${d.color}"></i>` : '')).join('')}</div>`;
    };
    const cell = (r, d) => {
      const v = r[d.k];
      if (v == null) return '<td class="r muted">–</td>';
      const sp = r.y.split[d.k];
      const rank = lowerBound(sp.sorted, v) + 1;
      const isBest = multi && v === best[d.k];
      return `<td class="r split-cell${isBest ? ' best' : ''}" data-y="${r.year}" data-k="${d.k}">${fmt(v)}<small>${rank}. / ${sp.sorted.length}</small></td>`;
    };
    return `<div class="table-wrap"><table class="split-table" id="splitTable">
      <thead><tr><th>Év</th><th class="c-bar">Arányok</th>${DISC.map((d) =>
        `<th class="r"><i class="key-dot" style="background:${d.color};margin-right:6px"></i>${d.label}</th>`).join('')}<th class="r">Célidő</th></tr></thead>
      <tbody>${rows.slice().reverse().map((r) => `<tr>
        <td><a href="${U.year(r.year)}">${r.year}</a></td>
        <td class="c-bar">${bar(r)}</td>
        ${DISC.map((d) => cell(r, d)).join('')}
        <td class="r split-cell${multi && r.t === bestT ? ' best' : ''}"><b>${fmt(r.t)}</b><small>${r.pos}. / ${r.y.n}</small></td>
      </tr>`).join('')}</tbody></table></div>`;
  }

  // részidő-cella tooltip (eseménydelegálással, mert a táblázat HTML-ként készül)
  document.addEventListener('pointermove', (ev) => {
    const td = ev.target.closest && ev.target.closest('#splitTable td[data-k]');
    if (!td) { if (document.getElementById('splitTable')?.dataset.tip) { hideTip(); delete document.getElementById('splitTable').dataset.tip; } return; }
    const y = M.Y.get(Number(td.dataset.y));
    const d = DISC.find((x) => x.k === td.dataset.k);
    const r = y.res.find((q) => String(q.a.id) === (location.hash.split('/')[2] || ''));
    if (!r) return;
    const sp = y.split[d.k];
    document.getElementById('splitTable').dataset.tip = '1';
    showTip(`<div class="tt-title">${d.label} · ${y.year}</div>
      ${ttRow('Idő', fmt(r[d.k]), d.color)}
      ${ttRow('Helyezés', `${lowerBound(sp.sorted, r[d.k]) + 1}. / ${sp.sorted.length}`)}
      ${ttRow('Mezőny mediánja', fmt(sp.median))}
      ${ttRow('A mediánhoz', fmtDiff(r[d.k] - sp.median))}`, ev.clientX, ev.clientY);
  });

  // ------------------------------------------------------------------
  // Nézet: évek
  // ------------------------------------------------------------------
  function renderYears() {
    const ys = M.years;
    const maxY = ys.reduce((b, y) => (y.n > b.n ? y : b));
    setHero({
      img: 'hero-uszas.jpg', pos: 'center 65%', compact: true,
      eyebrow: `eXtremeMan Nagyatád · ${ys[0].year} – ${ys[ys.length - 1].year}`, title: 'Évek',
      lead: `${ys.length} verseny, összesen ${nf.format(M.results)} célba érés. Kattints egy évre a teljes eredménylistáért.`,
    });
    $app.innerHTML = `
      <section class="card">
        <div class="card-head"><div><h2>Célba érkezők száma</h2><p>Teljes táv, egyéni.</p></div></div>
        <div class="chart" id="cnt"></div>
      </section>
      <section class="card">
        <div class="card-head"><div><h2>Győztes és medián idő</h2><p>Feljebb = gyorsabb.</p></div></div>
        ${legendHtml([{ name: 'Győztes idő', color: 'var(--s1)' }, { name: 'Medián idő', color: 'var(--s2)' }])}
        <div class="chart" id="tm"></div>
      </section>
      <section class="card">
        <div class="table-wrap"><table>
          <thead><tr><th>Év</th><th class="r">Célba érkezők</th><th class="r">Új finisherek</th><th>Győztes</th><th class="r">Győztes idő</th><th class="r">Medián</th></tr></thead>
          <tbody>${ys.slice().reverse().map((y) => `<tr>
            <td><a href="${U.year(y.year)}">${y.year}</a></td><td class="r">${y.n}</td><td class="r">${y.rookies}</td>
            <td><a href="${U.athlete(y.winner.a.id, y.winner.a.name)}">${esc(y.winner.a.name)}</a></td>
            <td class="r">${fmt(y.winner.t)}</td><td class="r">${fmt(y.median)}</td></tr>`).join('')}</tbody>
        </table></div>
      </section>`;
    const last = ys[ys.length - 1];
    columnChart(document.getElementById('cnt'), ys.map((y) => ({
      label: String(y.year),
      value: y.n,
      valueLabel: y === maxY || y === last ? String(y.n) : '',
      tip: `<div class="tt-title">${y.year}</div>${ttRow('Célba érkezők', y.n)}${ttRow('Új finisherek', y.rookies)}${ttRow('Győztes idő', fmt(y.winner.t))}`,
      onClick: () => { go(U.year(y.year)); },
    })), { ariaLabel: 'Célba érkezők száma évenként', labelEvery: 5 });
    lineChart(document.getElementById('tm'), {
      kind: 'time', invert: true,
      series: [
        { name: 'Győztes idő', color: 'var(--s1)', points: ys.map((y) => ({ x: y.year, y: y.winner.t })), dots: false, endLabel: 'győztes' },
        { name: 'Medián idő', color: 'var(--s2)', points: ys.map((y) => ({ x: y.year, y: y.median })), dots: false, endLabel: 'medián' },
      ],
      ariaLabel: 'Győztes és medián célidő évenként',
      tip: (x) => {
        const y = M.Y.get(x);
        return `<div class="tt-title">${x}</div>${ttRow('Győztes', fmt(y.winner.t), 'var(--s1)')}${ttRow('Medián', fmt(y.median), 'var(--s2)')}${ttRow('Célba érkezők', y.n)}`;
      },
      onClick: (x) => { go(U.year(x)); },
    });
  }

  // ------------------------------------------------------------------
  // Nézet: egy év
  // ------------------------------------------------------------------
  function renderYear(year) {
    const y = M.Y.get(year);
    if (!y) return renderNotFound('Erre az évre nincs adat.');
    const idx = M.years.indexOf(y);
    const prev = M.years[idx - 1], next = M.years[idx + 1];
    const sp = y.hasSplits;
    $app.innerHTML = `
      <div class="page-head">
        <div class="eyebrow"><a href="${U.years()}">← Évek</a></div>
        <div class="card-head" style="margin:0">
          <h1><span class="h1-pre">eXtremeMan Nagyatád eredmények</span> ${year}</h1>
          <div class="pager">
            <a href="${prev ? `${U.year(prev.year)}` : '#'}" aria-disabled="${!prev}" aria-label="Előző év">← ${prev ? prev.year : ''}</a>
            <a href="${next ? `${U.year(next.year)}` : '#'}" aria-disabled="${!next}" aria-label="Következő év">${next ? next.year : ''} →</a>
          </div>
        </div>
      </div>
      <div class="tiles">
        ${tile('Célba érkezők', y.n, `ebből ${y.rookies} új finisher`)}
        ${tile('Győztes idő', fmt(y.winner.t), `<a href="${U.athlete(y.winner.a.id, y.winner.a.name)}">${esc(y.winner.a.name)}</a>`)}
        ${tile('Medián idő', fmt(y.median), 'a mezőny fele ennél gyorsabb')}
        ${tile('Utolsó célba érkező', fmt(y.last.t), `<a href="${U.athlete(y.last.a.id, y.last.a.name)}">${esc(y.last.a.name)}</a>`)}
      </div>
      <section class="card">
        <div class="card-head"><div><h2>Célidők eloszlása</h2><p>Hányan értek célba az egyes félórás sávokban.</p></div></div>
        <div class="chart" id="hist"></div>
      </section>
      ${sp ? `<section class="card">
        <div class="card-head"><div><h2>Leggyorsabb részidők</h2><p>A mezőny medián részidői: ${DISC.slice(0, 3).map((d) => `${d.label.toLowerCase()} ${fmt(y.split[d.k].median)}`).join(' · ')}</p></div></div>
        <div class="grid-2" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">${DISC.slice(0, 3).map((d) => {
          const top = y.res.filter((r) => r[d.k] != null).sort((p, q) => p[d.k] - q[d.k]).slice(0, 5);
          return `<div><h3 style="font-size:15px;margin-bottom:4px"><i class="key-dot" style="background:${d.color};margin-right:8px"></i>${d.label}</h3>
            <ol class="rank-list">${top.map((r, i) => `<li><span class="pos">${i + 1}.</span><a class="who" href="${U.athlete(r.a.id, r.a.name)}">${esc(r.a.name)}</a><span class="val">${fmt(r[d.k])}</span></li>`).join('')}</ol></div>`;
        }).join('')}</div>
      </section>` : ''}
      <section class="card">
        <div class="card-head"><h2>Eredménylista</h2>
          <label class="search" style="flex:0 1 260px"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>
            <span class="sr-only">Keresés</span><input id="yq" type="search" placeholder="Keresés…"></label>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th class="r">Hely</th><th>Név</th>${sp ? '<th>Klub</th><th class="r">Úszás</th><th class="r">Kerékpár</th><th class="r">Futás</th>' : ''}<th class="r">Célidő</th><th class="r">Hányadik célba érés</th></tr></thead>
          <tbody id="ytb"></tbody>
        </table></div>
        <button class="btn show-more" id="ymore" type="button" hidden>Összes mutatása</button>
      </section>`;

    // hisztogram
    const bins = histBins(y);
    columnChart(document.getElementById('hist'), bins.map((b) => ({
      label: fmtHM(b.s),
      value: b.n,
      tip: `<div class="tt-title">${fmtHM(b.s)} – ${fmtHM(b.e)}</div>${ttRow('Célba érkezők', b.n)}`,
    })), { ariaLabel: `${year}: célidők eloszlása félórás sávokban`, labelEvery: 2 });

    const $tb = document.getElementById('ytb'), $more = document.getElementById('ymore');
    let limit = 100;
    const rowHtml = (r) => `<tr>
      <td class="r">${r.pos}.</td>
      <td><a href="${U.athlete(r.a.id, r.a.name)}">${esc(r.a.name)}</a></td>
      ${sp ? `<td class="muted">${esc(r.club || '')}</td><td class="r">${fmt(r.swim)}</td><td class="r">${fmt(r.bike)}</td><td class="r">${fmt(r.run)}</td>` : ''}
      <td class="r"><b>${fmt(r.t)}</b></td>
      <td class="r">${r.nth === 1 ? '<span class="pb-tag" style="margin:0">első</span>' : `${r.nth}.`}</td></tr>`;
    const fill = () => {
      const tokens = fold(document.getElementById('yq').value.trim()).split(/\s+/).filter(Boolean);
      const rows = y.res.filter((r) => tokens.every((t) => r.a.key.includes(t) || fold(r.club || '').includes(t)));
      $tb.innerHTML = rows.slice(0, limit).map(rowHtml).join('') || `<tr><td colspan="9" class="empty">Nincs találat.</td></tr>`;
      $more.hidden = rows.length <= limit;
    };
    document.getElementById('yq').addEventListener('input', debounce(fill, 120));
    $more.addEventListener('click', () => { limit = Infinity; fill(); });
    fill();
  }

  // ------------------------------------------------------------------
  // Nézet: rekordok
  // ------------------------------------------------------------------
  function renderRecords() {
    const fastest = [...M.athletes].sort((a, b) => a.best - b.best).slice(0, 25);
    const most = [...M.athletes].sort((a, b) => b.count - a.count || a.first - b.first).slice(0, 25);
    const streak = [...M.athletes].sort((a, b) => b.streak - a.streak || a.streakEnd - b.streakEnd).slice(0, 25);
    const longest = [...M.athletes].filter((a) => a.count > 1).sort((a, b) => (b.last - b.first) - (a.last - a.first)).slice(0, 25);
    const list = (arr, val, sub) => `<ol class="rank-list">${arr.map((a, i) => `<li><span class="pos">${i + 1}.</span>
      <span class="who"><a href="${U.athlete(a.id, a.name)}">${esc(a.name)}</a><small>${sub(a)}</small></span><span class="val">${val(a)}</span></li>`).join('')}</ol>`;
    setHero({
      img: 'hero-erem.jpg', pos: 'center 25%', compact: true,
      eyebrow: 'eXtremeMan Nagyatád · toplisták', title: 'Rekordok',
      lead: 'A leggyorsabbak, a legkitartóbbak és a leghűségesebbek a teljes távú egyéni célba érkezők között.',
    });
    $app.innerHTML = `
      <div class="grid-2">
        <section class="card"><div class="card-head"><div><h2>Leggyorsabb egyéni idők</h2><p>Versenyzőnként a legjobb idő.</p></div></div>
          ${list(fastest, (a) => fmt(a.best), (a) => a.bestRes.year)}</section>
        <section class="card"><div class="card-head"><div><h2>Legtöbb célba érés</h2><p>Nagyatádon, teljes távon.</p></div></div>
          ${list(most, (a) => `${a.count}×`, (a) => `${a.first}–${a.last}`)}</section>
        <section class="card"><div class="card-head"><div><h2>Leghosszabb sorozat</h2><p>Egymást követő években célba érve.</p></div></div>
          ${list(streak, (a) => `${a.streak} év`, (a) => `${a.streakEnd - a.streak + 1}–${a.streakEnd}`)}</section>
        <section class="card"><div class="card-head"><div><h2>Leghosszabb pályafutás</h2><p>Az első és az utolsó célba érés között eltelt évek.</p></div></div>
          ${list(longest, (a) => `${a.last - a.first} év`, (a) => `${a.first}–${a.last}`)}</section>
      </div>`;
  }


  // ------------------------------------------------------------------
  // További eXtremeMan versenyek (igény szerint betöltve: other_data / data/other.json)
  // ------------------------------------------------------------------
  function rpcHeaders() {
    const h = { 'Content-Type': 'application/json', apikey: CFG.supabaseKey };
    if (CFG.supabaseKey.startsWith('eyJ')) h.Authorization = `Bearer ${CFG.supabaseKey}`;
    return h;
  }
  const rpcUrl = (fn) => `${CFG.supabaseUrl.replace(/\/+$/, '')}/rest/v1/rpc/${fn}`;

  let otherPromise = null;
  function loadOther() {
    if (!otherPromise) {
      otherPromise = (async () => {
        let d = null;
        if (source === 'supabase') {
          try {
            const res = await fetch(rpcUrl('other_data'), { method: 'POST', headers: rpcHeaders(), body: '{}' });
            if (res.ok) d = await res.json();
          } catch (e) { /* tartalék fájl */ }
        }
        if (!d || !d.races || !d.races.length) d = await (await fetch(`${ROOT_PATH}data/other.json`)).json();
        return buildOther(d);
      })().catch((e) => { console.error(e); otherPromise = null; return null; });
    }
    return otherPromise;
  }

  function buildOther(d) {
    const races = d.races.map(([key, year, series, seriesName, name, segLabels, n, best, med, hasLaps]) => ({
      key, year, series, seriesName, name, n, best, median: med, res: [], hasLaps: !!hasLaps,
      segLabels: Array.isArray(segLabels) ? segLabels : JSON.parse(segLabels || '[]'),
    }));
    const people = new Map();
    for (const [id, name, by, sex] of d.athletes) people.set(id, { id, name, by, sex, key: fold(name) });
    const byAthlete = new Map();
    for (const [ri, aid, pos, sexRank, t, segs, club] of d.results) {
      const race = races[ri];
      if (!race) continue;
      const r = { race, aid, pos, sexRank, t, segs: Array.isArray(segs) ? segs : JSON.parse(segs || '[]'), club };
      race.res.push(r);
      if (!byAthlete.has(aid)) byAthlete.set(aid, []);
      byAthlete.get(aid).push(r);
    }
    for (const r of races) r.res.sort((x, y) => x.pos - y.pos);
    const series = new Map();
    for (const r of races) {
      if (!series.has(r.series)) series.set(r.series, { key: r.series, name: r.seriesName, races: [] });
      series.get(r.series).races.push(r);
    }
    return { races, byKey: new Map(races.map((r) => [r.key, r])), people, byAthlete, series };
  }
  const personOf = (O, id) => M.A.get(id) || O.people.get(id) || null;

  function otherResultsHtml(O, id) {
    const rs = O.byAthlete.get(id) || [];
    const groups = new Map();
    for (const r of rs) {
      if (!groups.has(r.race.series)) groups.set(r.race.series, []);
      groups.get(r.race.series).push(r);
    }
    const latest = (g) => Math.max(...g.map((r) => r.race.year));
    return [...groups.values()].sort((g1, g2) => latest(g2) - latest(g1)).map((g) => {
      g.sort((x, y) => y.race.year - x.race.year || x.race.name.localeCompare(y.race.name, 'hu'));
      return `<div class="other-series" id="s-${g[0].race.series}">
        <h3>${esc(g[0].race.seriesName)} <span class="muted">· ${g.length}×</span></h3>
        <div class="table-wrap"><table class="other-table">
          <thead><tr><th>Év</th><th>Táv</th><th class="r">Célidő</th><th class="r">Helyezés</th><th>Részidők</th></tr></thead>
          <tbody>${g.map((r) => `<tr>
            <td>${r.race.year}</td>
            <td><a href="${U.race(r.race.key)}">${esc(r.race.name)}</a>${r.race.hasLaps
              ? `<button type="button" class="lap-toggle" data-race="${r.race.key}" data-aid="${id}" aria-expanded="false">Körönként ▾</button>` : ''}</td>
            <td class="r"><b>${fmt(r.t)}</b></td>
            <td class="r">${r.pos}. <span class="muted">/ ${r.race.n}</span></td>
            <td class="segs">${r.race.segLabels.map((l, i) => (r.segs[i] != null ? `<span>${esc(l)} <b>${fmt(r.segs[i])}</b></span>` : '')).join('')}</td>
          </tr>`).join('')}</tbody>
        </table></div></div>`;
    }).join('');
  }

  function otherSummaryHtml(O, id, nagyatadCount) {
    const rs = O.byAthlete.get(id) || [];
    const per = new Map();
    for (const r of rs) per.set(r.race.series, { name: r.race.seriesName, n: (per.get(r.race.series)?.n || 0) + 1 });
    const chips = [];
    if (nagyatadCount) chips.push(`<span class="chip chip-main">Nagyatád teljes táv <b>${nagyatadCount}×</b></span>`);
    for (const [k, v] of [...per.entries()].sort((x, y) => y[1].n - x[1].n)) {
      chips.push(`<button type="button" class="chip" data-scroll="s-${k}">${esc(v.name)} <b>${v.n}×</b></button>`);
    }
    return chips.length > (nagyatadCount ? 1 : 0) ? `<span class="chips-label">Versenyei:</span>${chips.join('')}` : '';
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('[data-scroll]');
    if (b) document.getElementById(b.dataset.scroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest && e.target.closest('.lap-toggle');
    if (!btn) return;
    const tr = btn.closest('tr');
    const open = tr.nextElementSibling && tr.nextElementSibling.classList.contains('lap-row') ? tr.nextElementSibling : null;
    if (open) { open.remove(); btn.setAttribute('aria-expanded', 'false'); btn.textContent = 'Körönként ▾'; return; }
    btn.setAttribute('aria-expanded', 'true'); btn.textContent = 'Körönként ▴';
    const row = document.createElement('tr');
    row.className = 'lap-row';
    row.innerHTML = `<td colspan="5"><div class="lap-host">${loadingHtml}</div></td>`;
    tr.after(row);
    // a lenyitott rész a táblázat látható szélességét kapja (mobilon a táblázat oldalra görgethető)
    const wrap = tr.closest('.table-wrap');
    const host = row.querySelector('.lap-host');
    if (wrap) host.style.width = `${Math.max(260, wrap.clientWidth - 40)}px`;  // a .table-wrap két oldali 20 px-es belső margója nélkül
    const O = await loadOther();
    const key = btn.dataset.race, aid = Number(btn.dataset.aid);
    const race = O && O.byKey.get(key);
    const person = O && personOf(O, aid);
    if (!race || !person) return;
    renderLaps(host, person, race.year,
      { load: () => loadRaceLaps(key), raceKey: key, people: O.people });
  });

  function fillOther(a) {
    loadOther().then((O) => {
      const card = document.getElementById('otherCard');
      if (!O || !card || Number(card.dataset.aid) !== a.id) return;
      if (!(O.byAthlete.get(a.id) || []).length) return;
      document.getElementById('otherBody').innerHTML = otherResultsHtml(O, a.id);
      card.hidden = false;
      document.getElementById('otherSummary').innerHTML = otherSummaryHtml(O, a.id, a.count);
    });
  }

  const loadingHtml = '<div class="loading" role="status"><span class="spinner"></span> Betöltés…</div>';

  /** Versenyző, aki csak a további versenyeken indult (nincs nagyatádi teljes távja). */
  async function renderSideAthlete(id) {
    $app.innerHTML = loadingHtml;
    const O = await loadOther();
    if (currentRoute()[0] !== 'versenyzo' || Number(currentRoute()[1]) !== id) return;
    const p = O && O.people.get(id);
    const rs = (O && O.byAthlete.get(id)) || [];
    if (!p || !rs.length) return renderNotFound('Nincs ilyen versenyző.');
    document.title = `${p.name} – eXtremeMan eredmények`;
    canonicalize(U.athlete(p.id, p.name));
    const ys = rs.map((r) => r.race.year), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const club = [...rs].sort((x, y) => y.race.year - x.race.year).find((r) => r.club)?.club;
    const best = rs.reduce((b, r) => (r.pos / r.race.n < b.pos / b.race.n ? r : b));
    const nSeries = new Set(rs.map((r) => r.race.series)).size;
    $app.innerHTML = `
      <div class="page-head">
        <div class="eyebrow"><a href="${U.races()}">← Versenyek</a></div>
        <h1>${esc(p.name)}</h1>
        <p class="lead">${[p.by ? `Született ${p.by}` : '', club ? esc(club) : '',
          `${rs.length} eXtremeMan verseny ${y0 === y1 ? y0 : `${y0} és ${y1} között`}`].filter(Boolean).join(' · ')}</p>
        <div class="chips">${otherSummaryHtml(O, id, 0)}</div>
      </div>
      <div class="tiles">
        ${tile('Versenyek', `${rs.length}×`, `${nSeries} sorozatban`)}
        ${tile('Időszak', y0 === y1 ? String(y0) : `${y0}–${y1}`, '')}
        ${tile('Legjobb helyezés', `${best.pos}.`, `${esc(best.race.seriesName)} ${best.race.year} · ${esc(best.race.name)}`)}
        ${tile('Nagyatád teljes táv', '–', 'még nem szerepel a finisherek között')}
      </div>
      <section class="card"><div class="card-head"><div><h2>eXtremeMan versenyek</h2>
        <p>Versenysorozatonként, a legfrissebb elöl. A távra kattintva a teljes eredménylista nyílik meg.</p></div></div>
        ${otherResultsHtml(O, id)}</section>`;
  }

  /** Egy verseny (sorozat + év + táv) teljes eredménylistája. */
  async function renderRace(key) {
    $app.innerHTML = loadingHtml;
    const O = await loadOther();
    if (currentRoute()[1] !== key) return;
    const r = O && O.byKey.get(key);
    if (!r) return renderNotFound('Nincs ilyen verseny.');
    document.title = `${r.seriesName} ${r.year} – ${r.name} eredmények | eXtremeMan`;
    const sib = O.series.get(r.series).races;
    const sameYear = sib.filter((x) => x.year === r.year);
    const sameName = sib.filter((x) => x.name === r.name).sort((x, y) => y.year - x.year);
    const w = r.res[0], wp = w && personOf(O, w.aid);
    const chip = (x, label) => `<a class="chip${x === r ? ' active' : ''}" href="${U.race(x.key)}">${esc(label)} <span class="muted">${x.n}</span></a>`;
    $app.innerHTML = `
      <div class="page-head">
        <div class="eyebrow"><a href="${U.races()}">← Versenyek</a></div>
        <h1>${esc(r.seriesName)} ${r.year} <span class="h1-sub">${esc(r.name)}</span></h1>
      </div>
      <div class="tiles">
        ${tile('Célba érkezők', r.n, '')}
        ${tile('Győztes idő', fmt(r.best), wp ? `<a href="${U.athlete(wp.id, wp.name)}">${esc(wp.name)}</a>` : '')}
        ${tile('Medián idő', fmt(r.median), 'a mezőny fele ennél gyorsabb')}
        ${tile('Szakaszok', r.segLabels.filter((l) => !/^dep/i.test(l)).length || '–', esc(r.segLabels.filter((l) => !/^dep/i.test(l)).join(' · ')))}
      </div>
      ${sameYear.length > 1 ? `<div class="chips"><span class="chips-label">${r.year} további távjai:</span>${sameYear.map((x) => chip(x, x.name)).join('')}</div>` : ''}
      ${sameName.length > 1 ? `<div class="chips"><span class="chips-label">Ugyanez más években:</span>${sameName.map((x) => chip(x, String(x.year))).join('')}</div>` : ''}
      <section class="card">
        <div class="card-head"><h2>Eredménylista</h2>
          <label class="search" style="flex:0 1 260px"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>
            <span class="sr-only">Keresés</span><input id="rq" type="search" placeholder="Keresés…"></label>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th class="r">Hely</th><th>Név</th><th>Klub</th>${r.segLabels.map((l) => `<th class="r">${esc(l)}</th>`).join('')}<th class="r">Célidő</th></tr></thead>
          <tbody id="rtb"></tbody>
        </table></div>
        <button class="btn show-more" id="rmore" type="button" hidden>Összes mutatása</button>
      </section>`;
    let limit = 100;
    const $tb = document.getElementById('rtb'), $more = document.getElementById('rmore');
    const row = (x) => {
      const p = personOf(O, x.aid);
      return `<tr><td class="r">${x.pos}.</td><td>${p ? `<a href="${U.athlete(p.id, p.name)}">${esc(p.name)}</a>` : '?'}</td>
        <td class="muted">${esc(x.club || '')}</td>${r.segLabels.map((l, i) => `<td class="r">${fmt(x.segs[i])}</td>`).join('')}
        <td class="r"><b>${fmt(x.t)}</b></td></tr>`;
    };
    const fill = () => {
      const tokens = fold(document.getElementById('rq').value.trim()).split(/\s+/).filter(Boolean);
      const rows = r.res.filter((x) => {
        const p = personOf(O, x.aid);
        return tokens.every((t) => (p && p.key.includes(t)) || fold(x.club || '').includes(t));
      });
      $tb.innerHTML = rows.slice(0, limit).map(row).join('') || '<tr><td colspan="20" class="empty">Nincs találat.</td></tr>';
      $more.hidden = rows.length <= limit;
    };
    document.getElementById('rq').addEventListener('input', debounce(fill, 120));
    $more.addEventListener('click', () => { limit = Infinity; fill(); });
    fill();
  }

  /** Versenyek: az összes további eXtremeMan verseny sorozatonként. */
  async function renderRaces() {
    setHero({
      img: 'hero-bringa.jpg', pos: 'center 55%', compact: true,
      eyebrow: 'eXtremeMan · 2015 – 2026', title: 'Versenyek',
      lead: 'Az összes eXtremeMan verseny az EvoChip eredményeiből: Nagyatád többi táva, Kaposvár, Gyékényes, Balatonszemes, Tab, Velence, Székesfehérvár, Nágocs.',
    });
    $app.innerHTML = loadingHtml;
    const O = await loadOther();
    if (currentRoute()[0] !== 'versenyek') return;
    if (!O) return renderNotFound('A versenyek betöltése nem sikerült.');
    const list = [...O.series.values()].sort((x, y) => y.races.length - x.races.length);
    $app.innerHTML = `
      <section class="card"><div class="card-head"><div><h2>Nagyatád – teljes táv</h2>
        <p>Az eXtremeMan fő versenye 1990 óta: lásd a <a href="${U.home()}">finisherek névsorát</a> és az <a href="${U.years()}">évenkénti eredményeket</a>.</p></div></div></section>
      <div class="grid-2">${list.map((sr) => {
        const years = [...new Set(sr.races.map((x) => x.year))].sort((a, b) => b - a);
        return `<section class="card"><div class="card-head"><div><h2>${esc(sr.name)}</h2>
          <p>${sr.races.length} verseny · ${sr.races.reduce((t, x) => t + x.n, 0)} célba érkezés</p></div></div>
          ${years.map((y) => `<div class="race-year"><b>${y}</b><div class="chips">${sr.races.filter((x) => x.year === y)
            .map((x) => `<a class="chip" href="${U.race(x.key)}">${esc(x.name)} <span class="muted">${x.n}</span></a>`).join('')}</div></div>`).join('')}
        </section>`;
      }).join('')}</div>`;
  }

  function renderNotFound(msg) {
    $app.innerHTML = `<div class="notice"><p>${esc(msg)}</p><p><a href="${U.home()}">Vissza a finisherekhez</a></p></div>`;
  }

  // ------------------------------------------------------------------
  // Útválasztás
  // ------------------------------------------------------------------
  /** Az aktuális nézet a címből (ROOT_PATH-hoz képest):
   *  ['' | 'evek' | 'rekordok' | 'versenyek' | 'versenyzo', id, év | 'ev', év | 'verseny', kulcs] */
  function currentRoute() {
    let rel = location.pathname.startsWith(ROOT_PATH) ? location.pathname.slice(ROOT_PATH.length) : '';
    rel = decodeURIComponent(rel).replace(/index\.html$/, '').replace(/^\/+|\/+$/g, '');
    const parts = rel ? rel.split('/') : [''];
    const q = new URLSearchParams(location.search);
    if (parts[0] === 'versenyzo') return ['versenyzo', String(parseInt(parts[1], 10)), q.get('ev') || ''];
    if (parts[0] === 'ev' || parts[0] === 'verseny') return [parts[0], parts[1] || ''];
    if (['evek', 'rekordok', 'versenyek'].includes(parts[0])) return [parts[0]];
    return [''];
  }

  /** Navigáció újratöltés nélkül (History API). */
  function go(url, replace = false) {
    history[replace ? 'replaceState' : 'pushState'](null, '', url);
    route();
  }
  /** A versenyző címe mindig a pontos név-slugot mutassa (megosztáshoz, SEO). */
  function canonicalize(url) {
    const now = location.pathname + location.search;
    if (now !== url) history.replaceState(null, '', url);
  }
  // belső linkek: újratöltés nélküli navigáció
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith(ROOT_PATH)) return;
    if (/\.[a-z0-9]+$/i.test(url.pathname) && !/index\.html$/.test(url.pathname)) return; // fájlok (json, xml, kép)
    e.preventDefault();
    go(url.pathname + url.search);
  });
  window.addEventListener('popstate', route);

  /** Régi #/... linkek átírása az új címekre. */
  function upgradeHash() {
    const h = location.hash.replace(/^#\/?/, '');
    if (!location.hash.startsWith('#/')) return;
    const [v, x, y] = h.split('/');
    let url = U.home();
    if (v === 'versenyzo') { const a = M.A.get(Number(x)); url = U.athlete(x, a ? a.name : '', y); }
    else if (v === 'ev') url = U.year(x);
    else if (v === 'verseny') url = U.race(x);
    else if (v === 'evek') url = U.years();
    else if (v === 'rekordok') url = U.records();
    else if (v === 'versenyek') url = U.races();
    history.replaceState(null, '', url);
  }

  let firstRoute = true; // az oldal első kirajzolása (a statikus HTML még a helyén van)
  function route() {
    resetView();
    const [view, arg, arg2] = currentRoute();
    if (!['', 'evek', 'rekordok', 'versenyek'].includes(view || '')) $hero.innerHTML = '';
    const navKey = { versenyzo: 'list', '': 'list', evek: 'years', ev: 'years', rekordok: 'records', versenyek: 'races', verseny: 'races' }[view || ''] || 'list';
    document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === navKey));
    // a címek egyeznek a build_pages.py által generált statikus oldalakéval (SEO)
    let title = 'eXtremeMan Nagyatád finisherek – eredmények 1990 óta';
    if (view === 'versenyzo') {
      renderAthlete(Number(arg), Number(arg2) || null);
      const a = M.A.get(Number(arg));
      if (a) { title = `${a.name} – eXtremeMan Nagyatád eredmények`; canonicalize(U.athlete(a.id, a.name, arg2)); }
      else title = document.title; // a renderSideAthlete állítja be
    } else if (view === 'ev') { renderYear(Number(arg)); title = `eXtremeMan Nagyatád ${arg} eredmények – teljes táv`; }
    else if (view === 'evek') { renderYears(); title = 'Évek – eXtremeMan Nagyatád finisherek'; }
    else if (view === 'rekordok') { renderRecords(); title = 'Rekordok – eXtremeMan Nagyatád finisherek'; }
    else if (view === 'versenyek') { renderRaces(); title = 'Versenyek – eXtremeMan eredmények 2015 óta'; }
    else if (view === 'verseny') { renderRace(arg); title = document.title; }
    else { renderList(); }
    document.title = title;
    firstRoute = false;
    if (!view && listState.scroll) { window.scrollTo(0, listState.scroll); listState.scroll = 0; }
    else if (!(view === 'versenyzo' && arg2)) window.scrollTo(0, 0);
  }

  // téma váltó
  document.getElementById('themeBtn').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('theme', root.dataset.theme); } catch (e) { /* nem baj */ }
  });
  window.addEventListener('scroll', hideTip, { passive: true });

  // indulás
  fetchData().then(({ d, source: src }) => {
    M = buildModel(d);
    source = src;
    document.getElementById('dataSource').textContent = {
      supabase: 'Adatok: Supabase adatbázis.',
      fallback: 'A Supabase adatbázis most nem érhető el – a beépített pillanatkép látszik.',
      snapshot: 'Adatok: beépített pillanatkép (data/finishers.json).',
    }[source];
    upgradeHash();
    window.addEventListener('hashchange', () => { upgradeHash(); route(); });
    route();
  }).catch((e) => {
    console.error(e);
    $app.innerHTML = '<div class="notice"><p>Az adatok betöltése nem sikerült. Próbáld újra később.</p></div>';
  });
})();
