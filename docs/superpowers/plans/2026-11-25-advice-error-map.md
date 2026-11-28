# Advice Error Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-floor predicted-error map on the Advice page, with purple squares where Sextant measured consistently bad placement and stars where one more wall proxy helps most.

**Architecture:** A pure module `error_map.py` (numpy, shapely) turns the layout, proxy-to-proxy ranging, position history, pins and weak proxies into one grid per floor. `sextant/advice` adds its output. `sextant-map.js` gains an error layer; `sextant-health.js` embeds a `SextantMap` above the room table.

**Tech Stack:** Python 3 + numpy + shapely (already used by `advice.py`); Lit frontend, plain-class `SextantMap`; pytest; `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-25-advice-error-map-design.md`

## Global Constraints

- `error_map.py` imports nothing from Home Assistant and nothing from the package except `advice` (`_rooms_of`, `_wall_candidates`) and keeps the BPS MIT attribution in its docstring.
- Constants, verbatim from the spec: grid 0.5 m; range 15 m; distance floor 0.5 m; cap 8 m; defaults `a = 0.6, b = 0`; fit needs 8 pairs; `a >= 0.1, b >= 0`; jitter default 0.3 with 5 or fewer samples; `k_rx` clipped 0.6..2.0; 10 minutes per room; at most 2 stars; drop a star under 3% gain; purple squares 1 m; pin 3 m; floor flip back within 3 minutes and 3 m; jump 4 m out, back within 1.5 m in 60 s; 3 events across 2 clock hours.
- All new maths runs in the executor (`hass.async_add_executor_job`).
- `sextant/advice` stays `require_admin`. No version bump in the PR (bump happens at release, after David merges).
- UI copy: sentence case, plain words; legend `<1 m`, `2 m`, `3 m`, `4 m+`, "measured bad"; the caveat line: "Predicted from where the proxies are: the colours rank places, the metres are rough."
- Tests: `pytest tests/ -q` and `node --test tests/frontend/*.test.mjs` both pass at every commit.

## Review Focus

1. A floor with no placed proxies, or one or two: the field is the cap everywhere, no star, the note says why. No crash, no NaN in the payload. (Task 2 test.)
2. A house with no calibration samples (Bermuda fork without ranging): defaults are used, `calibrated` is false, the map still draws. (Task 1 test.)
3. Position history empty or very short: no purple from flips or jumps, weights fall back to 10 minutes a room. (Task 3 test.)
4. A floor without a scale, or rooms that are no-go: skipped, as `advise()` skips them. (Task 4 test.)
5. Re-running Analyse on another floor, or leaving the page and coming back: the map is rebuilt for the new floor, the old `SextantMap` destroyed, no stacked canvases. (Task 6 manual check.)

---

### Task 1: Noise fit and predicted error field

**Files:**
- Create: `custom_components/sextant/error_map.py`
- Test: `tests/test_error_map.py`

**Interfaces:**
- Produces:
  - `fit_noise(pairs: list[tuple[str, str, float, list[float]]]) -> dict` → `{"a": float, "b": float, "factor": {slug: float}, "pairs": int, "calibrated": bool}`. A pair is `(tx, rx, true_m, samples_m)`; samples already multiplied by the rx proxy's calibration correction (Task 4 does that).
  - `error_field(gx: np.ndarray, gy: np.ndarray, proxies: list[tuple[float, float, float]], a: float, b: float) -> np.ndarray`; points and proxies in metres, proxies `(x, y, k)`.
  - Private, ported from BPS: `_info(gx, gy, proxies, a, b)`, `_err(j00, j01, j11)`.

- [ ] **Step 1: Write the failing tests** (`import sextant` first, as `tests/test_advice.py` does)

```python
def test_fewer_than_eight_pairs_use_the_defaults():
    out = error_map.fit_noise([("a", "b", 3.0, [3.1] * 10)] * 7)
    assert (out["a"], out["b"], out["calibrated"], out["pairs"]) == (0.6, 0.0, False, 7)
    assert error_map.fit_noise([])["factor"] == {}

def test_the_fit_recovers_a_known_noise_line():
    # error = hypot(|ln bias|, jitter) chosen so it equals 0.2 + 0.05 d
    pairs = []  # build 12 pairs over d = 1..12 m with constant samples (jitter 0) and bias ln = 0.2 + 0.05 d
    ...
    out = error_map.fit_noise(pairs)
    assert abs(out["a"] - 0.2) < 0.02 and abs(out["b"] - 0.05) < 0.005 and out["calibrated"]

def test_a_proxy_that_ranges_worse_gets_a_bigger_factor(): ...  # one slug's pairs carry double bias: factor > 1.3, clipped <= 2.0

def test_the_centre_of_four_proxies_beats_a_point_off_to_one_side():
    sq = [(0, 0, 1.0), (6, 0, 1.0), (0, 6, 1.0), (6, 6, 1.0)]
    e = error_map.error_field(np.array([3.0, 12.0]), np.array([3.0, 3.0]), sq, 0.3, 0.0)
    assert e[0] < e[1]

def test_two_proxies_or_fewer_in_range_hit_the_cap():
    e = error_map.error_field(np.array([0.0, 30.0]), np.array([0.0, 0.0]), [(1, 0, 1.0), (2, 0, 1.0)], 0.3, 0.0)
    assert e[1] == error_map.ERR_CAP_M and np.isfinite(e).all()
```

Fill the `...` with the literal pair lists; the assertions above are the contract.

- [ ] **Step 2: Run** `pytest tests/test_error_map.py -q` → FAIL (`module 'sextant' has no attribute 'error_map'` or import error).

- [ ] **Step 3: Implement** the two functions and the constants (names: `GRID_M, MAX_RANGE_M, MIN_D_M, ERR_CAP_M, DEFAULT_A, DEFAULT_B, MIN_PAIRS_FOR_FIT, K_MIN, K_MAX`). Port BPS `fit_noise_model`, `_info`, `_err` (read it: `gh api repos/Hogster/BPS/contents/custom_components/bps/placement.py --jq .content | base64 -d`), with the pair error `hypot(|ln(median / true)|, std(ln samples) if len > 5 else 0.3)`. Skip pairs with `true_m <= 0` or no positive sample.

- [ ] **Step 4: Run** `pytest tests/test_error_map.py -q` → PASS.

- [ ] **Step 5: Commit** `git commit -m "error_map: BPS ranging-noise fit and predicted error field"`

### Task 2: Weights and stars

**Files:**
- Modify: `custom_components/sextant/error_map.py`
- Test: `tests/test_error_map.py`

**Interfaces:**
- Consumes: Task 1 `_info`, `_err`, `error_field`; `advice._rooms_of(floor) -> [(room, Polygon px)]`, `advice._wall_candidates(poly, scale) -> [(x_px, y_px)]`.
- Produces:
  - `room_seconds(layout: dict, tracks: dict[str, Iterable[tuple[float, str, float, float, int]]]) -> dict[tuple[str, str], float]`: `(floor name, room) -> seconds`. A point's time runs to the next point of the same thing, capped at 600 s, not across a `gap`; credited to the room the earlier point is in (vectorised `shapely.contains_xy` in plan px).
  - `floor_map(floor: dict, noise: dict, seconds: dict) -> dict | None` → `{"grid": {"x0", "y0", "step", "w", "h"}, "err": [float], "err_after": [float], "stars": [{"x", "y", "room", "gain_pct"}], "note": str}` (plan px, rounded to 0.1; `x0, y0` is the centre of the first cell; values row-major for every cell in the box of the rooms and proxies plus 1 m; drawing clips to rooms. The spec said null outside rooms; values everywhere let the bilinear blend reach the walls, and the clip does the masking). None for a floor without a scale or without rooms.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_empty_corner_room_gets_the_star():          # 3 proxies in Hall, a far room with none: stars[0]["room"] == "Far", on its wall (within WALL_INSET_M*scale+1 px of an edge)
def test_time_spent_moves_the_star():                   # two equal empty rooms either side; seconds favour one: the star goes there
def test_no_star_below_three_percent_gain():           # a floor already dense with proxies: stars == []
def test_a_floor_with_two_proxies_says_it_needs_three(): # stars == [] and "three proxies" in note; all err finite; same with zero proxies (all err == ERR_CAP_M)
def test_after_is_no_worse_than_before():               # every err_after <= err (+1e-9)
def test_room_seconds_caps_long_steps_and_skips_gaps():  # 2 points 3600 s apart -> 600 s; a gap point starts fresh
```

Use `test_advice._layout`/`_rect` style helpers (copy the two helpers; scale 100 px/m).

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Weights: `seconds.get((floor, room), 0) + 600` spread evenly over the room's cells, normalised. Candidates: `_wall_candidates` of every room, to metres. Greedy as BPS `analyze_floor`/`best_candidate` (chunk 64), two rounds, stop when `gain / before < 0.03`. New proxy `k` = median of `noise["factor"]` values, 1.0 if none. `note`: "needs three proxies on this floor before a spot can be chosen" when there are no stars and fewer than 3 placed proxies, else "". Placed proxies: the floor's receivers with `cords` x and y (as `advise()`), `k = factor.get(entity_id, 1.0)`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "error_map: weighted stars on walls, after-field, room seconds"`

### Task 3: Measured bad squares

**Files:**
- Modify: `custom_components/sextant/error_map.py`
- Test: `tests/test_error_map.py`

**Interfaces:**
- Produces: `bad_squares(layout: dict, tracks: dict, pins: list[dict], weak: list[dict]) -> dict[str, list[dict]]`, floor name → `[{"x", "y", "size", "kinds": {"pin"|"proxy"|"flip"|"jump": int}, "things": [entity], "hours": int}]`, `x, y` the square's top-left in plan px, `size` = 1 m in plan px. `pins` and `weak` items are `{"entity", "floor", "x", "y" (plan px), "error_m"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_pin_three_metres_off_turns_its_square_purple():       # error_m 3.0 -> one square with kinds == {"pin": 1}; 2.9 -> none
def test_a_weak_proxy_turns_its_square_purple():
def test_floor_flips_need_three_across_two_hours():              # 3 flips in one hour: none; 3 flips over 2 hours: one square, kinds["flip"] == 3, hours == 2
def test_a_flip_that_does_not_come_back_near_is_not_one():       # back on floor A 5 m away: no event
def test_jumps_out_and_back_count_and_a_real_walk_does_not():    # 4 m out, back within 1.5 m in 40 s: event; 4 m out, stays: none
def test_no_history_no_purple_from_history():                    # tracks == {}: only pin/proxy squares
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Constants `BAD_CELL_M = 1.0, PIN_BAD_M = 3.0, FLIP_BACK_S = 180, FLIP_NEAR_M = 3.0, JUMP_M = 4.0, JUMP_BACK_S = 60, JUMP_NEAR_M = 1.5, MIN_EVENTS = 3, MIN_HOURS = 2`. Flip: points `p[i-1]` on A, `p[i]` on another floor, a later `p[j]` back on A with `t_j - t_{i-1} <= 180` and within 3 m of `p[i-1]` → event at `p[i-1]`. Jump: same floor, `|p[i] - p[i-1]| >= 4`, a later `p[k]` with `t_k - t_{i-1} <= 60` within 1.5 m of `p[i-1]` → event at `p[i-1]`. Pool events by `(floor, floor(x/1), floor(y/1))`; a square is purple when it has a pin or proxy entry, or flip+jump events `>= 3` over `>= 2` distinct `int(t // 3600)`. `hours` counts those distinct hours.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "error_map: purple squares from pins, weak proxies, floor flips and jumps"`

### Task 4: Wire into `sextant/advice`

**Files:**
- Modify: `custom_components/sextant/error_map.py` (entry point), `custom_components/sextant/ws.py:1781-1802` (`ws_advice`)
- Test: `tests/test_error_map.py`

**Interfaces:**
- Consumes: Tasks 1-3; `calibration.solve_snapshot`, `calibration._true_distance_m(snap, a, b)`; `ws._evaluate_mark(hass, core, mark, weights=(0.0,), gains=(1.0,))` → rows, `rows[0]["mean_m"]`; `load_truth(hass)["marks"]` (`{id, entity, floor, x, y}` plan px); `core.get_position_history(hass).window(ent, 0.0, now)` and `history_mod._PointView`; `core._truth_buffer.entities()` (things Bluetooth places, as `_pin_gaps`).
- Produces: `floor_maps(layout, pairs, tracks, pins, weak) -> {"model": {"a", "b", "pairs", "calibrated"}, "maps": {floor name: floor_map(...) + {"bad": [...]}}}`. `sextant/advice` returns it merged into its result.

- [ ] **Step 1: Write the failing test** `test_floor_maps_covers_scaled_floors_and_skips_the_rest` (one scaled floor with rooms, one unscaled: `maps` has only the first; `model["calibrated"] is False` with no pairs; the payload passes `json.dumps` with `allow_nan=False`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `floor_maps`, then in `ws_advice`: take `snap = solve_snapshot(get_calibration_state(hass))` and pass `snap["samples"]` to `run_selftest` (replacing the hand-made copy). Build `pairs` from `snap["samples"]` keys `tx|rx` with `_true_distance_m(snap, tx, rx)`, samples times the rx receiver's layout `correction` (1.0 if unset; shortcut: the close-range fade is ignored). `weak` = the `advice` result rows' `weak` slugs, positioned from the self-test rows' `known`. Pins: one `_evaluate_mark` per mark, awaited before the executor job; skip a mark whose rows are empty. Run `floor_maps` in the same executor lambda as `advise`, `out.update(...)`.
- [ ] **Step 4: Run** `pytest tests/ -q` → all PASS.
- [ ] **Step 5: Commit** `git commit -m "Advice: error maps in sextant/advice"`

### Task 5: Error layer on the map

**Files:**
- Modify: `custom_components/sextant/frontend/sextant-map.js` (next to `buildWifiRaster` ~617, `setWifiHeat` ~1776, draw order ~1396, click ~990)
- Test: `tests/frontend/errormap.test.mjs`

**Interfaces:**
- Produces:
  - `export function errorRgb(m: number): [r, g, b]`: hue `120 * (1 - clamp((m - 0.5) / 3.5, 0, 1))`, via `hslRgb(h, 0.62, 0.48)`.
  - `export function errorAt(e, after, x, y): number | null`: bilinear value of `e.err` (or `e.err_after`) at plan point `x, y`; null outside the grid. Used by the raster and the tests.
  - `SextantMap.setErrorMap(e | null)` with `e = {grid, err, err_after, bad, stars, after: boolean}`; drawn outside edit mode after the Wi-Fi layer: the raster (5 sub-pixels a cell, alpha 0.55) clipped to the rooms, purple squares (`#7F77DD`, alpha 0.7) clipped to the rooms, then numbered stars (amber `#EF9F27`, outline `#633806`); with `after`, stars drawn as amber proxy dots.
  - Host callback `onPlanClick({x, y})`: a click outside edit mode that hits no thing, proxy or access point and did not pan.

- [ ] **Step 1: Write the failing tests**: `errorRgb(0.5)` has `g > r`; `errorRgb(4)` has `r > g`; `errorRgb(8)` equals `errorRgb(4)`; `errorAt` returns the cell value at a cell centre, the mean of two neighbours halfway, null outside.
- [ ] **Step 2: Run** `node --test tests/frontend/errormap.test.mjs` → FAIL.
- [ ] **Step 3: Implement**; the raster is a sibling of `buildWifiRaster`, not a fake access point.
- [ ] **Step 4: Run** `node --test tests/frontend/*.test.mjs` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Map: error layer, purple squares, stars, plan clicks"`

### Task 6: The map on the Advice page

**Files:**
- Modify: `custom_components/sextant/frontend/sextant-health.js` (`_renderAdvice` ~582, `updated`, `disconnectedCallback`)

**Interfaces:**
- Consumes: Task 4 `a.maps[floor]`, `a.model`; Task 5 `SextantMap`, `setErrorMap`, `onPlanClick`; `mapUrlFor(floor, this.data.maps)` and `pointInPolygon` (already imported from `sextant-map.js`).

- [ ] **Step 1: Implement**: above the per-floor tables, when `a?.maps`: floor buttons in `_adviceByFloor` order (label: floor, stars to add, purple count), a `<canvas>` with a `SextantMap` made once in `updated()` like `sextant-map-card.js` (`setFloor(floor, mapUrlFor(...))`, `setOptions({labels: true})`, `setErrorMap({...a.maps[floor], after})`), destroyed in `disconnectedCallback` and when the canvas leaves the DOM; a "with the suggested proxies" switch (`uiSwitch`); the legend and caveat line (Global Constraints); a card under the map: a click inside a purple square shows its kinds, things (`thingName`), hours; else the room under the click (`pointInPolygon`, room key `entity_id || zone_id`) shows that row's issue, median, third-proxy distance, time here, bounces, note, and for admins its "Show on plan". A floor with a `note` shows it under the switcher.
- [ ] **Step 2: Verify**: `node --test tests/frontend/*.test.mjs` passes (includes `no-duplicate-methods`); load the panel against the screenshot harness from Task 7 or a running instance and click a room, a purple square, the toggle, and another floor (Review Focus 5).
- [ ] **Step 3: Commit** `git commit -m "Advice: error map with floor switcher, legend, toggle and click cards"`

### Task 7: Docs and screenshot

**Files:**
- Modify: `docs/advice.md` (new "Error map" section after the issue table)
- Create: `img/screenshots/sextant-advice-map.png`

- [ ] **Step 1: Write** the section: what the colours are (prediction, rough metres, rank places), purple and its four kinds with their thresholds in words, stars (walls, weighted by where people and pets spend time, at most two a floor), the toggle, clicks, and that purple needs history: more `history_hours` on [Tuning](tuning.md) finds more. Same voice as the rest of the page.
- [ ] **Step 2: Screenshot**: a scratch page (scratchpad, not committed) that imports the real `sextant-map.js`, feeds it a made-up floor like the brainstorm mockup with `floor_maps` output generated by Python, rendered by headless Chromium (`npx playwright screenshot` or an installed Chromium). Swap in a shot of David's house later, after he installs a build.
- [ ] **Step 3: Commit** `git commit -m "docs: Advice error map"`

### Task 8: PR

- [ ] **Step 1:** `pytest tests/ -q` and `node --test tests/frontend/*.test.mjs` pass; push; `gh pr create --base main` with a summary, the calls list from the spec, and the screenshot.
- [ ] **Step 2:** Bind the PR (`ccd_pr`), run the deep Codex review, report its findings to David. Do not merge.
