# Advice error map: design

Date: 2026-11-25. Status: draft for David's approval (builder check done).

## Intent

David does not read the Advice page's room table. He wants to open Advice,
look at a floor plan, see a red blob in a room, and either click the room to
see the numbers behind it or go and put another BLE proxy in the red. BPS
0.3.0b1's "Receiver placement" heat map is the model he liked.

The Basement is the case in point: one large room where the cats are often
put in the wrong part of the room, or on the wrong floor. A room-level row
averages a bad half of a big room into one median; a map shows which half.

## Goals

- A per-floor map at the top of the Advice page: every half-metre square
  coloured by the **predicted** position error, green (under 1 m) to red
  (4 m and over), with a legend `<1 m, 2 m, 3 m, 4 m+`.
- **Purple squares** where Sextant has **measured** a consistently bad
  spot, drawn in the plan like the heat (no icons). Clicking one shows the
  evidence: what was seen, how often, over how long.
- **Stars** at up to two wall spots per floor where one more proxy cuts the
  predicted error most, weighted by where tracked things spend time.
- A "with the suggested proxies" toggle that redraws the floor as if the
  starred proxies were installed.
- Clicking a room shows the numbers its Advice row already has (issue,
  self-test median, third-proxy distance, time here, bounces, note).
- Admin-only, like the rest of the Advice page: `sextant/advice` is
  `require_admin` because it is a heavy job (commit 8c0917c, "Require admin
  on heavy jobs"), and the map rides on it. (Builder's call; see the
  calls list at the end.)

## Non-goals

- Predicting wrong-floor placements. The model looks at one floor's
  proxies. Wrong floor shows up only as measured purple ("floor flips").
- Storing the solver's per-fix fit cost. It would give a measured map
  wherever things walk, but it is a history format change; a follow-up.
- Candidate spots anywhere inside a room. A proxy needs an outlet, so
  candidates stay on walls (`advice._wall_candidates`).
- Changing the room rules, the room table, location pins, or the Edit page.

## Anti-goals

- A map that is red everywhere. The model's metres are pessimistic; the
  colour bins are fixed and the page says the colours rank places and the
  metres are rough. If David's real house comes out mostly red, the noise
  fit is wrong, not the house.
- Purple from one bad afternoon. A square turns purple only from repeated
  evidence (see thresholds).
- Slowing Home Assistant. All maths runs in the executor, vectorised.

## Decided with David

- The prediction is the map ("the prediction is great").
- Measured bad spots are flagged on top, as purple squares that fit in with
  the room, not as `!` markers.
- Pets count the same as people for weighting the stars, and their history
  counts as evidence for the purple. The cats roam and find the problems.
- Clicking a room shows its raw data.

## How it works

### Prediction (pure module `custom_components/sextant/error_map.py`)

Port of Hogster/BPS `custom_components/bps/placement.py` (MIT; keep the
attribution in the module docstring), adapted:

- **Noise** `sigma(d) = d * (a + b*d) * k_rx`. Fit `a, b` by least squares
  on proxy-to-proxy pairs: for each pair with a true distance, error =
  `hypot(|ln(median measured / true)|, std(ln samples))` (std defaults to
  0.3 with 5 or fewer samples), regressed on true distance. Fewer than 8
  pairs: defaults `a = 0.6, b = 0`. Clamp `a >= 0.1, b >= 0`.
  Inputs: `calibration.solve_snapshot(cal)` / the `SampleWindow`s in
  `cal["samples"]["tx|rx"]`, and `calibration._true_distance_m` (same
  floor only, mount heights used when set). One fit for the whole house;
  `k_rx` carries what differs per proxy.
- **k_rx** per proxy: the median of (pair error / model error) over that
  proxy's pairs, clipped to 0.6..2.0; 1.0 for a proxy with no pairs. This
  is BPS's factor. (Considered and rejected: the self-test error as k_rx.
  It mixes geometry into a ranging factor; it feeds the purple instead.)
- **Field** on a 0.5 m grid over the floor's rooms plus 1 m margin, masked
  to non-no-go rooms (`advice._rooms_of`): error = `sqrt(trace(J^-1))`,
  `J = sum(u u^T / sigma^2)` over placed proxies on that floor within 15 m,
  distance floored at 0.5 m, error capped at 8 m. Two-dimensional:
  shortcut, mount heights ignored in the field.
- **Weights**: seconds each tracked thing (people, pets, anything in
  position history) spent in each room over the kept history, plus 10
  minutes per room so an unvisited room still counts a little, spread
  evenly over that room's squares. Room-level on purpose: a misplaced fix
  still usually lands in the right room.
- **Stars**: greedy over the wall candidates of every room on the floor:
  the candidate that lowers the weighted mean error most, then the best
  second given the first. A pick that improves the weighted error by less
  than 3% is dropped. New proxy factor = median k_rx. Vectorised over
  candidates in chunks (BPS `best_candidate`).

### Measured bad spots (same module)

Pooled in 1 m squares. A square turns purple from any of:

| Evidence | Source | Bad when |
|---|---|---|
| Pin reads off | `ws._evaluate_mark(hass, core, mark, weights=(0.0,), gains=(1.0,))`, its `mean_m`: one re-solve per pin, not the full `truth/health` sweep | 3 m or more off; square of the pin |
| Proxy fails self-test | the self-test `ws_advice` already runs: rows `{entity, floor, known [x, y px], error_m}` | the weak-proxy rule `advise()` already applies (3 m or more, and twice the median of the room's other proxies); square of the placed proxy |
| Floor flips | position history | a thing leaves floor A for floor B and is back on A within 3 minutes, back within 3 m of where it left; square where it left |
| Jumps | position history | a fix leaves a spot by 4 m or more and is back within 1.5 m of it within 60 s; square it left |

"Consistently": floor flips and jumps need 3 or more events in the square
across at least 2 different clock hours. Pins and the self-test already
pool many cycles, so one counts. All thresholds are module constants.

"Position history" here and under Weights is `core.get_position_history(hass)`
(`history.py`): every tracked thing (people, pets, beacons), points
`(t, floor name, x_m, y_m, gap)` via `window()` / `_PointView`, kept for
`history_hours` on the Tuning page (default 6 h, up to 7 days). With the
default 6 h the purple fills slowly; the docs say so and point at the
setting. Weights come from the same history, not from `room_usage`.

### Server

`sextant/advice` grows `maps` and `model`, computed in the executor after
`advise()` (the pin re-solves are awaited before it): `model: {a, b,
pairs, calibrated}` once, and `maps: {floor name: {grid: {x0, y0, step,
w, h} in plan px, err: [metres rounded to 0.1, row-major, null outside
rooms], err_after: [same, with the stars], bad: [{x, y, size (plan px),
kinds: {pin|proxy|flip|jump: count}, things: [entity], hours}], stars:
[{x, y, room, gain_pct}], note}}` for every floor with a scale. A floor is
a few thousand squares, so all floors go in one response. One button, one
result, cached by the frontend as today.

A floor with fewer than three placed proxies is mostly at the cap; greedy
adds one proxy at a time and may find no gain. Then `stars` is empty and
`note` says the floor needs three proxies before a spot can be chosen.

### Frontend

- Advice page (`sextant-health.js`, `_renderAdvice`): a floor switcher (today's floor order, worst first) above a
  `SextantMap` embedded the way `sextant-map-card.js` does it (canvas,
  `setFloor`, `destroy` on teardown). The room table stays below.
- A new map layer for the error grid, a sibling of `buildWifiRaster` and
  `_drawWifiHeat` in `sextant-map.js` (bilinear upsampling, clipped to room
  polygons; that one is hard-wired to dBm, so share what is shared rather
  than fake an access point): hue 120 to 0 over
  0.5..4 m, about 55% opacity. Purple squares and numbered stars drawn on
  top. Proxies drawn as the map already draws receivers.
- Click on the map: a purple square shows its evidence card; otherwise the
  room under the click shows its row's numbers in a card under the map.
- Legend under the map: the four error bins, proxy, star, purple
  "measured bad", and one line: the colours are predicted from where the
  proxies are; they rank places, the metres are rough.

## Done means

- `error_map.py` pure (numpy, shapely), with `tests/test_error_map.py`
  covering the noise fit (defaults under 8 pairs, recovers a known a, b),
  the field (centre of a square of proxies beats one-sided; under 3
  proxies hits the cap), the stars (an empty corner gets the pick; weight
  moves it), and each purple detector including the "consistently" rule.
- `sextant/advice` returns `maps`; existing advice tests still pass.
- Heat layer, purple, stars, legend, toggle and click cards on the Advice
  page; a node test for the colour bins if the colour function is pure.
- `docs/advice.md` gains an "Error map" section and a screenshot.
- A PR against `main`; a deep Codex review before merge; David merges.

## Left to the builder

- Function names, module split, and how the error grid reaches the map.
- How the screenshot is taken. Installing anything on David's Home
  Assistant needs his say-so first.
- Exact hit-testing and card layout.

## Calls made without David (check these)

1. The map is admin-only, like the rest of Advice, because the analysis is
   a heavy job. Opening it to every user means opening `sextant/advice`.
2. Two sets of suggestions: the map's stars (model, per floor) and the room
   table's spots (rules, per room) both stay. The table is untouched.
3. Pins count as purple from one cheap re-solve per pin.
4. The stars and the purple read the position history (default 6 h), not
   the 48 h person log, because only the history has positions and pets.
5. k_rx is BPS's per-proxy ranging factor, not the self-test error.
6. One noise fit for the house; at most two stars per floor; 3% minimum gain.
