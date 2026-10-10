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
