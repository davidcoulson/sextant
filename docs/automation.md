[Sextant](../README.md) › Sensors, card, services and API

# Sensors, card, services and API

Each tracked device gets five sensors under its own `<device> (Sextant)`
device, nested beneath its Bermuda device:

| Sensor | State |
|---|---|
| `sensor.<device>_sextant_location` | **the one to read**: the spot if it is in one, otherwise the room |
| `sensor.<device>_sextant_floor` | the elected floor |
| `sensor.<device>_sextant_room` | the elected room, with hysteresis and the stationary lock |
| `sensor.<device>_sextant_nearest_room` | the nearest room on that floor, instantaneous |
| `sensor.<device>_sextant_spot` | the spot inside the room, `unknown` when in none; attribute `room` |

`_sextant_location` is the whole answer in one entity, at the finest
resolution available: *David Bedside Table* when the watch is on the table,
*Master Bedroom* when it is somewhere else in the room. Its attributes say
which of the two you got and fill in the rest, so nothing needs a second
lookup:

| Attribute | Value |
|---|---|
| `kind` | `spot` or `room` — the state alone cannot be told apart, *Couch* and *Office* both being names |
| `room` | always the room, whether the state is the spot or the room |
| `spot` | the spot, or `None` |
| `floor` | the elected floor |
| `area_id`, `floor_id` | the linked Home Assistant area and floor, or `None` where unlinked |
| `presence` | `here` (heard within `stale_after_secs`, 2 min), `quiet` (until `away_after_secs`, 15 min), `away` — on every one of the five sensors |
| `last_heard` | when the thing was last heard, ISO 8601 UTC, to within a minute: while it is the only thing changing it is written once a minute rather than every cycle, and exactly whenever the state or another attribute changes; not recorded |

When the state is a spot, `room` is the room that spot belongs to rather
than the separately elected room. The two disagree for a cycle or so while
a thing crosses a boundary, and a spot paired with a room it is not in is
worse than one that lags.

`_sextant_nearest_room` drops to `unknown` as soon as no proxy reports a
distance (about 30 s, Bermuda's timeout): the clean "who is home" signal.
`_sextant_room` and `_sextant_floor` hold their value through a grace
period (`position_timeout`, five minutes by default) so a brief gap does
not blink someone out of a room; after it the thing leaves the map and
all three read `unknown`. `sensor.sextant_position_accuracy` is the global
self-test result. `sensor.sextant_untracked_people` counts the people the
placed mmWave sensors see that no tracked thing accounts for, with the rooms
they are in as `rooms` ([mmWave sensors](edit.md#mmwave-sensors)).

## People

Give things an owner on the Things page and each person gets three sensors
of the same shape — `sensor.<person>_sextant_person_location`, `_room` and
`_floor` — placed by whichever of their things speaks for them (`via`), and a
`device_tracker.<person>_sextant`.

While Sextant hears any of the person's things they are placed by BLE
(`source: ble`). Not heard for a couple of minutes, the last place they were
put stands (`source: held`): they have not left the house. Once Sextant has
lost them (`presence: away`) the first GPS tracker in their list that is
neither broken nor stale gives the zone (`source: gps`), or the state is
`away` with nothing usable (`source: none`). The list is set per person on
the Things page (People card) and lives in the layout as `person_trackers`;
a tracker that is unknown, unavailable, or has not reported within
`gps_stale_secs` (two hours by default) is passed over, and `gps_ignored`
names the ones that were and why.

| Attribute (location sensor) | Value |
|---|---|
| `source` | `ble`, `held`, `gps` or `none` |
| `presence` | as for things: the most present of the person's things |
| `via`, `considered` | the thing that placed them, and every thing that was in the running |
| `zone`, `latitude`, `longitude`, `gps_accuracy`, `tracker` | the GPS side, carried whichever source is speaking |
| `distance_m` | from Home Assistant's home location, when there are coordinates |
| `gps_ignored` | `[{entity, reason}, …]` |

`device_tracker.<person>_sextant` says the same in Home Assistant's own
currency: `home` while presence is `here` or `quiet` (source type
`bluetooth_le`), the GPS fix once it is `away` (source type `gps`, so the
state is the zone), `not_home` with nothing usable. Add it to the person
entity, the map card, or a zone automation.

The tracker also says *when*: `arrived_at` while it reads home, `departed_at`
while away, ISO 8601 UTC, exactly one of the two set so the state and the
time agree (BLE lost them but GPS still has them in the home zone is still
home, and no departure). A departure is stamped at the last time any of the
person's things was heard, not when `away_after_secs` ran out - "left at
08:12" means 08:12 - and the quiet period is the grace, so someone heard
again within it never left. Both survive a restart, and they change only on an arrival or
a departure, so the recorder gets one row per event: trigger on the
attribute leaving `None` and the time is in the event
([recipe](recipes.md#when-someone-left)).

## Rooms

Each room on the plan gets `binary_sensor.<room>_sextant_occupancy`
(device class occupancy): `on` while Sextant places a person or a pet in
it. What counts is the thing speaking for each person ([People](#people))
and each pet's tag; a watch left on the bedside table while its owner's
phone is in the kitchen is a watch, not a person, and a wallet on the
counter or luggage in a bedroom is listed but does not make the room
occupied. A thing nobody owns (a guest's phone) counts by its class. A
robot vacuum is not counted at all. It answers the question a room automation asks - is
anyone in the Kitchen, and who - without a template over every thing's
sensor:

| Attribute | Value |
|---|---|
| `people` | the people placed in the room, by the thing that speaks for each |
| `pets` | the cats and dogs in it |
| `things` | every thing in it, by name, the ones heard lately first |
| `count` | how many people-bearing things and pets |
| `spots` | the spots they are in (the Couch, a bedside table) |
| `presence` | `here` while any of them was heard within `stale_after_secs`, `quiet` while all have gone quiet (the sensor stays `on` until they are `away`), `None` when empty |
| `room`, `floor`, `area_id`, `floor_id` | the room, its floor, and the linked Home Assistant area and floor |

The sensor sits on a `<Room> (Sextant)` device that is put in the room's
linked area when it is first created, and left wherever you move it
afterwards. Two floors with a room of the same name get the floor in the
entity id (`binary_sensor.second_floor_office_sextant_occupancy`).

It is also the shape an occupancy aggregator wants as an input: [Area
Occupancy Detection](https://github.com/Hankanman/Area-Occupancy-Detection)
takes it as a custom binary sensor for the area and gets identity with it,
alongside the room's motion and media sensors.

`sensor.sextant_people_home` counts the people Sextant hears in the house
(presence `here` or `quiet`), with `home` and `away` listing them by name
and `pets_home` the pets, kept apart (a cat may be a person to Home
Assistant, but not to this count).

[Recipes](recipes.md) has automations and cards built on all of this.

## Map card

```yaml
type: custom:sextant-map-card
floor: Ground Floor
entities:            # thing keys as in /api/sextant/cords; omit for every tracked thing
  - davids_phone
title: Downstairs    # optional
height: 360          # px
circles: false       # the solver's distance circles
trails: true
labels: true
subzones: true       # draw spots
follow: false        # switch floors with the first entity
```

The card draws with the panel's renderer and the same subscription, so it
shows exactly what Live shows. `image` (a URL) or `map_file` (the name of a
file in `config/sextant_maps/`) overrides the floor's plan.

## API

- `GET /api/sextant/cords`: one row per thing (`ent` is the thing key)
  with its position (`cords`), confidence, the radii the solver used and
  their fit residual, `floor` and the floor probabilities (`floors`), the
  room (`zone`), the raw room, the lock state and speed, the spot and the
  spot shares (`sub_zones`), the anchor proxy, the estimator and the
  fingerprint telemetry (`fp`).
- `sextant/subscribe` over the websocket pushes the same payload plus proxy
  health once per positioning cycle:

  ```js
  hass.connection.subscribeMessage(
    (event) => console.log(event.positions, event.offline_receivers),
    { type: "sextant/subscribe" },
  );
  ```
- Websocket commands, all request/response: `layout/get`, `layout/save`,
  `receivers`, `scanner_linking`, `beacon_links`, `adjust_zones`,
  `calibration/status`, `calibration/action`, `history/index`,
  `history/get`, `history/clear`, `kpi`, `kpi/baselines`,
  `kpi/baseline/save`, `kpi/baseline/delete`, `tuning/set`,
  `thing/tune`, `selftest`, `truth/mark`, `truth/list`,
  `truth/delete`, `truth/evaluate`, `truth/apply`, `proxy/info`, `advice`,
  `snapshots/list`, `snapshots/restore`, `thing/forget`,
  `person/trackers/set`, and under `bermuda/`: `candidates`,
  `tracked`, `track`, `scanners`, `scanner_ranging`, `options`,
  `options/set`, `findmy`, `findmy/add`, `findmy/remove`, `tiles`,
  `tile_identities`, `tile/bind`, `tile/adopt`. All are prefixed
  `sextant/`.
- `GET /api/sextant/selftest` runs the leave-one-out self-test on demand.

## Services

| Service | Fields | Does |
|---|---|---|
| `sextant.start_calibration` | `floor`, `duration` (600) | sample one floor and solve |
| `sextant.cancel_calibration` | | stop a run or turn auto calibration off |
| `sextant.apply_corrections` | `floor` | apply the last solve |
| `sextant.reset_corrections` | `floor` | remove a floor's corrections |
| `sextant.set_auto_calibration` | `enabled` | continuous calibration on or off |
| `sextant.set_receiver_heights` | `heights` (slug → m), `default` | proxy mount heights |
| `sextant.set_thing_heights` | `heights` (thing → m) | carry heights |
| `sextant.set_floor_bias_field` | `floor`, `action` (`flat` / `paint` / `clear`), `value`, `area` or `points`, `mode`, `cell_m` | shape a floor's election bias by place; see [bias fields](positioning.md). Returns the field's shape |
| `sextant.set_tuning` | `settings`, `reset` | any [tuning key](tuning.md#tuning-reference); an unknown key or out-of-range value is refused with the allowed range |

```yaml
action: sextant.set_tuning
data:
  settings: {position_estimator: fused, zone_switch_secs: 30}
```

```yaml
# Believe an upstairs fix that lands on the catwalk; doubt one out in the void.
action: sextant.set_floor_bias_field
data: {floor: Second Floor, action: paint, area: Catwalk, value: 1.4}
```
