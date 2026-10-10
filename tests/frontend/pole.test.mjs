// Room label placement: the pole of inaccessibility (sextant-map.js). Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";
import { polygonPole, polygonCentroid, pointInPolygon } from "../../custom_components/sextant/frontend/sextant-map.js";

const P = (pts) => pts.map(([x, y]) => ({ x, y }));
const wallDistance = (p, pts) => {
  let best = Infinity;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[i], b = pts[j], dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
    const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2));
    best = Math.min(best, Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy)));
  }
  return best;
};

test("a square's pole is its centre", () => {
  const sq = P([[0, 0], [100, 0], [100, 100], [0, 100]]);
  const p = polygonPole(sq, 0.5);
  assert.ok(Math.abs(p.x - 50) < 1 && Math.abs(p.y - 50) < 1);
});

test("an L-shaped room's label lands inside it and well clear of the walls, where the centroid does not", () => {
  // An L: a 300x100 bar along the bottom and a 100x300 bar up the left.
  const L = P([[0, 0], [100, 0], [100, 200], [300, 200], [300, 300], [0, 300]]);
  const c = polygonCentroid(L), p = polygonPole(L);
  assert.ok(pointInPolygon(p, L));
  assert.ok(wallDistance(p, L) >= 45, `pole only ${wallDistance(p, L)} from a wall`);
  assert.ok(wallDistance(c, L) < wallDistance(p, L));
});

test("a U-shaped room's centroid is outside it; the pole is not", () => {
  const U = P([[0, 0], [60, 0], [60, 200], [140, 200], [140, 0], [200, 0], [200, 260], [0, 260]]);
  assert.ok(!pointInPolygon(polygonCentroid(U), U));
  assert.ok(pointInPolygon(polygonPole(U), U));
});

test("degenerate outlines fall back without throwing", () => {
  assert.deepEqual(polygonPole(P([[1, 1], [5, 5]])), polygonCentroid(P([[1, 1], [5, 5]])));
  const flat = polygonPole(P([[0, 0], [10, 0], [20, 0]]));
  assert.ok(Number.isFinite(flat.x) && Number.isFinite(flat.y));
});

test("a sliver of a polygon is placed quickly, inside its box", () => {
  const t0 = Date.now();
  const p = polygonPole(P([[0, 0], [2000, 0], [2000, 0.001], [0, 0.001]]));
  assert.ok(Date.now() - t0 < 200);
  assert.ok(p.x >= 0 && p.x <= 2000 && p.y >= 0 && p.y <= 0.001);
});
