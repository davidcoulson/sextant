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
