/* WebGIS RDTR Kecamatan Sawoo — aplikasi peta (Leaflet) */
(function () {
  'use strict';

  const DEFAULT_ON = ['ADMINISTRASI_AR_DESAKEL', 'ADMINISTRASI_AR_KECAMATAN'];
  const HOME = L.latLngBounds([-8.052, 111.518], [-7.916, 111.666]);
  const $ = (s, r) => (r || document).querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 3 });

  /* ------------------------------------------------------------- peta */
  const map = L.map('map', { zoomControl: false, maxZoom: 21, minZoom: 9, zoomSnap: 0.5, zoomDelta: 0.5, preferCanvas: true });
  map.fitBounds(HOME);
  L.control.zoom({ position: 'topleft', zoomInTitle: 'Perbesar', zoomOutTitle: 'Perkecil' }).addTo(map);
  L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

  const HomeCtl = L.Control.extend({
    options: { position: 'topleft' },
    onAdd() {
      const d = L.DomUtil.create('div', 'leaflet-bar');
      const a = L.DomUtil.create('a', '', d);
      a.href = '#'; a.title = 'Kembali ke wilayah Sawoo'; a.setAttribute('role', 'button');
      a.innerHTML = '<svg viewBox="0 0 24 24" style="width:16px;height:16px;margin-top:6px"><path d="M3 11 12 3l9 8M5 10v10h5v-6h4v6h5V10"/></svg>';
      L.DomEvent.disableClickPropagation(d);
      L.DomEvent.on(a, 'click', (e) => { L.DomEvent.preventDefault(e); map.fitBounds(HOME); });
      return d;
    }
  });
  new HomeCtl().addTo(map);

  map.createPane('raster').style.zIndex = 250;
  const canvas = L.canvas({ padding: 0.5 });

  /* ---------------------------------------------------------- basemap */
  const g = (lyr) => L.tileLayer('https://mt{s}.google.com/vt/lyrs=' + lyr + '&x={x}&y={y}&z={z}', {
    subdomains: '0123', maxZoom: 21, maxNativeZoom: 20, attribution: '© Google'
  });
  const BASEMAPS = {
    sat: () => g('s'),
    hybrid: () => g('y'),
    road: () => g('m'),
    terrain: () => g('p'),
    osm: () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }),
    dark: () => L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { subdomains: 'abcd', maxZoom: 20, attribution: '© OpenStreetMap, © CARTO' })
  };
  const bmCache = {};
  let bmCurrent = null;
  function setBasemap(key) {
    if (!BASEMAPS[key]) key = 'sat';
    if (bmCurrent) map.removeLayer(bmCache[bmCurrent]);
    bmCache[key] = bmCache[key] || BASEMAPS[key]();
    bmCache[key].addTo(map).bringToBack();
    bmCurrent = key;
    document.querySelectorAll('#basemaps button').forEach((b) => b.classList.toggle('active', b.dataset.bm === key));
    writeHash();
  }
  document.querySelectorAll('#basemaps button').forEach((b) => b.addEventListener('click', () => setBasemap(b.dataset.bm)));

  /* ------------------------------------------------------ status bar */
  map.on('mousemove', (e) => { $('#coords').textContent = 'Lat/Lon: ' + e.latlng.lat.toFixed(5) + ', ' + e.latlng.lng.toFixed(5); });
  const zi = () => { $('#zoomInfo').textContent = 'Zoom: ' + map.getZoom(); };
  map.on('zoomend', zi); zi();

  /* ---------------------------------------------------------- layers */
  const S = { meta: [], rec: {}, loading: 0, ident: null };

  function rank(m) {
    if (m.type === 'raster') return -1;
    const k = m.kind, t = m.style && m.style.t;
    if (k === 'polygon') return t === 'outline' ? 1 : 0;
    if (k === 'line') return 2;
    return 3;
  }
  function reorder() {
    Object.values(S.rec).filter((r) => r.active && r.layer && r.meta.type === 'vector')
      .sort((a, b) => rank(a.meta) - rank(b.meta) || S.meta.indexOf(b.meta) - S.meta.indexOf(a.meta))
      .forEach((r) => r.layer.bringToFront());
    if (S.ident) S.ident.bringToFront();
  }

  function colorOf(m, f) {
    const st = m.style, c = st.c;
    if (st.field && c && typeof c === 'object' && !Array.isArray(c)) {
      const v = c[f.properties[st.field]];
      if (v) return v;
      return '#9e9e9e';
    }
    return typeof c === 'string' ? c : '#9e9e9e';
  }

  function styleFn(m, op) {
    const st = m.style, kind = m.kind;
    return (f) => {
      let col = colorOf(m, f), w = st.w, dash = st.dash;
      if (Array.isArray(col)) { w = col[1]; dash = col[2]; col = col[0]; }
      if (kind === 'line') return { color: col, weight: w || 2, dashArray: dash || null, opacity: 0.95 * op, lineCap: 'round' };
      if (kind === 'point') return { radius: st.r || 5, fillColor: col, fillOpacity: 0.92 * op, color: '#ffffff', weight: 1.2, opacity: op };
      if (st.t === 'outline') return { color: col, weight: w || 2, fill: false, dashArray: dash || null, opacity: 0.95 * op };
      if (st.nostroke) return { stroke: false, fillColor: col, fillOpacity: 0.62 * op };
      return { color: col, weight: 0.9, opacity: 0.9 * op, fillColor: col, fillOpacity: 0.55 * op };
    };
  }

  function bboxOf(coords, bb) {
    if (typeof coords[0] === 'number') {
      if (coords[0] < bb[0]) bb[0] = coords[0]; if (coords[1] < bb[1]) bb[1] = coords[1];
      if (coords[0] > bb[2]) bb[2] = coords[0]; if (coords[1] > bb[3]) bb[3] = coords[1];
    } else coords.forEach((c) => bboxOf(c, bb));
    return bb;
  }

  async function loadData(rec) {
    if (rec.data) return rec.data;
    S.loading++; $('#loading').classList.remove('hidden');
    try {
      const res = await fetch(rec.meta.file);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      rec.data = await res.json();
      rec.data.features.forEach((f) => { f._bb = bboxOf(f.geometry.coordinates, [180, 90, -180, -90]); });
      return rec.data;
    } finally {
      if (--S.loading <= 0) { S.loading = 0; $('#loading').classList.add('hidden'); }
    }
  }

  async function activate(id, on, opts) {
    const rec = S.rec[id];
    if (!rec) return;
    opts = opts || {};
    const box = rec.el;
    if (on) {
      rec.active = true; box.classList.add('active'); rec.cb.checked = true;
      try {
        if (!rec.layer) {
          if (rec.meta.type === 'raster') {
            rec.layer = L.imageOverlay(rec.meta.file, rec.meta.bounds, { pane: 'raster', opacity: rec.opacity, interactive: false });
          } else {
            const data = await loadData(rec);
            rec.layer = L.geoJSON(data, {
              renderer: canvas, interactive: false,
              style: styleFn(rec.meta, rec.opacity),
              pointToLayer: (f, ll) => L.circleMarker(ll, { renderer: canvas, interactive: false })
            });
          }
        }
        if (!rec.active) return;           // dimatikan selagi memuat
        rec.layer.addTo(map);
        if (rec.labelOn) setLabels(rec, true);
        reorder();
        if (opts.zoom) map.fitBounds(rec.meta.bounds, { padding: [30, 30], maxZoom: 15 });
        const err = box.querySelector('.lerr'); if (err) err.remove();
      } catch (e) {
        rec.active = false; box.classList.remove('active'); rec.cb.checked = false;
        const d = document.createElement('div'); d.className = 'lerr'; d.textContent = 'Gagal memuat layer (' + e.message + ')';
        box.appendChild(d);
      }
    } else {
      rec.active = false; box.classList.remove('active'); rec.cb.checked = false;
      if (rec.layer) map.removeLayer(rec.layer);
      setLabels(rec, false);
    }
    refreshUI();
  }

  /* ------------------------------------------------------------ label */
  function labelPoint(geom) {
    const t = geom.type, c = geom.coordinates;
    if (t === 'Point') return [c[1], c[0]];
    if (t === 'MultiPoint') return [c[0][1], c[0][0]];
    if (t === 'LineString') { const m = c[Math.floor(c.length / 2)]; return [m[1], m[0]]; }
    if (t === 'MultiLineString') { const l = c[0]; const m = l[Math.floor(l.length / 2)]; return [m[1], m[0]]; }
    const polys = t === 'Polygon' ? [c] : c;
    let best = null, area = -1;
    polys.forEach((p) => { const bb = bboxOf(p[0], [180, 90, -180, -90]); const a = (bb[2] - bb[0]) * (bb[3] - bb[1]); if (a > area) { area = a; best = bb; } });
    return [(best[1] + best[3]) / 2, (best[0] + best[2]) / 2];
  }
  function setLabels(rec, on) {
    if (rec.labels) { map.removeLayer(rec.labels); rec.labels = null; }
    if (!on || !rec.data || !rec.meta.label) return;
    const grp = L.layerGroup();
    rec.data.features.forEach((f) => {
      const v = f.properties[rec.meta.label];
      if (v === null || v === undefined || v === '') return;
      const ll = labelPoint(f.geometry);
      L.marker(ll, { interactive: false, keyboard: false, icon: L.divIcon({ className: 'lbl-wrap', html: '<span class="leaflet-tooltip lbl" style="position:relative;display:inline-block;transform:translate(-50%,-50%);white-space:nowrap">' + esc(typeof v === 'number' ? nf.format(v) : v) + '</span>', iconSize: [0, 0] }) }).addTo(grp);
    });
    grp.addTo(map); rec.labels = grp;
  }

  /* -------------------------------------------------------- identify */
  function pip(pt, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function inPoly(pt, rings) {
    if (!pip(pt, rings[0])) return false;
    for (let i = 1; i < rings.length; i++) if (pip(pt, rings[i])) return false;
    return true;
  }
  function segDist(p, a, b) {
    let x = a.x, y = a.y, dx = b.x - x, dy = b.y - y;
    if (dx || dy) {
      const t = ((p.x - x) * dx + (p.y - y) * dy) / (dx * dx + dy * dy);
      if (t > 1) { x = b.x; y = b.y; } else if (t > 0) { x += dx * t; y += dy * t; }
    }
    return Math.hypot(p.x - x, p.y - y);
  }
  function lineHit(latlng, coords, tol) {
    const p = map.latLngToLayerPoint(latlng);
    const pts = coords.map((c) => map.latLngToLayerPoint([c[1], c[0]]));
    for (let i = 1; i < pts.length; i++) if (segDist(p, pts[i - 1], pts[i]) <= tol) return true;
    return false;
  }
  function featureHit(f, latlng) {
    const t = f.geometry.type, c = f.geometry.coordinates, pt = [latlng.lng, latlng.lat];
    const tol = 9, p = map.latLngToLayerPoint(latlng);
    if (t === 'Polygon') return inPoly(pt, c);
    if (t === 'MultiPolygon') return c.some((r) => inPoly(pt, r));
    if (t === 'LineString') return lineHit(latlng, c, tol);
    if (t === 'MultiLineString') return c.some((l) => lineHit(latlng, l, tol));
    if (t === 'Point') return p.distanceTo(map.latLngToLayerPoint([c[1], c[0]])) <= tol + 2;
    if (t === 'MultiPoint') return c.some((q) => p.distanceTo(map.latLngToLayerPoint([q[1], q[0]])) <= tol + 2);
    return false;
  }
  function fmtVal(v) { return typeof v === 'number' ? nf.format(v) : esc(v); }
  function featureName(f) {
    const p = f.properties;
    return p.NAMOBJ || p.namobj || p.NAMA || p.WADMKD || p.DESA || p.kecamatan || p._cls || '';
  }

  let hits = [], hitIdx = 0, popup = null;
  function showHit(i) {
    hitIdx = (i + hits.length) % hits.length;
    const h = hits[hitIdx], m = h.rec.meta, p = h.f.properties;
    const rows = m.fields.filter((k) => p[k] !== null && p[k] !== undefined && p[k] !== '')
      .map((k) => '<tr><td>' + esc(m.aliases[k] || k) + '</td><td>' + fmtVal(p[k]) + '</td></tr>').join('');
    const nav = hits.length > 1
      ? '<div style="display:flex;align-items:center;gap:8px;padding:7px 14px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)">' +
        '<button class="mini" data-nav="-1">‹</button><span>' + (hitIdx + 1) + ' dari ' + hits.length + ' objek</span><button class="mini" data-nav="1">›</button></div>' : '';
    const nm = featureName(h.f);
    popup.setContent('<div class="pop-h"><b>' + esc(nm || m.title) + '</b><span>' + esc(m.title) + '</span></div>' +
      '<div class="pop-b"><table>' + (rows || '<tr><td colspan="2">Tidak ada atribut.</td></tr>') + '</table></div>' + nav);
    if (S.ident) map.removeLayer(S.ident);
    S.ident = L.geoJSON(h.f, {
      interactive: false, renderer: canvas,
      style: { color: '#ffea00', weight: 3, fillColor: '#ffea00', fillOpacity: 0.15, opacity: 1 },
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 9, color: '#ffea00', weight: 3, fillOpacity: 0.2, renderer: canvas, interactive: false })
    }).addTo(map);
    S.ident.bringToFront();
  }
  map.on('click', (e) => {
    const rank0 = (r) => rank(r.meta);
    hits = [];
    Object.values(S.rec).filter((r) => r.active && r.data && r.meta.type === 'vector').forEach((r) => {
      const ll = e.latlng, pad = r.meta.kind === 'polygon' ? 0 : 0.0006;
      r.data.features.forEach((f) => {
        const b = f._bb;
        if (ll.lng < b[0] - pad || ll.lng > b[2] + pad || ll.lat < b[1] - pad || ll.lat > b[3] + pad) return;
        if (featureHit(f, ll)) hits.push({ rec: r, f });
      });
    });
    hits.sort((a, b) => rank0(b.rec) - rank0(a.rec));        // titik/garis di atas poligon
    if (!hits.length) { if (S.ident) { map.removeLayer(S.ident); S.ident = null; } return; }
    popup = L.popup({ maxWidth: 340, autoPanPadding: [30, 60] }).setLatLng(e.latlng).openOn(map);
    popup.on('remove', () => { if (S.ident) { map.removeLayer(S.ident); S.ident = null; } });
    showHit(0);
    const el = popup.getElement();
    el.addEventListener('click', (ev) => {
      const b = ev.target.closest('[data-nav]');
      if (b) { ev.stopPropagation(); showHit(hitIdx + parseInt(b.dataset.nav, 10)); }
    });
  });

  /* --------------------------------------------------------- sidebar */
  function symbolEl(m) {
    const s = document.createElement('span');
    const lg = m.legend && m.legend[0];
    if (m.type === 'raster') { s.className = 'sym raster'; return s; }
    const col = lg ? lg.color : '#999';
    s.className = 'sym ' + (m.kind === 'line' ? 'line' : m.kind === 'point' ? 'point' : '');
    if (m.kind === 'line') s.style.borderTopColor = col;
    else if (lg && lg.outline) { s.style.background = 'transparent'; s.style.borderColor = col; s.style.borderWidth = '2px'; }
    else s.style.background = col;
    return s;
  }
  const KIND = { polygon: 'Poligon', line: 'Garis', point: 'Titik', raster: 'Raster' };
  const fmtSize = (b) => (b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB');

  function buildTree(manifest) {
    const tree = $('#tree');
    tree.innerHTML = '';
    manifest.groups.forEach((gname) => {
      const items = S.meta.filter((m) => m.group === gname);
      if (!items.length) return;
      const det = document.createElement('details'); det.className = 'group'; det.dataset.group = gname;
      det.innerHTML = '<summary><svg class="chev" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg><span>' + esc(gname) + '</span><span class="gcount">' + items.length + '</span></summary>';
      items.forEach((m) => {
        const el = document.createElement('div'); el.className = 'layer'; el.dataset.id = m.id;
        const row = document.createElement('div'); row.className = 'lrow';
        const cb = document.createElement('input'); cb.type = 'checkbox'; cb.id = 'cb_' + m.id; cb.setAttribute('aria-label', m.title);
        const txt = document.createElement('div'); txt.className = 'ltext';
        txt.innerHTML = '<div class="ltitle">' + esc(m.title) + '</div><div class="lmeta">' + KIND[m.kind] +
          (m.type === 'vector' ? ' · ' + nf.format(m.count) + ' objek' : '') + ' · ' + fmtSize(m.size) + '</div>';
        const btns = document.createElement('div'); btns.className = 'lbtns';
        const zoom = document.createElement('button'); zoom.className = 'mini'; zoom.title = 'Zoom ke layer';
        zoom.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/></svg>';
        btns.appendChild(zoom);
        let lab = null;
        if (m.label) { lab = document.createElement('button'); lab.className = 'mini'; lab.textContent = 'Aa'; lab.title = 'Tampilkan label'; btns.appendChild(lab); }
        row.append(cb, symbolEl(m), txt, btns);
        const ctl = document.createElement('div'); ctl.className = 'lctl';
        ctl.innerHTML = '<span>Opasitas</span><input type="range" min="0.1" max="1" step="0.05" value="1" aria-label="Opasitas ' + esc(m.title) + '"><span class="ov">100%</span>';
        el.append(row, ctl);
        det.appendChild(el);
        const rec = S.rec[m.id] = { meta: m, el, cb, active: false, layer: null, data: null, opacity: 1, labelOn: false, labels: null };
        cb.addEventListener('change', () => activate(m.id, cb.checked));
        rec.labBtn = lab;
        txt.querySelector('.ltitle').addEventListener('click', () => cb.click());
        zoom.addEventListener('click', () => { if (!rec.active) activate(m.id, true, { zoom: true }); else map.fitBounds(m.bounds, { padding: [30, 30], maxZoom: 15 }); });
        if (lab) lab.addEventListener('click', async () => {
          rec.labelOn = !rec.labelOn; lab.classList.toggle('on', rec.labelOn);
          if (rec.labelOn && !rec.active) await activate(m.id, true); else setLabels(rec, rec.labelOn && rec.active);
        });
        const rng = ctl.querySelector('input'), ov = ctl.querySelector('.ov');
        rng.addEventListener('input', () => {
          rec.opacity = parseFloat(rng.value); ov.textContent = Math.round(rec.opacity * 100) + '%';
          if (!rec.layer) return;
          if (m.type === 'raster') rec.layer.setOpacity(rec.opacity); else rec.layer.setStyle(styleFn(m, rec.opacity));
        });
      });
      tree.appendChild(det);
    });
  }

  function refreshUI() {
    const act = Object.values(S.rec).filter((r) => r.active);
    $('#activeCount').textContent = act.length + ' layer aktif';
    document.querySelectorAll('.group').forEach((d) => {
      const n = d.querySelectorAll('.layer.active').length, c = d.querySelector('.gcount');
      c.textContent = n ? n + ' / ' + d.querySelectorAll('.layer').length : d.querySelectorAll('.layer').length;
      c.classList.toggle('on', n > 0);
    });
    buildLegend(act);
    writeHash();
  }

  /* ---------------------------------------------------------- legenda */
  function buildLegend(act) {
    const body = $('#legendBody');
    if (!act.length) { body.innerHTML = '<div class="empty">Belum ada layer aktif. Centang layer pada panel kiri untuk menampilkan legendanya.</div>'; return; }
    const sorted = act.slice().sort((a, b) => S.meta.indexOf(a.meta) - S.meta.indexOf(b.meta));
    body.innerHTML = sorted.map((r) => {
      const m = r.meta; let inner = '';
      if (m.type === 'raster') {
        const lg = m.legend;
        if (lg.gradient) {
          inner = '<div class="lg-grad" style="background:linear-gradient(90deg,' + lg.gradient.map((s) => s[1] + ' ' + (s[0] * 100) + '%').join(',') + ')"></div>' +
            '<div class="lg-scale"><span>' + nf.format(lg.min) + '</span><span>' + esc(lg.unit) + '</span><span>' + nf.format(lg.max) + '</span></div>';
        } else inner = lg.classes.map((c) => '<div class="lg-row"><i class="lg-sw" style="background:' + c.color + '"></i>' + esc(c.label) + '</div>').join('');
      } else {
        inner = m.legend.map((c) => {
          let sw;
          if (m.kind === 'line') sw = '<i class="lg-sw line" style="border-top-color:' + c.color + ';border-top-width:' + Math.min(c.w || m.style.w || 2, 5) + 'px;border-top-style:' + ((c.dash || m.style.dash) ? 'dashed' : 'solid') + '"></i>';
          else if (m.kind === 'point') sw = '<i class="lg-sw pt" style="background:' + c.color + '"></i>';
          else if (c.outline) sw = '<i class="lg-sw outline" style="border-color:' + c.color + '"></i>';
          else sw = '<i class="lg-sw" style="background:' + c.color + '"></i>';
          return '<div class="lg-row">' + sw + '<span>' + esc(c.label) + '</span></div>';
        }).join('');
      }
      return '<div class="lg-layer"><div class="lg-title">' + esc(m.title) + '</div>' + inner + '</div>';
    }).join('');
  }

  /* -------------------------------------------------------- UI umum */
  function setSide(open) { document.body.classList.toggle('side-closed', !open); setTimeout(() => map.invalidateSize(), 280); }
  $('#menuBtn').addEventListener('click', () => setSide(document.body.classList.contains('side-closed')));
  $('#legendBtn').addEventListener('click', () => $('#legendPanel').classList.toggle('hidden'));
  $('#aboutBtn').addEventListener('click', () => $('#aboutModal').classList.remove('hidden'));
  document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => $('#' + b.dataset.close).classList.add('hidden')));
  $('#aboutModal').addEventListener('click', (e) => { if (e.target.id === 'aboutModal') e.target.classList.add('hidden'); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { $('#aboutModal').classList.add('hidden'); } });
  $('#expandAll').addEventListener('click', () => document.querySelectorAll('.group').forEach((d) => (d.open = true)));
  $('#collapseAll').addEventListener('click', () => document.querySelectorAll('.group').forEach((d) => (d.open = false)));
  $('#clearAll').addEventListener('click', () => Object.keys(S.rec).forEach((id) => S.rec[id].active && activate(id, false)));

  $('#search').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll('.group').forEach((d) => {
      let any = false;
      d.querySelectorAll('.layer').forEach((el) => {
        const m = S.rec[el.dataset.id].meta, hit = !q || m.title.toLowerCase().includes(q) || m.id.toLowerCase().includes(q);
        el.style.display = hit ? '' : 'none'; any = any || hit;
      });
      d.style.display = any ? '' : 'none';
      if (q && any) d.open = true;
    });
  });

  /* ------------------------------------------------------ hash/state */
  let hashTimer = null;
  function writeHash() {
    clearTimeout(hashTimer);
    hashTimer = setTimeout(() => {
      const ids = Object.values(S.rec).filter((r) => r.active).map((r) => r.meta.id);
      try { history.replaceState(null, '', '#bm=' + bmCurrent + '&l=' + ids.join(',')); } catch (e) { /* abaikan */ }
    }, 150);
  }
  function readHash() {
    const o = {};
    location.hash.slice(1).split('&').forEach((kv) => { const i = kv.indexOf('='); if (i > 0) o[kv.slice(0, i)] = kv.slice(i + 1); });
    return o;
  }

  /* ------------------------------------------------------------ mulai */
  fetch('data/layers.json').then((r) => r.json()).then((manifest) => {
    S.meta = manifest.layers;
    buildTree(manifest);
    $('#totalInfo').textContent = S.meta.length + ' layer · ' + S.meta.filter((m) => m.type === 'vector').length + ' vektor, ' + S.meta.filter((m) => m.type === 'raster').length + ' raster';
    const h = readHash();
    setBasemap(h.bm || 'sat');
    const ids = h.l ? h.l.split(',').filter((id) => S.rec[id]) : DEFAULT_ON;
    ids.forEach((id) => { const d = S.rec[id].el.closest('details'); d.open = true; activate(id, true); });
    if (!h.l && S.rec.ADMINISTRASI_AR_DESAKEL) { const r = S.rec.ADMINISTRASI_AR_DESAKEL; r.labelOn = true; if (r.labBtn) r.labBtn.classList.add('on'); }
    if (window.innerWidth <= 820) setSide(false);
    refreshUI();
  }).catch((e) => {
    $('#tree').innerHTML = '<div class="empty" style="padding:14px">Gagal memuat data (' + esc(e.message) + '). Jalankan melalui server web (mis. GitHub Pages atau <code>python3 -m http.server</code> di folder <code>docs</code>).</div>';
  });
})();
