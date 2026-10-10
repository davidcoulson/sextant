/**
 * The Property view: the whole house on a street or aerial map.
 *
 * Every floor is already in one frame - the house frame, in metres - through
 * the anchors (registration.py). This page puts that frame on the earth at the
 * site the user lines up (``layout.site``: a latitude and longitude for the
 * frame's origin and a rotation), draws every floor's rooms over the map, and
 * brings each thing's live position in through its floor's transform, so the
 * whole household - and anything outdoors - is on one picture.
 *
 * Tiles: the street map comes through Home Assistant's own map_tiles proxy
 * (2026.10+), so nothing leaves the house but what Home Assistant fetches.
 * The aerial view asks Esri's World Imagery directly from the browser, which
 * tells Esri which tiles are being looked at; it is off until chosen.
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { thingColor } from "./sextant-map.js";
import { sharedStyles, toast, callWS, thingName, uiButton, uiSegmented } from "./sextant-ui.js";
import { TILE, project, unproject, houseToWorld } from "./sextant-geo.js";

const MIN_ZOOM = 15, MAX_ZOOM = 22;
// Tiles exist to this zoom; past it the last level is drawn larger.
const TILE_MAX = { street: 19, aerial: 19 };
const AERIAL_URL = (z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;
const ATTRIBUTION = {
  street: "© OpenStreetMap contributors",
  aerial: "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
};
class SextantProperty extends LitElement {
  static properties = {
    hass: { attribute: false },
    data: { attribute: false },
    positions: { attribute: false },
    _geo: { state: true },
    _site: { state: true },       // the site as drawn: the saved one, or the one being lined up
    _adjust: { state: true },     // lining up: the drag moves the house, not the map
    _source: { state: true },
    _busy: { state: true },
  };

  constructor() {
    super();
    this._geo = null;
    this._site = null;
    this._adjust = false;
    this._busy = false;
    try { this._source = localStorage.getItem("sextant.property.source") === "aerial" ? "aerial" : "street"; } catch { this._source = "street"; }
    this._view = null;        // {lat, lon, zoom}
    this._tiles = new Map();  // url -> Image
    this._token = null;
    this._pointers = new Map();
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
    this._tokenTimer = setInterval(() => { if (this._source === "street") this._loadToken(); }, 4 * 60 * 1000);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._tokenTimer);
    this._resize?.disconnect();
  }

  updated(changed) {
    if (changed.has("data") && changed.get("data") && changed.get("data") !== this.data) this._load();
    this._draw();
  }

  firstUpdated() {
    this._canvas = this.renderRoot.querySelector("canvas");
    this._resize = new ResizeObserver(() => this._draw());
    this._resize.observe(this._canvas);
  }

  async _load() {
    const geo = await this.hass?.callWS({ type: "sextant/property" }).catch(() => null);
    if (!geo) return;
    this._geo = geo;
    if (!this._adjust) this._site = geo.site || (Number.isFinite(geo.home?.lat) ? { lat: geo.home.lat, lon: geo.home.lon, rotation: 0 } : null);
    if (!this._view && this._site) this._view = { lat: this._site.lat, lon: this._site.lon, zoom: 19 };
    if (this._source === "street") await this._loadToken();
    this._draw();
  }

  async _loadToken() {
    if (!this._geo?.map_tiles) return;
    const r = await this.hass?.callWS({ type: "map_tiles/access_token" }).catch(() => null);
    if (r?.token && r.token !== this._token) { this._token = r.token; this._tiles.clear(); this._draw(); }
  }

  _tileUrl(z, x, y) {
    if (this._source === "aerial") return AERIAL_URL(z, x, y);
    return this._token ? `/api/map_tiles/raster/${z}/${x}/${y}.png?token=${this._token}` : null;
  }

  _tile(z, x, y) {
    const n = 2 ** z;
    if (y < 0 || y >= n) return null;
    const url = this._tileUrl(z, ((x % n) + n) % n, y);
    if (!url) return null;
    let img = this._tiles.get(url);
    if (!img) {
      img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => this._draw();
      img.onerror = () => { img.failed = true; };
      img.src = url;
      if (this._tiles.size > 600) this._tiles.clear();
      this._tiles.set(url, img);
    }
    return img.complete && !img.failed && img.naturalWidth ? img : null;
  }

  // --- drawing -------------------------------------------------------------------

  _draw() {
    const cv = this._canvas;
    if (!cv || !this._view) return;
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this._paint(); });
  }

  _paint() {
    const cv = this._canvas, dpr = window.devicePixelRatio || 1, rect = cv.getBoundingClientRect();
    const W = rect.width, H = rect.height;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const dark = this.hass?.themes?.darkMode;
    ctx.fillStyle = dark ? "#1b1f24" : "#e9ecef";
    ctx.fillRect(0, 0, W, H);
    const v = this._view, zt = Math.min(Math.floor(v.zoom), TILE_MAX[this._source]), k = 2 ** (v.zoom - zt);
    const c = project(v.lat, v.lon, zt);
    const x0 = Math.floor((c.x - W / 2 / k) / TILE), x1 = Math.floor((c.x + W / 2 / k) / TILE);
    const y0 = Math.floor((c.y - H / 2 / k) / TILE), y1 = Math.floor((c.y + H / 2 / k) / TILE);
    ctx.imageSmoothingEnabled = true;
    for (let tx = x0; tx <= x1; tx++) for (let ty = y0; ty <= y1; ty++) {
      const img = this._tile(zt, tx, ty);
      if (img) ctx.drawImage(img, (tx * TILE - c.x) * k + W / 2, (ty * TILE - c.y) * k + H / 2, TILE * k + 0.5, TILE * k + 0.5);
    }
    if (!this._geo || !this._site) return;
    const cz = project(v.lat, v.lon, v.zoom);
    const toScreen = (hx, hy) => { const w = houseToWorld(hx, hy, this._site, v.zoom); return [w.x - cz.x + W / 2, w.y - cz.y + H / 2]; };
    const floors = this._geo.floors || [];
    // The ground floor (the first at or above level 0) is the footprint; the
    // others are outlines over it.
    const base = floors.find((f) => (f.level ?? 0) >= 0) || floors[0];
    for (const f of floors) {
      const isBase = f === base;
      for (const r of f.rooms) {
        ctx.beginPath();
        r.points.forEach(([x, y], i) => { const [sx, sy] = toScreen(x, y); i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy); });
        ctx.closePath();
        if (isBase) { ctx.fillStyle = "rgba(79, 91, 213, 0.18)"; ctx.fill(); }
        ctx.setLineDash(isBase ? [] : [5, 4]);
        ctx.strokeStyle = isBase ? "rgba(79, 91, 213, 0.9)" : "rgba(79, 91, 213, 0.45)";
        ctx.lineWidth = isBase ? 1.6 : 1;
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);
    // Outdoor proxies and placed access points: what is outside the walls.
    for (const f of floors) {
      for (const p of f.proxies) {
        if (!p.outdoor) continue;
        const [sx, sy] = toScreen(p.x, p.y);
        ctx.save(); ctx.translate(sx, sy); ctx.rotate(Math.PI / 4);
        ctx.fillStyle = "#1f7a8c"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
        ctx.fillRect(-5, -5, 10, 10); ctx.strokeRect(-5, -5, 10, 10); ctx.restore();
      }
      for (const a of f.access_points) {
        const [sx, sy] = toScreen(a.x, a.y);
        ctx.beginPath(); ctx.arc(sx, sy, 6, 0, Math.PI * 2);
        ctx.fillStyle = "#4f5bd5"; ctx.fill(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
      }
    }
    // Every thing with a fix, on whichever floor, through that floor's frame.
    const frames = this._geo.frames || {}, custom = this.data?.layout?.thing_colors || {};
    const labels = [];
    for (const t of this.positions?.positions || []) {
      const fr = frames[t.floor];
      if (!fr || !Array.isArray(t.cords)) continue;
      const lx = t.cords[0] / fr.scale, ly = t.cords[1] / fr.scale;
      const [sx, sy] = toScreen(fr.cos * lx - fr.sin * ly + fr.tx, fr.sin * lx + fr.cos * ly + fr.ty);
      if (sx < -20 || sy < -20 || sx > W + 20 || sy > H + 20) continue;
      ctx.beginPath(); ctx.arc(sx, sy, 7, 0, Math.PI * 2);
      ctx.fillStyle = thingColor(t.ent, custom); ctx.fill();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
      labels.push([thingName(this.data, t.ent), sx, sy + 17]);
    }
    ctx.font = "600 11px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (const [text, x, y] of labels) {
      const w = ctx.measureText(text).width + 8;
      ctx.fillStyle = dark ? "rgba(20,24,30,0.78)" : "rgba(255,255,255,0.82)";
      ctx.fillRect(x - w / 2, y - 8, w, 16);
      ctx.fillStyle = dark ? "#e8eaed" : "#1b1f24"; ctx.fillText(text, x, y);
    }
    if (this._adjust) {
      // The site's origin, the point the drag moves and the rotation turns about.
      const [ox, oy] = toScreen(0, 0);
      ctx.strokeStyle = "#d63384"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(ox - 10, oy); ctx.lineTo(ox + 10, oy); ctx.moveTo(ox, oy - 10); ctx.lineTo(ox, oy + 10); ctx.stroke();
    }
  }

  // --- interaction -----------------------------------------------------------------

  _local(e) { const r = this._canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }

  _down(e) {
    this._canvas.setPointerCapture?.(e.pointerId);
    this._pointers.set(e.pointerId, this._local(e));
    const p = this._local(e);
    this._drag = { start: p, view: { ...this._view }, site: this._site ? { ...this._site } : null, moved: false };
  }

  _move(e) {
    if (!this._pointers.has(e.pointerId) || !this._drag) return;
    const p = this._local(e), d = this._drag;
    this._pointers.set(e.pointerId, p);
    const dx = p.x - d.start.x, dy = p.y - d.start.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    const z = this._view.zoom;
    if (this._adjust && d.site) {
      // Move the house: its origin follows the pointer.
      const o = project(d.site.lat, d.site.lon, z), at = unproject(o.x + dx, o.y + dy, z);
      this._site = { ...d.site, lat: at.lat, lon: at.lon };
    } else {
      const c = project(d.view.lat, d.view.lon, z), at = unproject(c.x - dx, c.y - dy, z);
      this._view = { ...this._view, lat: at.lat, lon: at.lon };
    }
    this._draw();
  }

  _up(e) { this._pointers.delete(e.pointerId); this._drag = null; }

  _wheel(e) {
    e.preventDefault();
    const p = this._local(e);
    this._zoomAt(p, this._view.zoom - e.deltaY * 0.0025);
  }

  /** Zoom to ``zoom``, keeping the map point under ``p`` (screen px) still. */
  _zoomAt(p, zoom) {
    const v = this._view, rect = this._canvas.getBoundingClientRect();
    const z2 = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
    const c1 = project(v.lat, v.lon, v.zoom);
    const under = unproject(c1.x + p.x - rect.width / 2, c1.y + p.y - rect.height / 2, v.zoom);
    const u2 = project(under.lat, under.lon, z2);
    const c2 = unproject(u2.x - (p.x - rect.width / 2), u2.y - (p.y - rect.height / 2), z2);
    this._view = { lat: c2.lat, lon: c2.lon, zoom: z2 };
    this._draw();
  }

  _zoomBy(step) {
    const r = this._canvas.getBoundingClientRect();
    this._zoomAt({ x: r.width / 2, y: r.height / 2 }, this._view.zoom + step);
  }

  _fit() {
    if (!this._site) return;
    this._view = { lat: this._site.lat, lon: this._site.lon, zoom: 19 };
    this._draw();
  }

  _setSource(src) {
    this._source = src;
    try { localStorage.setItem("sextant.property.source", src); } catch { /* ignore */ }
    this._tiles.clear();
    if (src === "street") this._loadToken();
    this._draw();
  }

  _turn(deg) {
    if (!this._site) return;
    this._site = { ...this._site, rotation: ((((this._site.rotation || 0) + deg) % 360) + 360) % 360 };
    this._draw();
  }

  async _saveSite() {
    if (!this._site) return;
    this._busy = true;
    const r = await callWS(this, this.hass, { type: "sextant/site/set", lat: this._site.lat, lon: this._site.lon, rotation: this._site.rotation || 0 });
    this._busy = false;
    if (!r) return;
    this._adjust = false;
    toast(this, "House lined up on the map");
    this.dispatchEvent(new CustomEvent("layout-changed", { bubbles: true, composed: true }));
    this._load();
  }

  _cancelAdjust() {
    this._adjust = false;
    this._site = this._geo?.site || (Number.isFinite(this._geo?.home?.lat) ? { lat: this._geo.home.lat, lon: this._geo.home.lon, rotation: 0 } : null);
    this._draw();
  }

  render() {
    const geo = this._geo, admin = this.hass?.user?.is_admin !== false;
    const unregistered = (geo?.floors || []).filter((f) => !f.registered).map((f) => f.name);
    const noTiles = this._source === "street" && geo && !geo.map_tiles;
    return html`
      <div class="stage">
        <canvas @pointerdown=${(e) => this._down(e)} @pointermove=${(e) => this._move(e)} @pointerup=${(e) => this._up(e)}
                @pointercancel=${(e) => this._up(e)} @wheel=${(e) => this._wheel(e)}></canvas>
        <div class="bar">
          ${uiSegmented({ label: "Map", value: this._source, options: [
            { value: "street", label: "Street", title: "OpenStreetMap through Home Assistant's own map service" },
            { value: "aerial", label: "Aerial", title: "Esri World Imagery, fetched by this browser from Esri (Esri sees which tiles are viewed)" }],
            onChange: (v) => this._setSource(v) })}
          ${admin && !this._adjust ? uiButton({ label: geo?.site ? "Line up again" : "Line up the house", kind: "outline", icon: "mdi:map-marker-radius", onClick: () => { this._adjust = true; this._draw(); } }) : nothing}
        </div>
        ${this._adjust ? html`<div class="adjust">
          <div class="small">Drag the house onto its footprint on the map, then turn it to match.</div>
          <div class="row">
            <button class="iconbtn" title="Turn 15° anticlockwise" @click=${() => this._turn(-15)}>⟲15</button>
            <button class="iconbtn" title="Turn 1° anticlockwise" @click=${() => this._turn(-1)}>⟲1</button>
            <span class="deg">${Math.round((this._site?.rotation || 0) * 10) / 10}°</span>
            <button class="iconbtn" title="Turn 1° clockwise" @click=${() => this._turn(1)}>⟳1</button>
            <button class="iconbtn" title="Turn 15° clockwise" @click=${() => this._turn(15)}>⟳15</button>
          </div>
          <div class="row">${uiButton({ label: "Save", kind: "primary", disabled: this._busy, onClick: () => this._saveSite() })}${uiButton({ label: "Cancel", kind: "text", onClick: () => this._cancelAdjust() })}</div>
        </div>` : nothing}
        ${!geo ? html`<div class="note">Loading…</div>`
          : !this._site ? html`<div class="note">Set your home location in Home Assistant (Settings → System → General) to start the map there.</div>`
          : noTiles ? html`<div class="note">The street map needs Home Assistant 2026.10 or later. Aerial imagery still works.</div>`
          : !geo.site ? html`<div class="note">Not lined up yet: the house is drawn at your home location${admin ? ". Use “Line up the house” to move and turn it onto its footprint" : ""}.</div>`
          : unregistered.length > 1 ? html`<div class="note">${unregistered.join(", ")} ${unregistered.length === 1 ? "is" : "are"} not lined up with the other floors (Edit → Anchor), so ${unregistered.length === 1 ? "it is" : "they are"} drawn on ${unregistered.length === 1 ? "its" : "their"} own.</div>` : nothing}
        <div class="zoom">
          <button title="Back to the house" aria-label="Back to the house" @click=${() => this._fit()}><ha-icon icon="mdi:home-map-marker"></ha-icon></button>
          <button title="Zoom in" aria-label="Zoom in" @click=${() => this._zoomBy(0.5)}><ha-icon icon="mdi:plus"></ha-icon></button>
          <button title="Zoom out" aria-label="Zoom out" @click=${() => this._zoomBy(-0.5)}><ha-icon icon="mdi:minus"></ha-icon></button>
        </div>
        <div class="attribution">${ATTRIBUTION[this._source]}</div>
      </div>`;
  }

  static styles = [sharedStyles, css`
    :host { display: block; height: 100%; }
    .stage { position: relative; width: 100%; height: 100%; min-height: 360px; overflow: hidden; }
    canvas { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; cursor: grab; }
    .bar { position: absolute; left: 10px; top: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .adjust, .note { position: absolute; left: 10px; top: 58px; max-width: min(380px, calc(100% - 20px)); padding: 8px 10px; border-radius: 10px;
      background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); font-size: 13px; }
    .adjust { display: flex; flex-direction: column; gap: 8px; }
    .adjust .row { display: flex; gap: 6px; align-items: center; }
    .adjust .deg { min-width: 48px; text-align: center; font-variant-numeric: tabular-nums; }
    .iconbtn { border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); border-radius: 8px; padding: 4px 8px; cursor: pointer; }
    .zoom { position: absolute; right: 10px; bottom: 26px; display: flex; gap: 2px; padding: 4px; border-radius: 12px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); }
    .zoom button { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent; color: var(--primary-text-color); cursor: pointer; }
    .attribution { position: absolute; right: 6px; bottom: 4px; font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(255,255,255,0.75); color: #333; }
  `];
}

customElements.define("sextant-property", SextantProperty);
