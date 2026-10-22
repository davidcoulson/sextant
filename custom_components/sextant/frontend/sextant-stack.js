/**
 * The Stack view: every floor drawn in one isometric picture, lowest first,
 * each at its elevation, with the things and proxies standing on them.
 *
 * The anchors (registration.py) already put every floor in one frame - the
 * house frame, in metres - and each floor has an elevation (set, or storeys
 * from its level). A parallel projection of that frame is affine on each
 * floor plane, so a floor's plan image goes down with one canvas transform
 * and keeps its detail; what must stay upright on the screen (dots, labels,
 * stems) is drawn in screen space at the projected point.
 *
 * Floors come through the same geometry as the Property view
 * (``sextant/property``): rooms, proxies and access points in house metres,
 * and each floor's plan->house transform for live positions.
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { MAP_FRAME_WIDTH, thingColor, thingRgba, staleness, shortAge } from "./sextant-map.js";
import { sharedStyles, thingName, uiButton, uiSegmented, mapUrlFor } from "./sextant-ui.js";

const DEG = Math.PI / 180;
const SLAB_M = 0.18;          // how thick a floor slab is drawn
const WALL_M = 0.45;          // how high the rooms' walls are drawn
// The light: from the plan's north-west, so a wall's shadow falls south-east
// (down and right on the plan) this many times the wall's height long, and a
// floor's shadow lands on the one below offset this fraction of the drop.
const SHADOW_DIR = [Math.SQRT1_2, Math.SQRT1_2];
const SHADOW_K = 0.8;
const DROP_K = 0.12;
// Faces lit from the upper left of the screen: how bright a face is from the
// direction its edge runs on the screen.
const LIGHT = [-0.6, -0.8];
const WALK_M = 1.0;           // a thing with no height set stands at chest height
const PROXY_M = 1.6;          // a proxy with no mount height set
const MIN_K = 4, MAX_K = 400; // screen px per house metre
// Spread: how far apart the floors sit, as a multiple of their real elevation
// difference. Real is 1; more pulls them apart so what is under a slab shows.
const SPREADS = { real: 1, apart: 1.8, exploded: 3 };

const OBJECT_URLS = new Map(); // authenticated image path -> object URL, per page load

class SextantStack extends LitElement {
  static properties = {
    hass: { attribute: false },
    data: { attribute: false },
    positions: { attribute: false },
    _geo: { state: true },
    _spread: { state: true },
    _plans: { state: true },     // whether the plan images are drawn
    _walls: { state: true },     // whether the rooms are extruded a little
    _focus: { state: true },     // the clicked thing's entity, or null
  };

  constructor() {
    super();
    this._geo = null;
    this._focus = null;
    try {
      this._spread = localStorage.getItem("sextant.stack.spread") || "apart";
      this._plans = localStorage.getItem("sextant.stack.plans") !== "off";
      this._walls = localStorage.getItem("sextant.stack.walls") !== "off";
    } catch { this._spread = "apart"; this._plans = true; this._walls = true; }
    if (!(this._spread in SPREADS)) this._spread = "apart";
    // The camera: px per metre, where the house origin lands on the screen,
    // the turn about the vertical, and the tilt (0 is a plan, 90 a side view).
    this._view = { k: 40, ox: 0, oy: 0, yaw: 45, pitch: 55 };
    this._fitted = false;
    this._images = new Map();  // floor name -> Image (loaded or loading)
    this._pointers = new Map();
    this._hits = [];           // what was drawn where, for clicks: [{x, y, r, ent}]
  }

  connectedCallback() {
    super.connectedCallback();
    if (this._canvas && this._resize) this._resize.observe(this._canvas);
    this._load();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._resize?.disconnect();
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
  }

  updated(changed) {
    if (changed.has("data") && changed.get("data") && changed.get("data") !== this.data) this._load();
    const dark = !!this.hass?.themes?.darkMode, themed = dark !== this._dark;
    this._dark = dark;
    if (themed || ["positions", "data", "_geo", "_spread", "_plans", "_walls", "_focus"].some((k) => changed.has(k))) this._draw();
  }

  firstUpdated() {
    this._canvas = this.renderRoot.querySelector("canvas");
    this._resize = new ResizeObserver(() => { if (!this._fitted) this._fit(); else this._draw(); });
    this._resize.observe(this._canvas);
  }

  async _load() {
    const geo = await this.hass?.callWS({ type: "sextant/property" }).catch(() => null);
    if (!geo) return;
    this._geo = geo;
    for (const f of geo.floors || []) this._image(f.name);
    if (!this._fitted) this._fit();
    this._draw();
  }

  /** The floor's plan image, fetched with the user's session once and kept. */
  _image(floorName) {
    const url = mapUrlFor(floorName, this.data?.maps);
    if (!url) return null;
    let img = this._images.get(floorName);
    if (img && img.url === url) return img.complete && img.naturalWidth ? img : null;
    img = new Image();
    img.url = url;
    img.onload = () => { this._planCache?.delete(floorName); this._draw(); };
    this._images.set(floorName, img);
    const cached = OBJECT_URLS.get(url);
    if (cached) { img.src = cached; return null; }
    this.hass.fetchWithAuth(url).then(async (r) => {
      if (!r.ok) return;
      const o = URL.createObjectURL(await r.blob());
      OBJECT_URLS.set(url, o);
      img.src = o;
    }).catch(() => { /* no plan: the rooms still draw */ });
    return null;
  }

  /** The plan inverted for a dark page (see SextantMap._darkPlan). */
  _darkPlan(floorName, img) {
    this._planCache ??= new Map();
    const hit = this._planCache.get(floorName);
    if (hit?.image === img) return hit.canvas;
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const cx = c.getContext("2d");
    cx.filter = "invert(1) hue-rotate(180deg) brightness(0.62)";
    cx.drawImage(img, 0, 0);
    this._planCache.set(floorName, { image: img, canvas: c });
    return c;
  }

  // --- projection ------------------------------------------------------------------

  /** The floor's height in the picture: its elevation, spread out. */
  _z(floor) { return (floor.elevation || 0) * SPREADS[this._spread]; }

  /** A house point (metres, y down the plan, z up) on the screen. */
  _project(hx, hy, z = 0) {
    const v = this._view, a = v.yaw * DEG, ca = Math.cos(a), sa = Math.sin(a);
    const rx = hx * ca - hy * sa, ry = hx * sa + hy * ca;
    return [v.ox + rx * v.k, v.oy + (ry * Math.cos(v.pitch * DEG) - z * Math.sin(v.pitch * DEG)) * v.k];
  }

  /** The house point on a floor's plane under a screen point. */
  _unproject(sx, sy, z = 0) {
    const v = this._view, a = v.yaw * DEG, ca = Math.cos(a), sa = Math.sin(a);
    const rx = (sx - v.ox) / v.k, ry = ((sy - v.oy) / v.k + z * Math.sin(v.pitch * DEG)) / Math.cos(v.pitch * DEG);
    return [rx * ca + ry * sa, -rx * sa + ry * ca];
  }

  /** Plan pixels of a floor to the house frame, through its registration. */
  _house(frame, px, py) {
    const lx = px / frame.scale, ly = py / frame.scale;
    return [frame.cos * lx - frame.sin * ly + frame.tx, frame.sin * lx + frame.cos * ly + frame.ty];
  }

  /** The plan's frame in pixels (what the layout's coordinates are in): the
   * image scaled to MAP_FRAME_WIDTH wide, as the flat map draws it. */
  _planSize(floorName) {
    const img = this._images.get(floorName);
    if (img?.naturalWidth) return [MAP_FRAME_WIDTH, MAP_FRAME_WIDTH * img.naturalHeight / img.naturalWidth];
    return null;
  }

  /** The plan's edge in house metres, or null before the image has loaded. */
  _outline(f, frame) {
    const size = this._planSize(f.name);
    return size ? [[0, 0], [size[0], 0], size, [0, size[1]]].map(([x, y]) => this._house(frame, x, y)) : null;
  }

  // --- drawing ----------------------------------------------------------------------

  _draw() {
    if (!this._canvas || this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this._paint(); });
  }

  _paint() {
    const cv = this._canvas, dpr = window.devicePixelRatio || 1, rect = cv.getBoundingClientRect();
    const W = rect.width, H = rect.height;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const dark = this._dark;
    ctx.fillStyle = dark ? "#1b1f24" : "#e9ecef";
    ctx.fillRect(0, 0, W, H);
    this._hits = [];
    const geo = this._geo;
    if (!geo) return;
    const frames = geo.frames || {}, floors = geo.floors || [];
    const line = dark ? "rgba(232,234,237," : "rgba(27,31,36,";

    for (const f of floors) {
      const frame = frames[f.name];
      if (!frame) continue;
      const z = this._z(f);
      const above = floors.find((g) => g !== f && frames[g.name] && this._z(g) > z);
      this._paintFloor(ctx, f, frame, z, W, H, dpr, dark, line, floors.length === 1, above ? { polys: this._footprint(above, frames[above.name]), dz: this._z(above) - z } : null);
      // Proxies and access points stand on the floor, on a stem.
      const heights = this._proxyHeights(f.name);
      for (const p of f.proxies) {
        const h = heights.get(p.slug) ?? PROXY_M;
        this._stem(ctx, p.x, p.y, z, h, line);
        const [sx, sy] = this._project(p.x, p.y, z + h);
        ctx.save(); ctx.translate(sx, sy); ctx.rotate(Math.PI / 4);
        ctx.fillStyle = p.outdoor ? "#1f7a8c" : "#2a9d8f"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.2;
        ctx.fillRect(-4, -4, 8, 8); ctx.strokeRect(-4, -4, 8, 8); ctx.restore();
      }
      for (const a of f.access_points) {
        const [sx, sy] = this._project(a.x, a.y, z + 0.05);
        ctx.beginPath(); ctx.arc(sx, sy, 4, 0, Math.PI * 2);
        ctx.fillStyle = "#4f5bd5"; ctx.fill(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1; ctx.stroke();
      }
    }

    // Every thing with a fix, on whichever floor, over all the slabs: a
    // person downstairs is not hidden by the floor above.
    const byName = new Map(floors.map((f) => [f.name, f]));
    const custom = this.data?.layout?.thing_colors || {}, heights = this.data?.layout?.thing_heights || {};
    const labels = [];
    const rows = (this.positions?.positions || []).filter((t) => frames[t.floor] && byName.has(t.floor) && Array.isArray(t.cords));
    // Far things first, so a near one is drawn over them.
    const placed = rows.map((t) => {
      const f = byName.get(t.floor), fr = frames[t.floor], z = this._z(f);
      const [hx, hy] = this._house(fr, t.cords[0], t.cords[1]);
      const h = Number.isFinite(heights[t.ent]) ? Math.max(0.1, heights[t.ent]) : WALK_M;
      const [sx, sy] = this._project(hx, hy, z + h);
      return { t, hx, hy, z, h, sx, sy };
    }).sort((a, b) => a.sy - b.sy);
    for (const { t, hx, hy, z, h, sx, sy } of placed) {
      const focused = this._focus && t.ent === this._focus;
      const { age, ghost } = staleness(t, 120);
      ctx.save();
      if (this._focus && !focused) ctx.globalAlpha = 0.3;
      if (ghost) ctx.globalAlpha *= 0.45;
      const color = thingColor(t.ent, custom);
      // The stem and the shadow on the floor say where on the plan it is;
      // the dot floats at its height.
      const [fx, fy] = this._project(hx, hy, z);
      ctx.beginPath(); ctx.ellipse(fx, fy, 6, 6 * Math.cos(this._view.pitch * DEG), 0, 0, Math.PI * 2);
      ctx.fillStyle = thingRgba(t.ent, custom, 0.35); ctx.fill();
      ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(sx, sy);
      ctx.strokeStyle = thingRgba(t.ent, custom, 0.7); ctx.lineWidth = 1.5; ctx.stroke();
      const r = focused ? 10 : 7;
      if (!ghost) {
        ctx.beginPath(); ctx.arc(sx, sy, r * 1.8, 0, Math.PI * 2);
        ctx.fillStyle = thingRgba(t.ent, custom, 0.08 + 0.22 * (t.conf ?? 0.5)); ctx.fill();
      }
      ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
      if (ghost) ctx.setLineDash([4, 3]);
      ctx.strokeStyle = focused ? "#ffd166" : "#fff"; ctx.lineWidth = 2; ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
      const name = thingName(this.data, t.ent);
      labels.push([ghost ? `${name} · ${shortAge(age)} ago` : name, sx, sy - r - 9, focused]);
      this._hits.push({ x: sx, y: sy, r: r + 4, ent: t.ent });
    }
    ctx.font = "600 11px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const taken = [];
    for (const [text, x, y, focused] of labels) {
      const w = ctx.measureText(text).width + 8;
      const box = [x - w / 2, y - 8, x + w / 2, y + 8];
      if (!focused && taken.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
      taken.push(box);
      ctx.globalAlpha = this._focus && !focused ? 0.4 : 1;
      ctx.fillStyle = dark ? "rgba(20,24,30,0.8)" : "rgba(255,255,255,0.85)";
      ctx.fillRect(x - w / 2, y - 8, w, 16);
      ctx.fillStyle = dark ? "#e8eaed" : "#1b1f24"; ctx.fillText(text, x, y);
    }
    ctx.globalAlpha = 1;
  }

  /** One floor: its slab (the rooms' footprint, or the plan's edge when no
   * room is drawn), the plan image clipped to that footprint, the room
   * outlines (and walls), with the no-go areas punched out. Drawn on an
   * offscreen canvas so the punching takes nothing from the floors below. */
  _paintFloor(ctx, f, frame, z, W, H, dpr, dark, line, lone, above) {
    const polys = this._footprint(f, frame);
    if (!polys.length) return;
    const off = this._off ??= document.createElement("canvas");
    if (off.width !== Math.round(W * dpr) || off.height !== Math.round(H * dpr)) { off.width = Math.round(W * dpr); off.height = Math.round(H * dpr); }
    const o = off.getContext("2d");
    o.setTransform(dpr, 0, 0, dpr, 0, 0);
    o.clearRect(0, 0, W, H);
    const path = (pts) => { o.beginPath(); pts.forEach((p, i) => (i ? o.lineTo(p[0], p[1]) : o.moveTo(p[0], p[1]))); o.closePath(); };
    const union = (polys, zz) => {
      o.beginPath();
      for (const poly of polys) poly.forEach(([x, y], i) => { const p = this._project(x, y, zz); i ? o.lineTo(p[0], p[1]) : o.moveTo(p[0], p[1]); });
      o.closePath();
    };
    // ``paint`` gives a face's fill from how lit it is (0 dark .. 1 bright).
    const sides = (polys, z0, z1, paint, stroke) => {
      for (const poly of polys) for (let i = 0; i < poly.length; i++) {
        const a = poly[i], b = poly[(i + 1) % poly.length];
        const p = this._project(a[0], a[1], z0), q = this._project(b[0], b[1], z0);
        path([p, q, this._project(b[0], b[1], z1), this._project(a[0], a[1], z1)]);
        if (paint) { o.fillStyle = paint(this._lit(p, q)); }
        o.fill();
        if (stroke) { o.strokeStyle = stroke; o.stroke(); }
      }
    };
    // The slab: its sides, then its top over them (a side between two rooms
    // is under the nearer room's top, so only the outer edge shows).
    o.lineWidth = 0.8;
    sides(polys, z, z - SLAB_M, (lit) => (dark ? `hsl(215, 12%, ${22 + 16 * lit}%)` : `hsl(215, 10%, ${56 + 18 * lit}%)`), line + "0.3)");
    union(polys, z);
    // The top is a mid grey on a dark page, not black: a shadow has to show on it.
    o.fillStyle = dark ? "hsl(215, 10%, 34%)" : "rgba(255,255,255,0.96)"; o.fill();
    const img = this._plans ? this._image(f.name) : null;
    const size = img ? this._planSize(f.name) : null;
    if (img && size) {
      // Plan px -> screen is affine on this floor: three points fix it.
      o.save();
      union(polys, z); o.clip();
      const [e, g] = this._project(...this._house(frame, 0, 0), z);
      const [ax, ay] = this._project(...this._house(frame, 1, 0), z);
      const [cx, cy] = this._project(...this._house(frame, 0, 1), z);
      o.transform(ax - e, ay - g, cx - e, cy - g, e, g);
      // On a dark page the inverted plan is light lines on black: screened
      // onto the grey top, the lines lighten it and the black leaves it be.
      if (dark) { o.globalCompositeOperation = "screen"; o.globalAlpha = 0.8; } else { o.globalAlpha = 0.9; }
      o.drawImage(dark ? this._darkPlan(f.name, img) : img, 0, 0, size[0], size[1]);
      o.restore();
    }
    // Shadows on this floor: a soft one from the floor above, and, with walls
    // up, a sharp one along every wall. Both stay on the slab (clipped), and
    // each is one union fill so overlaps do not double up.
    o.save();
    union(polys, z); o.clip();
    if (above?.polys.length) {
      const off = above.dz * DROP_K;
      // Drawn far off the canvas with its shadow brought back: a blurred
      // shadow of the shape without the shape itself.
      o.save();
      o.shadowColor = dark ? "rgba(0,0,0,0.5)" : "rgba(0,0,0,0.28)"; o.shadowBlur = 18;
      o.shadowOffsetX = 4000 * dpr; o.shadowOffsetY = 0;
      o.translate(-4000, 0);
      o.beginPath();
      for (const poly of above.polys) poly.forEach(([x, y], i) => { const p = this._project(x + off * SHADOW_DIR[0], y + off * SHADOW_DIR[1], z); i ? o.lineTo(p[0], p[1]) : o.moveTo(p[0], p[1]); });
      o.closePath(); o.fillStyle = "#000"; o.fill();
      o.restore();
    }
    if (this._walls) {
      const len = WALL_M * SHADOW_K, dx = len * SHADOW_DIR[0], dy = len * SHADOW_DIR[1];
      o.beginPath();
      for (const r of f.rooms) for (let i = 0; i < r.points.length; i++) {
        const a = r.points[i], b = r.points[(i + 1) % r.points.length];
        [this._project(a[0], a[1], z), this._project(b[0], b[1], z), this._project(b[0] + dx, b[1] + dy, z), this._project(a[0] + dx, a[1] + dy, z)]
          .forEach((p, j) => (j ? o.lineTo(p[0], p[1]) : o.moveTo(p[0], p[1])));
        o.closePath();
      }
      o.fillStyle = dark ? "rgba(0,0,0,0.42)" : "rgba(0,0,0,0.22)"; o.fill();
    }
    o.restore();
    union(polys, z); o.strokeStyle = line + "0.5)"; o.lineWidth = 1; o.stroke();
    for (const r of f.rooms) {
      path(r.points.map(([x, y]) => this._project(x, y, z)));
      if (!img) { o.fillStyle = "rgba(79, 91, 213, 0.14)"; o.fill(); }
      o.strokeStyle = "rgba(79, 91, 213, 0.75)"; o.lineWidth = 1.2; o.stroke();
    }
    if (this._walls) {
      // A short wall along every edge, lit from the upper left of the screen,
      // so the rooms read as rooms and not lines on a slab.
      o.lineWidth = 0.7;
      sides(f.rooms.map((r) => r.points), z + WALL_M, z, (lit) => (dark ? `hsla(232, 18%, ${26 + 24 * lit}%, 0.75)` : `hsla(232, 25%, ${66 + 26 * lit}%, 0.8)`), "rgba(79, 91, 213, 0.45)");
    }
    // The no-go areas (a void over the hall, a stairwell) are cut right
    // through the slab.
    const holes = (f.no_go || []).map((n) => n.points);
    if (holes.length) {
      o.globalCompositeOperation = "destination-out";
      o.fillStyle = "#000";
      sides(holes, z, z - SLAB_M);
      union(holes, z); o.fill();
      o.globalCompositeOperation = "source-over";
      // The hole's edge, where it runs through the slab (a no-go drawn outside every room cuts nothing and shows nothing).
      o.save(); union(polys, z); o.clip();
      for (const h of holes) { path(h.map(([x, y]) => this._project(x, y, z))); o.strokeStyle = line + "0.3)"; o.lineWidth = 0.8; o.setLineDash([3, 3]); o.stroke(); o.setLineDash([]); }
      o.restore();
    }
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(off, 0, 0); ctx.restore();
    // The floor's name on its near corner.
    const corner = polys.flat().map(([x, y]) => this._project(x, y, z)).reduce((a, b) => (b[1] > a[1] ? b : a));
    ctx.font = "600 12px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillStyle = line + "0.85)";
    ctx.fillText(f.name + (f.registered || lone ? "" : " (not lined up)"), corner[0] + 6, corner[1] + 4);
  }

  /** How lit a vertical face along the screen segment p-q is, 0..1: faces
   * square to the light are bright, those along it dark. */
  _lit(p, q) {
    const dx = q[0] - p[0], dy = q[1] - p[1], n = Math.hypot(dx, dy) || 1;
    return Math.abs((-dy / n) * LIGHT[0] + (dx / n) * LIGHT[1]);
  }

  /** The floor's footprint in house metres: its rooms, or, with none drawn,
   * the plan's edge. */
  _footprint(f, frame) {
    if (f.rooms.length) return f.rooms.map((r) => r.points);
    const outline = this._outline(f, frame);
    return outline ? [outline] : [];
  }

  _stem(ctx, x, y, z, h, line) {
    const [fx, fy] = this._project(x, y, z), [sx, sy] = this._project(x, y, z + h);
    ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(sx, sy);
    ctx.strokeStyle = line + "0.35)"; ctx.lineWidth = 1; ctx.stroke();
  }

  /** Proxy mount heights by entity id, from the layout's receivers. */
  _proxyHeights(floorName) {
    const f = (this.data?.layout?.floor || []).find((x) => x.name === floorName);
    const out = new Map();
    for (const r of f?.receivers || []) if (Number.isFinite(r.height)) out.set(r.entity_id, r.height);
    return out;
  }

  // --- interaction --------------------------------------------------------------------

  _local(e) { const r = this._canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }

  _down(e) {
    try { this._canvas.setPointerCapture?.(e.pointerId); } catch { /* ignore */ }
    this._pointers.set(e.pointerId, this._local(e));
    this._startGesture();
  }

  _startGesture() {
    const pts = [...this._pointers.values()];
    if (!pts.length) { this._drag = null; return; }
    if (pts.length >= 2) {
      const [a, b] = pts;
      this._drag = { pinch: true, view: { ...this._view }, mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, dist: Math.hypot(a.x - b.x, a.y - b.y) };
      return;
    }
    this._drag = { start: pts[0], view: { ...this._view }, moved: false };
  }

  _move(e) {
    if (!this._pointers.has(e.pointerId) || !this._drag) return;
    const p = this._local(e), d = this._drag;
    this._pointers.set(e.pointerId, p);
    if (d.pinch) {
      const [a, b] = [...this._pointers.values()];
      if (!b) return;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, dist = Math.hypot(a.x - b.x, a.y - b.y);
      const k = Math.max(MIN_K, Math.min(MAX_K, d.view.k * dist / Math.max(d.dist, 1))), s = k / d.view.k;
      this._view = { ...d.view, k, ox: mid.x - (d.mid.x - d.view.ox) * s, oy: mid.y - (d.mid.y - d.view.oy) * s };
      this._draw();
      return;
    }
    const dx = p.x - d.start.x, dy = p.y - d.start.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (e.shiftKey || e.buttons === 2) {
      // Shift-drag (or the right button) turns and tilts instead of panning.
      this._view = this._about(d.view, { yaw: d.view.yaw + dx * 0.4, pitch: Math.max(10, Math.min(85, d.view.pitch - dy * 0.3)) });
    } else {
      this._view = { ...this._view, ox: d.view.ox + dx, oy: d.view.oy + dy };
    }
    this._draw();
  }

  _up(e) {
    const d = this._drag;
    this._pointers.delete(e.pointerId);
    if (d && !d.pinch && !d.moved) this._click(this._local(e));
    this._startGesture();
  }

  _click(p) {
    // The nearest dot under the pointer; the one on top was drawn last.
    const hit = [...this._hits].reverse().find((h) => Math.hypot(h.x - p.x, h.y - p.y) <= h.r);
    this._focus = hit && hit.ent !== this._focus ? hit.ent : null;
  }

  _wheel(e) {
    e.preventDefault();
    const p = this._local(e);
    this._zoomAt(p, this._view.k * Math.exp(-e.deltaY * 0.002));
  }

  _zoomAt(p, k) {
    const v = this._view, k2 = Math.max(MIN_K, Math.min(MAX_K, k)), s = k2 / v.k;
    this._view = { ...v, k: k2, ox: p.x - (p.x - v.ox) * s, oy: p.y - (p.y - v.oy) * s };
    this._draw();
  }

  _zoomBy(f) {
    const r = this._canvas.getBoundingClientRect();
    this._zoomAt({ x: r.width / 2, y: r.height / 2 }, this._view.k * f);
  }

  _turn(deg) { this._view = this._about(this._view, { yaw: this._view.yaw + deg }); this._draw(); }
  _tilt(deg) { this._view = this._about(this._view, { pitch: Math.max(10, Math.min(85, this._view.pitch + deg)) }); this._draw(); }

  /** ``view`` with ``change`` (a yaw and/or pitch) applied about the middle
   * of the house: the view turns, then moves so the middle stays where it was
   * on the screen, rather than swinging about the plan's corner. */
  _about(view, change) {
    const [mx, my, mz] = this._middle();
    const saved = this._view;
    this._view = view;
    const [bx, by] = this._project(mx, my, mz);
    this._view = { ...view, ...change };
    const [ax, ay] = this._project(mx, my, mz);
    const out = { ...this._view, ox: this._view.ox + bx - ax, oy: this._view.oy + by - ay };
    this._view = saved;
    return out;
  }

  /** The middle of the house in house metres, halfway up the stack. */
  _middle() {
    const geo = this._geo, frames = geo?.frames || {};
    const pts = [], zs = [];
    for (const f of geo?.floors || []) {
      const frame = frames[f.name];
      if (!frame) continue;
      zs.push(this._z(f));
      for (const [x, y] of this._footprint(f, frame).flat()) pts.push([x, y]);
    }
    if (!pts.length) return [0, 0, 0];
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2, (Math.min(...zs) + Math.max(...zs)) / 2];
  }

  /** The view that shows every floor: the projected corners fill the page. */
  _fit() {
    const geo = this._geo, rect = this._canvas?.getBoundingClientRect();
    if (!geo || !rect?.width) return;
    const frames = geo.frames || {};
    const pts = [];
    for (const f of geo.floors || []) {
      const frame = frames[f.name];
      if (!frame) continue;
      const z = this._z(f);
      for (const [x, y] of this._footprint(f, frame).flat()) pts.push([x, y, z - SLAB_M], [x, y, z + 2]);
    }
    if (!pts.length) return;
    const v = { ...this._view, k: 1, ox: 0, oy: 0 };
    const saved = this._view; this._view = v;
    const ss = pts.map(([x, y, z]) => this._project(x, y, z));
    this._view = saved;
    const xs = ss.map((s) => s[0]), ys = ss.map((s) => s[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const k = Math.max(MIN_K, Math.min(MAX_K, Math.min((rect.width * 0.86) / Math.max(x1 - x0, 1), (rect.height * 0.8) / Math.max(y1 - y0, 1))));
    this._view = { ...this._view, k, ox: rect.width / 2 - ((x0 + x1) / 2) * k, oy: rect.height / 2 - ((y0 + y1) / 2) * k };
    this._fitted = true;
    this._draw();
  }

  _setSpread(v) {
    this._spread = v;
    try { localStorage.setItem("sextant.stack.spread", v); } catch { /* ignore */ }
    this._fit();
  }

  _toggle(key) {
    this[key] = !this[key];
    try { localStorage.setItem(`sextant.stack.${key.slice(1)}`, this[key] ? "on" : "off"); } catch { /* ignore */ }
  }

  render() {
    const geo = this._geo;
    const unregistered = (geo?.floors || []).filter((f) => !f.registered).map((f) => f.name);
    return html`
      <div class="stage">
        <canvas @pointerdown=${(e) => this._down(e)} @pointermove=${(e) => this._move(e)} @pointerup=${(e) => this._up(e)}
                @pointercancel=${(e) => this._up(e)} @wheel=${(e) => this._wheel(e)} @contextmenu=${(e) => e.preventDefault()}></canvas>
        <div class="bar">
          ${uiSegmented({ label: "Floors", value: this._spread, options: [
            { value: "real", label: "Real", title: "Floors at their real elevations" },
            { value: "apart", label: "Apart", title: "Floors pulled a little apart, so what is under a slab shows" },
            { value: "exploded", label: "Exploded", title: "Floors well apart" }],
            onChange: (v) => this._setSpread(v) })}
          ${uiButton({ label: "Plans", kind: this._plans ? "primary" : "outline", icon: "mdi:floor-plan", onClick: () => this._toggle("_plans") })}
          ${uiButton({ label: "Walls", kind: this._walls ? "primary" : "outline", icon: "mdi:wall", onClick: () => this._toggle("_walls") })}
        </div>
        ${!geo ? html`<div class="note">Loading…</div>`
          : !(geo.floors || []).length ? html`<div class="note">No floors yet: draw one in Edit.</div>`
          : unregistered.length && (geo.floors || []).length > 1 ? html`<div class="note">${unregistered.join(", ")} ${unregistered.length === 1 ? "is" : "are"} not lined up with the other floors (Edit → Anchor), so ${unregistered.length === 1 ? "it is" : "they are"} drawn on ${unregistered.length === 1 ? "its" : "their"} own frame.</div>`
          : nothing}
        <div class="hint">Drag to move · shift-drag to turn and tilt · wheel to zoom · click a thing to pick it out</div>
        <div class="zoom">
          <button title="Turn left" aria-label="Turn left" @click=${() => this._turn(-15)}><ha-icon icon="mdi:rotate-left"></ha-icon></button>
          <button title="Turn right" aria-label="Turn right" @click=${() => this._turn(15)}><ha-icon icon="mdi:rotate-right"></ha-icon></button>
          <button title="Tilt up (more plan)" aria-label="Tilt up" @click=${() => this._tilt(-10)}><ha-icon icon="mdi:angle-acute"></ha-icon></button>
          <button title="Tilt down (more side)" aria-label="Tilt down" @click=${() => this._tilt(10)}><ha-icon icon="mdi:angle-obtuse"></ha-icon></button>
          <button title="Show the whole house" aria-label="Show the whole house" @click=${() => this._fit()}><ha-icon icon="mdi:fit-to-page-outline"></ha-icon></button>
          <button title="Zoom in" aria-label="Zoom in" @click=${() => this._zoomBy(1.4)}><ha-icon icon="mdi:plus"></ha-icon></button>
          <button title="Zoom out" aria-label="Zoom out" @click=${() => this._zoomBy(1 / 1.4)}><ha-icon icon="mdi:minus"></ha-icon></button>
        </div>
      </div>`;
  }

  static styles = [sharedStyles, css`
    :host { display: block; height: 100%; }
    .stage { position: relative; width: 100%; height: 100%; min-height: 360px; overflow: hidden; }
    canvas { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; cursor: grab; }
    .bar { position: absolute; left: 10px; top: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 4px 6px; border-radius: 12px;
      background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); }
    .note { position: absolute; left: 10px; top: 64px; max-width: min(380px, calc(100% - 20px)); padding: 8px 10px; border-radius: 10px;
      background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); font-size: 13px; }
    .hint { position: absolute; left: 10px; bottom: 8px; font-size: 11px; color: var(--secondary-text-color); pointer-events: none; }
    .zoom { position: absolute; right: 10px; bottom: 26px; display: flex; gap: 2px; padding: 4px; border-radius: 12px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); }
    .zoom button { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent; color: var(--primary-text-color); cursor: pointer; }
    @media (max-width: 600px) { .hint { display: none; } }
  `];
}

customElements.define("sextant-stack", SextantStack);
