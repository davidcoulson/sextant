/**
 * Web Mercator for the Property view: the tile maps' projection, and the
 * house frame (metres, y down the plan) placed on it at a site.
 */
export const TILE = 256;
const EARTH_MPP = 156543.03392804097;   // metres per pixel at zoom 0 on the equator

/** Web Mercator: a latitude/longitude in world pixels at zoom ``z``. */
export function project(lat, lon, z) {
  const size = TILE * 2 ** z, sin = Math.sin((lat * Math.PI) / 180);
  return { x: ((lon + 180) / 360) * size, y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size };
}

export function unproject(x, y, z) {
  const size = TILE * 2 ** z, n = Math.PI - (2 * Math.PI * y) / size;
  return { lat: (180 / Math.PI) * Math.atan(Math.sinh(n)), lon: (x / size) * 360 - 180 };
}

export function metresPerPixel(lat, z) { return (EARTH_MPP * Math.cos((lat * Math.PI) / 180)) / 2 ** z; }

/** A house-frame point (metres, y down the plan) to world pixels at zoom ``z``,
 * for a site {lat, lon, rotation (degrees clockwise)}. */
export function houseToWorld(hx, hy, site, z) {
  const r = ((site.rotation || 0) * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r);
  const o = project(site.lat, site.lon, z), m = metresPerPixel(site.lat, z);
  return { x: o.x + (hx * c - hy * s) / m, y: o.y + (hx * s + hy * c) / m };
}

/** The view after a two-finger pinch, from where it started: zoomed by the
 * change in finger spread (clamped to [minZoom, maxZoom]), and moved so the
 * map point that was between the fingers stays between them. ``view`` is
 * {lat, lon, zoom}; ``mid0``/``mid`` the fingers' midpoint at the start and
 * now, in screen px from the canvas's top-left; ``w``/``h`` its size. */
export function pinchView(view, mid0, dist0, mid, dist, w, h, minZoom, maxZoom) {
  const zoom = Math.max(minZoom, Math.min(maxZoom, view.zoom + Math.log2(Math.max(dist, 1) / Math.max(dist0, 1))));
  const c0 = project(view.lat, view.lon, view.zoom);
  const under = unproject(c0.x + mid0.x - w / 2, c0.y + mid0.y - h / 2, view.zoom);
  const u = project(under.lat, under.lon, zoom);
  const c = unproject(u.x - (mid.x - w / 2), u.y - (mid.y - h / 2), zoom);
  return { lat: c.lat, lon: c.lon, zoom };
}
