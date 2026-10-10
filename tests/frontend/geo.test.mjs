// Property view projection (sextant-geo.js). Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";
import { project, unproject, metresPerPixel, houseToWorld } from "../../custom_components/sextant/frontend/sextant-geo.js";

const near = (a, b, eps) => assert.ok(Math.abs(a - b) <= eps, `${a} vs ${b}`);

test("project and unproject round-trip", () => {
  const p = project(35.2271, -80.8431, 19), back = unproject(p.x, p.y, 19);
  near(back.lat, 35.2271, 1e-9);
  near(back.lon, -80.8431, 1e-9);
});

test("the origin of the world is at the antimeridian and the equator's centre", () => {
  const p = project(0, -180, 0);
  near(p.x, 0, 1e-9);
  near(p.y, 128, 1e-9);
});

test("ten metres east is ten metres of pixels at the site's latitude", () => {
  const site = { lat: 35.2, lon: -80.8, rotation: 0 }, z = 20;
  const o = houseToWorld(0, 0, site, z), e = houseToWorld(10, 0, site, z);
  near((e.x - o.x) * metresPerPixel(35.2, z), 10, 1e-6);
  near(e.y, o.y, 1e-9);
});

test("rotation turns the house clockwise", () => {
  const site = { lat: 35.2, lon: -80.8, rotation: 90 }, z = 20;
  const o = houseToWorld(0, 0, site, z), p = houseToWorld(10, 0, site, z);
  // The plan's +x points down the screen (south) after a quarter turn clockwise.
  near(p.x, o.x, 1e-6);
  assert.ok(p.y > o.y);
});

test("a pinch zooms by the finger spread and keeps the point between the fingers still", async () => {
  const { pinchView } = await import("../../custom_components/sextant/frontend/sextant-geo.js");
  const view = { lat: 41.3, lon: -81.76, zoom: 19 }, W = 800, H = 600;
  const mid0 = { x: 200, y: 150 };
  const v = pinchView(view, mid0, 100, mid0, 200, W, H, 15, 22);
  near(v.zoom, 20, 1e-9);
  // The map point that was under mid0 is still under it.
  const before = project(view.lat, view.lon, 19), after = project(v.lat, v.lon, 20);
  const pBefore = unproject(before.x + mid0.x - W / 2, before.y + mid0.y - H / 2, 19);
  const pAfter = unproject(after.x + mid0.x - W / 2, after.y + mid0.y - H / 2, 20);
  near(pAfter.lat, pBefore.lat, 1e-9);
  near(pAfter.lon, pBefore.lon, 1e-9);
  // Clamped at the limits.
  near(pinchView(view, mid0, 100, mid0, 10000, W, H, 15, 22).zoom, 22, 1e-9);
});
